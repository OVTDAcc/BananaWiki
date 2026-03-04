"""Draft management."""

from datetime import datetime, timezone

from ._connection import get_db


# ---------------------------------------------------------------------------
#  Draft helpers
# ---------------------------------------------------------------------------
def save_draft(page_id, user_id, title, content):
    """Insert or replace a draft for the given (page, user) pair."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO drafts (page_id, user_id, title, content, updated_at) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(page_id, user_id) DO UPDATE SET title=?, content=?, updated_at=?",
        (page_id, user_id, title, content, now, title, content, now),
    )
    conn.commit()
    conn.close()


def get_draft(page_id, user_id):
    """Return the draft for a specific (page, user) pair, or None if none exists."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM drafts WHERE page_id=? AND user_id=?", (page_id, user_id)
    ).fetchone()
    conn.close()
    return row


def get_drafts_for_page(page_id):
    """Return all drafts for a given page, with editor usernames joined."""
    conn = get_db()
    rows = conn.execute(
        "SELECT d.*, u.username FROM drafts d JOIN users u ON d.user_id=u.id WHERE d.page_id=?",
        (page_id,),
    ).fetchall()
    conn.close()
    return rows


def delete_draft(page_id, user_id):
    """Delete the draft for the given (page, user) pair."""
    conn = get_db()
    conn.execute("DELETE FROM drafts WHERE page_id=? AND user_id=?", (page_id, user_id))
    conn.commit()
    conn.close()


def transfer_draft(page_id, from_user, to_user):
    """Transfer a draft from one user to another (atomic).

    Deletes the target user's existing draft (if any) and transfers the
    source user's draft.
    """
    conn = get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("DELETE FROM drafts WHERE page_id=? AND user_id=?", (page_id, to_user))
        conn.execute(
            "UPDATE drafts SET user_id=?, updated_at=? WHERE page_id=? AND user_id=?",
            (to_user, now, page_id, from_user),
        )
        conn.commit()
    finally:
        conn.close()


def get_user_draft_count(user_id):
    """Return number of pending drafts for a user across all pages."""
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM drafts WHERE user_id=?", (user_id,)
    ).fetchone()
    conn.close()
    return row["cnt"] if row else 0


def list_user_drafts(user_id):
    """Return all drafts belonging to a user, with page info."""
    conn = get_db()
    rows = conn.execute(
        "SELECT d.*, p.title AS page_title, p.slug AS page_slug "
        "FROM drafts d JOIN pages p ON d.page_id = p.id "
        "WHERE d.user_id=? ORDER BY d.updated_at DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    return rows

