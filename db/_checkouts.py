"""Page checkout/lock management."""

from datetime import datetime, timezone, timedelta

from ._connection import get_db


# Checkout timeout: pages are automatically released after 30 minutes of inactivity
CHECKOUT_TIMEOUT_MINUTES = 30


# ---------------------------------------------------------------------------
#  Checkout helpers
# ---------------------------------------------------------------------------
def acquire_checkout(page_id, user_id):
    """Attempt to acquire a checkout lock on a page.

    Returns:
        dict: Checkout record if successful
        None: If page is already checked out by another user
    """
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()

    try:
        # Check if page is already checked out
        existing = conn.execute(
            "SELECT * FROM page_checkouts WHERE page_id=?",
            (page_id,)
        ).fetchone()

        if existing:
            # Check if checkout has expired
            checkout_time = datetime.fromisoformat(existing["checked_out_at"])
            timeout = timedelta(minutes=CHECKOUT_TIMEOUT_MINUTES)

            if datetime.now(timezone.utc) - checkout_time < timeout:
                # Still active checkout by another user
                if existing["user_id"] != user_id:
                    return None
                # Same user, refresh the checkout
                conn.execute(
                    "UPDATE page_checkouts SET checked_out_at=? WHERE page_id=?",
                    (now, page_id)
                )
                conn.commit()
                result = conn.execute(
                    "SELECT pc.*, u.username FROM page_checkouts pc "
                    "JOIN users u ON pc.user_id=u.id WHERE pc.page_id=?",
                    (page_id,)
                ).fetchone()
                return result
            else:
                # Expired, delete it
                conn.execute("DELETE FROM page_checkouts WHERE page_id=?", (page_id,))

        # Acquire new checkout
        conn.execute(
            "INSERT INTO page_checkouts (page_id, user_id, checked_out_at) "
            "VALUES (?, ?, ?)",
            (page_id, user_id, now)
        )
        conn.commit()

        result = conn.execute(
            "SELECT pc.*, u.username FROM page_checkouts pc "
            "JOIN users u ON pc.user_id=u.id WHERE pc.page_id=?",
            (page_id,)
        ).fetchone()
        return result
    finally:
        conn.close()


def release_checkout(page_id, user_id=None):
    """Release a checkout lock on a page.

    Args:
        page_id: The page ID to release
        user_id: If provided, only releases if this user owns the checkout
    """
    conn = get_db()
    try:
        if user_id:
            conn.execute(
                "DELETE FROM page_checkouts WHERE page_id=? AND user_id=?",
                (page_id, user_id)
            )
        else:
            conn.execute(
                "DELETE FROM page_checkouts WHERE page_id=?",
                (page_id,)
            )
        conn.commit()
    finally:
        conn.close()


def get_checkout(page_id):
    """Get the current checkout for a page, or None if not checked out.

    Automatically cleans up expired checkouts.
    """
    conn = get_db()
    try:
        checkout = conn.execute(
            "SELECT pc.*, u.username FROM page_checkouts pc "
            "JOIN users u ON pc.user_id=u.id WHERE pc.page_id=?",
            (page_id,)
        ).fetchone()

        if not checkout:
            return None

        # Check if expired
        checkout_time = datetime.fromisoformat(checkout["checked_out_at"])
        timeout = timedelta(minutes=CHECKOUT_TIMEOUT_MINUTES)

        if datetime.now(timezone.utc) - checkout_time >= timeout:
            # Expired, clean up
            conn.execute("DELETE FROM page_checkouts WHERE page_id=?", (page_id,))
            conn.commit()
            return None

        return checkout
    finally:
        conn.close()


def refresh_checkout(page_id, user_id):
    """Refresh the checkout timestamp for a page.

    Returns:
        bool: True if checkout was refreshed, False if checkout doesn't exist or belongs to another user
    """
    conn = get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        cursor = conn.execute(
            "UPDATE page_checkouts SET checked_out_at=? WHERE page_id=? AND user_id=?",
            (now, page_id, user_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def list_all_checkouts():
    """List all active checkouts (admin view).

    Automatically cleans up expired checkouts.
    """
    conn = get_db()
    try:
        # Clean up expired checkouts first
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=CHECKOUT_TIMEOUT_MINUTES)).isoformat()
        conn.execute(
            "DELETE FROM page_checkouts WHERE checked_out_at < ?",
            (cutoff,)
        )
        conn.commit()

        # Get all remaining checkouts
        rows = conn.execute(
            "SELECT pc.*, u.username, p.title AS page_title, p.slug AS page_slug "
            "FROM page_checkouts pc "
            "JOIN users u ON pc.user_id=u.id "
            "JOIN pages p ON pc.page_id=p.id "
            "ORDER BY pc.checked_out_at DESC"
        ).fetchall()
        return rows
    finally:
        conn.close()


def get_user_checkouts(user_id):
    """Get all checkouts belonging to a specific user."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT pc.*, p.title AS page_title, p.slug AS page_slug "
            "FROM page_checkouts pc "
            "JOIN pages p ON pc.page_id=p.id "
            "WHERE pc.user_id=? "
            "ORDER BY pc.checked_out_at DESC",
            (user_id,)
        ).fetchall()
        return rows
    finally:
        conn.close()


def cleanup_user_checkouts(user_id):
    """Release all checkouts for a user (e.g., on logout or suspension)."""
    conn = get_db()
    try:
        conn.execute("DELETE FROM page_checkouts WHERE user_id=?", (user_id,))
        conn.commit()
    finally:
        conn.close()
