"""
BananaWiki – Main Flask application
"""

import os
import io
import re
import uuid
import json
import sqlite3
import difflib
import zipfile
import functools
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, send_from_directory, send_file, abort,
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
    db.record_login_attempt(ip)


def _clear_login_attempts():
    """Clear failed login attempts for the current IP (on successful login)."""
    ip = request.remote_addr or "unknown"
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


def compute_char_diff(old_text, new_text):
    """Return (added_chars, deleted_chars) between two text versions."""
    old_text = old_text or ""
    new_text = new_text or ""
    added = deleted = 0
    matcher = difflib.SequenceMatcher(None, old_text, new_text, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "insert":
            added += j2 - j1
        elif tag == "delete":
            deleted += i2 - i1
        elif tag == "replace":
            added += j2 - j1
            deleted += i2 - i1
    return added, deleted


def compute_diff_html(old_text, new_text):
    """Return inline word-level diff HTML showing the full new content with change highlights."""
    import re
    from markupsafe import Markup, escape

    old_text = old_text or ""
    new_text = new_text or ""

    # Tokenize preserving whitespace as separate tokens so spacing is retained
    def tokenize(text):
        return re.split(r"(\s+)", text)

    old_tokens = tokenize(old_text)
    new_tokens = tokenize(new_text)

    matcher = difflib.SequenceMatcher(None, old_tokens, new_tokens, autojunk=False)
    parts = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for tok in new_tokens[j1:j2]:
                parts.append(str(escape(tok)))
        elif tag == "insert":
            for tok in new_tokens[j1:j2]:
                if tok.strip():
                    parts.append(
                        '<ins style="background:rgba(63,185,80,.25);color:#7ee787;text-decoration:none;border-radius:2px">'
                        + str(escape(tok))
                        + "</ins>"
                    )
                else:
                    parts.append(str(escape(tok)))
        elif tag == "delete":
            for tok in old_tokens[i1:i2]:
                if tok.strip():
                    parts.append(
                        '<del style="background:rgba(255,107,107,.2);color:#ff8585;border-radius:2px">'
                        + str(escape(tok))
                        + "</del>"
                    )
                else:
                    parts.append(str(escape(tok)))
        elif tag == "replace":
            has_del = False
            for tok in old_tokens[i1:i2]:
                if tok.strip():
                    parts.append(
                        '<del style="background:rgba(255,107,107,.2);color:#ff8585;border-radius:2px">'
                        + str(escape(tok))
                        + "</del>"
                    )
                    has_del = True
                else:
                    parts.append(str(escape(tok)))
            sep_needed = has_del
            for tok in new_tokens[j1:j2]:
                if tok.strip():
                    if sep_needed:
                        parts.append(" ")
                        sep_needed = False
                    parts.append(
                        '<ins style="background:rgba(63,185,80,.25);color:#7ee787;text-decoration:none;border-radius:2px">'
                        + str(escape(tok))
                        + "</ins>"
                    )
                else:
                    parts.append(str(escape(tok)))
    return Markup(
        '<pre style="white-space:pre-wrap;word-break:break-word;'
        "font-family:'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace;"
        'font-size:.88rem;line-height:1.75;margin:0">'
        + "".join(parts)
        + "</pre>"
    )


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


def allowed_attachment(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in config.ATTACHMENT_ALLOWED_EXTENSIONS


# Human-readable display labels for user roles.
ROLE_LABELS = {
    "user": "Member",
    "editor": "Editor",
    "admin": "Administrator",
    "protected_admin": "Administrator",
}


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


def editor_has_category_access(user, category_id):
    """Return True if *user* may edit content in the given *category_id*.

    Admins always have access.  Editors with unrestricted access also always
    have access.  Restricted editors only have access to their explicitly
    allowed categories; uncategorised pages (category_id=None) are not
    accessible to restricted editors.
    """
    if user["role"] in ("admin", "protected_admin"):
        return True
    access = db.get_editor_access(user["id"])
    if not access["restricted"]:
        return True
    if category_id is None:
        return False
    return int(category_id) in access["allowed_category_ids"]


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
    user_accessibility = db.get_user_accessibility(user["id"]) if user else {}
    sidebar_people = db.list_published_profiles()[:19] if user else []
    current_user_profile = db.get_user_profile(user["id"]) if user else None
    return {
        "current_user": user,
        "settings": settings,
        "time_ago": time_ago,
        "format_datetime": format_datetime,
        "page_history_enabled": config.PAGE_HISTORY_ENABLED,
        "all_categories": db.list_categories(),
        "active_announcements": active_announcements,
        "user_accessibility": user_accessibility,
        "sidebar_people": sidebar_people,
        "current_user_profile": current_user_profile,
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
        notify_change("user_login", f"User '{user['username']}' logged in")
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
def _profile_next(fallback):
    """Return next_url from the current form post if it is a safe same-site path, else fallback."""
    url = request.form.get("next_url", "").strip()
    # Only accept simple same-site paths: must start with / but not // and contain no backslashes
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return fallback


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

    if action == "update_profile":
        real_name = request.form.get("real_name", "").strip()[:100]
        bio = request.form.get("bio", "").strip()[:500]
        avatar_file = request.files.get("avatar")
        profile = db.get_user_profile(user["id"])
        old_avatar = profile["avatar_filename"] if profile else ""
        new_avatar = old_avatar
        if avatar_file and avatar_file.filename:
            if not allowed_file(avatar_file.filename):
                flash("Invalid avatar file type.", "error")
                return redirect(url_for("account_settings"))
            # 1 MB limit for avatars
            avatar_file.stream.seek(0, 2)
            size = avatar_file.stream.tell()
            avatar_file.stream.seek(0)
            if size > 1 * 1024 * 1024:
                flash("Avatar must be 1 MB or smaller.", "error")
                return redirect(url_for("account_settings"))
            try:
                img = Image.open(avatar_file.stream)
                img.verify()
                avatar_file.stream.seek(0)
            except Exception:
                flash("Avatar is not a valid image.", "error")
                return redirect(url_for("account_settings"))
            avatar_dir = os.path.join(config.UPLOAD_FOLDER, "avatars")
            os.makedirs(avatar_dir, exist_ok=True)
            ext = avatar_file.filename.rsplit(".", 1)[1].lower()
            new_avatar = f"avatars/{uuid.uuid4().hex}.{ext}"
            save_path = os.path.abspath(os.path.join(config.UPLOAD_FOLDER, new_avatar))
            if os.path.commonpath([os.path.abspath(config.UPLOAD_FOLDER), save_path]) != os.path.abspath(config.UPLOAD_FOLDER):
                flash("Invalid upload path.", "error")
                return redirect(url_for("account_settings"))
            avatar_file.save(save_path)
            notify_file_upload(new_avatar, save_path, display_name=f"Avatar for {user['username']}")
            # Remove old avatar file if different
            if old_avatar and old_avatar != new_avatar:
                old_path = os.path.join(config.UPLOAD_FOLDER, old_avatar)
                if os.path.isfile(old_path):
                    os.remove(old_path)
                notify_file_deleted(old_avatar)
        db.upsert_user_profile(user["id"], real_name=real_name, bio=bio, avatar_filename=new_avatar)
        log_action("update_profile", request, user=user)
        flash("Profile updated.", "success")
        return redirect(_profile_next(url_for("account_settings")))

    if action == "remove_avatar":
        profile = db.get_user_profile(user["id"])
        if profile and profile["avatar_filename"]:
            old_path = os.path.join(config.UPLOAD_FOLDER, profile["avatar_filename"])
            if os.path.isfile(old_path):
                os.remove(old_path)
            notify_file_deleted(profile["avatar_filename"])
            db.upsert_user_profile(user["id"], avatar_filename="")
        flash("Avatar removed.", "success")
        return redirect(_profile_next(url_for("account_settings")))

    if action == "publish_profile":
        profile = db.get_user_profile(user["id"])
        if profile and profile["page_disabled_by_admin"]:
            flash("Your profile page has been disabled by an admin.", "error")
            return redirect(url_for("account_settings"))
        db.upsert_user_profile(user["id"], page_published=True)
        log_action("publish_profile", request, user=user)
        flash("Your profile page is now public.", "success")
        return redirect(_profile_next(url_for("account_settings")))

    if action == "unpublish_profile":
        db.upsert_user_profile(user["id"], page_published=False)
        log_action("unpublish_profile", request, user=user)
        flash("Your profile page is now hidden.", "success")
        return redirect(_profile_next(url_for("account_settings")))

    if action == "delete_profile":
        profile = db.get_user_profile(user["id"])
        if profile and profile["avatar_filename"]:
            old_path = os.path.join(config.UPLOAD_FOLDER, profile["avatar_filename"])
            if os.path.isfile(old_path):
                os.remove(old_path)
            notify_file_deleted(profile["avatar_filename"])
        db.delete_user_profile(user["id"])
        log_action("delete_profile", request, user=user)
        flash("Your profile page has been deleted.", "success")
        return redirect(_profile_next(url_for("account_settings")))

    categories, uncategorized = db.get_category_tree()
    profile = db.get_user_profile(user["id"])
    return render_template("account/settings.html", user=user,
                           categories=categories, uncategorized=uncategorized,
                           profile=profile)


def _build_user_export_zip(user):
    """Build an in-memory ZIP file containing all exported data for a user.

    ``user`` must be a valid user row (as returned by ``db.get_user_by_id``).
    Returns a ``BytesIO`` object ready to be sent as a file download.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Account info (exclude password hash)
        account_data = {
            "id": user["id"],
            "username": user["username"],
            "role": user["role"],
            "suspended": bool(user["suspended"]),
            "invite_code": user["invite_code"],
            "created_at": user["created_at"],
            "last_login_at": user["last_login_at"],
            "easter_egg_found": bool(user["easter_egg_found"]),
            "is_superuser": bool(user["is_superuser"]),
        }
        zf.writestr("account.json", json.dumps(account_data, indent=2))

        # Username history
        username_history = [dict(r) for r in db.get_username_history(user["id"])]
        zf.writestr("username_history.json", json.dumps(username_history, indent=2))

        # Contributions (page edits)
        contributions = [dict(r) for r in db.get_user_contributions(user["id"])]
        zf.writestr("contributions.json", json.dumps(contributions, indent=2))

        # Drafts
        drafts = [dict(r) for r in db.list_user_drafts(user["id"])]
        zf.writestr("drafts.json", json.dumps(drafts, indent=2))

        # Accessibility preferences
        accessibility = db.get_user_accessibility(user["id"])
        zf.writestr("accessibility.json", json.dumps(accessibility, indent=2))

    buf.seek(0)
    return buf


@app.route("/account/export")
@login_required
def export_own_data():
    """Allow a logged-in user to download all their own data as a ZIP file."""
    user = get_current_user()
    buf = _build_user_export_zip(user)
    filename = f"userdata_{user['username']}.zip"
    log_action("export_own_data", request, user=user)
    return send_file(buf, mimetype="application/zip",
                     as_attachment=True, download_name=filename)


# ---------------------------------------------------------------------------
#  Users – People list & profiles
# ---------------------------------------------------------------------------
@app.route("/users")
@login_required
def users_list():
    query = request.args.get("q", "").strip().lower()
    current_user = get_current_user()
    if current_user["role"] in ("admin", "protected_admin"):
        users = db.list_all_users_with_profiles()
    else:
        users = db.list_published_profiles()
        # Normalise column names so template works for both result sets
        users = [dict(u) for u in users]
        for u in users:
            u.setdefault("role", "user")
            u.setdefault("suspended", 0)
            u.setdefault("page_published", 1)
            u.setdefault("page_disabled_by_admin", 0)
    if query:
        users = [u for u in users if query in u["username"].lower()
                 or query in u["real_name"].lower()]
    categories, uncategorized = db.get_category_tree()
    return render_template("users/list.html", users=users, query=query,
                           categories=categories, uncategorized=uncategorized)


@app.route("/users/<string:username>")
@login_required
def user_profile(username):
    target = db.get_user_by_username(username)
    if not target:
        abort(404)
    profile = db.get_user_profile(target["id"])
    current_user = get_current_user()
    is_admin = current_user["role"] in ("admin", "protected_admin")
    is_own = current_user["id"] == target["id"]
    # Only admins and the user themselves can view unpublished/disabled profiles
    if not (is_admin or is_own):
        if not profile or not profile["page_published"] or profile["page_disabled_by_admin"]:
            abort(404)
    contrib_year, contributions = db.get_contributions_by_day(target["id"])
    contribution_list = db.get_user_contributions(target["id"])
    categories, uncategorized = db.get_category_tree()
    return render_template(
        "users/profile.html",
        target=target,
        profile=profile,
        contributions=contributions,
        contrib_year=contrib_year,
        contribution_list=contribution_list,
        is_own=is_own,
        is_admin=is_admin,
        role_labels=ROLE_LABELS,
        categories=categories,
        uncategorized=uncategorized,
    )


@app.route("/admin/users/<string:user_id>/profile", methods=["POST"])
@login_required
@admin_required
def admin_moderate_profile(user_id):
    """Admin: edit or disable a user's profile page."""
    target = db.get_user_by_id(user_id)
    if not target:
        abort(404)
    current_user = get_current_user()
    action = request.form.get("action", "")

    if action == "edit_profile":
        real_name = request.form.get("real_name", "").strip()[:100]
        bio = request.form.get("bio", "").strip()[:500]
        db.upsert_user_profile(user_id, real_name=real_name, bio=bio)
        log_action("admin_edit_profile", request, user=current_user,
                   target_user=target["username"])
        notify_change("admin_edit_profile", f"Profile of '{target['username']}' edited")
        flash("Profile updated.", "success")

    elif action == "remove_avatar":
        profile = db.get_user_profile(user_id)
        if profile and profile["avatar_filename"]:
            old_path = os.path.join(config.UPLOAD_FOLDER, profile["avatar_filename"])
            if os.path.isfile(old_path):
                os.remove(old_path)
            notify_file_deleted(profile["avatar_filename"])
            db.upsert_user_profile(user_id, avatar_filename="")
        log_action("admin_remove_avatar", request, user=current_user,
                   target_user=target["username"])
        notify_change("admin_remove_avatar", f"Avatar removed for '{target['username']}'")
        flash("Avatar removed.", "success")

    elif action == "disable_profile":
        db.upsert_user_profile(user_id, page_disabled_by_admin=True, page_published=False)
        log_action("admin_disable_profile", request, user=current_user,
                   target_user=target["username"])
        notify_change("admin_disable_profile", f"Profile of '{target['username']}' disabled")
        flash("Profile disabled.", "success")

    elif action == "enable_profile":
        db.upsert_user_profile(user_id, page_disabled_by_admin=False)
        log_action("admin_enable_profile", request, user=current_user,
                   target_user=target["username"])
        notify_change("admin_enable_profile", f"Profile of '{target['username']}' re-enabled")
        flash("Profile re-enabled.", "success")

    elif action == "delete_profile":
        profile = db.get_user_profile(user_id)
        if profile and profile["avatar_filename"]:
            old_path = os.path.join(config.UPLOAD_FOLDER, profile["avatar_filename"])
            if os.path.isfile(old_path):
                os.remove(old_path)
            notify_file_deleted(profile["avatar_filename"])
        db.delete_user_profile(user_id)
        log_action("admin_delete_profile", request, user=current_user,
                   target_user=target["username"])
        notify_change("admin_delete_profile", f"Profile of '{target['username']}' deleted")
        flash("Profile deleted.", "success")

    return redirect(url_for("admin_users"))


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
    attachments = db.get_page_attachments(page["id"])
    prev_page, next_page = db.get_adjacent_pages(page["id"])
    return render_template(
        "wiki/page.html",
        page=page,
        content_html=content_html,
        categories=categories,
        uncategorized=uncategorized,
        editor_info=editor_info,
        attachments=attachments,
        prev_page=prev_page,
        next_page=next_page,
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
    # Compute per-entry char diffs (compare each entry to the next older one)
    history_list = list(history)
    diff_stats = {}
    for idx, entry in enumerate(history_list):
        prev_content = history_list[idx + 1]["content"] if idx + 1 < len(history_list) else ""
        added, deleted = compute_char_diff(prev_content, entry["content"])
        diff_stats[entry["id"]] = {"added": added, "deleted": deleted}
    return render_template(
        "wiki/history.html",
        page=page,
        history=history_list,
        diff_stats=diff_stats,
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
    # Find the previous (older) history entry to diff against
    history = db.get_page_history(page["id"])
    history_list = list(history)
    prev_content = None
    for idx, h in enumerate(history_list):
        if h["id"] == entry_id and idx + 1 < len(history_list):
            prev_content = history_list[idx + 1]["content"]
            break
    if prev_content is not None:
        diff_html = compute_diff_html(prev_content, entry["content"])
    else:
        diff_html = None
    content_html = render_markdown(entry["content"])
    categories, uncategorized = db.get_category_tree()
    return render_template(
        "wiki/history_entry.html",
        page=page,
        entry=entry,
        content_html=content_html,
        diff_html=diff_html,
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
                   f"Reverted to version from {entry['created_at']}", is_revert=True)
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
    if not editor_has_category_access(user, page["category_id"]):
        flash("You do not have permission to edit pages in this category.", "error")
        return redirect(url_for("view_page", slug=slug))
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

        # Update category if provided and changed
        new_cat_id = request.form.get("category_id")
        try:
            new_cat_id = int(new_cat_id) if new_cat_id else None
        except (TypeError, ValueError):
            new_cat_id = page["category_id"]
        if new_cat_id != page["category_id"]:
            if new_cat_id and not db.get_category(new_cat_id):
                flash("Category update skipped: selected category does not exist.", "error")
            elif not editor_has_category_access(user, new_cat_id):
                flash("Category update skipped: you do not have permission to move pages into this category.", "error")
            else:
                db.update_page_category(page["id"], new_cat_id)
                log_action("move_page", request, user=user, page=slug, category_id=new_cat_id)

        # Update difficulty tag if provided
        tag = request.form.get("difficulty_tag", "").strip().lower()
        if tag in db.VALID_DIFFICULTY_TAGS:
            custom_label = ""
            custom_color = ""
            if tag == "custom":
                custom_label = request.form.get("tag_custom_label", "").strip()[:50]
                custom_color = request.form.get("tag_custom_color", "").strip()
                if not custom_label:
                    flash("Custom tag requires a label.", "error")
                    tag = ""
                elif not _is_valid_hex_color(custom_color):
                    flash("Custom tag requires a valid hex color.", "error")
                    tag = ""
            if tag in db.VALID_DIFFICULTY_TAGS:
                db.update_page_tag(page["id"], tag, custom_label, custom_color)
        elif tag:
            flash("Invalid difficulty tag submitted.", "error")

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
    attachments = db.get_page_attachments(page["id"])
    return render_template(
        "wiki/edit.html",
        page=page,
        draft=draft,
        other_drafts=other_drafts,
        categories=categories,
        uncategorized=uncategorized,
        attachments=attachments,
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
    if not editor_has_category_access(user, page["category_id"]):
        flash("You do not have permission to edit pages in this category.", "error")
        if page["is_home"]:
            return redirect(url_for("home"))
        return redirect(url_for("view_page", slug=slug))
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
        form_data = {
            "title": title, "content": content, "category_id": cat_id or "",
            "difficulty_tag": request.form.get("difficulty_tag", ""),
            "tag_custom_label": request.form.get("tag_custom_label", ""),
            "tag_custom_color": request.form.get("tag_custom_color", "#4a90d9"),
        }
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
        if not editor_has_category_access(user, cat_id):
            flash("You do not have permission to create pages in this category.", "error")
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
        # Apply initial difficulty tag if specified
        tag = request.form.get("difficulty_tag", "").strip().lower()
        if tag in db.VALID_DIFFICULTY_TAGS and tag:
            custom_label = ""
            custom_color = ""
            if tag == "custom":
                custom_label = request.form.get("tag_custom_label", "").strip()[:50]
                custom_color = request.form.get("tag_custom_color", "").strip()
                if not custom_label or not _is_valid_hex_color(custom_color):
                    tag = ""
            if tag:
                page_id = db.get_page_by_slug(slug)["id"]
                db.update_page_tag(page_id, tag, custom_label, custom_color)
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
    if not editor_has_category_access(user, page["category_id"]):
        flash("You do not have permission to delete pages in this category.", "error")
        return redirect(url_for("view_page", slug=slug))
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
    if not editor_has_category_access(user, page["category_id"]):
        flash("You do not have permission to move pages from this category.", "error")
        return redirect(url_for("view_page", slug=slug))
    if not editor_has_category_access(user, cat_id):
        flash("You do not have permission to move pages into this category.", "error")
        return redirect(url_for("view_page", slug=slug))
    db.update_page_category(page["id"], cat_id)
    log_action("move_page", request, user=user, page=slug, category_id=cat_id)
    notify_change("page_move", f"Page '{slug}' moved")
    flash("Page moved.", "success")
    return redirect(url_for("view_page", slug=slug))


@app.route("/page/<slug>/tag", methods=["POST"])
@login_required
@editor_required
@rate_limit(20, 60)
def update_page_tag(slug):
    page = db.get_page_by_slug(slug)
    if not page:
        abort(404)
    user = get_current_user()
    if not editor_has_category_access(user, page["category_id"]):
        flash("You do not have permission to edit pages in this category.", "error")
        if page["is_home"]:
            return redirect(url_for("home"))
        return redirect(url_for("view_page", slug=slug))
    tag = request.form.get("difficulty_tag", "").strip().lower()
    if tag not in db.VALID_DIFFICULTY_TAGS:
        flash("Invalid difficulty tag.", "error")
        if page["is_home"]:
            return redirect(url_for("home"))
        return redirect(url_for("view_page", slug=slug))
    custom_label = ""
    custom_color = ""
    if tag == "custom":
        custom_label = request.form.get("tag_custom_label", "").strip()[:50]
        custom_color = request.form.get("tag_custom_color", "").strip()
        if not custom_label:
            flash("Custom tag requires a label.", "error")
            if page["is_home"]:
                return redirect(url_for("home"))
            return redirect(url_for("view_page", slug=slug))
        if not _is_valid_hex_color(custom_color):
            flash("Custom tag requires a valid hex color.", "error")
            if page["is_home"]:
                return redirect(url_for("home"))
            return redirect(url_for("view_page", slug=slug))
    db.update_page_tag(page["id"], tag, custom_label, custom_color)
    log_action("update_page_tag", request, user=user, page=slug, tag=tag)
    notify_change("page_tag", f"Page '{slug}' tag updated to '{tag}'")
    flash("Tag updated.", "success")
    if page["is_home"]:
        return redirect(url_for("home"))
    return redirect(url_for("view_page", slug=slug))


@app.route("/category/create", methods=["POST"])
@login_required
@editor_required
@rate_limit(20, 60)
def create_category():
    user = get_current_user()
    access = db.get_editor_access(user["id"])
    if access["restricted"]:
        flash("You do not have permission to create categories.", "error")
        return redirect(_safe_referrer() or url_for("home"))
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
    user = get_current_user()
    if db.get_editor_access(user["id"])["restricted"]:
        flash("You do not have permission to edit categories.", "error")
        return redirect(_safe_referrer() or url_for("home"))
    name = request.form.get("name", "").strip()
    if not name:
        flash("Category name is required.", "error")
        return redirect(_safe_referrer() or url_for("home"))
    if len(name) > 100:
        flash("Category name must be 100 characters or fewer.", "error")
        return redirect(_safe_referrer() or url_for("home"))
    db.update_category(cat_id, name)
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
    user = get_current_user()
    if db.get_editor_access(user["id"])["restricted"]:
        flash("You do not have permission to move categories.", "error")
        return redirect(_safe_referrer() or url_for("home"))
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
    user = get_current_user()
    if db.get_editor_access(user["id"])["restricted"]:
        flash("You do not have permission to delete categories.", "error")
        return redirect(_safe_referrer() or url_for("home"))
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
    log_action("delete_category", request, user=user, category_id=cat_id, page_action=page_action)
    notify_change("category_delete", f"Category {cat_id} deleted")
    flash("Category deleted.", "success")
    return redirect(_safe_referrer() or url_for("home"))


@app.route("/page/<slug>/rename", methods=["POST"])
@login_required
@editor_required
@rate_limit(10, 60)
def rename_page_slug(slug):
    page = db.get_page_by_slug(slug)
    if not page:
        abort(404)
    if page["is_home"]:
        flash("Cannot change the URL of the home page.", "error")
        return redirect(url_for("home"))
    user = get_current_user()
    if not editor_has_category_access(user, page["category_id"]):
        flash("You do not have permission to edit pages in this category.", "error")
        return redirect(url_for("view_page", slug=slug))
    new_slug = request.form.get("new_slug", "").strip()
    if not new_slug:
        flash("New URL slug is required.", "error")
        return redirect(url_for("view_page", slug=slug))
    new_slug = slugify(new_slug)
    if not new_slug:
        flash("Invalid slug.", "error")
        return redirect(url_for("view_page", slug=slug))
    if new_slug == slug:
        flash("New URL is the same as the current one.", "info")
        return redirect(url_for("view_page", slug=slug))
    if db.get_page_by_slug(new_slug):
        flash("That URL slug is already in use by another page.", "error")
        return redirect(url_for("view_page", slug=slug))
    db.update_page_slug(page["id"], new_slug)
    log_action("rename_page_slug", request, user=user, page=slug, new_slug=new_slug)
    notify_change("page_rename", f"Page '{slug}' renamed to '{new_slug}'")
    flash("Page URL updated. All internal links have been updated automatically.", "success")
    return redirect(url_for("view_page", slug=new_slug))


@app.route("/category/<int:cat_id>/sequential-nav", methods=["POST"])
@login_required
@editor_required
@rate_limit(20, 60)
def toggle_category_sequential_nav(cat_id):
    cat = db.get_category(cat_id)
    if not cat:
        abort(404)
    user = get_current_user()
    if db.get_editor_access(user["id"])["restricted"]:
        flash("You do not have permission to modify categories.", "error")
        return redirect(_safe_referrer() or url_for("home"))
    enabled = request.form.get("sequential_nav", "0") == "1"
    db.update_category_sequential_nav(cat_id, enabled)
    log_action("toggle_sequential_nav", request, user=user, category_id=cat_id, enabled=enabled)
    notify_change("category_sequential_nav", f"Category {cat_id} sequential navigation {'enabled' if enabled else 'disabled'}")
    flash("Sequential navigation setting updated.", "success")
    return redirect(_safe_referrer() or url_for("home"))


# ---------------------------------------------------------------------------
#  Pages search API (for link autocomplete)
# ---------------------------------------------------------------------------
@app.route("/api/pages/search")
@login_required
@rate_limit(60, 60)
def api_pages_search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify([])
    results = db.search_pages(query)
    return jsonify([{"title": r["title"], "slug": r["slug"]} for r in results])


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
                    notify_file_deleted(fname)
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


# ---------------------------------------------------------------------------
#  Page Attachments
# ---------------------------------------------------------------------------

@app.route("/api/page/<int:page_id>/attachments", methods=["POST"])
@login_required
@editor_required
@rate_limit(20, 60)
def upload_attachment(page_id):
    """Upload a file attachment to a wiki page (max 5 MB)."""
    page = db.get_page(page_id)
    if not page:
        return jsonify({"error": "Page not found"}), 404
    user = get_current_user()
    if not editor_has_category_access(user, page["category_id"]):
        return jsonify({"error": "Access denied"}), 403
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename or not allowed_attachment(f.filename):
        return jsonify({"error": "File type not allowed"}), 400
    # Stream to a temp file while enforcing the size limit
    os.makedirs(config.ATTACHMENT_FOLDER, exist_ok=True)
    ext = f.filename.rsplit(".", 1)[1].lower()
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    attach_root = os.path.abspath(config.ATTACHMENT_FOLDER)
    filepath = os.path.abspath(os.path.join(attach_root, stored_name))
    if os.path.commonpath([attach_root, filepath]) != attach_root:
        return jsonify({"error": "Invalid upload path"}), 400
    file_size = 0
    chunk_size = 64 * 1024  # 64 KB
    try:
        with open(filepath, "wb") as out:
            while True:
                chunk = f.stream.read(chunk_size)
                if not chunk:
                    break
                file_size += len(chunk)
                if file_size > config.MAX_ATTACHMENT_SIZE:
                    out.close()
                    os.remove(filepath)
                    return jsonify({"error": "File exceeds the 5 MB limit"}), 413
                out.write(chunk)
    except OSError:
        if os.path.isfile(filepath):
            os.remove(filepath)
        return jsonify({"error": "Failed to save file"}), 500
    original_name = secure_filename(f.filename)
    attachment_id = db.add_page_attachment(page_id, stored_name, original_name, file_size, user["id"])
    log_action("upload_attachment", request, user=user, page=page["slug"], filename=original_name)
    notify_change("attachment_upload", f"Attachment '{original_name}' uploaded to page '{page['slug']}'")
    notify_file_upload(stored_name, filepath, display_name=original_name)
    return jsonify({"id": attachment_id, "name": original_name, "size": file_size})


@app.route("/api/attachments/<int:attachment_id>", methods=["DELETE"])
@login_required
@editor_required
@rate_limit(20, 60)
def delete_attachment(attachment_id):
    """Delete a page attachment."""
    attachment = db.get_page_attachment(attachment_id)
    if not attachment:
        return jsonify({"error": "Not found"}), 404
    page = db.get_page(attachment["page_id"])
    user = get_current_user()
    if page and not editor_has_category_access(user, page["category_id"]):
        return jsonify({"error": "Access denied"}), 403
    filepath = os.path.join(config.ATTACHMENT_FOLDER, attachment["filename"])
    attach_root = os.path.abspath(config.ATTACHMENT_FOLDER)
    filepath = os.path.abspath(filepath)
    if os.path.commonpath([attach_root, filepath]) == attach_root and os.path.isfile(filepath):
        os.remove(filepath)
    db.delete_page_attachment(attachment_id)
    log_action("delete_attachment", request, user=user, filename=attachment["original_name"])
    notify_change("attachment_delete", f"Attachment '{attachment['original_name']}' deleted from page '{page['slug'] if page else 'unknown'}'")
    notify_file_deleted(attachment["filename"])
    return jsonify({"ok": True})


@app.route("/page/<slug>/attachments/<int:attachment_id>/download")
@login_required
def download_attachment(slug, attachment_id):
    """Download a single attachment."""
    page = db.get_page_by_slug(slug)
    if not page:
        abort(404)
    attachment = db.get_page_attachment(attachment_id)
    if not attachment or attachment["page_id"] != page["id"]:
        abort(404)
    attach_root = os.path.abspath(config.ATTACHMENT_FOLDER)
    filepath = os.path.abspath(os.path.join(attach_root, attachment["filename"]))
    if os.path.commonpath([attach_root, filepath]) != attach_root:
        abort(404)
    if not os.path.isfile(filepath):
        abort(404)
    return send_file(filepath, as_attachment=True, download_name=attachment["original_name"])


@app.route("/page/<slug>/attachments/download-all")
@login_required
def download_all_attachments(slug):
    """Download all attachments for a page as a ZIP file."""
    page = db.get_page_by_slug(slug)
    if not page:
        abort(404)
    attachments = db.get_page_attachments(page["id"])
    if not attachments:
        flash("No attachments to download.", "error")
        return redirect(url_for("view_page", slug=slug))
    attach_root = os.path.abspath(config.ATTACHMENT_FOLDER)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for att in attachments:
            filepath = os.path.abspath(os.path.join(attach_root, att["filename"]))
            if os.path.commonpath([attach_root, filepath]) == attach_root and os.path.isfile(filepath):
                zf.write(filepath, att["original_name"])
    buf.seek(0)
    zip_name = f"{slug}-attachments.zip"
    return send_file(buf, mimetype="application/zip", as_attachment=True, download_name=zip_name)


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


# ---------------------------------------------------------------------------
#  Accessibility / user preferences API
# ---------------------------------------------------------------------------
@app.route("/api/accessibility", methods=["GET"])
@login_required
def api_get_accessibility():
    user = get_current_user()
    return jsonify(db.get_user_accessibility(user["id"]))


_VALID_FONT_SCALES = {0.85, 0.9, 1.0, 1.1, 1.2, 1.35}
_VALID_CONTRASTS = {0, 1, 2, 3, 4, 5}
_VALID_LINE_HEIGHTS = {0, 1, 2}
_VALID_LETTER_SPACINGS = {0, 1, 2}


@app.route("/api/accessibility", methods=["POST"])
@login_required
@rate_limit(60, 60)
def api_save_accessibility():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "invalid request"}), 400
    user = get_current_user()
    current = db.get_user_accessibility(user["id"])

    font_scale = data.get("font_scale", current["font_scale"])
    try:
        font_scale = float(font_scale)
    except (TypeError, ValueError):
        font_scale = 1.0
    if font_scale not in _VALID_FONT_SCALES:
        font_scale = min(_VALID_FONT_SCALES, key=lambda x: abs(x - font_scale))

    contrast = data.get("contrast", current["contrast"])
    try:
        contrast = int(contrast)
    except (TypeError, ValueError):
        contrast = 0
    if contrast not in _VALID_CONTRASTS:
        contrast = 0

    sidebar_width = data.get("sidebar_width", current["sidebar_width"])
    try:
        sidebar_width = int(sidebar_width)
        sidebar_width = max(180, min(500, sidebar_width))
    except (TypeError, ValueError):
        sidebar_width = 250

    def _clean_color(val):
        val = str(val).strip()
        if not val:
            return ""
        if re.match(r'^#[0-9a-fA-F]{3,8}$', val):
            return val
        if re.match(r'^rgb\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)$', val):
            return val
        return ""

    prefs = {
        "font_scale": font_scale,
        "contrast": contrast,
        "sidebar_width": sidebar_width,
        "custom_bg": _clean_color(data.get("custom_bg", current.get("custom_bg", ""))),
        "custom_text": _clean_color(data.get("custom_text", current.get("custom_text", ""))),
        "custom_primary": _clean_color(data.get("custom_primary", current.get("custom_primary", ""))),
        "custom_secondary": _clean_color(data.get("custom_secondary", current.get("custom_secondary", ""))),
        "custom_accent": _clean_color(data.get("custom_accent", current.get("custom_accent", ""))),
        "custom_sidebar": _clean_color(data.get("custom_sidebar", current.get("custom_sidebar", ""))),
    }

    line_height = data.get("line_height", current.get("line_height", 0))
    try:
        line_height = int(line_height)
    except (TypeError, ValueError):
        line_height = 0
    if line_height not in _VALID_LINE_HEIGHTS:
        line_height = 0
    prefs["line_height"] = line_height

    letter_spacing = data.get("letter_spacing", current.get("letter_spacing", 0))
    try:
        letter_spacing = int(letter_spacing)
    except (TypeError, ValueError):
        letter_spacing = 0
    if letter_spacing not in _VALID_LETTER_SPACINGS:
        letter_spacing = 0
    prefs["letter_spacing"] = letter_spacing

    reduce_motion = data.get("reduce_motion", current.get("reduce_motion", 0))
    try:
        reduce_motion = 1 if reduce_motion else 0
    except (TypeError, ValueError):
        reduce_motion = 0
    prefs["reduce_motion"] = reduce_motion
    db.save_user_accessibility(user["id"], prefs)
    return jsonify({"ok": True})


@app.route("/api/accessibility/reset", methods=["POST"])
@login_required
@rate_limit(10, 60)
def api_reset_accessibility():
    user = get_current_user()
    db.save_user_accessibility(user["id"], dict(db._A11Y_DEFAULTS))
    return jsonify({"ok": True, "defaults": db._A11Y_DEFAULTS})


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


@app.route("/admin/users/<string:user_id>/editor-access", methods=["GET", "POST"])
@login_required
@admin_required
def admin_editor_access(user_id):
    """Manage category-based access restrictions for an editor account."""
    target = db.get_user_by_id(user_id)
    if not target:
        abort(404)
    if target["role"] not in ("editor",):
        flash("Category access can only be configured for editor accounts.", "error")
        return redirect(url_for("admin_users"))

    current_user = get_current_user()
    all_categories = db.list_categories()

    if request.method == "POST":
        restricted = request.form.get("restricted") == "1"
        selected_ids = [
            int(v) for v in request.form.getlist("category_ids")
            if v.isdigit()
        ]
        db.set_editor_access(user_id, restricted, selected_ids if restricted else [])
        log_action(
            "admin_set_editor_access", request, user=current_user,
            target_user=target["username"],
            restricted=restricted,
            category_ids=selected_ids if restricted else [],
        )
        notify_change("admin_editor_access", f"Editor access updated for '{target['username']}'")
        flash("Editor access settings updated.", "success")
        return redirect(url_for("admin_editor_access", user_id=user_id))

    access = db.get_editor_access(user_id)
    categories, uncategorized = db.get_category_tree()
    return render_template(
        "admin/editor_access.html",
        target=target,
        access=access,
        all_categories=all_categories,
        categories=categories,
        uncategorized=uncategorized,
    )


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


@app.route("/admin/users/<string:user_id>/export")
@login_required
@admin_required
def admin_export_user_data(user_id):
    """Allow an admin to download all data for any user as a ZIP file."""
    target = db.get_user_by_id(user_id)
    if not target:
        abort(404)
    buf = _build_user_export_zip(target)
    current_user = get_current_user()
    log_action("admin_export_user_data", request, user=current_user,
               target_user=target["username"])
    filename = f"userdata_{target['username']}.zip"
    return send_file(buf, mimetype="application/zip",
                     as_attachment=True, download_name=filename)


# ---------------------------------------------------------------------------
#  Admin – Site migration (export / import)
# ---------------------------------------------------------------------------
@app.route("/admin/migration")
@login_required
@admin_required
def admin_migration():
    """Render the site migration page."""
    user = get_current_user()
    categories, uncategorized = db.get_category_tree()
    log_action("view_migration", request, user=user)
    return render_template("admin/migration.html",
                           categories=categories, uncategorized=uncategorized)


@app.route("/admin/migration/export", methods=["POST"])
@login_required
@admin_required
def admin_migration_export():
    """Export the entire site as a ZIP containing a single JSON file."""
    user = get_current_user()
    data = db.export_site_data()
    payload = json.dumps(data, indent=2).encode("utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("site_export.json", payload)
    buf.seek(0)

    log_action("export_site", request, user=user)
    notify_change("site_export", "Full site exported")
    filename = f"site_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.zip"
    return send_file(buf, mimetype="application/zip",
                     as_attachment=True, download_name=filename)


@app.route("/admin/migration/import", methods=["POST"])
@login_required
@admin_required
def admin_migration_import():
    """Import a previously exported site ZIP."""
    user = get_current_user()
    mode = request.form.get("import_mode", "")
    if mode not in ("delete_all", "override", "keep"):
        flash("Invalid import mode selected.", "error")
        return redirect(url_for("admin_migration"))

    f = request.files.get("import_file")
    if not f or not f.filename:
        flash("No file selected.", "error")
        return redirect(url_for("admin_migration"))

    if not f.filename.lower().endswith(".zip"):
        flash("Please upload a .zip file.", "error")
        return redirect(url_for("admin_migration"))

    try:
        raw = f.read()
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = zf.namelist()
            json_names = [n for n in names if n.endswith(".json")]
            if not json_names:
                flash("The uploaded archive contains no JSON data file.", "error")
                return redirect(url_for("admin_migration"))
            with zf.open(json_names[0]) as jf:
                data = json.load(jf)
    except zipfile.BadZipFile:
        flash("The uploaded file is not a valid ZIP archive.", "error")
        return redirect(url_for("admin_migration"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        flash("The data file inside the archive is not valid JSON.", "error")
        return redirect(url_for("admin_migration"))
    except Exception as exc:
        get_logger().warning("site import – failed to read archive: %s", exc)
        flash("Failed to read the uploaded archive.", "error")
        return redirect(url_for("admin_migration"))

    try:
        db.import_site_data(data, mode)
    except ValueError as exc:
        flash(f"Import failed: {exc}", "error")
        return redirect(url_for("admin_migration"))
    except Exception as exc:
        get_logger().exception("site import – unexpected error (mode=%s): %s", mode, exc)
        flash("An unexpected error occurred during import. The operation was rolled back.", "error")
        return redirect(url_for("admin_migration"))

    mode_labels = {
        "delete_all": "all previous data deleted, file restored",
        "override": "previous data kept, conflicts overridden",
        "keep": "previous data kept, conflicts left as-is",
    }
    log_action("import_site", request, user=user, mode=mode)
    notify_change("site_import", f"Full site imported (mode={mode})")
    flash(f"Site data imported successfully ({mode_labels[mode]}).", "success")
    return redirect(url_for("admin_migration"))


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


# ---------------------------------------------------------------------------
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

    app.run(host=config.HOST, port=config.PORT, debug=False)
