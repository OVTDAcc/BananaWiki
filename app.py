"""
BananaWiki – Main Flask application entry point.

This module creates the Flask application, registers middleware, hooks, and
routes, and re-exports key symbols for backward compatibility with the test
suite and other consumers that ``import app`` or ``from app import …``.

Utility functions live in :mod:`helpers`.  Route handlers are grouped in the
:mod:`routes` package.  Database operations live in :mod:`db`.
"""

from datetime import datetime, timedelta, timezone

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify,
)
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

import config
import db
from wiki_logger import log_request, log_action, get_logger

# Import helpers so they can be re-exported from this module
from helpers import (                                       # noqa: F401
    ALLOWED_TAGS, ALLOWED_ATTRS, _DUMMY_HASH, ROLE_LABELS, _USERNAME_RE,
    _RateLimitStore, _LOGIN_ATTEMPTS, _LOGIN_MAX_ATTEMPTS, _LOGIN_WINDOW,
    _check_login_rate_limit, _record_login_attempt, _clear_login_attempts,
    _RL_LOCK, _RL_STORE, _RL_GLOBAL_MAX, _RL_GLOBAL_WINDOW, _rl_check,
    rate_limit,
    render_markdown, _make_video_iframe, _embed_videos_in_html,
    compute_char_diff, compute_diff_html, compute_formatted_diff_html,
    slugify, allowed_file, allowed_attachment,
    _is_valid_hex_color, _is_valid_username,
    _safe_referrer, get_current_user,
    login_required, editor_required, admin_required, editor_has_category_access,
    get_site_timezone, time_ago, format_datetime, format_datetime_local_input,
    get_time_since_last_chat_cleanup, get_time_until_next_chat_cleanup,
)

# Re-export cleanup_unused_uploads (tests import it from app)
from routes.uploads import cleanup_unused_uploads           # noqa: F401

# ---------------------------------------------------------------------------
#  Flask application setup
# ---------------------------------------------------------------------------
app = Flask(
    __name__,
    template_folder="app/templates",
    static_folder="app/static",
)
app.secret_key = config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.permanent_session_lifetime = timedelta(days=7)

# --- Reverse-proxy support ---
if config.PROXY_MODE:
    app.wsgi_app = ProxyFix(
        app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
    )
    app.config["SESSION_COOKIE_SECURE"] = True
    app.config["PREFERRED_URL_SCHEME"] = "https"

csrf = CSRFProtect(app)


# ---------------------------------------------------------------------------
#  Template filters
# ---------------------------------------------------------------------------
@app.template_filter("render_md")
def render_md_filter(text):
    """Jinja2 filter that renders Markdown to sanitised HTML."""
    from markupsafe import Markup
    return Markup(render_markdown(text or ""))


def dedupe_flashed_messages(messages):
    """Return flashed messages without duplicate category/message pairs."""
    unique_messages = []
    seen = set()
    for message in messages or []:
        key = tuple(message) if isinstance(message, (list, tuple)) else message
        if key in seen:
            continue
        seen.add(key)
        unique_messages.append(message)
    return unique_messages


# ---------------------------------------------------------------------------
#  Context processors
# ---------------------------------------------------------------------------
@app.context_processor
def inject_globals():
    """Inject common variables into every template context."""
    settings = db.get_site_settings()
    user = get_current_user()
    active_announcements = db.get_active_announcements(bool(user))
    user_accessibility = db.get_user_accessibility(user["id"]) if user else {}
    sidebar_people = db.list_published_profiles()[:19] if user else []
    current_user_profile = db.get_user_profile(user["id"]) if user else None
    total_unread_dm = db.get_total_unread_dm_count(user["id"]) if user else 0
    total_unread_group = db.get_total_unread_group_count(user["id"]) if user else 0
    return {
        "current_user": user,
        "settings": settings,
        "time_ago": time_ago,
        "format_datetime": format_datetime,
        "format_datetime_local_input": format_datetime_local_input,
        "page_history_enabled": config.PAGE_HISTORY_ENABLED,
        "all_categories": db.list_categories(),
        "active_announcements": active_announcements,
        "user_accessibility": user_accessibility,
        "sidebar_people": sidebar_people,
        "current_user_profile": current_user_profile,
        "utcnow": datetime.now(timezone.utc).isoformat(),
        "time_since_last_chat_cleanup": get_time_since_last_chat_cleanup,
        "time_until_next_chat_cleanup": get_time_until_next_chat_cleanup,
        "total_unread_dm": total_unread_dm,
        "total_unread_group": total_unread_group,
        "dedupe_flashed_messages": dedupe_flashed_messages,
    }


# ---------------------------------------------------------------------------
#  Request hooks
# ---------------------------------------------------------------------------
@app.after_request
def set_security_headers(response):
    """Add security headers to every response."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self'; "
        "frame-src https://www.youtube.com https://player.vimeo.com; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    return response


@app.before_request
def before_request_hook():
    """Enforce setup, lockdown, session limits, and global rate limiting."""
    settings = db.get_site_settings()
    if not settings["setup_done"] and request.endpoint not in ("setup", "static"):
        return redirect(url_for("setup"))

    # Lockdown mode: non-admin users are kicked out
    if settings["lockdown_mode"] and request.endpoint not in (
        "lockdown", "login", "logout", "static", "view_announcement"
    ):
        user = get_current_user()
        if not user or user["role"] not in ("admin", "protected_admin"):
            if user:
                session.clear()
            if request.path.startswith("/api/"):
                return jsonify({"error": "Wiki is in lockdown mode."}), 403
            return redirect(url_for("lockdown"))

    # Session limit: enforce one active session per user
    if settings["session_limit_enabled"] and request.endpoint not in (
        "login", "logout", "setup", "static", "session_conflict", "session_conflict_force"
    ):
        uid = session.get("user_id")
        if uid:
            user = db.get_user_by_id(uid)
            if user:
                stored_token = user["session_token"]
                session_token = session.get("session_token")
                if stored_token and session_token != stored_token:
                    session.clear()
                    return redirect(url_for("session_conflict"))

    # Global rate limit (skip static files)
    if request.endpoint and request.endpoint != "static":
        ip = request.remote_addr or "unknown"
        if not _rl_check(ip, "global", _RL_GLOBAL_MAX, _RL_GLOBAL_WINDOW):
            log_action("rate_limited_global", request)
            if request.path.startswith("/api/"):
                return jsonify({"error": "Too many requests. Please slow down."}), 429
            try:
                categories, uncategorized = db.get_category_tree()
            except Exception:
                categories, uncategorized = [], []
            return render_template("wiki/429.html", categories=categories,
                                   uncategorized=uncategorized), 429

    user = get_current_user()
    log_request(request, user)


# ---------------------------------------------------------------------------
#  Route registration
# ---------------------------------------------------------------------------
from routes import register_all_routes  # noqa: E402
register_all_routes(app)


# ---------------------------------------------------------------------------
#  Initialisation
# ---------------------------------------------------------------------------
db.init_db()
get_logger()

if __name__ == "__main__":
    # Development-only entry point.
    # For production, use:  gunicorn wsgi:app -c gunicorn.conf.py
    print(" * WARNING: Flask development server \u2014 not for production.")
    print(" * Production:  gunicorn wsgi:app -c gunicorn.conf.py")

    app.run(host=config.HOST, port=config.PORT, debug=False)
