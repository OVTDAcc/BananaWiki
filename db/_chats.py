"""Direct messaging (DM) chat helpers."""

import sqlite3
from datetime import datetime, timezone

from ._connection import get_db


# ---------------------------------------------------------------------------
#  Chat helpers
# ---------------------------------------------------------------------------
def get_or_create_chat(user1_id, user2_id):
    """Return an existing chat between two users, or create one.
    
    The pair is always stored with the smaller id first to enforce
    the UNIQUE constraint regardless of who initiates.
    """
    a, b = sorted([user1_id, user2_id])
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM chats WHERE user1_id=? AND user2_id=?", (a, b)
    ).fetchone()
    if row:
        conn.close()
        return dict(row)
    try:
        conn.execute(
            "INSERT INTO chats (user1_id, user2_id) VALUES (?, ?)", (a, b)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # concurrent insert – row already exists
    row = conn.execute(
        "SELECT * FROM chats WHERE user1_id=? AND user2_id=?", (a, b)
    ).fetchone()
    conn.close()
    return dict(row)


def get_chat_by_id(chat_id):
    """Return a single chat row or None."""
    conn = get_db()
    row = conn.execute("SELECT * FROM chats WHERE id=?", (chat_id,)).fetchone()
    conn.close()
    return row


def is_chat_participant(chat_id, user_id):
    """Return True if user_id is part of the chat."""
    conn = get_db()
    row = conn.execute(
        "SELECT 1 FROM chats WHERE id=? AND (user1_id=? OR user2_id=?)",
        (chat_id, user_id, user_id),
    ).fetchone()
    conn.close()
    return row is not None


def get_user_chats(user_id):
    """Return all chats for a user, with the other user's info and last message."""
    conn = get_db()
    rows = conn.execute(
        "SELECT c.*, "
        "  CASE WHEN c.user1_id=? THEN u2.username ELSE u1.username END AS other_username, "
        "  CASE WHEN c.user1_id=? THEN c.user2_id ELSE c.user1_id END AS other_user_id, "
        "  m.content AS last_message, "
        "  m.created_at AS last_message_at "
        "FROM chats c "
        "JOIN users u1 ON c.user1_id=u1.id "
        "JOIN users u2 ON c.user2_id=u2.id "
        "LEFT JOIN chat_messages m ON m.id = ("
        "  SELECT id FROM chat_messages WHERE chat_id=c.id ORDER BY created_at DESC LIMIT 1"
        ") "
        "WHERE c.user1_id=? OR c.user2_id=? "
        "ORDER BY COALESCE(m.created_at, c.created_at) DESC",
        (user_id, user_id, user_id, user_id),
    ).fetchall()
    conn.close()
    return rows


def get_chat_messages(chat_id):
    """Return all messages in a chat, oldest first, with sender info and attachments."""
    conn = get_db()
    rows = conn.execute(
        "SELECT cm.*, u.username AS sender_name "
        "FROM chat_messages cm "
        "JOIN users u ON cm.sender_id=u.id "
        "WHERE cm.chat_id=? "
        "ORDER BY cm.created_at ASC",
        (chat_id,),
    ).fetchall()
    # Fetch attachments for each message
    messages = []
    for r in rows:
        msg = dict(r)
        atts = conn.execute(
            "SELECT * FROM chat_attachments WHERE message_id=? ORDER BY id ASC",
            (r["id"],),
        ).fetchall()
        msg["attachments"] = [dict(a) for a in atts]
        messages.append(msg)
    conn.close()
    return messages


def send_chat_message(chat_id, sender_id, content, ip_address=""):
    """Insert a new message into a chat. Returns the new message id."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO chat_messages (chat_id, sender_id, content, ip_address, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (chat_id, sender_id, content, ip_address, now),
    )
    msg_id = cur.lastrowid
    conn.commit()
    conn.close()
    return msg_id


def add_chat_attachment(message_id, filename, original_name, file_size):
    """Record a new attachment for a chat message. Returns the attachment id."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO chat_attachments (message_id, filename, original_name, file_size, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (message_id, filename, original_name, file_size, now),
    )
    att_id = cur.lastrowid
    conn.commit()
    conn.close()
    return att_id


def get_user_chat_attachment_count_today(user_id):
    """Return the number of chat attachments sent by user today (since last cleanup)."""
    conn = get_db()
    count = conn.execute(
        "SELECT COUNT(*) FROM chat_attachments ca "
        "JOIN chat_messages cm ON ca.message_id=cm.id "
        "WHERE cm.sender_id=?",
        (user_id,),
    ).fetchone()[0]
    conn.close()
    return count


def get_chat_attachment(attachment_id):
    """Return a single chat attachment row or None."""
    conn = get_db()
    row = conn.execute(
        "SELECT ca.*, cm.chat_id, cm.sender_id "
        "FROM chat_attachments ca "
        "JOIN chat_messages cm ON ca.message_id=cm.id "
        "WHERE ca.id=?",
        (attachment_id,),
    ).fetchone()
    conn.close()
    return row


def get_all_chats_admin():
    """Return all chats with both usernames (for admin view)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT c.*, u1.username AS user1_name, u2.username AS user2_name, "
        "  (SELECT COUNT(*) FROM chat_messages WHERE chat_id=c.id) AS message_count, "
        "  m.created_at AS last_message_at "
        "FROM chats c "
        "JOIN users u1 ON c.user1_id=u1.id "
        "JOIN users u2 ON c.user2_id=u2.id "
        "LEFT JOIN chat_messages m ON m.id = ("
        "  SELECT id FROM chat_messages WHERE chat_id=c.id ORDER BY created_at DESC LIMIT 1"
        ") "
        "ORDER BY COALESCE(m.created_at, c.created_at) DESC"
    ).fetchall()
    conn.close()
    return rows


def get_user_chats_admin(user_id):
    """Return all chats for a specific user (admin view)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT c.*, u1.username AS user1_name, u2.username AS user2_name, "
        "  (SELECT COUNT(*) FROM chat_messages WHERE chat_id=c.id) AS message_count, "
        "  m.created_at AS last_message_at "
        "FROM chats c "
        "JOIN users u1 ON c.user1_id=u1.id "
        "JOIN users u2 ON c.user2_id=u2.id "
        "LEFT JOIN chat_messages m ON m.id = ("
        "  SELECT id FROM chat_messages WHERE chat_id=c.id ORDER BY created_at DESC LIMIT 1"
        ") "
        "WHERE c.user1_id=? OR c.user2_id=? "
        "ORDER BY COALESCE(m.created_at, c.created_at) DESC",
        (user_id, user_id),
    ).fetchall()
    conn.close()
    return rows


def get_all_messages_for_backup():
    """Return all chat messages with sender/receiver info and attachments for Telegram backup."""
    conn = get_db()
    rows = conn.execute(
        "SELECT cm.*, u.username AS sender_name, "
        "  CASE WHEN c.user1_id=cm.sender_id THEN u2.username ELSE u1.username END AS receiver_name "
        "FROM chat_messages cm "
        "JOIN chats c ON cm.chat_id=c.id "
        "JOIN users u ON cm.sender_id=u.id "
        "JOIN users u1 ON c.user1_id=u1.id "
        "JOIN users u2 ON c.user2_id=u2.id "
        "ORDER BY cm.created_at ASC"
    ).fetchall()
    messages = []
    for r in rows:
        msg = dict(r)
        atts = conn.execute(
            "SELECT * FROM chat_attachments WHERE message_id=? ORDER BY id ASC",
            (r["id"],),
        ).fetchall()
        msg["attachments"] = [dict(a) for a in atts]
        messages.append(msg)
    conn.close()
    return messages


def cleanup_old_chat_messages(retention_days=30):
    """Delete chat messages older than retention_days (and their attachments via CASCADE).

    Args:
        retention_days: Keep messages newer than this many days

    Returns list of attachment filenames that need to be removed from disk.
    """
    conn = get_db()
    # Collect attachment filenames for messages that will be deleted
    filenames = conn.execute(
        """SELECT ca.filename FROM chat_attachments ca
           JOIN chat_messages cm ON ca.message_id = cm.id
           WHERE datetime(cm.created_at) < datetime('now', '-' || ? || ' days')""",
        (retention_days,)
    ).fetchall()
    files_to_delete = [r["filename"] for r in filenames]
    # Delete messages older than retention period (attachments cascade)
    conn.execute(
        """DELETE FROM chat_messages
           WHERE datetime(created_at) < datetime('now', '-' || ? || ' days')""",
        (retention_days,)
    )
    # Also delete empty chats (chats with no messages)
    conn.execute(
        "DELETE FROM chats WHERE id NOT IN (SELECT DISTINCT chat_id FROM chat_messages)"
    )
    conn.commit()
    conn.close()
    return files_to_delete

