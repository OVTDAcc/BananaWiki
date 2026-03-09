"""User CRUD, accessibility, login attempts, and editor access."""

import json
import string
import secrets
from datetime import datetime, timedelta, timezone

from werkzeug.security import generate_password_hash

from ._connection import get_db


# ---------------------------------------------------------------------------
#  ID Generation helpers
# ---------------------------------------------------------------------------
def _gen_user_id():
    """Generate a random 8-character alphanumeric lowercase user ID."""
    chars = string.ascii_lowercase + string.digits
    return ''.join(secrets.choice(chars) for _ in range(8))


def generate_random_id(length=12):
    """Generate a random alphanumeric ID for entities.

    This function generates cryptographically secure random IDs that can be used
    for groups, pages, categories, and other entities as an alternative to
    sequential INTEGER AUTOINCREMENT IDs.

    Args:
        length (int): Length of the ID to generate (default: 12 characters)

    Returns:
        str: Random alphanumeric lowercase ID

    Note:
        Using random IDs instead of sequential integers provides:
        - Better privacy (can't enumerate all entities by incrementing IDs)
        - Harder to guess entity counts or creation patterns
        - More suitable for public-facing URLs

        However, migrating existing entities from INTEGER to TEXT IDs requires:
        - Database schema changes (PRIMARY KEY type change)
        - Foreign key relationship updates
        - Route parameter type changes (<int:id> to <string:id>)
        - Extensive testing to prevent regressions

        For this reason, this function is provided as a foundation for future
        migration work, but not yet integrated into all entity creation paths.
    """
    chars = string.ascii_lowercase + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))


# ---------------------------------------------------------------------------
#  User helpers
# ---------------------------------------------------------------------------


def create_user(username, hashed_pw, role="user", invite_code=None):
    """Create a new user and return its generated ID."""
    conn = get_db()
    try:
        cur = conn.cursor()
        uid = _gen_user_id()
        while conn.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
            uid = _gen_user_id()
        cur.execute(
            "INSERT INTO users (id, username, password, role, invite_code) VALUES (?, ?, ?, ?, ?)",
            (uid, username, hashed_pw, role, invite_code),
        )
        conn.commit()
    finally:
        conn.close()
    return uid


def get_user_by_id(user_id):
    """Return the user row for the given *user_id*, or None if not found."""
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return user


def get_user_by_username(username):
    """Return the user row for the given *username* (case-insensitive), or None."""
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone()
    conn.close()
    return user


_ALLOWED_USER_COLUMNS = {"username", "password", "role", "suspended", "last_login_at", "session_token",
                         "oauth_provider", "oauth_id"}


def update_user(user_id, **kwargs):
    """Update one or more user columns for the given *user_id*.

    Only columns listed in ``_ALLOWED_USER_COLUMNS`` may be changed;
    any unknown column name raises :exc:`ValueError`.
    """
    if not user_id:
        raise ValueError("user_id is required")
    for k in kwargs:
        if k not in _ALLOWED_USER_COLUMNS:
            raise ValueError(f"Invalid column: {k}")
    if not kwargs:
        return
    conn = get_db()
    try:
        sets = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [user_id]
        conn.execute(f"UPDATE users SET {sets} WHERE id=?", vals)
        conn.commit()
    finally:
        conn.close()


def delete_user(user_id):
    """Delete a user and nullify any invite codes they used."""
    if not user_id:
        raise ValueError("user_id is required")
    conn = get_db()
    try:
        conn.execute("UPDATE invite_codes SET used_by=NULL WHERE used_by=?", (user_id,))
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def record_username_change(user_id, old_username, new_username):
    """Record a username change in the history table."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO username_history (user_id, old_username, new_username, changed_at) VALUES (?, ?, ?, ?)",
        (user_id, old_username, new_username, now),
    )
    conn.commit()
    conn.close()


def get_username_history(user_id):
    """Return all username changes for a user, newest first."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM username_history WHERE user_id=? ORDER BY changed_at DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    return rows


def set_easter_egg_found(user_id):
    """Mark that the user has found the easter egg (one-way: 0 -> 1 only)."""
    conn = get_db()
    conn.execute(
        "UPDATE users SET easter_egg_found=1 WHERE id=? AND easter_egg_found=0",
        (user_id,),
    )
    conn.commit()
    conn.close()


def get_user_by_oauth(provider, oauth_id):
    """Return the user row for the given OAuth *provider* and *oauth_id*, or None."""
    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE oauth_provider=? AND oauth_id=?",
        (provider, str(oauth_id)),
    ).fetchone()
    conn.close()
    return user


def create_oauth_user(username, oauth_provider, oauth_id, role="user"):
    """Create a new user via OAuth login (no usable password) and return its ID.

    The password column is filled with a hash of a random secret so that
    no plain-text password can ever match it, preventing password-based login
    until an admin explicitly sets one.
    """
    # Random 32-byte hex – discarded immediately, never stored in plaintext
    sentinel_hash = generate_password_hash(secrets.token_hex(32))
    conn = get_db()
    try:
        cur = conn.cursor()
        uid = _gen_user_id()
        while conn.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
            uid = _gen_user_id()
        cur.execute(
            "INSERT INTO users (id, username, password, role, oauth_provider, oauth_id)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (uid, username, sentinel_hash, role, oauth_provider, str(oauth_id)),
        )
        conn.commit()
    finally:
        conn.close()
    return uid


def list_oauth_users():
    """Return all users that signed up via an OAuth provider (non-NULL oauth_provider)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM users WHERE oauth_provider IS NOT NULL ORDER BY created_at"
    ).fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
#  Accessibility / user preferences
# ---------------------------------------------------------------------------
_A11Y_DEFAULTS = {
    "font_scale": 1.0,
    "contrast": 0,
    "sidebar_width": 250,
    "content_max_width": 0,
    "editor_pane_width": 0,
    "editor_height": 0,
    "custom_bg": "",
    "custom_text": "",
    "custom_primary": "",
    "custom_secondary": "",
    "custom_accent": "",
    "custom_sidebar": "",
    "line_height": 0,
    "letter_spacing": 0,
    "reduce_motion": 0,
}


def get_user_accessibility(user_id):
    """Return the accessibility preferences dict for a user (merged with defaults)."""
    conn = get_db()
    row = conn.execute("SELECT accessibility FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    result = dict(_A11Y_DEFAULTS)
    if row and row["accessibility"]:
        try:
            saved = json.loads(row["accessibility"])
            result.update({k: v for k, v in saved.items() if k in _A11Y_DEFAULTS})
        except (json.JSONDecodeError, TypeError):
            pass
    return result


def save_user_accessibility(user_id, prefs):
    """Persist accessibility preferences for a user."""
    cleaned = {k: prefs[k] for k in _A11Y_DEFAULTS if k in prefs}
    conn = get_db()
    conn.execute("UPDATE users SET accessibility=? WHERE id=?",
                 (json.dumps(cleaned), user_id))
    conn.commit()
    conn.close()


def record_login_attempt(ip):
    """Insert a failed login attempt record for the given *ip* address."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("INSERT INTO login_attempts (ip, attempted_at) VALUES (?, ?)", (ip, now))
    conn.commit()
    conn.close()


def count_recent_login_attempts(ip, window_seconds):
    """Return count of attempts from IP within the last window_seconds."""
    conn = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=window_seconds)).isoformat()
    # Prune old entries to keep table small
    conn.execute("DELETE FROM login_attempts WHERE attempted_at < ?", (cutoff,))
    cnt = conn.execute(
        "SELECT COUNT(*) FROM login_attempts WHERE ip=? AND attempted_at >= ?",
        (ip, cutoff),
    ).fetchone()[0]
    conn.commit()
    conn.close()
    return cnt


def clear_login_attempts(ip):
    """Remove all failed login attempt records for the given *ip* address."""
    conn = get_db()
    conn.execute("DELETE FROM login_attempts WHERE ip=?", (ip,))
    conn.commit()
    conn.close()


def clear_all_login_attempts():
    """Remove all failed login attempt records from the database."""
    conn = get_db()
    conn.execute("DELETE FROM login_attempts")
    conn.commit()
    conn.close()


def list_users(role_filter=None, status_filter=None):
    """Return a list of all users, optionally filtered by *role_filter* and/or *status_filter*.

    *status_filter* accepts ``'active'`` or ``'suspended'``.
    """
    conn = get_db()
    q = "SELECT * FROM users WHERE 1=1"
    params = []
    if role_filter:
        q += " AND role=?"
        params.append(role_filter)
    if status_filter == "active":
        q += " AND suspended=0"
    elif status_filter == "suspended":
        q += " AND suspended=1"
    q += " ORDER BY created_at"
    users = conn.execute(q, params).fetchall()
    conn.close()
    return users


def count_admins():
    """Return the number of active (non-suspended) admin or protected_admin accounts."""
    conn = get_db()
    cnt = conn.execute(
        "SELECT COUNT(*) FROM users WHERE role IN ('admin', 'protected_admin') AND suspended=0"
    ).fetchone()[0]
    conn.close()
    return cnt


# ---------------------------------------------------------------------------
#  Editor category access helpers
# ---------------------------------------------------------------------------
def get_editor_access(user_id):
    """Return the category access settings for an editor.

    Returns a dict with:
      - ``restricted`` (bool): True if the editor is limited to specific categories.
      - ``allowed_category_ids`` (list[int]): The IDs of categories the editor may access
        (only meaningful when ``restricted`` is True).
    """
    conn = get_db()
    row = conn.execute(
        "SELECT restricted FROM editor_category_access WHERE user_id=?", (user_id,)
    ).fetchone()
    restricted = bool(row["restricted"]) if row else False
    if restricted:
        rows = conn.execute(
            "SELECT category_id FROM editor_allowed_categories WHERE user_id=?", (user_id,)
        ).fetchall()
        allowed_ids = [r["category_id"] for r in rows]
    else:
        allowed_ids = []
    conn.close()
    return {"restricted": restricted, "allowed_category_ids": allowed_ids}


def set_user_chat_disabled(user_id, disabled):
    """Enable or disable the chat feature for a user."""
    conn = get_db()
    conn.execute(
        "UPDATE users SET chat_disabled=? WHERE id=?",
        (1 if disabled else 0, user_id),
    )
    conn.commit()
    conn.close()


def is_user_chat_disabled(user_id):
    """Return True if the user has been disabled from using chat."""
    conn = get_db()
    row = conn.execute("SELECT chat_disabled FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    if not row:
        return False
    return bool(row["chat_disabled"])


def set_editor_access(user_id, restricted, category_ids=None):
    """Persist category access settings for an editor.

    Args:
        user_id: The editor's user ID.
        restricted: If True the editor can only access the specified categories.
        category_ids: Iterable of category IDs to allow (ignored when restricted=False).
    """
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO editor_category_access (user_id, restricted) VALUES (?, ?)",
        (user_id, 1 if restricted else 0),
    )
    conn.execute(
        "DELETE FROM editor_allowed_categories WHERE user_id=?", (user_id,)
    )
    if restricted and category_ids:
        for cat_id in category_ids:
            conn.execute(
                "INSERT OR IGNORE INTO editor_allowed_categories (user_id, category_id) VALUES (?, ?)",
                (user_id, cat_id),
            )
    conn.commit()
    conn.close()

