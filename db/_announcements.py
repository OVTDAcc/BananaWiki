"""Announcements and contributions."""

from datetime import datetime, timezone

from ._connection import get_db


# ---------------------------------------------------------------------------
#  Announcement helpers
# ---------------------------------------------------------------------------
def create_announcement(content, color, text_size, visibility, expires_at, user_id,
                        not_removable=1, show_countdown=1):
    conn = get_db()
    try:
        cur = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        cur.execute(
            "INSERT INTO announcements (content, color, text_size, visibility, expires_at, is_active, not_removable, show_countdown, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)",
            (content, color, text_size, visibility, expires_at or None, int(not_removable), int(show_countdown), user_id, now),
        )
        ann_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return ann_id


def get_announcement(ann_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM announcements WHERE id=?", (ann_id,)).fetchone()
    conn.close()
    return row


def list_announcements():
    conn = get_db()
    rows = conn.execute(
        "SELECT a.*, COALESCE(u.username, 'deleted user') AS creator_name "
        "FROM announcements a LEFT JOIN users u ON a.created_by=u.id "
        "ORDER BY a.created_at DESC"
    ).fetchall()
    conn.close()
    return rows


_ALLOWED_ANN_COLUMNS = {"content", "color", "text_size", "visibility", "expires_at", "is_active", "not_removable", "show_countdown"}


def update_announcement(ann_id, **kwargs):
    for k in kwargs:
        if k not in _ALLOWED_ANN_COLUMNS:
            raise ValueError(f"Invalid column: {k}")
    conn = get_db()
    try:
        sets = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [ann_id]
        conn.execute(f"UPDATE announcements SET {sets} WHERE id=?", vals)
        conn.commit()
    finally:
        conn.close()


def delete_announcement(ann_id):
    conn = get_db()
    conn.execute("DELETE FROM announcements WHERE id=?", (ann_id,))
    conn.commit()
    conn.close()


def get_user_contributions(user_id):
    """Return all page history entries edited by a user, with page info."""
    conn = get_db()
    rows = conn.execute(
        "SELECT ph.id, ph.page_id, COALESCE(p.title, '[deleted page]') AS page_title, "
        "COALESCE(p.slug, '') AS page_slug, "
        "ph.title AS edit_title, ph.content, ph.edit_message, ph.created_at "
        "FROM page_history ph "
        "LEFT JOIN pages p ON ph.page_id = p.id "
        "WHERE ph.edited_by=? ORDER BY ph.created_at DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    return rows


def get_active_announcements(is_logged_in):
    """Return active, non-expired announcements matching the user's login state."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    logged_in_int = 1 if is_logged_in else 0
    rows = conn.execute(
        "SELECT * FROM announcements "
        "WHERE is_active=1 "
        "  AND (expires_at IS NULL OR expires_at > ?) "
        "  AND (visibility='both' "
        "       OR (visibility='logged_in' AND ?=1) "
        "       OR (visibility='logged_out' AND ?=0)) "
        "ORDER BY created_at DESC",
        (now, logged_in_int, logged_in_int),
    ).fetchall()
    conn.close()
    return rows

