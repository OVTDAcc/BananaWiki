"""
BananaWiki – Utility functions, constants, and shared helpers.

Extracted from app.py to keep route handlers separate from reusable logic.
"""

import re
import difflib
import functools
import threading
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import urlparse

from flask import request, session, redirect, url_for, flash, jsonify, abort
from werkzeug.security import generate_password_hash
import markdown
import bleach
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import config
import db
from wiki_logger import log_action


# ---------------------------------------------------------------------------
#  Constants
# ---------------------------------------------------------------------------
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

# Human-readable display labels for user roles.
ROLE_LABELS = {
    "user": "Member",
    "editor": "Editor",
    "admin": "Administrator",
    "protected_admin": "Administrator",
}

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


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
#  Markdown rendering
# ---------------------------------------------------------------------------
def render_markdown(text, embed_videos=False):
    """Convert markdown to sanitised HTML.

    When *embed_videos* is True, bare YouTube and Vimeo links are replaced
    with responsive iframe embeds after sanitisation.
    """
    html = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "toc", "nl2br"],
    )
    html = bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS)
    if embed_videos:
        html = _embed_videos_in_html(html)
    return html


_YT_WATCH_RE = re.compile(
    r'<a href="(https?://(?:www\.)?youtube\.com/watch\?[^"<]*)">\1</a>',
    re.IGNORECASE,
)
_YT_SHORT_RE = re.compile(
    r'<a href="(https?://youtu\.be/[^"<]*)">\1</a>',
    re.IGNORECASE,
)
_VIMEO_RE = re.compile(
    r'<a href="(https?://(?:www\.)?vimeo\.com/[^"<]*)">\1</a>',
    re.IGNORECASE,
)

# Bare URL patterns (markdown does not autolink plain URLs; they appear as text)
_YT_WATCH_BARE_RE = re.compile(
    r'<p>\s*(https?://(?:www\.)?youtube\.com/watch\?[^\s<>]*)\s*</p>',
    re.IGNORECASE,
)
_YT_SHORT_BARE_RE = re.compile(
    r'<p>\s*(https?://youtu\.be/[^\s<>]*)\s*</p>',
    re.IGNORECASE,
)
_VIMEO_BARE_RE = re.compile(
    r'<p>\s*(https?://(?:www\.)?vimeo\.com/(\d+)[^\s<>]*)\s*</p>',
    re.IGNORECASE,
)


def _make_video_iframe(embed_src):
    return (
        '<div class="video-embed" style="position:relative;padding-bottom:56.25%;height:0;overflow:hidden;margin:1rem 0">'
        f'<iframe src="{embed_src}" style="position:absolute;top:0;left:0;width:100%;height:100%;border:0" '
        'allowfullscreen loading="lazy"></iframe>'
        '</div>'
    )


def _embed_videos_in_html(html):
    """Replace bare YouTube/Vimeo anchor links with responsive iframe embeds."""
    _yt_vid_re = re.compile(r'[?&]v=([A-Za-z0-9_-]{11})', re.IGNORECASE)
    _yt_short_re = re.compile(r'youtu\.be/([A-Za-z0-9_-]{11})', re.IGNORECASE)
    _vimeo_vid_re = re.compile(r'vimeo\.com/(\d+)', re.IGNORECASE)

    def _yt_watch_replace(m):
        vid_m = _yt_vid_re.search(m.group(1))
        if not vid_m:
            return m.group(0)
        return _make_video_iframe(f"https://www.youtube.com/embed/{vid_m.group(1)}")

    def _yt_short_replace(m):
        vid_m = _yt_short_re.search(m.group(1))
        if not vid_m:
            return m.group(0)
        return _make_video_iframe(f"https://www.youtube.com/embed/{vid_m.group(1)}")

    def _vimeo_replace(m):
        vid_m = _vimeo_vid_re.search(m.group(1))
        if not vid_m:
            return m.group(0)
        return _make_video_iframe(f"https://player.vimeo.com/video/{vid_m.group(1)}")

    # Handle linked URLs (markdown angle-bracket or explicit link syntax)
    html = _YT_WATCH_RE.sub(_yt_watch_replace, html)
    html = _YT_SHORT_RE.sub(_yt_short_replace, html)
    html = _VIMEO_RE.sub(_vimeo_replace, html)
    # Handle bare URLs (plain text in <p> tags, no markdown linking)
    html = _YT_WATCH_BARE_RE.sub(_yt_watch_replace, html)
    html = _YT_SHORT_BARE_RE.sub(_yt_short_replace, html)
    html = _VIMEO_BARE_RE.sub(_vimeo_replace, html)
    return html


# ---------------------------------------------------------------------------
#  Diff computation
# ---------------------------------------------------------------------------
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
    """Return inline word-level diff HTML showing the full new content with change highlights.

    Output is wrapped in a <pre> block (markdown/raw view).
    """
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
                        '<ins class="diff-ins">'
                        + str(escape(tok))
                        + "</ins>"
                    )
                else:
                    parts.append(str(escape(tok)))
        elif tag == "delete":
            for tok in old_tokens[i1:i2]:
                if tok.strip():
                    parts.append(
                        '<del class="diff-del">'
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
                        '<del class="diff-del">'
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
                        '<ins class="diff-ins">'
                        + str(escape(tok))
                        + "</ins>"
                    )
                else:
                    parts.append(str(escape(tok)))
    return Markup(
        '<pre class="diff-pre">'
        + "".join(parts)
        + "</pre>"
    )


def compute_formatted_diff_html(old_text, new_text):
    """Return formatted diff HTML rendered as rich HTML (formatted/rendered view).

    Computes a word-level diff on the rendered HTML of both versions, wrapping
    changed text words in <ins class="diff-ins"> and <del class="diff-del"> spans.
    HTML tags themselves are always emitted as-is (from the new version) so the
    document structure is preserved.

    Text tokens come directly from bleach-sanitized render_markdown() output so
    they are already HTML-safe; no further escaping is applied.
    """
    from markupsafe import Markup

    old_html = render_markdown(old_text or "")
    new_html = render_markdown(new_text or "")

    # Split rendered HTML into alternating text-chunks and tag-chunks.
    # Pattern: (<[^>]+>) captures tags; the rest are text fragments.
    # Text fragments from render_markdown() are already bleach-sanitized HTML,
    # so they do not need additional escaping.
    def tokenize_html(html):
        return re.split(r"(<[^>]+>)", html)

    old_tokens = tokenize_html(old_html)
    new_tokens = tokenize_html(new_html)

    matcher = difflib.SequenceMatcher(None, old_tokens, new_tokens, autojunk=False)
    parts = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            parts.extend(new_tokens[j1:j2])
        elif tag == "insert":
            for tok in new_tokens[j1:j2]:
                if tok.startswith("<"):
                    parts.append(tok)
                elif tok.strip():
                    parts.append('<ins class="diff-ins">' + tok + "</ins>")
                else:
                    parts.append(tok)
        elif tag == "delete":
            for tok in old_tokens[i1:i2]:
                # Emit deleted text only; skip structural tags from old version
                if not tok.startswith("<") and tok.strip():
                    parts.append('<del class="diff-del">' + tok + "</del>")
                elif not tok.startswith("<"):
                    parts.append(tok)
        elif tag == "replace":
            for tok in old_tokens[i1:i2]:
                if not tok.startswith("<") and tok.strip():
                    parts.append('<del class="diff-del">' + tok + "</del>")
                elif not tok.startswith("<"):
                    parts.append(tok)
            for tok in new_tokens[j1:j2]:
                if tok.startswith("<"):
                    parts.append(tok)
                elif tok.strip():
                    parts.append('<ins class="diff-ins">' + tok + "</ins>")
                else:
                    parts.append(tok)
    return Markup("".join(parts))


# ---------------------------------------------------------------------------
#  Slugify
# ---------------------------------------------------------------------------
def slugify(text):
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = text.strip("-")
    if not text:
        text = "page"
    return text


# ---------------------------------------------------------------------------
#  File validation
# ---------------------------------------------------------------------------
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in config.ALLOWED_EXTENSIONS


def allowed_attachment(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in config.ATTACHMENT_ALLOWED_EXTENSIONS


# ---------------------------------------------------------------------------
#  Validation
# ---------------------------------------------------------------------------
def _is_valid_hex_color(value):
    """Return True if value is a valid 7-char hex color like #aabbcc."""
    return bool(re.fullmatch(r"#[0-9a-fA-F]{6}", value))


def _is_valid_username(value):
    """Return True if the username contains only safe characters.

    Allowed: letters, digits, underscores and hyphens.
    This prevents log-injection (newlines / control chars) and
    avoids confusing Unicode look-alikes.
    """
    return bool(_USERNAME_RE.fullmatch(value))


# ---------------------------------------------------------------------------
#  URL helpers
# ---------------------------------------------------------------------------
def _safe_referrer():
    """Return request.referrer only if it is same-origin; otherwise return None."""
    ref = request.referrer
    if not ref:
        return None
    parsed = urlparse(ref)
    if parsed.netloc and parsed.netloc != request.host:
        return None
    return ref


# ---------------------------------------------------------------------------
#  Auth helpers
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
#  Time helpers
# ---------------------------------------------------------------------------
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


def format_datetime_local_input(dt_str):
    """Convert a UTC ISO datetime to site-timezone value for datetime-local inputs."""
    if not dt_str:
        return ""
    try:
        dt = datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return ""
    site_tz = get_site_timezone()
    dt_local = dt.astimezone(site_tz)
    return dt_local.strftime("%Y-%m-%dT%H:%M")
