"""Invite code management."""

import string
import secrets
from datetime import datetime, timedelta, timezone

import config

from ._connection import get_db


# ---------------------------------------------------------------------------
#  Invite code helpers
# ---------------------------------------------------------------------------
def generate_invite_code(created_by):
    """Generate and persist a new invite code for *created_by*.  Returns the code string."""
    chars = string.ascii_uppercase + string.digits
    code = "".join(secrets.choice(chars) for _ in range(4)) + "-" + "".join(secrets.choice(chars) for _ in range(4))
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=config.INVITE_CODE_EXPIRY_HOURS)
    conn = get_db()
    conn.execute(
        "INSERT INTO invite_codes (code, created_by, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (code, created_by, now.isoformat(), expires.isoformat()),
    )
    conn.commit()
    conn.close()
    return code


def validate_invite_code(code):
    """Return the invite row if valid, else None."""
    conn = get_db()
    row = conn.execute(
        "SELECT ic.*, u.suspended AS creator_suspended "
        "FROM invite_codes ic "
        "JOIN users u ON ic.created_by = u.id "
        "WHERE ic.code=? AND ic.used_by IS NULL AND ic.used_at IS NULL AND ic.deleted=0",
        (code,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    expires = datetime.fromisoformat(row["expires_at"]).replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires:
        return None
    if row["creator_suspended"]:
        return None
    return row


def use_invite_code(code, user_id):
    """Mark an invite code as used by *user_id*.  Returns True if the update succeeded."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    cur = conn.execute(
        "UPDATE invite_codes SET used_by=?, used_at=? WHERE code=? AND used_by IS NULL AND used_at IS NULL AND deleted=0",
        (user_id, now, code),
    )
    conn.commit()
    updated = cur.rowcount > 0
    conn.close()
    return updated


def delete_invite_code(code_id):
    """Soft-delete an invite code by setting its ``deleted`` flag."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    conn.execute("UPDATE invite_codes SET deleted=1, deleted_at=? WHERE id=?", (now, code_id))
    conn.commit()
    conn.close()


def hard_delete_invite_code(code_id):
    """Permanently remove an expired/used/deleted invite code record."""
    conn = get_db()
    conn.execute("DELETE FROM invite_codes WHERE id=?", (code_id,))
    conn.commit()
    conn.close()


def list_invite_codes(active_only=True):
    """Return invite codes, optionally limited to active (unused, non-expired, non-deleted) ones."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    if active_only:
        rows = conn.execute(
            "SELECT ic.*, COALESCE(u.username, 'deleted user') AS creator_name FROM invite_codes ic "
            "LEFT JOIN users u ON ic.created_by=u.id "
            "WHERE ic.used_by IS NULL AND ic.deleted=0 AND ic.expires_at > ? "
            "ORDER BY ic.created_at DESC",
            (now,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT ic.*, COALESCE(u.username, 'deleted user') AS creator_name, u2.username AS used_by_name "
            "FROM invite_codes ic "
            "LEFT JOIN users u ON ic.created_by=u.id "
            "LEFT JOIN users u2 ON ic.used_by=u2.id "
            "ORDER BY ic.created_at DESC"
        ).fetchall()
    conn.close()
    return rows


def list_expired_codes():
    """Return all invite codes that have been used, soft-deleted, or have expired."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    rows = conn.execute(
        "SELECT ic.*, COALESCE(u.username, 'deleted user') AS creator_name, u2.username AS used_by_name "
        "FROM invite_codes ic "
        "LEFT JOIN users u ON ic.created_by=u.id "
        "LEFT JOIN users u2 ON ic.used_by=u2.id "
        "WHERE ic.used_by IS NOT NULL OR ic.used_at IS NOT NULL OR ic.deleted=1 OR ic.expires_at <= ? "
        "ORDER BY ic.created_at DESC",
        (now,),
    ).fetchall()
    conn.close()
    return rows
