"""API token creation, lookup, and revocation."""

import secrets
from datetime import datetime, timezone

from ._connection import get_db

_TOKEN_BYTES = 32  # 256-bit token → 64 hex chars


def _gen_token():
    return secrets.token_hex(_TOKEN_BYTES)


def create_api_token(user_id, name):
    """Create a new API token for *user_id* with the given *name*.

    Returns the new token string (plain-text, shown once).
    """
    token = _gen_token()
    conn = get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO api_tokens (user_id, token, name, created_at) VALUES (?, ?, ?, ?)",
            (user_id, token, name, now),
        )
        conn.commit()
    finally:
        conn.close()
    return token


def get_api_token_by_value(token):
    """Return the token row for *token*, or None if not found."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM api_tokens WHERE token=?", (token,)
    ).fetchone()
    conn.close()
    return row


def list_user_api_tokens(user_id):
    """Return all API tokens for *user_id*, newest first.

    The ``token`` column is masked; only ``id``, ``name``,
    ``created_at``, and ``last_used_at`` are returned.
    """
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name, created_at, last_used_at FROM api_tokens WHERE user_id=? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    return rows


def revoke_api_token(token_id, user_id):
    """Delete the token with *token_id* belonging to *user_id*.

    Returns True if a row was deleted, False otherwise.
    """
    conn = get_db()
    try:
        cur = conn.execute(
            "DELETE FROM api_tokens WHERE id=? AND user_id=?", (token_id, user_id)
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def update_token_last_used(token_id):
    """Update the ``last_used_at`` timestamp for *token_id*."""
    conn = get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE api_tokens SET last_used_at=? WHERE id=?", (now, token_id)
        )
        conn.commit()
    finally:
        conn.close()


def revoke_all_user_api_tokens(user_id):
    """Delete all API tokens for *user_id*."""
    conn = get_db()
    try:
        conn.execute("DELETE FROM api_tokens WHERE user_id=?", (user_id,))
        conn.commit()
    finally:
        conn.close()
