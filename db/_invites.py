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
        "SELECT * FROM invite_codes WHERE code=? AND used_by IS NULL AND used_at IS NULL AND deleted=0",
        (code,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    expires = datetime.fromisoformat(row["expires_at"]).replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires:
        return None
    return row


def use_invite_code(code, user_id):
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

