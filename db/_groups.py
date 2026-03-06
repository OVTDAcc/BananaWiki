"""Group chat helpers."""

import sqlite3
import string
import secrets
from datetime import datetime, timezone

from ._connection import get_db


# ---------------------------------------------------------------------------
#  Group Chats
# ---------------------------------------------------------------------------

def generate_invite_code_for_group():
    """Generate a random 8-character invite code for a group chat."""
    return ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))


def create_group_chat(name, creator_id):
    """Create a new group chat and add the creator as owner. Returns the group dict."""
    conn = get_db()
    invite_code = generate_invite_code_for_group()
    now = datetime.now(timezone.utc).isoformat()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO group_chats (name, creator_id, invite_code, created_at) VALUES (?, ?, ?, ?)",
            (name, creator_id, invite_code, now),
        )
        group_id = cur.lastrowid
        cur.execute(
            "INSERT INTO group_members (group_id, user_id, role, joined_at) VALUES (?, ?, 'owner', ?)",
            (group_id, creator_id, now),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM group_chats WHERE id=?", (group_id,)).fetchone()
    finally:
        conn.close()
    return dict(row)


def get_or_create_global_chat():
    """Return the global chat (is_global=1), creating it if necessary. Returns a dict."""
    conn = get_db()
    row = conn.execute("SELECT * FROM group_chats WHERE is_global=1").fetchone()
    if row:
        conn.close()
        return dict(row)
    now = datetime.now(timezone.utc).isoformat()
    invite_code = generate_invite_code_for_group()
    try:
        conn.execute(
            "INSERT INTO group_chats (name, creator_id, invite_code, is_global, created_at) "
            "VALUES (?, NULL, ?, 1, ?)",
            ("Global Chat", invite_code, now),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    row = conn.execute("SELECT * FROM group_chats WHERE is_global=1").fetchone()
    conn.close()
    return dict(row)


def get_group_chat(group_id):
    """Return a single group chat dict, or None."""
    conn = get_db()
    row = conn.execute("SELECT * FROM group_chats WHERE id=?", (group_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_group_chat_by_invite(invite_code):
    """Return a group chat by its invite code, or None."""
    conn = get_db()
    row = conn.execute("SELECT * FROM group_chats WHERE invite_code=?", (invite_code,)).fetchone()
    conn.close()
    return dict(row) if row else None


def is_group_member(group_id, user_id):
    """Return True if user is a member of the group."""
    conn = get_db()
    row = conn.execute(
        "SELECT 1 FROM group_members WHERE group_id=? AND user_id=?",
        (group_id, user_id),
    ).fetchone()
    conn.close()
    return row is not None


def get_group_member(group_id, user_id):
    """Return the group_members row for a user in a group, or None."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM group_members WHERE group_id=? AND user_id=?",
        (group_id, user_id),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_group_member_role(group_id, user_id):
    """Return the role string ('owner', 'moderator', 'member') or None if not a member."""
    conn = get_db()
    row = conn.execute(
        "SELECT role FROM group_members WHERE group_id=? AND user_id=?",
        (group_id, user_id),
    ).fetchone()
    conn.close()
    return row["role"] if row else None


def add_group_member(group_id, user_id, role="member"):
    """Add a user to a group. Returns True if added, False if already a member."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            "INSERT INTO group_members (group_id, user_id, role, joined_at) VALUES (?, ?, ?, ?)",
            (group_id, user_id, role, now),
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False


def remove_group_member(group_id, user_id):
    """Remove a user from a group."""
    conn = get_db()
    conn.execute(
        "DELETE FROM group_members WHERE group_id=? AND user_id=?",
        (group_id, user_id),
    )
    conn.commit()
    conn.close()


def get_group_members(group_id):
    """Return all non-banned members of a group with their user info."""
    conn = get_db()
    rows = conn.execute(
        "SELECT gm.*, u.username FROM group_members gm "
        "JOIN users u ON gm.user_id=u.id "
        "WHERE gm.group_id=? AND gm.banned=0 "
        "ORDER BY CASE gm.role WHEN 'owner' THEN 0 WHEN 'moderator' THEN 1 ELSE 2 END, gm.joined_at ASC",
        (group_id,),
    ).fetchall()
    conn.close()
    return rows


def set_group_member_role(group_id, user_id, new_role):
    """Update a member's role in a group."""
    conn = get_db()
    conn.execute(
        "UPDATE group_members SET role=? WHERE group_id=? AND user_id=?",
        (new_role, group_id, user_id),
    )
    conn.commit()
    conn.close()


def set_group_member_timeout(group_id, user_id, until):
    """Set a timeout on a group member. `until` is an ISO datetime string, or None to clear the timeout."""
    conn = get_db()
    conn.execute(
        "UPDATE group_members SET timed_out_until=? WHERE group_id=? AND user_id=?",
        (until, group_id, user_id),
    )
    conn.commit()
    conn.close()


def is_group_member_timed_out(group_id, user_id):
    """Return True if the member is currently timed out."""
    conn = get_db()
    row = conn.execute(
        "SELECT timed_out_until FROM group_members WHERE group_id=? AND user_id=?",
        (group_id, user_id),
    ).fetchone()
    conn.close()
    if not row or not row["timed_out_until"]:
        return False
    try:
        timeout_dt = datetime.fromisoformat(row["timed_out_until"])
        if timeout_dt.tzinfo is None:
            timeout_dt = timeout_dt.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < timeout_dt
    except (ValueError, TypeError):
        return False


def get_user_groups(user_id):
    """Return all groups a user is a member of, with last message info."""
    conn = get_db()
    rows = conn.execute(
        "SELECT gc.*, gm.role AS my_role, "
        "  m.content AS last_message, m.created_at AS last_message_at, "
        "  (SELECT COUNT(*) FROM group_members WHERE group_id=gc.id) AS member_count "
        "FROM group_chats gc "
        "JOIN group_members gm ON gc.id=gm.group_id AND gm.user_id=? "
        "LEFT JOIN group_messages m ON m.id = ("
        "  SELECT id FROM group_messages WHERE group_id=gc.id ORDER BY created_at DESC LIMIT 1"
        ") "
        "ORDER BY COALESCE(m.created_at, gc.created_at) DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    return rows


def send_group_message(group_id, sender_id, content, ip_address="", is_system=False):
    """Insert a new message into a group chat. Returns the new message id."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO group_messages (group_id, sender_id, content, is_system, ip_address, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (group_id, sender_id, content, 1 if is_system else 0, ip_address, now),
    )
    msg_id = cur.lastrowid
    conn.commit()
    conn.close()
    return msg_id


def send_group_system_message(group_id, content):
    """Insert a system message (no sender) into a group chat."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO group_messages (group_id, sender_id, content, is_system, ip_address, created_at) "
        "VALUES (?, NULL, ?, 1, '', ?)",
        (group_id, content, now),
    )
    msg_id = cur.lastrowid
    conn.commit()
    conn.close()
    return msg_id


def get_group_messages(group_id):
    """Return all messages in a group, oldest first, with sender info and attachments."""
    conn = get_db()
    rows = conn.execute(
        "SELECT gm.*, u.username AS sender_name "
        "FROM group_messages gm "
        "LEFT JOIN users u ON gm.sender_id=u.id "
        "WHERE gm.group_id=? "
        "ORDER BY gm.created_at ASC",
        (group_id,),
    ).fetchall()
    messages = []
    for r in rows:
        msg = dict(r)
        atts = conn.execute(
            "SELECT * FROM group_attachments WHERE message_id=? ORDER BY id ASC",
            (r["id"],),
        ).fetchall()
        msg["attachments"] = [dict(a) for a in atts]
        messages.append(msg)
    conn.close()
    return messages


def add_group_attachment(message_id, filename, original_name, file_size):
    """Record a new attachment for a group message. Returns the attachment id."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO group_attachments (message_id, filename, original_name, file_size, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (message_id, filename, original_name, file_size, now),
    )
    att_id = cur.lastrowid
    conn.commit()
    conn.close()
    return att_id


def get_group_attachment(attachment_id):
    """Return a single group attachment row with group_id and sender_id, or None."""
    conn = get_db()
    row = conn.execute(
        "SELECT ga.*, gm.group_id, gm.sender_id "
        "FROM group_attachments ga "
        "JOIN group_messages gm ON ga.message_id=gm.id "
        "WHERE ga.id=?",
        (attachment_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_group_message(message_id):
    """Delete a single group message (attachments cascade). Returns list of attachment filenames."""
    conn = get_db()
    filenames = conn.execute(
        "SELECT filename FROM group_attachments WHERE message_id=?", (message_id,)
    ).fetchall()
    files = [r["filename"] for r in filenames]
    conn.execute("DELETE FROM group_messages WHERE id=?", (message_id,))
    conn.commit()
    conn.close()
    return files


def get_group_message_by_id(message_id):
    """Return a single group message row, or None."""
    conn = get_db()
    row = conn.execute("SELECT * FROM group_messages WHERE id=?", (message_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_group_chats_admin():
    """Return all group chats with member counts (for admin view)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT gc.*, u.username AS creator_name, "
        "  (SELECT COUNT(*) FROM group_members WHERE group_id=gc.id) AS member_count, "
        "  (SELECT COUNT(*) FROM group_messages WHERE group_id=gc.id) AS message_count, "
        "  m.created_at AS last_message_at "
        "FROM group_chats gc "
        "LEFT JOIN users u ON gc.creator_id=u.id "
        "LEFT JOIN group_messages m ON m.id = ("
        "  SELECT id FROM group_messages WHERE group_id=gc.id ORDER BY created_at DESC LIMIT 1"
        ") "
        "ORDER BY COALESCE(m.created_at, gc.created_at) DESC"
    ).fetchall()
    conn.close()
    return rows


def get_all_group_messages_for_backup():
    """Return all group messages with sender info and attachments for Telegram backup."""
    conn = get_db()
    rows = conn.execute(
        "SELECT gm.*, gc.name AS group_name, u.username AS sender_name "
        "FROM group_messages gm "
        "JOIN group_chats gc ON gm.group_id=gc.id "
        "LEFT JOIN users u ON gm.sender_id=u.id "
        "ORDER BY gm.created_at ASC"
    ).fetchall()
    messages = []
    for r in rows:
        msg = dict(r)
        atts = conn.execute(
            "SELECT * FROM group_attachments WHERE message_id=? ORDER BY id ASC",
            (r["id"],),
        ).fetchall()
        msg["attachments"] = [dict(a) for a in atts]
        messages.append(msg)
    conn.close()
    return messages


def get_group_messages_for_export(group_id):
    """Return all messages for a specific group with sender info and attachments for export.

    Args:
        group_id: The group chat ID to export messages from.

    Returns:
        A tuple of (messages, group_info) where:
        - messages is a list of message dicts with attachments
        - group_info is the group chat dict
    """
    conn = get_db()

    # Get group info
    group_row = conn.execute(
        "SELECT * FROM group_chats WHERE id=?", (group_id,)
    ).fetchone()
    if not group_row:
        conn.close()
        return [], None

    group_info = dict(group_row)

    # Get all messages for this group
    rows = conn.execute(
        "SELECT gm.*, u.username AS sender_name "
        "FROM group_messages gm "
        "LEFT JOIN users u ON gm.sender_id=u.id "
        "WHERE gm.group_id=? "
        "ORDER BY gm.created_at ASC",
        (group_id,)
    ).fetchall()

    messages = []
    for r in rows:
        msg = dict(r)
        # Get attachments for this message
        atts = conn.execute(
            "SELECT * FROM group_attachments WHERE message_id=? ORDER BY id ASC",
            (r["id"],),
        ).fetchall()
        msg["attachments"] = [dict(a) for a in atts]
        messages.append(msg)

    conn.close()
    return messages, group_info


def cleanup_old_group_messages():
    """Delete all group messages (and their attachments via CASCADE).

    Returns list of attachment filenames that need to be removed from disk.
    Unlike DM chats, group chats themselves are NOT deleted (they persist).
    """
    conn = get_db()
    filenames = conn.execute(
        "SELECT ga.filename FROM group_attachments ga"
    ).fetchall()
    files_to_delete = [r["filename"] for r in filenames]
    conn.execute("DELETE FROM group_messages")
    conn.commit()
    conn.close()
    return files_to_delete


def get_user_group_attachment_count_today(user_id):
    """Return the number of group attachments sent by user today (since last cleanup)."""
    conn = get_db()
    count = conn.execute(
        "SELECT COUNT(*) FROM group_attachments ga "
        "JOIN group_messages gm ON ga.message_id=gm.id "
        "WHERE gm.sender_id=?",
        (user_id,),
    ).fetchone()[0]
    conn.close()
    return count


def transfer_group_ownership(group_id, old_owner_id, new_owner_id):
    """Transfer group ownership: old owner becomes moderator, new owner gets ownership."""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE group_members SET role='moderator' WHERE group_id=? AND user_id=?",
            (group_id, old_owner_id),
        )
        conn.execute(
            "UPDATE group_members SET role='owner' WHERE group_id=? AND user_id=?",
            (group_id, new_owner_id),
        )
        conn.execute(
            "UPDATE group_chats SET creator_id=? WHERE id=?",
            (new_owner_id, group_id),
        )
        conn.commit()
    finally:
        conn.close()


def ban_group_member(group_id, user_id):
    """Permanently ban a user from a group. The member row is kept with banned=1."""
    conn = get_db()
    conn.execute(
        "UPDATE group_members SET banned=1 WHERE group_id=? AND user_id=?",
        (group_id, user_id),
    )
    conn.commit()
    conn.close()


def unban_group_member(group_id, user_id):
    """Revoke a ban and remove the user from the group so they can rejoin."""
    conn = get_db()
    conn.execute(
        "DELETE FROM group_members WHERE group_id=? AND user_id=?",
        (group_id, user_id),
    )
    conn.commit()
    conn.close()


def is_group_member_banned(group_id, user_id):
    """Return True if the user is banned from the group."""
    conn = get_db()
    row = conn.execute(
        "SELECT banned FROM group_members WHERE group_id=? AND user_id=?",
        (group_id, user_id),
    ).fetchone()
    conn.close()
    if not row:
        return False
    return bool(row["banned"])


def get_group_banned_members(group_id):
    """Return all banned members of a group with their user info."""
    conn = get_db()
    rows = conn.execute(
        "SELECT gm.*, u.username FROM group_members gm "
        "JOIN users u ON gm.user_id=u.id "
        "WHERE gm.group_id=? AND gm.banned=1 "
        "ORDER BY gm.joined_at ASC",
        (group_id,),
    ).fetchall()
    conn.close()
    return rows


def regenerate_group_invite_code(group_id, custom_code=None):
    """Generate a new invite code for a group, revoking the previous one. Returns the new code.

    If *custom_code* is provided it is used directly (caller must validate format/uniqueness).
    Otherwise a random 8-character code is generated.
    """
    conn = get_db()
    new_code = custom_code if custom_code else generate_invite_code_for_group()
    conn.execute(
        "UPDATE group_chats SET invite_code=? WHERE id=?",
        (new_code, group_id),
    )
    conn.commit()
    conn.close()
    return new_code


def set_group_chat_active(group_id, is_active):
    """Set the active/inactive state of a group chat (used to deactivate/reactivate the global chat)."""
    conn = get_db()
    conn.execute(
        "UPDATE group_chats SET is_active=? WHERE id=?",
        (1 if is_active else 0, group_id),
    )
    conn.commit()
    conn.close()


def delete_group_chat(group_id):
    """Permanently delete a group chat and all its messages/members.

    Returns a list of attachment filenames that need to be removed from disk.
    The global chat cannot be deleted via this function – callers must enforce that.
    """
    conn = get_db()
    filenames = conn.execute(
        "SELECT ga.filename FROM group_attachments ga "
        "JOIN group_messages gm ON ga.message_id=gm.id "
        "WHERE gm.group_id=?",
        (group_id,),
    ).fetchall()
    files = [r["filename"] for r in filenames]
    # Cascade deletes messages, members, attachments via FK constraints
    conn.execute("DELETE FROM group_chats WHERE id=?", (group_id,))
    conn.commit()
    conn.close()
    return files
