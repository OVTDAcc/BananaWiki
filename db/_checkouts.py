"""Page checkout (edit-lock) management.

A checkout is a short-lived record that lets editors signal they are actively
editing a page.  Other users see the checkout on the page view and a warning
on the edit page.  Checkouts expire automatically after
``config.CHECKOUT_TIMEOUT_MINUTES`` minutes and are released when the editing
user saves the page.
"""

from datetime import datetime, timedelta, timezone

import config
from ._connection import get_db


def _now_utc() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


def checkout_page(page_id: int, user_id: str) -> None:
    """Create or refresh a checkout for *user_id* on *page_id*.

    If the user already holds the checkout it is refreshed (expires_at is
    pushed forward).  If another user holds a non-expired checkout nothing
    changes – callers should call :func:`get_page_checkout` first to decide
    whether to proceed.
    """
    conn = get_db()
    now = _now_utc()
    expires = now + timedelta(minutes=config.CHECKOUT_TIMEOUT_MINUTES)
    conn.execute(
        """
        INSERT INTO page_checkouts (page_id, user_id, checked_out_at, expires_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(page_id) DO UPDATE
            SET user_id        = excluded.user_id,
                checked_out_at = excluded.checked_out_at,
                expires_at     = excluded.expires_at
        """,
        (page_id, user_id, now.isoformat(), expires.isoformat()),
    )
    conn.commit()
    conn.close()


def release_checkout(page_id: int, user_id: str) -> None:
    """Release the checkout held by *user_id* for *page_id*.

    Does nothing if the user does not hold the checkout.
    """
    conn = get_db()
    conn.execute(
        "DELETE FROM page_checkouts WHERE page_id=? AND user_id=?",
        (page_id, user_id),
    )
    conn.commit()
    conn.close()


def get_page_checkout(page_id: int):
    """Return the active checkout row for *page_id*, or ``None``.

    Expired checkouts are treated as absent (they are deleted as a side
    effect so that they do not accumulate).
    """
    conn = get_db()
    row = conn.execute(
        """
        SELECT c.*, u.username
        FROM page_checkouts c
        JOIN users u ON c.user_id = u.id
        WHERE c.page_id = ?
        """,
        (page_id,),
    ).fetchone()
    if row is None:
        conn.close()
        return None
    # Expire check
    expires = datetime.fromisoformat(row["expires_at"])
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if _now_utc() > expires:
        conn.execute("DELETE FROM page_checkouts WHERE page_id=?", (page_id,))
        conn.commit()
        conn.close()
        return None
    conn.close()
    return row


def cleanup_expired_checkouts() -> int:
    """Delete all expired checkout rows.  Returns the number of rows removed."""
    conn = get_db()
    now = _now_utc().isoformat()
    cur = conn.execute(
        "DELETE FROM page_checkouts WHERE expires_at < ?", (now,)
    )
    count = cur.rowcount
    conn.commit()
    conn.close()
    return count
