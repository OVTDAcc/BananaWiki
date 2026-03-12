"""Page reservation management."""

from datetime import datetime, timedelta, timezone

import config
from ._connection import get_db
from ._settings import get_site_settings


# ---------------------------------------------------------------------------
#  Reservation helpers
# ---------------------------------------------------------------------------
def reservations_enabled():
    """Return True when the page reservation system is enabled site-wide."""
    settings = get_site_settings()
    return bool(settings and settings["page_reservations_enabled"])


def _get_reservation_hours(settings, key, default, minimum):
    """Return a validated reservation hour setting with config fallback.

    Args:
        settings: Site settings row or mapping to read from.
        key: Setting name containing the reservation hour value.
        default: Fallback hour value from config.
        minimum: Minimum allowed hour value.

    Returns:
        int: A validated hour value suitable for timedelta(hours=...).
    """
    if not settings:
        return default
    try:
        return max(minimum, int(settings[key]))
    except (KeyError, TypeError, ValueError):
        return default


def reserve_page(page_id, user_id):
    """
    Reserve a page for the given user.

    Returns:
        dict: Reservation data with keys: id, page_id, user_id, reserved_at, expires_at, released_at
        None: If the page is already reserved or user is in cooldown

    Raises:
        ValueError: If page is already reserved or user is in cooldown
    """
    if not reservations_enabled():
        raise ValueError("Page reservations are currently disabled")

    settings = get_site_settings()
    conn = get_db()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=_get_reservation_hours(
        settings, "page_reservation_duration_hours", config.PAGE_RESERVATION_DURATION_HOURS, 1
    ))

    try:
        # Use BEGIN IMMEDIATE to serialise concurrent reservation attempts
        conn.execute("BEGIN IMMEDIATE")

        # Check if page is already reserved (and not expired or released)
        existing = conn.execute(
            "SELECT pr.*, u.role FROM page_reservations pr "
            "LEFT JOIN users u ON pr.user_id = u.id "
            "WHERE pr.page_id=? AND pr.expires_at > ? AND pr.released_at IS NULL",
            (page_id, now.isoformat()),
        ).fetchone()

        if existing:
            # Auto-release if the reserving user was deleted or lost edit permissions
            ex_role = existing["role"] if "role" in existing.keys() else None
            if ex_role is None or ex_role not in ("editor", "admin", "protected_admin"):
                conn.execute(
                    "UPDATE page_reservations SET released_at=? WHERE id=?",
                    (now.isoformat(), existing["id"]),
                )
            else:
                conn.execute("ROLLBACK")
                conn.close()
                raise ValueError("Page is already reserved by another user")

        # Check if user is in cooldown for this page
        cooldown = conn.execute(
            "SELECT * FROM user_page_cooldowns WHERE page_id=? AND user_id=? AND cooldown_until > ?",
            (page_id, user_id, now.isoformat()),
        ).fetchone()

        if cooldown:
            conn.execute("ROLLBACK")
            conn.close()
            raise ValueError("User is in cooldown period for this page")

        # Delete any old released or expired reservations for this page
        conn.execute(
            "DELETE FROM page_reservations WHERE page_id=? AND (released_at IS NOT NULL OR expires_at <= ?)",
            (page_id, now.isoformat())
        )

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
        return dict(reservation) if reservation else None
    except Exception as e:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
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
    if not reservations_enabled():
        return False

    settings = get_site_settings()
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
    cooldown_until = now + timedelta(hours=_get_reservation_hours(
        settings, "page_reservation_cooldown_hours", config.PAGE_RESERVATION_COOLDOWN_HOURS, 0
    ))
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
    if not reservations_enabled():
        result = {
            'is_reserved': False,
            'reserved_by': None,
            'reserved_by_username': None,
            'reserved_at': None,
            'expires_at': None,
            'time_remaining': None,
        }
        if user_id:
            result.update({
                'user_in_cooldown': False,
                'cooldown_until': None,
                'cooldown_remaining': None,
            })
        return result

    conn = get_db()
    now = datetime.now(timezone.utc)

    # Check active reservation
    reservation = conn.execute(
        "SELECT pr.*, u.username, u.role FROM page_reservations pr "
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
        # Auto-release if the reserving user was deleted or lost edit permissions
        user_role = reservation["role"] if "role" in reservation.keys() else None
        if user_role is None or user_role not in ("editor", "admin", "protected_admin"):
            conn.execute(
                "UPDATE page_reservations SET released_at=? WHERE id=?",
                (now.isoformat(), reservation["id"]),
            )
            conn.commit()
            reservation = None

    if reservation:
        expires = datetime.fromisoformat(reservation["expires_at"]).replace(tzinfo=timezone.utc)
        result.update({
            'is_reserved': True,
            'reserved_by': reservation["user_id"],
            'reserved_by_username': reservation["username"] if "username" in reservation.keys() else None,
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
    if not reservations_enabled():
        return (False, "Page reservations are currently disabled")

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

    Admins and protected admins can always edit, even if the page is
    reserved by someone else (consistent with the template-level bypass).

    Returns:
        tuple: (can_edit: bool, reason: str)
        - (True, "") if user can edit
        - (False, reason) if user cannot edit
    """
    if not reservations_enabled():
        return (True, "")

    status = get_page_reservation_status(page_id, user_id)

    if not status['is_reserved']:
        # No reservation, anyone can edit
        return (True, "")

    if status['reserved_by'] == user_id:
        # User holds the reservation
        return (True, "")

    # Someone else holds the reservation — check if user is admin
    conn = get_db()
    user = conn.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    if user and user["role"] in ("admin", "protected_admin"):
        return (True, "")

    return (False, f"Page is reserved by {status['reserved_by_username']}")


def get_user_reservations(user_id):
    """
    Get all active reservations for a user.

    Returns:
        list: List of reservation dicts with page info
    """
    if not reservations_enabled():
        return []

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


def get_all_active_reservations():
    """
    Get all active (non-expired, non-released) reservations across all pages.
    Also cleans up expired reservations and cooldowns before returning.

    Returns:
        list: List of reservation dicts including page title/slug and username.
    """
    if not reservations_enabled():
        return []

    cleanup_expired_reservations()

    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()

    rows = conn.execute(
        "SELECT pr.*, p.title, p.slug, u.username "
        "FROM page_reservations pr "
        "JOIN pages p ON pr.page_id = p.id "
        "JOIN users u ON pr.user_id = u.id "
        "WHERE pr.expires_at > ? AND pr.released_at IS NULL "
        "ORDER BY pr.reserved_at DESC",
        (now,),
    ).fetchall()

    conn.close()
    return rows


def _build_sidebar_page_status(
    is_reserved=False,
    reserved_by_current_user=False,
    reservation_label=None,
    user_in_cooldown=False,
    cooldown_label=None,
):
    """Build a consistent sidebar reservation/cooldown payload."""
    return {
        "is_reserved": is_reserved,
        "reserved_by_current_user": reserved_by_current_user,
        "reservation_label": reservation_label,
        "user_in_cooldown": user_in_cooldown,
        "cooldown_label": cooldown_label,
    }


def get_active_page_reservations_map(user_id=None, page_ids=None):
    """
    Return active reservation/cooldown metadata keyed by page ID for sidebar/search UI.

    Args:
        user_id: Current viewer ID, used to mark reservations owned by them.
        page_ids: Optional iterable of page IDs to limit the query scope.

    Returns:
        dict: ``{page_id: {"is_reserved": bool, "reserved_by_current_user": bool,
               "reservation_label": str | None, "user_in_cooldown": bool,
               "cooldown_label": str | None}}`` for viewer-visible sidebar status.
    """
    if not reservations_enabled():
        return {}

    has_page_filter = page_ids is not None
    if has_page_filter:
        normalized_page_ids = []
        for page_id in page_ids:
            try:
                normalized_page_ids.append(int(page_id))
            except (TypeError, ValueError):
                continue
        page_ids = normalized_page_ids
    else:
        page_ids = []
    if has_page_filter and not page_ids:
        return {}

    cleanup_expired_reservations()

    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    query = (
        "SELECT pr.page_id, pr.user_id "
        "FROM page_reservations pr "
        "JOIN users u ON pr.user_id = u.id "
        "WHERE pr.expires_at > ? AND pr.released_at IS NULL "
        "AND u.role IN ('editor', 'admin', 'protected_admin')"
    )
    params = [now]
    if has_page_filter:
        placeholders = ",".join("?" for _ in page_ids)
        query += f" AND pr.page_id IN ({placeholders})"
        params.extend(page_ids)
    rows = conn.execute(query, params).fetchall()

    reservations = {}
    for row in rows:
        reserved_by_current_user = bool(user_id and row["user_id"] == user_id)
        reservations[row["page_id"]] = _build_sidebar_page_status(
            is_reserved=True,
            reserved_by_current_user=reserved_by_current_user,
            reservation_label=(
                "Reserved by you" if reserved_by_current_user else "Reserved by another user"
            ),
        )

    if user_id:
        cooldown_query = (
            "SELECT page_id FROM user_page_cooldowns "
            "WHERE user_id=? AND cooldown_until > ?"
        )
        cooldown_params = [user_id, now]
        if has_page_filter:
            placeholders = ",".join("?" for _ in page_ids)
            cooldown_query += f" AND page_id IN ({placeholders})"
            cooldown_params.extend(page_ids)
        cooldown_rows = conn.execute(cooldown_query, cooldown_params).fetchall()

        for row in cooldown_rows:
            reservations.setdefault(row["page_id"], _build_sidebar_page_status())
            reservations[row["page_id"]]["user_in_cooldown"] = True
            reservations[row["page_id"]]["cooldown_label"] = "Cooldown active for you"

    conn.close()
    return reservations


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
