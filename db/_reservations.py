"""Page reservation management."""

from datetime import datetime, timedelta, timezone

import config
from ._connection import get_db


# ---------------------------------------------------------------------------
#  Reservation helpers
# ---------------------------------------------------------------------------
def reserve_page(page_id, user_id):
    """
    Reserve a page for the given user.

    Returns:
        dict: Reservation data with keys: id, page_id, user_id, reserved_at, expires_at, released_at
        None: If the page is already reserved or user is in cooldown

    Raises:
        ValueError: If page is already reserved or user is in cooldown
    """
    conn = get_db()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=config.PAGE_RESERVATION_DURATION_HOURS)

    # Check if page is already reserved (and not expired)
    existing = conn.execute(
        "SELECT * FROM page_reservations WHERE page_id=? AND expires_at > ?",
        (page_id, now.isoformat()),
    ).fetchone()

    if existing:
        conn.close()
        raise ValueError("Page is already reserved by another user")

    # Check if user is in cooldown for this page
    cooldown = conn.execute(
        "SELECT * FROM user_page_cooldowns WHERE page_id=? AND user_id=? AND cooldown_until > ?",
        (page_id, user_id, now.isoformat()),
    ).fetchone()

    if cooldown:
        conn.close()
        raise ValueError("User is in cooldown period for this page")

    try:
        # Create reservation
        conn.execute(
            "INSERT INTO page_reservations (page_id, user_id, reserved_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (page_id, user_id, now.isoformat(), expires.isoformat()),
        )
        conn.commit()

        # Fetch the created reservation
        reservation = conn.execute(
            "SELECT * FROM page_reservations WHERE page_id=? AND user_id=?",
            (page_id, user_id),
        ).fetchone()
        conn.close()
        return reservation
    except Exception as e:
        conn.close()
        raise e


def release_page_reservation(page_id, user_id=None):
    """
    Release a page reservation and start cooldown for the user.

    Args:
        page_id: ID of the page to release
        user_id: If provided, only release if this user holds the reservation.
                If None, release regardless of who holds it.

    Returns:
        bool: True if reservation was released, False if no active reservation found
    """
    conn = get_db()
    now = datetime.now(timezone.utc)

    # Find active reservation
    query = "SELECT * FROM page_reservations WHERE page_id=? AND expires_at > ? AND released_at IS NULL"
    params = [page_id, now.isoformat()]

    if user_id:
        query += " AND user_id=?"
        params.append(user_id)

    reservation = conn.execute(query, params).fetchone()

    if not reservation:
        conn.close()
        return False

    # Mark as released
    conn.execute(
        "UPDATE page_reservations SET released_at=? WHERE id=?",
        (now.isoformat(), reservation["id"]),
    )

    # Create cooldown entry
    cooldown_until = now + timedelta(hours=config.PAGE_RESERVATION_COOLDOWN_HOURS)
    conn.execute(
        "INSERT OR REPLACE INTO user_page_cooldowns (page_id, user_id, cooldown_until) "
        "VALUES (?, ?, ?)",
        (page_id, reservation["user_id"], cooldown_until.isoformat()),
    )

    conn.commit()
    conn.close()
    return True


def get_page_reservation_status(page_id, user_id=None):
    """
    Get the reservation status for a page.

    Returns:
        dict: {
            'is_reserved': bool,
            'reserved_by': user_id or None,
            'reserved_by_username': username or None,
            'reserved_at': ISO datetime string or None,
            'expires_at': ISO datetime string or None,
            'time_remaining': timedelta or None,
            'user_in_cooldown': bool (only if user_id provided),
            'cooldown_until': ISO datetime string or None (only if user_id provided),
            'cooldown_remaining': timedelta or None (only if user_id provided),
        }
    """
    conn = get_db()
    now = datetime.now(timezone.utc)

    # Check active reservation
    reservation = conn.execute(
        "SELECT pr.*, u.username FROM page_reservations pr "
        "LEFT JOIN users u ON pr.user_id = u.id "
        "WHERE pr.page_id=? AND pr.expires_at > ? AND pr.released_at IS NULL",
        (page_id, now.isoformat()),
    ).fetchone()

    result = {
        'is_reserved': False,
        'reserved_by': None,
        'reserved_by_username': None,
        'reserved_at': None,
        'expires_at': None,
        'time_remaining': None,
    }

    if reservation:
        expires = datetime.fromisoformat(reservation["expires_at"]).replace(tzinfo=timezone.utc)
        result.update({
            'is_reserved': True,
            'reserved_by': reservation["user_id"],
            'reserved_by_username': reservation.get("username"),
            'reserved_at': reservation["reserved_at"],
            'expires_at': reservation["expires_at"],
            'time_remaining': expires - now,
        })

    # Check user cooldown if user_id provided
    if user_id:
        cooldown = conn.execute(
            "SELECT * FROM user_page_cooldowns WHERE page_id=? AND user_id=? AND cooldown_until > ?",
            (page_id, user_id, now.isoformat()),
        ).fetchone()

        result['user_in_cooldown'] = bool(cooldown)
        result['cooldown_until'] = cooldown["cooldown_until"] if cooldown else None
        result['cooldown_remaining'] = None

        if cooldown:
            cooldown_dt = datetime.fromisoformat(cooldown["cooldown_until"]).replace(tzinfo=timezone.utc)
            result['cooldown_remaining'] = cooldown_dt - now

    conn.close()
    return result


def cleanup_expired_reservations():
    """
    Clean up expired reservations (past expires_at) and old cooldown entries.
    This is useful for keeping the database clean, but not strictly necessary
    since all queries check expiry times.

    Returns:
        dict: {'reservations_cleaned': int, 'cooldowns_cleaned': int}
    """
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()

    # Mark expired reservations as released (if not already marked)
    result = conn.execute(
        "UPDATE page_reservations SET released_at=? WHERE expires_at <= ? AND released_at IS NULL",
        (now, now),
    )
    reservations_cleaned = result.rowcount

    # Delete expired cooldowns
    result = conn.execute(
        "DELETE FROM user_page_cooldowns WHERE cooldown_until <= ?",
        (now,),
    )
    cooldowns_cleaned = result.rowcount

    conn.commit()
    conn.close()

    return {
        'reservations_cleaned': reservations_cleaned,
        'cooldowns_cleaned': cooldowns_cleaned,
    }


def can_user_reserve_page(page_id, user_id):
    """
    Check if a user can reserve a page.

    Returns:
        tuple: (can_reserve: bool, reason: str)
        - (True, "") if user can reserve
        - (False, reason) if user cannot reserve
    """
    status = get_page_reservation_status(page_id, user_id)

    if status['is_reserved']:
        if status['reserved_by'] == user_id:
            return (False, "You have already reserved this page")
        else:
            return (False, f"Page is reserved by {status['reserved_by_username']}")

    if status.get('user_in_cooldown'):
        return (False, "You are in cooldown period for this page")

    return (True, "")


def can_user_edit_page(page_id, user_id):
    """
    Check if a user can edit a page based on reservation status.

    Returns:
        tuple: (can_edit: bool, reason: str)
        - (True, "") if user can edit
        - (False, reason) if user cannot edit
    """
    status = get_page_reservation_status(page_id, user_id)

    if not status['is_reserved']:
        # No reservation, anyone can edit
        return (True, "")

    if status['reserved_by'] == user_id:
        # User holds the reservation
        return (True, "")

    # Someone else holds the reservation
    return (False, f"Page is reserved by {status['reserved_by_username']}")


def get_user_reservations(user_id):
    """
    Get all active reservations for a user.

    Returns:
        list: List of reservation dicts with page info
    """
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()

    rows = conn.execute(
        "SELECT pr.*, p.title, p.slug FROM page_reservations pr "
        "JOIN pages p ON pr.page_id = p.id "
        "WHERE pr.user_id=? AND pr.expires_at > ? AND pr.released_at IS NULL "
        "ORDER BY pr.reserved_at DESC",
        (user_id, now),
    ).fetchall()

    conn.close()
    return rows


def force_release_reservation(page_id):
    """
    Force release a reservation (admin action).
    Does NOT create a cooldown entry.

    Returns:
        bool: True if reservation was released, False if no active reservation found
    """
    conn = get_db()
    now = datetime.now(timezone.utc)

    # Find active reservation
    reservation = conn.execute(
        "SELECT * FROM page_reservations WHERE page_id=? AND expires_at > ? AND released_at IS NULL",
        (page_id, now.isoformat()),
    ).fetchone()

    if not reservation:
        conn.close()
        return False

    # Mark as released without creating cooldown
    conn.execute(
        "UPDATE page_reservations SET released_at=? WHERE id=?",
        (now.isoformat(), reservation["id"]),
    )

    conn.commit()
    conn.close()
    return True
