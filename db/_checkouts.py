"""Page checkout / edit locking helpers."""

from datetime import datetime, timedelta, timezone

from ._connection import get_db

CHECKOUT_TIMEOUT_SECONDS = 15 * 60


def _now():
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


def _parse_ts(value):
    """Parse an ISO-ish timestamp string into a datetime, or None if invalid."""
    if not value:
        return None
    try:
        # Normalise bare "Z" suffix for fromisoformat
        if isinstance(value, str) and value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _is_expired(row, now=None):
    """Return True if a checkout row is past the timeout window."""
    now = now or _now()
    ts = _parse_ts(row["last_seen"])
    if not ts:
        return True
    return ts <= now - timedelta(seconds=CHECKOUT_TIMEOUT_SECONDS)


def _fetch_checkout(conn, page_id):
    """Internal helper: fetch checkout row with user + page details."""
    return conn.execute(
        """
        SELECT pc.page_id, pc.user_id, pc.acquired_at, pc.last_seen,
               p.title AS page_title, p.slug AS page_slug,
               u.username
        FROM page_checkouts pc
        JOIN pages p ON pc.page_id = p.id
        LEFT JOIN users u ON pc.user_id = u.id
        WHERE pc.page_id=?
        """,
        (page_id,),
    ).fetchone()


def cleanup_expired_checkouts(now=None, conn=None):
    """Remove any expired checkouts; return the number removed."""
    close_conn = False
    if conn is None:
        conn = get_db()
        close_conn = True
    now = now or _now()
    cutoff = now - timedelta(seconds=CHECKOUT_TIMEOUT_SECONDS)
    rows = conn.execute("SELECT page_id, last_seen FROM page_checkouts").fetchall()
    expired_ids = []
    for row in rows:
        ts = _parse_ts(row["last_seen"])
        if not ts or ts <= cutoff:
            expired_ids.append(row["page_id"])
    if expired_ids:
        conn.executemany("DELETE FROM page_checkouts WHERE page_id=?", [(pid,) for pid in expired_ids])
        conn.commit()
    if close_conn:
        conn.close()
    return len(expired_ids)


def get_checkout(page_id):
    """Return the active checkout for ``page_id``, or ``None`` if none exists."""
    conn = get_db()
    try:
        cleanup_expired_checkouts(conn=conn)
        return _fetch_checkout(conn, page_id)
    finally:
        conn.close()


def acquire_checkout(page_id, user_id, now=None):
    """Acquire a checkout for ``page_id`` if available.

    Returns a tuple ``(checkout_row, acquired_bool)``. If another user holds an
    active checkout, ``acquired_bool`` is False and the current holder is
    returned.
    """
    conn = get_db()
    try:
        now_dt = now or _now()
        now_str = now_dt.isoformat()
        cleanup_expired_checkouts(now=now_dt, conn=conn)
        existing = conn.execute(
            "SELECT page_id, user_id, acquired_at, last_seen FROM page_checkouts WHERE page_id=?",
            (page_id,),
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO page_checkouts (page_id, user_id, acquired_at, last_seen) "
                "VALUES (?, ?, ?, ?)",
                (page_id, user_id, now_str, now_str),
            )
            conn.commit()
            return _fetch_checkout(conn, page_id), True
        if existing["user_id"] == user_id:
            conn.execute(
                "UPDATE page_checkouts SET last_seen=? WHERE page_id=?",
                (now_str, page_id),
            )
            conn.commit()
            return _fetch_checkout(conn, page_id), True
        if _is_expired(existing, now=now_dt):
            conn.execute(
                "UPDATE page_checkouts SET user_id=?, acquired_at=?, last_seen=? WHERE page_id=?",
                (user_id, now_str, now_str, page_id),
            )
            conn.commit()
            return _fetch_checkout(conn, page_id), True
        return _fetch_checkout(conn, page_id), False
    finally:
        conn.close()


def refresh_checkout(page_id, user_id, now=None):
    """Refresh ``last_seen`` for the current holder.

    Returns ``(checkout_row, refreshed_bool)``. If another user holds the
    checkout, ``refreshed_bool`` is False and their row is returned. If the
    checkout expired, it is removed and ``(None, False)`` is returned.
    """
    conn = get_db()
    try:
        now_dt = now or _now()
        now_str = now_dt.isoformat()
        existing = conn.execute(
            "SELECT page_id, user_id, acquired_at, last_seen FROM page_checkouts WHERE page_id=?",
            (page_id,),
        ).fetchone()
        if not existing:
            return None, False
        if _is_expired(existing, now=now_dt):
            conn.execute("DELETE FROM page_checkouts WHERE page_id=?", (page_id,))
            conn.commit()
            return None, False
        if existing["user_id"] != user_id:
            return _fetch_checkout(conn, page_id), False
        conn.execute(
            "UPDATE page_checkouts SET last_seen=? WHERE page_id=?",
            (now_str, page_id),
        )
        conn.commit()
        return _fetch_checkout(conn, page_id), True
    finally:
        conn.close()


def release_checkout(page_id, user_id=None, force=False):
    """Release the checkout for ``page_id``.

    If ``force`` is False, the checkout is removed only when held by
    ``user_id``. Returns True if a row was deleted.
    """
    conn = get_db()
    try:
        params = [page_id]
        sql = "DELETE FROM page_checkouts WHERE page_id=?"
        if not force and user_id is not None:
            sql += " AND user_id=?"
            params.append(user_id)
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_active_checkouts():
    """Return all active checkouts with page + user details."""
    conn = get_db()
    try:
        cleanup_expired_checkouts(conn=conn)
        rows = conn.execute(
            """
            SELECT pc.page_id, pc.user_id, pc.acquired_at, pc.last_seen,
                   p.title AS page_title, p.slug AS page_slug,
                   u.username
            FROM page_checkouts pc
            JOIN pages p ON pc.page_id = p.id
            LEFT JOIN users u ON pc.user_id = u.id
            ORDER BY pc.last_seen DESC
            """
        ).fetchall()
        return rows
    finally:
        conn.close()
