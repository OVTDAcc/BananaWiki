"""User profiles and contribution heatmap."""

from datetime import datetime, timezone

from ._connection import get_db


# ---------------------------------------------------------------------------
#  User Profiles
# ---------------------------------------------------------------------------

def get_user_profile(user_id):
    """Return the profile row for a user, or None if not set up."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM user_profiles WHERE user_id=?", (user_id,)
    ).fetchone()
    conn.close()
    return row


def upsert_user_profile(user_id, real_name=None, bio=None,
                        avatar_filename=None, page_published=None,
                        page_disabled_by_admin=None):
    """Create or update a user profile, updating only the supplied fields."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    existing = conn.execute(
        "SELECT * FROM user_profiles WHERE user_id=?", (user_id,)
    ).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO user_profiles "
            "(user_id, real_name, bio, avatar_filename, page_published, "
            " page_disabled_by_admin, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                real_name or "",
                bio or "",
                avatar_filename or "",
                1 if page_published else 0,
                1 if page_disabled_by_admin else 0,
                now,
            ),
        )
    else:
        fields = {"updated_at": now}
        if real_name is not None:
            fields["real_name"] = real_name
        if bio is not None:
            fields["bio"] = bio
        if avatar_filename is not None:
            fields["avatar_filename"] = avatar_filename
        if page_published is not None:
            fields["page_published"] = 1 if page_published else 0
        if page_disabled_by_admin is not None:
            fields["page_disabled_by_admin"] = 1 if page_disabled_by_admin else 0
        set_clause = ", ".join(f"{k}=?" for k in fields)
        vals = list(fields.values()) + [user_id]
        conn.execute(
            f"UPDATE user_profiles SET {set_clause} WHERE user_id=?", vals  # noqa: S608
        )
    conn.commit()
    conn.close()


def delete_user_profile(user_id):
    """Delete a user profile (retains contribution history)."""
    conn = get_db()
    conn.execute("DELETE FROM user_profiles WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def list_published_profiles():
    """Return users with a published profile, ordered by username."""
    conn = get_db()
    rows = conn.execute(
        "SELECT u.id, u.username, up.real_name, up.bio, up.avatar_filename "
        "FROM users u "
        "JOIN user_profiles up ON u.id = up.user_id "
        "WHERE up.page_published=1 AND up.page_disabled_by_admin=0 "
        "AND u.suspended=0 "
        "ORDER BY u.username COLLATE NOCASE"
    ).fetchall()
    conn.close()
    return rows


def list_all_users_with_profiles():
    """Return all users with their profile data (for admin / People page)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT u.id, u.username, u.role, u.suspended, "
        "COALESCE(up.real_name, '') AS real_name, "
        "COALESCE(up.bio, '') AS bio, "
        "COALESCE(up.avatar_filename, '') AS avatar_filename, "
        "COALESCE(up.page_published, 0) AS page_published, "
        "COALESCE(up.page_disabled_by_admin, 0) AS page_disabled_by_admin "
        "FROM users u "
        "LEFT JOIN user_profiles up ON u.id = up.user_id "
        "ORDER BY u.username COLLATE NOCASE"
    ).fetchall()
    conn.close()
    return rows


def get_contributions_by_day(user_id):
    """Return a tuple (year, {date_str: count}) of daily wiki edits for a user (current calendar year)."""
    conn = get_db()
    year = datetime.now(timezone.utc).year
    start = f"{year}-01-01"
    end_exclusive = f"{year + 1}-01-01"
    rows = conn.execute(
        "SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS cnt "
        "FROM page_history "
        "WHERE edited_by=? AND created_at >= ? AND created_at < ? "
        "GROUP BY day",
        (user_id, start, end_exclusive),
    ).fetchall()
    conn.close()
    return year, {r["day"]: r["cnt"] for r in rows}

