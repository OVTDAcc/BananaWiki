"""Role history, custom tags, and contribution management."""

from ._connection import get_db


# ---------------------------------------------------------------------------
#  Role History
# ---------------------------------------------------------------------------

def record_role_change(user_id, old_role, new_role, changed_by=None):
    """Record a role change in the role_history table."""
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO role_history (user_id, old_role, new_role, changed_by) "
            "VALUES (?, ?, ?, ?)",
            (user_id, old_role, new_role, changed_by),
        )
        conn.commit()
    finally:
        conn.close()


def get_role_history(user_id):
    """Return the role change history for a user, newest first."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT rh.*, u.username AS changed_by_username "
            "FROM role_history rh "
            "LEFT JOIN users u ON rh.changed_by = u.id "
            "WHERE rh.user_id=? ORDER BY rh.changed_at DESC",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()
    return rows


# ---------------------------------------------------------------------------
#  User Custom Tags
# ---------------------------------------------------------------------------

def get_user_custom_tags(user_id):
    """Return custom tags for a user, ordered by sort_order."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM user_custom_tags WHERE user_id=? ORDER BY sort_order ASC, id ASC",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()
    return rows


def add_user_custom_tag(user_id, label, color="#9b59b6"):
    """Add a new custom tag for a user. Returns the new tag id."""
    conn = get_db()
    try:
        # Get the next sort_order value
        row = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order "
            "FROM user_custom_tags WHERE user_id=?",
            (user_id,),
        ).fetchone()
        next_order = row["next_order"]
        cur = conn.execute(
            "INSERT INTO user_custom_tags (user_id, label, color, sort_order) "
            "VALUES (?, ?, ?, ?)",
            (user_id, label, color, next_order),
        )
        tag_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return tag_id


def update_user_custom_tag(tag_id, label=None, color=None):
    """Update label and/or color of a custom tag."""
    conn = get_db()
    try:
        fields = {}
        if label is not None:
            fields["label"] = label
        if color is not None:
            fields["color"] = color
        if fields:
            set_clause = ", ".join(f"{k}=?" for k in fields)
            vals = list(fields.values()) + [tag_id]
            conn.execute(
                f"UPDATE user_custom_tags SET {set_clause} WHERE id=?", vals  # noqa: S608
            )
            conn.commit()
    finally:
        conn.close()


def delete_user_custom_tag(tag_id):
    """Delete a custom tag by its id."""
    conn = get_db()
    try:
        conn.execute("DELETE FROM user_custom_tags WHERE id=?", (tag_id,))
        conn.commit()
    finally:
        conn.close()


def reorder_user_custom_tags(user_id, tag_ids):
    """Reorder custom tags for a user given a list of tag IDs in desired order."""
    conn = get_db()
    try:
        for idx, tid in enumerate(tag_ids):
            conn.execute(
                "UPDATE user_custom_tags SET sort_order=? WHERE id=? AND user_id=?",
                (idx, tid, user_id),
            )
        conn.commit()
    finally:
        conn.close()


def get_user_custom_tag(tag_id):
    """Return a single custom tag by id, or None."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM user_custom_tags WHERE id=?", (tag_id,)
        ).fetchone()
    finally:
        conn.close()
    return row


# ---------------------------------------------------------------------------
#  Admin Attribution Management
# ---------------------------------------------------------------------------

def deattribute_contribution(entry_id):
    """Remove attribution from a single page history entry (set edited_by to NULL)."""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE page_history SET edited_by=NULL WHERE id=?",
            (entry_id,),
        )
        conn.commit()
    finally:
        conn.close()


def deattribute_all_user_contributions(user_id):
    """Remove attribution from ALL page history entries by a user.

    Returns the number of entries affected.
    """
    conn = get_db()
    try:
        cur = conn.execute(
            "UPDATE page_history SET edited_by=NULL WHERE edited_by=?",
            (user_id,),
        )
        count = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return count


def delete_role_history_entry(entry_id):
    """Delete a single role history entry by id."""
    conn = get_db()
    try:
        conn.execute("DELETE FROM role_history WHERE id=?", (entry_id,))
        conn.commit()
    finally:
        conn.close()


def delete_all_role_history(user_id):
    """Delete all role history entries for a user.

    Returns the number of entries deleted.
    """
    conn = get_db()
    try:
        cur = conn.execute(
            "DELETE FROM role_history WHERE user_id=?", (user_id,),
        )
        count = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return count


def get_role_history_entry(entry_id):
    """Return a single role history entry by id, or None."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM role_history WHERE id=?", (entry_id,)
        ).fetchone()
    finally:
        conn.close()
    return row


def mass_reattribute_contributions(from_user_id, to_user_id):
    """Transfer ALL page history entries from one user to another across all pages.

    Returns the number of entries updated.
    """
    conn = get_db()
    try:
        cur = conn.execute(
            "UPDATE page_history SET edited_by=? WHERE edited_by=?",
            (to_user_id, from_user_id),
        )
        count = cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return count

