"""
BananaWiki – Main Flask application
"""

import os
import re
import uuid
import json
import sqlite3
import functools
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, send_from_directory, abort,
)
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import markdown
import bleach
from PIL import Image
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

import config
import db
from wiki_logger import log_request, log_action, get_logger
from sync import notify_change, notify_file_upload, notify_file_deleted

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

# --- SSL / HTTPS awareness ---
_ssl_enabled = bool(config.SSL_CERT and config.SSL_KEY)
if _ssl_enabled:
    app.config["SESSION_COOKIE_SECURE"] = True
    app.config["PREFERRED_URL_SCHEME"] = "https"

# --- Reverse-proxy support ---
if config.PROXY_MODE:
    app.wsgi_app = ProxyFix(
        app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
    )
    # Assume TLS is terminated upstream; still mark cookies Secure.
    app.config["SESSION_COOKIE_SECURE"] = True
    app.config["PREFERRED_URL_SCHEME"] = "https"

csrf = CSRFProtect(app)

ALLOWED_TAGS = list(bleach.ALLOWED_TAGS) + [
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "br", "hr", "pre", "code",
    "table", "thead", "tbody", "tr", "th", "td",
    "ul", "ol", "li", "dl", "dt", "dd",
    "img", "figure", "figcaption",
    "div", "span", "section",
    "del", "ins", "sup", "sub",
]
ALLOWED_ATTRS = {
    "*": ["class", "id"],
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title", "width", "height"],
    "td": ["align"],
    "th": ["align"],
}

# Pre-computed dummy hash for constant-time login checks
_DUMMY_HASH = generate_password_hash("dummy-constant-time-check")

# ---------------------------------------------------------------------------
#  Login rate limiting (per-IP, shared across workers via DB)
# ---------------------------------------------------------------------------
class _RateLimitStore(dict):
    """Compatibility shim for tests; backing data lives in DB."""

    def clear(self):
        super().clear()
        db.clear_all_login_attempts()


_LOGIN_ATTEMPTS = _RateLimitStore()
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW = 60  # seconds


def _check_login_rate_limit():
    """Return True if the request IP is allowed to attempt login."""
    ip = request.remote_addr or "unknown"
    recent = db.count_recent_login_attempts(ip, _LOGIN_WINDOW)
    return recent < _LOGIN_MAX_ATTEMPTS


def _record_login_attempt():
    """Record a failed login attempt for the current IP."""
    ip = request.remote_addr or "unknown"
    _LOGIN_ATTEMPTS.setdefault(ip, [])
    _LOGIN_ATTEMPTS[ip].append(datetime.now(timezone.utc).timestamp())
    db.record_login_attempt(ip)


def _clear_login_attempts():
    """Clear failed login attempts for the current IP (on successful login)."""
    ip = request.remote_addr or "unknown"
    _LOGIN_ATTEMPTS.pop(ip, None)
    db.clear_login_attempts(ip)


# ---------------------------------------------------------------------------
#  General rate limiting (in-memory, per-worker, thread-safe)
# ---------------------------------------------------------------------------
_RL_LOCK = threading.Lock()
_RL_STORE = defaultdict(list)   # (ip, bucket) → list of UTC timestamps
_RL_GLOBAL_MAX = 300            # max requests per window for all endpoints
_RL_GLOBAL_WINDOW = 60          # window size in seconds


def _rl_check(ip, bucket, max_requests, window):
    """Return True if the request is within the rate limit, and record it."""
    key = (ip, bucket)
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - window
    with _RL_LOCK:
        timestamps = _RL_STORE[key]
        _RL_STORE[key] = [t for t in timestamps if t > cutoff]
        if len(_RL_STORE[key]) >= max_requests:
            return False
        _RL_STORE[key].append(now)
        return True


def rate_limit(max_requests=60, window=60):
    """Route decorator that enforces a per-IP rate limit."""
    def decorator(f):
        bucket = f.__name__
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            ip = request.remote_addr or "unknown"
            if not _rl_check(ip, bucket, max_requests, window):
                log_action("rate_limited", request, endpoint=bucket)
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Too many requests. Please slow down."}), 429
                flash("Too many requests. Please slow down.", "error")
                abort(429)
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------
def render_markdown(text):
    """Convert markdown to sanitised HTML."""
    html = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "toc", "nl2br"],
    )
    return bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS)


@app.template_filter("render_md")
def render_md_filter(text):
    from markupsafe import Markup
    return Markup(render_markdown(text or ""))


def slugify(text):
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = text.strip("-")
    if not text:
        text = "page"
    return text


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in config.ALLOWED_EXTENSIONS


def _is_valid_hex_color(value):
    """Return True if value is a valid 7-char hex color like #aabbcc."""
    return bool(re.fullmatch(r"#[0-9a-fA-F]{6}", value))


_USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _is_valid_username(value):
    """Return True if the username contains only safe characters.

    Allowed: letters, digits, underscores and hyphens.
    This prevents log-injection (newlines / control chars) and
    avoids confusing Unicode look-alikes.
    """
    return bool(_USERNAME_RE.fullmatch(value))


def _safe_referrer():
    """Return request.referrer only if it is same-origin; otherwise return None."""
    ref = request.referrer
    if not ref:
        return None
    parsed = urlparse(ref)
    if parsed.netloc and parsed.netloc != request.host:
        return None
    return ref


def get_current_user():
    uid = session.get("user_id")
    if uid:
        return db.get_user_by_id(uid)
    return None


def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        user = db.get_user_by_id(session["user_id"])
        if not user:
            session.clear()
            flash("Account not found.", "error")
            return redirect(url_for("login"))
        if user["suspended"]:
            session.clear()
            flash("Your account has been suspended.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def editor_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user or user["role"] not in ("editor", "admin", "protected_admin"):
            flash("You do not have permission to perform this action.", "error")
            return redirect(url_for("home"))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user or user["role"] not in ("admin", "protected_admin"):
            flash("Admin access required.", "error")
            return redirect(url_for("home"))
        return f(*args, **kwargs)
    return wrapper


def get_site_timezone():
    """Return the zoneinfo timezone configured in site settings (defaults to UTC)."""
    settings = db.get_site_settings()
    tz_name = (settings["timezone"] if settings and settings["timezone"] else "UTC")
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        return ZoneInfo("UTC")


def time_ago(dt_str):
    """Return a human-readable 'X ago' or 'in X' string."""
    if not dt_str:
        return "never"
    try:
        dt = datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return "unknown"
    diff = datetime.now(timezone.utc) - dt
    secs = int(diff.total_seconds())
    if secs < 0:
        # Future date
        secs = abs(secs)
        if secs < 60:
            return "in a moment"
        elif secs < 3600:
            m = secs // 60
            return f"in {m} minute{'s' if m != 1 else ''}"
        elif secs < 86400:
            h = secs // 3600
            return f"in {h} hour{'s' if h != 1 else ''}"
        else:
            d = secs // 86400
            return f"in {d} day{'s' if d != 1 else ''}"
    if secs < 60:
        return "just now"
    elif secs < 3600:
        m = secs // 60
        return f"{m} minute{'s' if m != 1 else ''} ago"
    elif secs < 86400:
        h = secs // 3600
        return f"{h} hour{'s' if h != 1 else ''} ago"
    else:
        d = secs // 86400
        return f"{d} day{'s' if d != 1 else ''} ago"


def format_datetime(dt_str):
    """Return a human-readable date/time string in the configured site timezone."""
    if not dt_str:
        return ""
    try:
        dt = datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return ""
    site_tz = get_site_timezone()
    dt_local = dt.astimezone(site_tz)
    tz_label = dt_local.strftime("%Z")
    return dt_local.strftime(f"%Y-%m-%d %H:%M {tz_label}")


# ---------------------------------------------------------------------------
#  Context processors
# ---------------------------------------------------------------------------
@app.context_processor
def inject_globals():
    settings = db.get_site_settings()
    user = get_current_user()
    active_announcements = db.get_active_announcements(bool(user))
    return {
        "current_user": user,
        "settings": settings,
        "time_ago": time_ago,
        "format_datetime": format_datetime,
        "page_history_enabled": config.PAGE_HISTORY_ENABLED,
        "all_categories": db.list_categories(),
        "active_announcements": active_announcements,
    }


# ---------------------------------------------------------------------------
#  Request hooks
# ---------------------------------------------------------------------------
@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    return response


@app.before_request
def before_request_hook():
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
#  Setup (first boot)
# ---------------------------------------------------------------------------
@app.route("/setup", methods=["GET", "POST"])
def setup():
    settings = db.get_site_settings()
    if settings["setup_done"]:
        return redirect(url_for("home"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not username or not password:
            flash("Username and password are required.", "error")
            return render_template("auth/setup.html")
        if len(username) < 3:
            flash("Username must be at least 3 characters.", "error")
            return render_template("auth/setup.html")
        if len(username) > 50:
            flash("Username must be 50 characters or fewer.", "error")
            return render_template("auth/setup.html")
        if not _is_valid_username(username):
            flash("Username may only contain letters, digits, underscores and hyphens.", "error")
            return render_template("auth/setup.html")
        if password != confirm:
            flash("Passwords do not match.", "error")
            return render_template("auth/setup.html")
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("auth/setup.html")

        hashed = generate_password_hash(password)
        # Re-check setup_done to prevent race condition
        settings = db.get_site_settings()
        if settings["setup_done"]:
            flash("Setup already completed.", "info")
            return redirect(url_for("login"))
        try:
            db.create_user(username, hashed, role="admin")
        except sqlite3.IntegrityError:
            flash("Username already taken.", "error")
            return render_template("auth/setup.html")
        db.update_site_settings(setup_done=1)
        log_action("setup_complete", request, username=username)
        notify_change("setup_complete", f"Admin account '{username}' created")
        flash("Admin account created! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("auth/setup.html")


# ---------------------------------------------------------------------------
#  Authentication
# ---------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    settings = db.get_site_settings()
    if not settings["setup_done"]:
        return redirect(url_for("setup"))

    lockdown = bool(settings["lockdown_mode"])

    if request.method == "POST":
        if not _check_login_rate_limit():
            log_action("login_rate_limited", request)
            flash("Too many login attempts. Please wait a minute.", "error")
            return render_template("auth/login.html", lockdown=lockdown), 429

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = db.get_user_by_username(username)

        if not user:
            # Constant-time: check against dummy hash to prevent timing enumeration
            check_password_hash(_DUMMY_HASH, password)
            _record_login_attempt()
            log_action("login_failed", request, username=username)
            flash("Invalid username or password.", "error")
            return render_template("auth/login.html", lockdown=lockdown)

        if not check_password_hash(user["password"], password):
            _record_login_attempt()
            log_action("login_failed", request, username=username)
            flash("Invalid username or password.", "error")
            return render_template("auth/login.html", lockdown=lockdown)

        if user["suspended"]:
            log_action("login_suspended", request, username=username)
            flash("Your account has been suspended. Contact an administrator.", "error")
            return render_template("auth/login.html", lockdown=lockdown)

        if lockdown and user["role"] not in ("admin", "protected_admin"):
            log_action("login_blocked_lockdown", request, username=username)
            flash("This wiki is currently in lockdown. Only admins can log in.", "error")
            return render_template("auth/login.html", lockdown=lockdown)

        session.clear()
        session.permanent = True
        session["user_id"] = user["id"]
        _clear_login_attempts()
        db.update_user(user["id"], last_login_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
        log_action("login_success", request, user=user)
        return redirect(url_for("home"))

    return render_template("auth/login.html", lockdown=lockdown)


@app.route("/signup", methods=["GET", "POST"])
@rate_limit(10, 60)
def signup():
    settings = db.get_site_settings()
    if not settings["setup_done"]:
        return redirect(url_for("setup"))
    if settings["lockdown_mode"]:
        return redirect(url_for("lockdown"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        invite = request.form.get("invite_code", "").strip().upper()

        if not username or not password or not invite:
            flash("All fields are required.", "error")
            return render_template("auth/signup.html")
        if len(username) < 3:
            flash("Username must be at least 3 characters.", "error")
            return render_template("auth/signup.html")
        if len(username) > 50:
            flash("Username must be 50 characters or fewer.", "error")
            return render_template("auth/signup.html")
        if not _is_valid_username(username):
            flash("Username may only contain letters, digits, underscores and hyphens.", "error")
            return render_template("auth/signup.html")
        if password != confirm:
            flash("Passwords do not match.", "error")
            return render_template("auth/signup.html")
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("auth/signup.html")

        code_row = db.validate_invite_code(invite)
        if not code_row:
            log_action("signup_invalid_code", request, code=invite, username=username)
            flash("Invalid or expired invite code.", "error")
            return render_template("auth/signup.html")

        if db.get_user_by_username(username):
            flash("Username already taken.", "error")
            return render_template("auth/signup.html")

        hashed = generate_password_hash(password)
        try:
            user_id = db.create_user(username, hashed, invite_code=invite)
        except sqlite3.IntegrityError:
            flash("Username already taken.", "error")
            return render_template("auth/signup.html")
        if not db.use_invite_code(invite, user_id):
            # Race condition: code was used by another user concurrently
            db.delete_user(user_id)
            flash("This invite code was just used. Please request a new code.", "error")
            return render_template("auth/signup.html")

        log_action("signup_success", request, username=username, invite_code=invite)
        notify_change("user_signup", f"New user '{username}' registered")
        flash("Account created! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("auth/signup.html")


@app.route("/logout", methods=["POST"])
def logout():
    user = get_current_user()
    if user:
        log_action("logout", request, user=user)
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


@app.route("/lockdown")
def lockdown():
    settings = db.get_site_settings()
    if not settings["lockdown_mode"]:
        return redirect(url_for("login"))
    return render_template("auth/lockdown.html", settings=settings)


# ---------------------------------------------------------------------------
#  Account settings
# ---------------------------------------------------------------------------
@app.route("/account", methods=["GET", "POST"])
@login_required
@rate_limit(10, 60)
def account_settings():
    user = get_current_user()
    action = request.form.get("action", "") if request.method == "POST" else ""

    if action == "change_username":
        if user["is_superuser"]:
            flash("This account is protected and cannot be modified.", "error")
            return redirect(url_for("account_settings"))
        new_username = request.form.get("new_username", "").strip()
        password = request.form.get("password", "")
        if not check_password_hash(user["password"], password):
            flash("Incorrect password.", "error")
        elif len(new_username) < 3:
            flash("Username must be at least 3 characters.", "error")
        elif len(new_username) > 50:
            flash("Username must be 50 characters or fewer.", "error")
        elif not _is_valid_username(new_username):
            flash("Username may only contain letters, digits, underscores and hyphens.", "error")
        elif db.get_user_by_username(new_username) and new_username.lower() != user["username"].lower():
            flash("Username already taken.", "error")
        else:
            try:
                db.update_user(user["id"], username=new_username)
            except sqlite3.IntegrityError:
                flash("Username already taken.", "error")
                return redirect(url_for("account_settings"))
            else:
                db.record_username_change(user["id"], user["username"], new_username)
                log_action("change_username", request, user=user, new_username=new_username)
                notify_change("user_change_username", f"User '{user['username']}' renamed to '{new_username}'")
                flash("Username updated.", "success")
        return redirect(url_for("account_settings"))

    if action == "change_password":
        if user["is_superuser"]:
            flash("This account is protected and cannot be modified.", "error")
            return redirect(url_for("account_settings"))
        current_pw = request.form.get("current_password", "")
        new_pw = request.form.get("new_password", "")
        confirm_pw = request.form.get("confirm_password", "")
        if not check_password_hash(user["password"], current_pw):
            flash("Incorrect current password.", "error")
        elif new_pw != confirm_pw:
            flash("New passwords do not match.", "error")
        elif len(new_pw) < 6:
            flash("Password must be at least 6 characters.", "error")
        else:
            db.update_user(user["id"], password=generate_password_hash(new_pw))
            log_action("change_password", request, user=user)
            notify_change("user_change_password", f"User '{user['username']}' changed password")
            flash("Password updated.", "success")
        return redirect(url_for("account_settings"))

    if action == "delete_account":
        if user["is_superuser"]:
            flash("This account is protected and cannot be deleted.", "error")
            return redirect(url_for("account_settings"))
        password = request.form.get("password", "")
        if not check_password_hash(user["password"], password):
            flash("Incorrect password.", "error")
            return redirect(url_for("account_settings"))
        if user["role"] in ("admin", "protected_admin") and db.count_admins() <= 1:
            flash("Cannot delete the last admin account.", "error")
            return redirect(url_for("account_settings"))
        log_action("delete_account", request, user=user)
        notify_change("user_delete_account", f"User '{user['username']}' deleted their account")
        db.delete_user(user["id"])
        session.clear()
        flash("Your account has been deleted.", "info")
        return redirect(url_for("login"))

    if action == "toggle_protected_admin":
        if user["role"] not in ("admin", "protected_admin"):
            flash("Only admins can toggle protected admin status.", "error")
            return redirect(url_for("account_settings"))
        password = request.form.get("password", "")
        if not check_password_hash(user["password"], password):
            flash("Incorrect password.", "error")
            return redirect(url_for("account_settings"))
        if user["role"] == "admin":
            db.update_user(user["id"], role="protected_admin")
            log_action("enable_protected_admin", request, user=user)
            notify_change("user_enable_protected_admin", f"User '{user['username']}' enabled protected admin status")
            flash("Protected admin status enabled.", "success")
        else:
            db.update_user(user["id"], role="admin")
            log_action("disable_protected_admin", request, user=user)
            notify_change("user_disable_protected_admin", f"User '{user['username']}' disabled protected admin status")
            flash("Protected admin status disabled.", "success")
        return redirect(url_for("account_settings"))

    categories, uncategorized = db.get_category_tree()
    return render_template("account/settings.html", user=user,
                           categories=categories, uncategorized=uncategorized)


# ---------------------------------------------------------------------------
#  Wiki – Home & pages
# ---------------------------------------------------------------------------
@app.route("/")
@login_required
def home():
    page = db.get_home_page()
    user = get_current_user()
    content_html = render_markdown(page["content"]) if page else ""
    categories, uncategorized = db.get_category_tree()

    editor_info = None
    if page and page["last_edited_by"]:
        editor = db.get_user_by_id(page["last_edited_by"])
        if editor:
            editor_info = {
                "username": editor["username"],
                "time_ago": time_ago(page["last_edited_at"]),
                "edited_at": format_datetime(page["last_edited_at"]),
            }

    log_action("view_page", request, user=user, page="home")
    return render_template(
        "wiki/page.html",
        page=page,
        content_html=content_html,
        categories=categories,
        uncategorized=uncategorized,
        editor_info=editor_info,
    )


@app.route("/page/<slug>")
@login_required
def view_page(slug):
    page = db.get_page_by_slug(slug)
    if not page:
        abort(404)
    user = get_current_user()
    content_html = render_markdown(page["content"])
    categories, uncategorized = db.get_category_tree()

    editor_info = None
    if page["last_edited_by"]:
        editor = db.get_user_by_id(page["last_edited_by"])
        if editor:
            editor_info = {
                "username": editor["username"],
                "time_ago": time_ago(page["last_edited_at"]),
                "edited_at": format_datetime(page["last_edited_at"]),
            }

    log_action("view_page", request, user=user, page=slug)
    return render_template(
        "wiki/page.html",
        page=page,
        content_html=content_html,
        categories=categories,
        uncategorized=uncategorized,
        editor_info=editor_info,
    )


@app.route("/page/<slug>/history")
@login_required
def page_history(slug):
    if not config.PAGE_HISTORY_ENABLED:
        abort(404)
    page = db.get_page_by_slug(slug)
    if not page:
        abort(404)
    history = db.get_page_history(page["id"])
    current_user = get_current_user()
    all_users = db.list_users() if current_user and current_user["role"] in ("admin", "protected_admin") else []
    categories, uncategorized = db.get_category_tree()
    return render_template(
        "wiki/history.html",
        page=page,
        history=history,
        all_users=all_users,
        categories=categories,
        uncategorized=uncategorized,
    )


@app.route("/page/<slug>/history/<int:entry_id>")
@login_required
def view_history_entry(slug, entry_id):
    if not config.PAGE_HISTORY_ENABLED:
        abort(404)
    page = db.get_page_by_slug(slug)
    if not page:
        abort(404)
    entry = db.get_history_entry(entry_id)
    if not entry or entry["page_id"] != page["id"]:
        abort(404)
    content_html = render_markdown(entry["content"])
    categories, uncategorized = db.get_category_tree()
    return render_template(
        "wiki/history_entry.html",
        page=page,
        entry=entry,
        content_html=content_html,
        categories=categories,
        uncategorized=uncategorized,
    )


@app.route("/page/<slug>/revert/<int:entry_id>", methods=["POST"])
@login_required
@editor_required
@rate_limit(20, 60)
def revert_page(slug, entry_id):
    if not config.PAGE_HISTORY_ENABLED:
        abort(404)
    page = db.get_page_by_slug(slug)
    if not page:
        abort(404)
    entry = db.get_history_entry(entry_id)
    if not entry or entry["page_id"] != page["id"]:
        abort(404)
    user = get_current_user()
    db.update_page(page["id"], entry["title"], entry["content"], user["id"],
                   f"Reverted to version from {entry['created_at']}")
    log_action("revert_page", request, user=user, page=slug, entry_id=entry_id)
    notify_change("page_revert", f"Page '{slug}' reverted")
    flash("Page reverted.", "success")
    return redirect(url_for("view_page", slug=slug))


@app.route("/page/<slug>/history/<int:entry_id>/transfer", methods=["POST"])
@login_required
@admin_required
@rate_limit(20, 60)
def transfer_attribution(slug, entry_id):
    if not config.PAGE_HISTORY_ENABLED:
        abort(404)
    page = db.get_page_by_slug(slug)
    if not page:
        abort(404)
    entry = db.get_history_entry(entry_id)
    if not entry or entry["page_id"] != page["id"]:
        abort(404)
    new_user_id = request.form.get("new_user_id", "").strip()
    target_user = db.get_user_by_id(new_user_id) if new_user_id else None
    if not target_user:
        flash("Invalid target user.", "error")
        return redirect(url_for("page_history", slug=slug))
    user = get_current_user()
    db.transfer_history_attribution(entry_id, new_user_id)
    log_action("transfer_attribution", request, user=user, page=slug,
               entry_id=entry_id, new_user=target_user["username"])
    notify_change("transfer_attribution",
                  f"Attribution of entry {entry_id} on '{slug}' transferred to '{target_user['username']}'")
    flash(f"Attribution transferred to {target_user['username']}.", "success")
    return redirect(url_for("page_history", slug=slug))


@app.route("/page/<slug>/history/bulk-transfer", methods=["POST"])
@login_required
@admin_required
@rate_limit(20, 60)
def bulk_transfer_attribution(slug):
    if not config.PAGE_HISTORY_ENABLED:
        abort(404)
    page = db.get_page_by_slug(slug)
    if not page:
        abort(404)
    from_user_id = request.form.get("from_user_id", "").strip()
    new_user_id = request.form.get("new_user_id", "").strip()
    from_user = db.get_user_by_id(from_user_id) if from_user_id else None
    target_user = db.get_user_by_id(new_user_id) if new_user_id else None
    if not from_user or not target_user:
        flash("Invalid user selection.", "error")
        return redirect(url_for("page_history", slug=slug))
    user = get_current_user()
    count = db.bulk_transfer_history_attribution(page["id"], from_user_id, new_user_id)
    log_action("bulk_transfer_attribution", request, user=user, page=slug,
               from_user=from_user["username"], to_user=target_user["username"], count=count)
    notify_change("bulk_transfer_attribution",
                  f"Bulk attribution on '{slug}' transferred from '{from_user['username']}' to '{target_user['username']}'")
    flash(f"Transferred {count} contribution(s) to {target_user['username']}.", "success")
    return redirect(url_for("page_history", slug=slug))


# ---------------------------------------------------------------------------
#  Page editing
# ---------------------------------------------------------------------------
@app.route("/page/<slug>/edit", methods=["GET", "POST"])
@login_required
@editor_required
@rate_limit(20, 60)
def edit_page(slug):
    page = db.get_page_by_slug(slug)
    if not page:
        abort(404)
    user = get_current_user()
    categories, uncategorized = db.get_category_tree()

    # Check for existing drafts from other users
    other_drafts = [
        d for d in db.get_drafts_for_page(page["id"]) if d["user_id"] != user["id"]
    ]

    if request.method == "POST":
        title = request.form.get("title", page["title"]).strip()
        content = request.form.get("content", "")
        edit_message = request.form.get("edit_message", "").strip()
        if not title:
            title = page["title"]

        # Collect contributor names from other users' drafts
        all_drafts = db.get_drafts_for_page(page["id"])
        contributors = [d["username"] for d in all_drafts if d["user_id"] != user["id"]]

        # Build commit message with contributors
        if contributors:
            contributor_list = ", ".join(contributors)
            if edit_message:
                edit_message = f"{edit_message} (contributors: {contributor_list})"
            else:
                edit_message = f"Contributors: {contributor_list}"

        db.update_page(page["id"], title, content, user["id"], edit_message)

        # Clean up all drafts for this page (committer + contributors)
        db.delete_draft(page["id"], user["id"])
        for d in all_drafts:
            if d["user_id"] != user["id"]:
                db.delete_draft(page["id"], d["user_id"])

        cleanup_unused_uploads()
        log_action("edit_page", request, user=user, page=slug, message=edit_message)
        notify_change("page_edit", f"Page '{slug}' edited")
        flash("Page updated.", "success")
        if page["is_home"]:
            return redirect(url_for("home"))
        return redirect(url_for("view_page", slug=slug))

    # Load draft if exists
    draft = db.get_draft(page["id"], user["id"])
    return render_template(
        "wiki/edit.html",
        page=page,
        draft=draft,
        other_drafts=other_drafts,
        categories=categories,
        uncategorized=uncategorized,
    )


@app.route("/page/<slug>/edit/title", methods=["POST"])
@login_required
@editor_required
@rate_limit(20, 60)
def edit_page_title(slug):
    page = db.get_page_by_slug(slug)
    if not page:
        abort(404)
    user = get_current_user()
    new_title = request.form.get("title", "").strip()
    if not new_title:
        flash("Title is required.", "error")
    elif len(new_title) > 200:
        flash("Title must be 200 characters or fewer.", "error")
    else:
        db.update_page_title(page["id"], new_title, user["id"])
        log_action("edit_page_title", request, user=user, page=slug, new_title=new_title)
        notify_change("page_title_edit", f"Page '{slug}' title changed to '{new_title}'")
        flash("Title updated.", "success")
    if page["is_home"]:
        return redirect(url_for("home"))
    return redirect(url_for("view_page", slug=slug))


# ---------------------------------------------------------------------------
#  Page/Category CRUD (editors/admins)
# ---------------------------------------------------------------------------
@app.route("/create-page", methods=["GET", "POST"])
@login_required
@editor_required
@rate_limit(20, 60)
def create_page():
    user = get_current_user()
    categories, uncategorized = db.get_category_tree()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "")
        cat_id = request.form.get("category_id")
        form_data = {"title": title, "content": content, "category_id": cat_id or ""}
        try:
            cat_id = int(cat_id) if cat_id else None
        except (TypeError, ValueError):
            flash("Invalid category.", "error")
            return render_template("wiki/create_page.html", categories=categories,
                                   uncategorized=uncategorized, form=form_data)
        if not title:
            flash("Title is required.", "error")
            return render_template("wiki/create_page.html", categories=categories,
                                   uncategorized=uncategorized, form=form_data)
        if len(title) > 200:
            flash("Title must be 200 characters or fewer.", "error")
            return render_template("wiki/create_page.html", categories=categories,
                                   uncategorized=uncategorized, form=form_data)
        if cat_id and not db.get_category(cat_id):
            flash("Selected category does not exist.", "error")
            return render_template("wiki/create_page.html", categories=categories,
                                   uncategorized=uncategorized, form=form_data)
        slug = slugify(title)
        # ensure unique slug
        base_slug = slug
        counter = 1
        while db.get_page_by_slug(slug):
            slug = f"{base_slug}-{counter}"
            counter += 1
        db.create_page(title, slug, content, cat_id, user["id"])
        cleanup_unused_uploads()
        log_action("create_page", request, user=user, page=slug)
        notify_change("page_create", f"Page '{slug}' created")
        flash("Page created. Open it to start editing with Markdown.", "success")
        return redirect(url_for("view_page", slug=slug))

    return render_template("wiki/create_page.html", categories=categories,
                           uncategorized=uncategorized)


@app.route("/page/<slug>/delete", methods=["POST"])
@login_required
@editor_required
@rate_limit(10, 60)
def delete_page_route(slug):
    page = db.get_page_by_slug(slug)
    if not page:
        abort(404)
    if page["is_home"]:
        flash("Cannot delete the home page.", "error")
        return redirect(url_for("view_page", slug=slug))
    user = get_current_user()
    db.delete_page(page["id"])
    cleanup_unused_uploads()
    log_action("delete_page", request, user=user, page=slug)
    notify_change("page_delete", f"Page '{slug}' deleted")
    flash("Page deleted.", "success")
    return redirect(url_for("home"))


@app.route("/page/<slug>/move", methods=["POST"])
@login_required
@editor_required
@rate_limit(20, 60)
def move_page(slug):
    page = db.get_page_by_slug(slug)
    if not page:
        abort(404)
    cat_id = request.form.get("category_id")
    try:
        cat_id = int(cat_id) if cat_id else None
    except (TypeError, ValueError):
        flash("Invalid category.", "error")
        return redirect(url_for("view_page", slug=slug))
    if cat_id and not db.get_category(cat_id):
        flash("Selected category does not exist.", "error")
        return redirect(url_for("view_page", slug=slug))
    user = get_current_user()
    db.update_page_category(page["id"], cat_id)
    log_action("move_page", request, user=user, page=slug, category_id=cat_id)
    notify_change("page_move", f"Page '{slug}' moved")
    flash("Page moved.", "success")
    return redirect(url_for("view_page", slug=slug))


@app.route("/category/create", methods=["POST"])
@login_required
@editor_required
@rate_limit(20, 60)
def create_category():
    name = request.form.get("name", "").strip()
    parent_id = request.form.get("parent_id")
    try:
        parent_id = int(parent_id) if parent_id else None
    except (TypeError, ValueError):
        flash("Invalid parent category.", "error")
        return redirect(_safe_referrer() or url_for("home"))
    if not name:
        flash("Category name is required.", "error")
        return redirect(_safe_referrer() or url_for("home"))
    if len(name) > 100:
        flash("Category name must be 100 characters or fewer.", "error")
        return redirect(_safe_referrer() or url_for("home"))
    if parent_id and not db.get_category(parent_id):
        flash("Selected parent category does not exist.", "error")
        return redirect(_safe_referrer() or url_for("home"))
    db.create_category(name, parent_id)
    user = get_current_user()
    log_action("create_category", request, user=user, category=name)
    notify_change("category_create", f"Category '{name}' created")
    flash("Category created.", "success")
    return redirect(_safe_referrer() or url_for("home"))


@app.route("/category/<int:cat_id>/edit", methods=["POST"])
@login_required
@editor_required
@rate_limit(20, 60)
def edit_category(cat_id):
    cat = db.get_category(cat_id)
    if not cat:
        abort(404)
    name = request.form.get("name", "").strip()
    if not name:
        flash("Category name is required.", "error")
        return redirect(_safe_referrer() or url_for("home"))
    if len(name) > 100:
        flash("Category name must be 100 characters or fewer.", "error")
        return redirect(_safe_referrer() or url_for("home"))
    db.update_category(cat_id, name)
    user = get_current_user()
    log_action("edit_category", request, user=user, category_id=cat_id, new_name=name)
    notify_change("category_edit", f"Category {cat_id} renamed to '{name}'")
    flash("Category updated.", "success")
    return redirect(_safe_referrer() or url_for("home"))


@app.route("/category/<int:cat_id>/move", methods=["POST"])
@login_required
@editor_required
@rate_limit(20, 60)
def move_category(cat_id):
    cat = db.get_category(cat_id)
    if not cat:
        abort(404)
    parent_id = request.form.get("parent_id")
    try:
        parent_id = int(parent_id) if parent_id else None
    except (TypeError, ValueError):
        parent_id = None
    # Prevent moving a category into itself or a descendant (circular ref)
    if parent_id == cat_id:
        flash("Cannot move a category into itself.", "error")
        return redirect(_safe_referrer() or url_for("home"))
    if parent_id and not db.get_category(parent_id):
        flash("Target category does not exist.", "error")
        return redirect(_safe_referrer() or url_for("home"))
    if parent_id and db.is_descendant_of(cat_id, parent_id):
        flash("Cannot move a category into one of its own subcategories.", "error")
        return redirect(_safe_referrer() or url_for("home"))
    db.update_category_parent(cat_id, parent_id)
    user = get_current_user()
    log_action("move_category", request, user=user, category_id=cat_id, new_parent=parent_id)
    notify_change("category_move", f"Category {cat_id} moved to parent {parent_id}")
    flash("Category moved.", "success")
    return redirect(_safe_referrer() or url_for("home"))


@app.route("/category/<int:cat_id>/delete", methods=["POST"])
@login_required
@editor_required
@rate_limit(10, 60)
def delete_category_route(cat_id):
    cat = db.get_category(cat_id)
    if not cat:
        abort(404)
    page_action = request.form.get("page_action", "uncategorize")
    target_cat = request.form.get("target_category_id")
    try:
        target_cat = int(target_cat) if target_cat else None
    except (TypeError, ValueError):
        target_cat = None
    if page_action not in ("uncategorize", "delete", "move"):
        page_action = "uncategorize"
    if page_action == "move" and (not target_cat or target_cat == cat_id
                                  or not db.get_category(target_cat)):
        page_action = "uncategorize"
    db.delete_category(cat_id, page_action=page_action, target_category_id=target_cat)
    user = get_current_user()
    log_action("delete_category", request, user=user, category_id=cat_id, page_action=page_action)
    notify_change("category_delete", f"Category {cat_id} deleted")
    flash("Category deleted.", "success")
    return redirect(_safe_referrer() or url_for("home"))


# ---------------------------------------------------------------------------
#  Live preview API
# ---------------------------------------------------------------------------
@app.route("/api/preview", methods=["POST"])
@login_required
@rate_limit(30, 60)
def api_preview():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid request: missing or malformed JSON"}), 400
    content = data.get("content", "")
    html = render_markdown(content)
    return jsonify({"html": html})


# ---------------------------------------------------------------------------
#  Drafts / autosave API
# ---------------------------------------------------------------------------
@app.route("/api/draft/save", methods=["POST"])
@login_required
@editor_required
@rate_limit(30, 60)
def api_save_draft():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "invalid request"}), 400
    page_id = data.get("page_id")
    if page_id is None:
        return jsonify({"error": "missing page_id"}), 400
    try:
        page_id = int(page_id)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid page_id"}), 400
    title = data.get("title", "")
    content = data.get("content", "")
    user = get_current_user()
    page = db.get_page(page_id)
    if not page:
        return jsonify({"error": "page not found"}), 404
    db.save_draft(page_id, user["id"], title, content)
    return jsonify({"ok": True})


@app.route("/api/draft/load/<int:page_id>")
@login_required
@editor_required
def api_load_draft(page_id):
    user = get_current_user()
    draft = db.get_draft(page_id, user["id"])
    if draft:
        return jsonify({"title": draft["title"], "content": draft["content"],
                        "updated_at": draft["updated_at"]})
    return jsonify({"title": None, "content": None})


@app.route("/api/draft/others/<int:page_id>")
@login_required
@editor_required
def api_other_drafts(page_id):
    user = get_current_user()
    page = db.get_page(page_id)
    if not page:
        return jsonify({"error": "page not found"}), 404
    drafts = db.get_drafts_for_page(page_id)
    others = [{"username": d["username"], "user_id": d["user_id"],
               "updated_at": d["updated_at"]} for d in drafts if d["user_id"] != user["id"]]
    return jsonify({"drafts": others, "page_last_edited_at": page["last_edited_at"]})


@app.route("/api/draft/transfer", methods=["POST"])
@login_required
@editor_required
@rate_limit(30, 60)
def api_transfer_draft():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "invalid request"}), 400
    page_id = data.get("page_id")
    from_user = data.get("from_user_id")
    try:
        page_id = int(page_id)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid page_id or from_user_id"}), 400
    if not from_user:
        return jsonify({"error": "invalid page_id or from_user_id"}), 400
    user = get_current_user()
    if from_user == user["id"]:
        return jsonify({"error": "cannot transfer draft from yourself"}), 400
    source_draft = db.get_draft(page_id, from_user)
    if not source_draft:
        return jsonify({"error": "draft not found"}), 404
    db.transfer_draft(page_id, from_user, user["id"])
    log_action("transfer_draft", request, user=user, page_id=page_id, from_user=from_user)
    return jsonify({"ok": True})


@app.route("/api/draft/delete", methods=["POST"])
@login_required
@editor_required
@rate_limit(30, 60)
def api_delete_draft():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "invalid request"}), 400
    page_id = data.get("page_id")
    if page_id is None:
        return jsonify({"error": "missing page_id"}), 400
    try:
        page_id = int(page_id)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid page_id"}), 400
    user = get_current_user()
    db.delete_draft(page_id, user["id"])
    cleanup_unused_uploads()
    return jsonify({"ok": True})


@app.route("/api/draft/mine")
@login_required
@editor_required
def api_my_drafts():
    """List all pending drafts for the current user."""
    user = get_current_user()
    drafts = db.list_user_drafts(user["id"])
    return jsonify([
        {
            "page_id": d["page_id"],
            "page_title": d["page_title"],
            "page_slug": d["page_slug"],
            "title": d["title"],
            "updated_at": d["updated_at"],
            "updated_at_formatted": format_datetime(d["updated_at"]),
        }
        for d in drafts
    ])


# ---------------------------------------------------------------------------
#  Image upload
# ---------------------------------------------------------------------------
def cleanup_unused_uploads():
    """Delete uploaded image files that are not referenced in any page or history.

    Called after draft deletion, page commit, page creation, and page deletion
    so that images uploaded but never committed (or removed before committing)
    are automatically purged.  Images still present in the revision history are
    preserved because :func:`db.get_all_referenced_image_filenames` scans
    both ``pages.content`` and ``page_history.content``.
    """
    if not os.path.isdir(config.UPLOAD_FOLDER):
        return
    referenced = db.get_all_referenced_image_filenames()
    for fname in os.listdir(config.UPLOAD_FOLDER):
        if fname.startswith("."):
            continue
        if fname not in referenced:
            fpath = os.path.join(config.UPLOAD_FOLDER, fname)
            if os.path.isfile(fpath):
                try:
                    os.remove(fpath)
                except OSError:
                    pass


@app.route("/api/upload", methods=["POST"])
@login_required
@editor_required
@rate_limit(10, 60)
def upload_image():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename or not allowed_file(f.filename):
        return jsonify({"error": "Invalid file type"}), 400
    # Validate that the file is a genuine image by reading it with Pillow
    try:
        img = Image.open(f.stream)
        img.verify()
        f.stream.seek(0)
    except Exception:
        return jsonify({"error": "File is not a valid image"}), 400
    os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
    ext = f.filename.rsplit(".", 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    upload_root = os.path.abspath(config.UPLOAD_FOLDER)
    filepath = os.path.abspath(os.path.normpath(os.path.join(upload_root, filename)))
    if os.path.commonpath([upload_root, filepath]) != upload_root:
        return jsonify({"error": "Invalid upload path"}), 400
    f.save(filepath)
    user = get_current_user()
    log_action("upload_image", request, user=user, filename=filename)
    notify_file_upload(filename, filepath)
    url = url_for("static", filename=f"uploads/{filename}")
    return jsonify({"url": url, "filename": filename})


@app.route("/api/upload/delete", methods=["POST"])
@login_required
@editor_required
@rate_limit(10, 60)
def delete_upload():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "invalid request"}), 400
    filename = data.get("filename", "")
    safe_name = secure_filename(filename)
    if not safe_name:
        return jsonify({"error": "invalid filename"}), 400
    filepath = os.path.join(config.UPLOAD_FOLDER, safe_name)
    upload_root = os.path.abspath(config.UPLOAD_FOLDER)
    filepath = os.path.abspath(os.path.normpath(filepath))
    if os.path.commonpath([upload_root, filepath]) != upload_root:
        return jsonify({"error": "invalid filename"}), 400
    if os.path.isfile(filepath):
        os.remove(filepath)
        user = get_current_user()
        log_action("delete_upload", request, user=user, filename=safe_name)
        notify_file_deleted(safe_name)
    return jsonify({"ok": True})


@app.route("/easter-egg")
@login_required
def easter_egg():
    """Easter egg celebration page — shows whether the user has found the egg."""
    user = get_current_user()
    categories, uncategorized = db.get_category_tree()
    return render_template(
        "wiki/easter_egg.html",
        categories=categories,
        uncategorized=uncategorized,
    )


@app.route("/api/easter-egg/trigger", methods=["POST"])
@login_required
@rate_limit(10, 60)
def easter_egg_trigger():
    """Record that the logged-in user has found the easter egg (one-way flag)."""
    user = get_current_user()
    db.set_easter_egg_found(user["id"])
    log_action("easter_egg_triggered", request, user=user)
    return jsonify({"ok": True})


@app.route("/api/reorder/pages", methods=["POST"])
@login_required
@editor_required
@rate_limit(60, 60)
def api_reorder_pages():
    """Persist a new page sort order. Body: {"ids": [<page_id>, ...]}"""
    data = request.get_json(silent=True)
    if not data or not isinstance(data.get("ids"), list):
        return jsonify({"error": "invalid request"}), 400
    try:
        ids = [int(i) for i in data["ids"]]
    except (TypeError, ValueError):
        return jsonify({"error": "invalid ids"}), 400
    db.update_pages_sort_order(ids)
    user = get_current_user()
    log_action("reorder_pages", request, user=user, count=len(ids))
    notify_change("pages_reorder", "Page order updated")
    return jsonify({"ok": True})


@app.route("/api/reorder/categories", methods=["POST"])
@login_required
@editor_required
@rate_limit(60, 60)
def api_reorder_categories():
    """Persist a new category sort order. Body: {"ids": [<cat_id>, ...]}"""
    data = request.get_json(silent=True)
    if not data or not isinstance(data.get("ids"), list):
        return jsonify({"error": "invalid request"}), 400
    try:
        ids = [int(i) for i in data["ids"]]
    except (TypeError, ValueError):
        return jsonify({"error": "invalid ids"}), 400
    db.update_categories_sort_order(ids)
    user = get_current_user()
    log_action("reorder_categories", request, user=user, count=len(ids))
    notify_change("categories_reorder", "Category order updated")
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
#  Admin – User management
# ---------------------------------------------------------------------------
@app.route("/admin/users")
@login_required
@admin_required
def admin_users():
    role_filter = request.args.get("role")
    status_filter = request.args.get("status")
    users = db.list_users(role_filter=role_filter, status_filter=status_filter)
    categories, uncategorized = db.get_category_tree()
    return render_template("admin/users.html", users=users,
                           role_filter=role_filter, status_filter=status_filter,
                           categories=categories, uncategorized=uncategorized)


@app.route("/admin/users/<string:user_id>/edit", methods=["POST"])
@login_required
@admin_required
def admin_edit_user(user_id):
    target = db.get_user_by_id(user_id)
    if not target:
        abort(404)
    action = request.form.get("action", "")
    current_user = get_current_user()

    if target["is_superuser"]:
        flash("This account is protected and cannot be modified.", "error")
        return redirect(url_for("admin_users"))

    if action == "change_username":
        if target["role"] == "protected_admin" and user_id != current_user["id"]:
            flash("Protected admin accounts can only be edited by their owner.", "error")
            return redirect(url_for("admin_users"))
        new_name = request.form.get("username", "").strip()
        if not new_name or len(new_name) < 3:
            flash("Username must be at least 3 characters.", "error")
        elif len(new_name) > 50:
            flash("Username must be 50 characters or fewer.", "error")
        elif not _is_valid_username(new_name):
            flash("Username may only contain letters, digits, underscores and hyphens.", "error")
        else:
            existing = db.get_user_by_username(new_name)
            if existing and existing["id"] != user_id:
                flash("Username already taken.", "error")
            else:
                try:
                    db.update_user(user_id, username=new_name)
                except sqlite3.IntegrityError:
                    flash("Username already taken.", "error")
                    return redirect(url_for("admin_users"))
                else:
                    db.record_username_change(user_id, target["username"], new_name)
                    log_action("admin_change_username", request, user=current_user,
                               target_user=target["username"], new_username=new_name)
                    notify_change("admin_change_username", f"User '{target['username']}' renamed to '{new_name}'")
                    flash("Username updated.", "success")

    elif action == "change_password":
        if target["role"] == "protected_admin" and user_id != current_user["id"]:
            flash("Protected admin accounts can only be edited by their owner.", "error")
            return redirect(url_for("admin_users"))
        new_pw = request.form.get("password", "")
        confirm_pw = request.form.get("confirm_password", "")
        if len(new_pw) < 6:
            flash("Password must be at least 6 characters.", "error")
        elif new_pw != confirm_pw:
            flash("Passwords do not match.", "error")
        else:
            db.update_user(user_id, password=generate_password_hash(new_pw))
            log_action("admin_change_password", request, user=current_user,
                       target_user=target["username"])
            notify_change("admin_change_password", f"Password changed for '{target['username']}'")
            flash("Password updated.", "success")

    elif action == "change_role":
        new_role = request.form.get("role", "")
        if new_role not in ("user", "editor", "admin"):
            flash("Invalid role.", "error")
        elif target["role"] == "protected_admin":
            flash("Protected admin status can only be changed by the account owner.", "error")
        elif user_id == current_user["id"] and new_role != current_user["role"]:
            flash("Cannot change your own role.", "error")
        elif target["role"] in ("admin", "protected_admin") and new_role not in ("admin", "protected_admin") and db.count_admins() <= 1:
            flash("Cannot demote the last admin.", "error")
        else:
            db.update_user(user_id, role=new_role)
            log_action("admin_change_role", request, user=current_user,
                       target_user=target["username"], new_role=new_role)
            notify_change("admin_change_role", f"User '{target['username']}' role changed to '{new_role}'")
            flash("Role updated.", "success")

    elif action == "suspend":
        if user_id == current_user["id"]:
            flash("Cannot suspend your own account.", "error")
        elif target["role"] == "protected_admin":
            flash("Protected admin accounts cannot be suspended by other admins.", "error")
        elif target["role"] in ("admin", "protected_admin") and db.count_admins() <= 1:
            flash("Cannot suspend the last admin.", "error")
        else:
            db.update_user(user_id, suspended=1)
            log_action("admin_suspend", request, user=current_user,
                       target_user=target["username"])
            notify_change("admin_suspend", f"User '{target['username']}' suspended")
            flash("User suspended.", "success")

    elif action == "unsuspend":
        db.update_user(user_id, suspended=0)
        log_action("admin_unsuspend", request, user=current_user,
                   target_user=target["username"])
        notify_change("admin_unsuspend", f"User '{target['username']}' unsuspended")
        flash("User unsuspended.", "success")

    elif action == "delete":
        if user_id == current_user["id"]:
            flash("Cannot delete your own account from here. Use account settings instead.", "error")
        elif target["role"] == "protected_admin":
            flash("Protected admin accounts cannot be deleted by other admins.", "error")
        elif target["role"] in ("admin", "protected_admin") and db.count_admins() <= 1:
            flash("Cannot delete the last admin.", "error")
        else:
            db.delete_user(user_id)
            log_action("admin_delete_user", request, user=current_user,
                       target_user=target["username"])
            notify_change("admin_delete_user", f"User '{target['username']}' deleted")
            flash("User deleted.", "success")

    return redirect(url_for("admin_users"))


@app.route("/admin/users/create", methods=["POST"])
@login_required
@admin_required
def admin_create_user():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    confirm = request.form.get("confirm_password", "")
    role = request.form.get("role", "user")

    if not username or not password:
        flash("Username and password are required.", "error")
    elif len(username) < 3:
        flash("Username must be at least 3 characters.", "error")
    elif len(username) > 50:
        flash("Username must be 50 characters or fewer.", "error")
    elif not _is_valid_username(username):
        flash("Username may only contain letters, digits, underscores and hyphens.", "error")
    elif password != confirm:
        flash("Passwords do not match.", "error")
    elif len(password) < 6:
        flash("Password must be at least 6 characters.", "error")
    elif role not in ("user", "editor", "admin"):
        flash("Invalid role.", "error")
    elif db.get_user_by_username(username):
        flash("Username already taken.", "error")
    else:
        hashed = generate_password_hash(password)
        try:
            db.create_user(username, hashed, role=role)
        except sqlite3.IntegrityError:
            flash("Username already taken.", "error")
            return redirect(url_for("admin_users"))
        current_user = get_current_user()
        log_action("admin_create_user", request, user=current_user,
                   new_username=username, role=role)
        notify_change("admin_create_user", f"User '{username}' created with role '{role}'")
        flash(f"User '{username}' created.", "success")

    return redirect(url_for("admin_users"))


# ---------------------------------------------------------------------------
#  Admin – Invite codes
# ---------------------------------------------------------------------------
@app.route("/admin/codes")
@login_required
@admin_required
def admin_codes():
    codes = db.list_invite_codes(active_only=True)
    categories, uncategorized = db.get_category_tree()
    return render_template("admin/codes.html", codes=codes,
                           categories=categories, uncategorized=uncategorized)


@app.route("/admin/codes/expired")
@login_required
@admin_required
def admin_codes_expired():
    codes = db.list_expired_codes()
    categories, uncategorized = db.get_category_tree()
    return render_template("admin/codes_expired.html", codes=codes,
                           categories=categories, uncategorized=uncategorized)


@app.route("/admin/codes/generate", methods=["POST"])
@login_required
@admin_required
def admin_generate_code():
    user = get_current_user()
    code = db.generate_invite_code(user["id"])
    log_action("generate_invite_code", request, user=user, code=code)
    notify_change("invite_code_generate", f"Invite code '{code}' generated")
    flash(f"Invite code generated: {code}", "success")
    return redirect(url_for("admin_codes"))


@app.route("/admin/codes/<int:code_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_delete_code(code_id):
    user = get_current_user()
    db.delete_invite_code(code_id)
    log_action("delete_invite_code", request, user=user, code_id=code_id)
    notify_change("invite_code_delete", f"Invite code {code_id} deleted")
    flash("Invite code deleted.", "success")
    return redirect(url_for("admin_codes"))


@app.route("/admin/codes/expired/<int:code_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_hard_delete_code(code_id):
    user = get_current_user()
    db.hard_delete_invite_code(code_id)
    log_action("hard_delete_invite_code", request, user=user, code_id=code_id)
    notify_change("invite_code_hard_delete", f"Invite code {code_id} permanently removed")
    flash("Invite code permanently removed.", "success")
    return redirect(url_for("admin_codes_expired"))


# ---------------------------------------------------------------------------
#  Admin – Site settings
# ---------------------------------------------------------------------------

_VALID_FAVICON_TYPES = {'yellow', 'green', 'blue', 'red', 'orange', 'cyan', 'purple', 'lime', 'custom'}
_FAVICON_ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "ico", "gif", "webp"}
FAVICON_UPLOAD_FOLDER = os.path.join(app.static_folder, "favicons")


def _allowed_favicon_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in _FAVICON_ALLOWED_EXTENSIONS


@app.route("/admin/settings", methods=["GET", "POST"])
@login_required
@admin_required
def admin_settings():
    if request.method == "POST":
        site_name = request.form.get("site_name", "").strip() or "BananaWiki"
        if len(site_name) > 100:
            flash("Site name must be 100 characters or fewer.", "error")
            return redirect(url_for("admin_settings"))
        color_fields = {
            "primary_color": request.form.get("primary_color", "#7c8dc6"),
            "secondary_color": request.form.get("secondary_color", "#151520"),
            "accent_color": request.form.get("accent_color", "#6e8aca"),
            "text_color": request.form.get("text_color", "#b8bcc8"),
            "sidebar_color": request.form.get("sidebar_color", "#111118"),
            "bg_color": request.form.get("bg_color", "#0d0d14"),
        }
        for name, val in color_fields.items():
            if not _is_valid_hex_color(val):
                flash(f"Invalid color value for {name}.", "error")
                return redirect(url_for("admin_settings"))
        tz_name = request.form.get("timezone", "UTC").strip() or "UTC"
        try:
            ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, KeyError):
            flash("Invalid time zone selected.", "error")
            return redirect(url_for("admin_settings"))

        # Favicon settings
        favicon_enabled = 1 if request.form.get("favicon_enabled") else 0
        favicon_type = request.form.get("favicon_type", "yellow").strip()
        if favicon_type not in _VALID_FAVICON_TYPES:
            favicon_type = "yellow"

        current_settings = db.get_site_settings()
        favicon_custom = current_settings["favicon_custom"] if current_settings["favicon_custom"] else ""

        if favicon_type == "custom":
            f = request.files.get("favicon_custom_file")
            if f and f.filename and _allowed_favicon_file(f.filename):
                try:
                    img = Image.open(f.stream)
                    img.verify()
                    f.stream.seek(0)
                except Exception:
                    flash("Custom favicon is not a valid image.", "error")
                    return redirect(url_for("admin_settings"))
                # Remove old custom favicon if present
                if favicon_custom:
                    old_path = os.path.join(FAVICON_UPLOAD_FOLDER, favicon_custom)
                    if os.path.isfile(old_path) and favicon_custom.startswith("custom_"):
                        try:
                            os.remove(old_path)
                        except OSError:
                            pass
                os.makedirs(FAVICON_UPLOAD_FOLDER, exist_ok=True)
                ext = f.filename.rsplit(".", 1)[1].lower()
                favicon_custom = f"custom_{uuid.uuid4().hex}.{ext}"
                upload_root = os.path.abspath(FAVICON_UPLOAD_FOLDER)
                filepath = os.path.abspath(os.path.join(upload_root, favicon_custom))
                if os.path.commonpath([upload_root, filepath]) != upload_root:
                    flash("Invalid favicon upload path.", "error")
                    return redirect(url_for("admin_settings"))
                f.save(filepath)

        db.update_site_settings(
            site_name=site_name,
            timezone=tz_name,
            favicon_enabled=favicon_enabled,
            favicon_type=favicon_type,
            favicon_custom=favicon_custom,
            lockdown_mode=1 if request.form.get("lockdown_mode") else 0,
            lockdown_message=request.form.get("lockdown_message", "").strip()[:1000],
            **color_fields,
        )
        user = get_current_user()
        log_action("update_settings", request, user=user, site_name=site_name)
        notify_change("settings_update", f"Site settings updated (name='{site_name}')")
        flash("Settings updated.", "success")
        return redirect(url_for("admin_settings"))

    settings = db.get_site_settings()
    categories, uncategorized = db.get_category_tree()
    return render_template("admin/settings.html", settings=settings,
                           timezones=sorted(available_timezones()),
                           favicon_types=sorted(_VALID_FAVICON_TYPES - {"custom"}),
                           categories=categories, uncategorized=uncategorized)


@app.route("/admin/users/<string:user_id>/audit")
@login_required
@admin_required
def admin_user_audit(user_id):
    target = db.get_user_by_id(user_id)
    if not target:
        abort(404)
    log_entries = _read_user_audit_log(target["username"])
    username_history = db.get_username_history(user_id)
    categories, uncategorized = db.get_category_tree()
    return render_template("admin/audit.html", target=target,
                           log_entries=log_entries,
                           username_history=username_history,
                           categories=categories, uncategorized=uncategorized)


def _read_user_audit_log(username, max_entries=200):
    """Read log entries for a specific user from the log file."""
    log_file = config.LOG_FILE
    if not os.path.exists(log_file):
        return []
    entries = []
    search_term = f"user={username} "
    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if search_term in line:
                    entries.append(line.strip())
        # Return most recent entries first
        return entries[-max_entries:][::-1]
    except OSError:
        return []


# ---------------------------------------------------------------------------
#  Admin – Announcements
# ---------------------------------------------------------------------------
_VALID_ANN_COLORS = {"red", "orange", "yellow", "blue", "green"}
_VALID_ANN_SIZES = {"small", "normal", "large"}
_VALID_ANN_VISIBILITY = {"logged_in", "logged_out", "both"}


@app.route("/admin/announcements")
@login_required
@admin_required
def admin_announcements():
    announcements = db.list_announcements()
    categories, uncategorized = db.get_category_tree()
    return render_template("admin/announcements.html",
                           announcements=announcements,
                           categories=categories, uncategorized=uncategorized)


@app.route("/admin/announcements/create", methods=["POST"])
@login_required
@admin_required
def admin_create_announcement():
    content = request.form.get("content", "").strip()
    color = request.form.get("color", "orange")
    text_size = request.form.get("text_size", "normal")
    visibility = request.form.get("visibility", "both")
    expires_at = request.form.get("expires_at", "").strip() or None
    user = get_current_user()

    if not content:
        flash("Announcement content is required.", "error")
        return redirect(url_for("admin_announcements"))
    if len(content) > 2000:
        flash("Announcement content must be 2000 characters or fewer.", "error")
        return redirect(url_for("admin_announcements"))
    if color not in _VALID_ANN_COLORS:
        flash("Invalid color.", "error")
        return redirect(url_for("admin_announcements"))
    if text_size not in _VALID_ANN_SIZES:
        flash("Invalid text size.", "error")
        return redirect(url_for("admin_announcements"))
    if visibility not in _VALID_ANN_VISIBILITY:
        flash("Invalid visibility.", "error")
        return redirect(url_for("admin_announcements"))
    if expires_at:
        try:
            datetime.fromisoformat(expires_at)
        except ValueError:
            flash("Invalid expiration date format.", "error")
            return redirect(url_for("admin_announcements"))

    db.create_announcement(content, color, text_size, visibility, expires_at, user["id"])
    log_action("create_announcement", request, user=user)
    notify_change("announcement_create", "Announcement created")
    flash("Announcement created.", "success")
    return redirect(url_for("admin_announcements"))


@app.route("/admin/announcements/<int:ann_id>/edit", methods=["POST"])
@login_required
@admin_required
def admin_edit_announcement(ann_id):
    ann = db.get_announcement(ann_id)
    if not ann:
        abort(404)
    content = request.form.get("content", "").strip()
    color = request.form.get("color", "orange")
    text_size = request.form.get("text_size", "normal")
    visibility = request.form.get("visibility", "both")
    expires_at = request.form.get("expires_at", "").strip() or None
    is_active = 1 if request.form.get("is_active") else 0
    user = get_current_user()

    if not content:
        flash("Announcement content is required.", "error")
        return redirect(url_for("admin_announcements"))
    if len(content) > 2000:
        flash("Announcement content must be 2000 characters or fewer.", "error")
        return redirect(url_for("admin_announcements"))
    if color not in _VALID_ANN_COLORS:
        flash("Invalid color.", "error")
        return redirect(url_for("admin_announcements"))
    if text_size not in _VALID_ANN_SIZES:
        flash("Invalid text size.", "error")
        return redirect(url_for("admin_announcements"))
    if visibility not in _VALID_ANN_VISIBILITY:
        flash("Invalid visibility.", "error")
        return redirect(url_for("admin_announcements"))
    if expires_at:
        try:
            datetime.fromisoformat(expires_at)
        except ValueError:
            flash("Invalid expiration date format.", "error")
            return redirect(url_for("admin_announcements"))

    db.update_announcement(ann_id, content=content, color=color, text_size=text_size,
                           visibility=visibility, expires_at=expires_at, is_active=is_active)
    log_action("edit_announcement", request, user=user, ann_id=ann_id)
    notify_change("announcement_edit", f"Announcement {ann_id} updated")
    flash("Announcement updated.", "success")
    return redirect(url_for("admin_announcements"))


@app.route("/admin/announcements/<int:ann_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_delete_announcement(ann_id):
    ann = db.get_announcement(ann_id)
    if not ann:
        abort(404)
    user = get_current_user()
    db.delete_announcement(ann_id)
    log_action("delete_announcement", request, user=user, ann_id=ann_id)
    notify_change("announcement_delete", f"Announcement {ann_id} deleted")
    flash("Announcement deleted.", "success")
    return redirect(url_for("admin_announcements"))


# ---------------------------------------------------------------------------
#  Public – Announcement full view
# ---------------------------------------------------------------------------
@app.route("/announcements/<int:ann_id>")
def view_announcement(ann_id):
    ann = db.get_announcement(ann_id)
    if not ann:
        abort(404)
    # Check visibility
    user = get_current_user()
    is_logged_in = bool(user)
    if ann["visibility"] == "logged_in" and not is_logged_in:
        abort(404)
    if ann["visibility"] == "logged_out" and is_logged_in:
        abort(404)
    # Check if active and not expired
    if not ann["is_active"]:
        abort(404)
    if ann["expires_at"]:
        try:
            exp = datetime.fromisoformat(ann["expires_at"]).replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > exp:
                abort(404)
        except ValueError:
            pass
    content_html = render_markdown(ann["content"])
    categories, uncategorized = db.get_category_tree()
    return render_template("wiki/announcement.html", ann=ann,
                           content_html=content_html,
                           categories=categories, uncategorized=uncategorized)
#  Error handlers
# ---------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(e):
    categories, uncategorized = db.get_category_tree()
    return render_template("wiki/404.html", categories=categories,
                           uncategorized=uncategorized), 404


@app.errorhandler(403)
def forbidden(e):
    categories, uncategorized = db.get_category_tree()
    return render_template("wiki/403.html", categories=categories,
                           uncategorized=uncategorized), 403


@app.errorhandler(413)
def request_entity_too_large(e):
    flash("File too large. Maximum upload size is 16 MB.", "error")
    return redirect(_safe_referrer() or url_for("home"))


@app.errorhandler(429)
def too_many_requests(e):
    try:
        categories, uncategorized = db.get_category_tree()
    except Exception:
        categories, uncategorized = [], []
    return render_template("wiki/429.html", categories=categories,
                           uncategorized=uncategorized), 429


@app.errorhandler(500)
def internal_error(e):
    try:
        categories, uncategorized = db.get_category_tree()
    except Exception:
        categories, uncategorized = [], []
    return render_template("wiki/500.html", categories=categories,
                           uncategorized=uncategorized), 500


# ---------------------------------------------------------------------------
#  Main
# ---------------------------------------------------------------------------
db.init_db()
get_logger()

if __name__ == "__main__":
    # Development-only entry point.
    # For production, use:  gunicorn wsgi:app -c gunicorn.conf.py
    print(" * WARNING: Flask development server — not for production.")
    print(" * Production:  gunicorn wsgi:app -c gunicorn.conf.py")

    ssl_ctx = None
    if config.SSL_CERT and config.SSL_KEY:
        ssl_ctx = (config.SSL_CERT, config.SSL_KEY)

    app.run(host=config.HOST, port=config.PORT, debug=False,
            ssl_context=ssl_ctx)
