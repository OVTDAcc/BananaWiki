"""Custom permission management for editors and users."""

from ._connection import get_db


def get_user_permissions(user_id):
    """Get all custom permissions for a user.

    Returns:
        dict: {
            'enabled_permissions': set of permission keys,
            'category_access': {
                'restricted': bool,
                'allowed_category_ids': list of category IDs (for read access)
            },
            'category_write_access': {
                'restricted': bool,
                'allowed_category_ids': list of category IDs (for write access)
            }
        }
    """
    conn = get_db()
    cur = conn.cursor()

    # Get enabled permissions
    enabled = set()
    rows = cur.execute(
        "SELECT permission_key FROM user_permissions WHERE user_id = ?",
        (user_id,)
    ).fetchall()
    for row in rows:
        enabled.add(row[0])

    # Get category read access
    cat_access = cur.execute(
        "SELECT restricted FROM user_category_access WHERE user_id = ? AND access_type = 'read'",
        (user_id,)
    ).fetchone()

    if cat_access:
        restricted_read = bool(cat_access[0])
        if restricted_read:
            allowed_read = [
                r[0] for r in cur.execute(
                    "SELECT category_id FROM user_allowed_categories WHERE user_id = ? AND access_type = 'read'",
                    (user_id,)
                ).fetchall()
            ]
        else:
            allowed_read = []
    else:
        restricted_read = False
        allowed_read = []

    # Get category write access
    cat_write = cur.execute(
        "SELECT restricted FROM user_category_access WHERE user_id = ? AND access_type = 'write'",
        (user_id,)
    ).fetchone()

    if cat_write:
        restricted_write = bool(cat_write[0])
        if restricted_write:
            allowed_write = [
                r[0] for r in cur.execute(
                    "SELECT category_id FROM user_allowed_categories WHERE user_id = ? AND access_type = 'write'",
                    (user_id,)
                ).fetchall()
            ]
        else:
            allowed_write = []
    else:
        restricted_write = False
        allowed_write = []

    conn.close()
    return {
        'enabled_permissions': enabled,
        'category_access': {
            'restricted': restricted_read,
            'allowed_category_ids': allowed_read,
        },
        'category_write_access': {
            'restricted': restricted_write,
            'allowed_category_ids': allowed_write,
        }
    }


def set_user_permissions(user_id, permission_keys,
                        read_restricted=False, read_category_ids=None,
                        write_restricted=False, write_category_ids=None):
    """Set custom permissions for a user.

    Args:
        user_id: User ID
        permission_keys: Set or list of permission keys to enable
        read_restricted: Whether to restrict read access to specific categories
        read_category_ids: List of category IDs for read access (if restricted)
        write_restricted: Whether to restrict write access to specific categories
        write_category_ids: List of category IDs for write access (if restricted)
    """
    conn = get_db()
    cur = conn.cursor()

    user_row = cur.execute(
        "SELECT role FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()
    if not user_row:
        conn.close()
        raise ValueError("User not found")
    role = user_row["role"]

    from helpers._permissions import sanitize_permission_keys

    permission_keys = sanitize_permission_keys(role, permission_keys)
    read_category_ids = list(dict.fromkeys(read_category_ids or []))
    write_category_ids = list(dict.fromkeys(write_category_ids or []))

    if role != "editor":
        write_restricted = False
        write_category_ids = []
    elif not write_restricted:
        read_restricted = False
        read_category_ids = []
    elif read_restricted:
        read_category_ids = list(dict.fromkeys(read_category_ids + write_category_ids))

    # Clear existing permissions
    cur.execute("DELETE FROM user_permissions WHERE user_id = ?", (user_id,))
    cur.execute("DELETE FROM user_category_access WHERE user_id = ?", (user_id,))
    cur.execute("DELETE FROM user_allowed_categories WHERE user_id = ?", (user_id,))

    # Insert new permissions
    for key in permission_keys:
        cur.execute(
            "INSERT INTO user_permissions (user_id, permission_key) VALUES (?, ?)",
            (user_id, key)
        )

    # Set read category access
    cur.execute(
        "INSERT INTO user_category_access (user_id, access_type, restricted) VALUES (?, 'read', ?)",
        (user_id, 1 if read_restricted else 0)
    )
    if read_restricted and read_category_ids:
        for cat_id in read_category_ids:
            cur.execute(
                "INSERT INTO user_allowed_categories (user_id, category_id, access_type) VALUES (?, ?, 'read')",
                (user_id, cat_id)
            )

    # Set write category access
    cur.execute(
        "INSERT INTO user_category_access (user_id, access_type, restricted) VALUES (?, 'write', ?)",
        (user_id, 1 if write_restricted else 0)
    )
    if write_restricted and write_category_ids:
        for cat_id in write_category_ids:
            cur.execute(
                "INSERT INTO user_allowed_categories (user_id, category_id, access_type) VALUES (?, ?, 'write')",
                (user_id, cat_id)
            )

    conn.commit()
    conn.close()


def has_permission(user, permission_key):
    """Check if a user has a specific permission.

    Args:
        user: User dict with at least 'id' and 'role' keys
        permission_key: Permission key to check

    Returns:
        bool: True if user has the permission
    """
    if not user:
        return False

    # Admins and protected_admins have all permissions
    # Use subscript access for sqlite3.Row compatibility (no .get() method)
    role = user["role"] if "role" in user.keys() else None
    if role in ("admin", "protected_admin"):
        return True

    from helpers._permissions import is_permission_assignable_to_role

    if not is_permission_assignable_to_role(permission_key, role):
        return False

    # Regular users and editors use custom permissions
    permissions = get_user_permissions(user["id"])
    return permission_key in permissions['enabled_permissions']


def has_category_read_access(user, category_id):
    """Check if user has read access to a specific category.

    Args:
        user: User dict
        category_id: Category ID to check (can be None for uncategorized)

    Returns:
        bool: True if user has access
    """
    if not user:
        return False

    # Admins always have access (handle both dict and sqlite3.Row)
    role = user["role"] if "role" in user.keys() else None
    if role in ("admin", "protected_admin"):
        return True

    user_id = user["id"] if "id" in user.keys() else None
    if not user_id:
        return False

    permissions = get_user_permissions(user_id)
    cat_access = permissions['category_access']

    # If not restricted, user has access to all
    if not cat_access['restricted']:
        return True

    # If restricted, check if category is in allowed list
    # Note: uncategorized pages (None) are not accessible when restricted
    if category_id is None:
        return False

    if int(category_id) in cat_access['allowed_category_ids']:
        return True

    return has_category_write_access(user, category_id)


def has_category_write_access(user, category_id):
    """Check if user has write access to a specific category.

    Args:
        user: User dict
        category_id: Category ID to check (can be None for uncategorized)

    Returns:
        bool: True if user has write access
    """
    if not user:
        return False

    # Admins always have access (handle both dict and sqlite3.Row)
    role = user["role"] if "role" in user.keys() else None
    if role in ("admin", "protected_admin"):
        return True
    if role != "editor":
        return False

    user_id = user["id"] if "id" in user.keys() else None
    if not user_id:
        return False

    permissions = get_user_permissions(user_id)
    cat_access = permissions['category_write_access']

    # Check if user has any custom permissions set at all
    # If not, fall back to old editor_category_access system for backward compatibility
    conn = get_db()
    cur = conn.cursor()
    has_custom_perms = cur.execute(
        "SELECT 1 FROM user_category_access WHERE user_id = ? AND access_type = 'write'",
        (user_id,)
    ).fetchone()
    conn.close()

    if not has_custom_perms and role == "editor":
        # Fall back to old system
        from ._users import get_editor_access
        old_access = get_editor_access(user_id)
        if not old_access["restricted"]:
            return True
        if category_id is None:
            return False
        return int(category_id) in old_access["allowed_category_ids"]

    # Use new permission system
    # If not restricted, user has write access to all
    if not cat_access['restricted']:
        return True

    # If restricted, check if category is in allowed list
    # Note: uncategorized pages (None) are not accessible when restricted
    if category_id is None:
        return False

    return int(category_id) in cat_access['allowed_category_ids']


def clear_user_permissions(user_id):
    """Clear all custom permissions for a user.

    Args:
        user_id: User ID
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM user_permissions WHERE user_id = ?", (user_id,))
    cur.execute("DELETE FROM user_category_access WHERE user_id = ?", (user_id,))
    cur.execute("DELETE FROM user_allowed_categories WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
