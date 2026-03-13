"""Site data export and import."""

from datetime import datetime, timezone
import re

from ._connection import get_db


# ---------------------------------------------------------------------------
#  Site migration – export / import
# ---------------------------------------------------------------------------
_MIGRATION_VERSION = 1
_VALID_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Tables exported in dependency order (parents before children).
_EXPORT_TABLES = [
    "users",
    "invite_codes",
    "site_settings",
    "categories",
    "pages",
    "page_history",
    "drafts",
    "login_attempts",
    "announcements",
    "username_history",
    "editor_category_access",
    "editor_allowed_categories",
    "page_attachments",
    "user_profiles",
    "chats",
    "chat_messages",
    "chat_attachments",
    "group_chats",
    "group_members",
    "group_messages",
    "group_attachments",
    "role_history",
    "user_custom_tags",
    "user_permissions",
    "user_category_access",
    "user_allowed_categories",
    "badge_types",
    "user_badges",
    "badge_notifications",
    "page_reservations",
    "user_page_cooldowns",
]


def _get_migration_tables(conn):
    """Return all user tables in a stable migration order."""
    existing_tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        if _VALID_TABLE_NAME_RE.fullmatch(row["name"])
    }
    ordered_tables = [table for table in _EXPORT_TABLES if table in existing_tables]
    extra_tables = sorted(existing_tables - set(ordered_tables))
    return ordered_tables + extra_tables


def export_site_data():
    """Return a dict containing all site data suitable for JSON serialisation.

    The dict has the shape::

        {
            "_meta": {"version": 1, "exported_at": "<iso8601>"},
            "users": [...],
            "invite_codes": [...],
            ...
        }
    """
    conn = get_db()
    data = {
        "_meta": {
            "version": _MIGRATION_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }
    }
    for table in _get_migration_tables(conn):
        # Safe: _get_migration_tables() filters sqlite_master names through
        # _VALID_TABLE_NAME_RE before returning them.
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        data[table] = [dict(r) for r in rows]
    conn.close()
    return data


def import_site_data(data, mode):
    """Import site data from a previously exported dict.

    ``mode`` must be one of:

    * ``"delete_all"`` – clear all existing data first, then insert everything
      from the export.
    * ``"override"`` – keep existing data but replace any conflicting rows with
      the imported values (``INSERT OR REPLACE``).
    * ``"keep"`` – keep existing data; silently skip any conflicting rows
      (``INSERT OR IGNORE``).

    Raises ``ValueError`` for an unrecognised mode or an incompatible export
    version.
    """
    if mode not in ("delete_all", "override", "keep"):
        raise ValueError(f"Unknown import mode: {mode!r}")

    meta = data.get("_meta", {})
    version = meta.get("version", 1)
    if version != _MIGRATION_VERSION:
        raise ValueError(
            f"Incompatible export version {version!r} "
            f"(expected {_MIGRATION_VERSION})"
        )

    conn = get_db()
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("BEGIN")

        tables = _get_migration_tables(conn)

        if mode == "delete_all":
            # Delete in reverse dependency order to avoid FK violations even
            # though FK enforcement is off – keeps things tidy.
            for table in reversed(tables):
                if table == "site_settings":
                    # Keep the singleton row; we will update it below.
                    continue
                # Safe: table names in *tables* come from _get_migration_tables()
                # and are validated with _VALID_TABLE_NAME_RE.
                conn.execute(f"DELETE FROM {table}")  # noqa: S608

        insert_prefix = {
            "delete_all": "INSERT OR REPLACE",
            "override": "INSERT OR REPLACE",
            "keep": "INSERT OR IGNORE",
        }[mode]

        for table in tables:
            rows = data.get(table, [])
            if not rows:
                continue

            # Derive column list from the first row; skip unknown columns so
            # that exports from older schema versions still load gracefully.
            conn_cols = {
                r[1]
                for r in conn.execute(
                    # Safe: table names in *tables* come from
                    # _get_migration_tables() and match _VALID_TABLE_NAME_RE.
                    f"PRAGMA table_info({table})"  # noqa: S608
                ).fetchall()
            }
            import_cols = [c for c in rows[0].keys() if c in conn_cols]
            if not import_cols:
                continue

            col_str = ", ".join(import_cols)
            placeholders = ", ".join("?" for _ in import_cols)
            sql = (
                # Safe: table names in *tables* come from
                # _get_migration_tables() and match _VALID_TABLE_NAME_RE.
                f"{insert_prefix} INTO {table} ({col_str}) "  # noqa: S608
                f"VALUES ({placeholders})"
            )

            if table == "site_settings" and mode == "delete_all":
                # site_settings has a singleton row; always use REPLACE.
                sql = (
                    f"INSERT OR REPLACE INTO {table} ({col_str}) "  # noqa: S608
                    f"VALUES ({placeholders})"
                )

            for row in rows:
                vals = [row.get(c) for c in import_cols]
                conn.execute(sql, vals)

        if (
            "user_permissions" not in data
            or "user_category_access" not in data
            or "user_allowed_categories" not in data
        ):
            from helpers._permissions import get_default_permissions

            legacy_users_needing_defaults = conn.execute(
                "SELECT id, role FROM users "
                "WHERE role IN ('editor', 'user') "
                "AND NOT EXISTS (SELECT 1 FROM user_permissions up WHERE up.user_id = users.id) "
                "AND NOT EXISTS (SELECT 1 FROM user_category_access uca WHERE uca.user_id = users.id)"
            ).fetchall()
            for user_row in legacy_users_needing_defaults:
                default_permissions = get_default_permissions(user_row["role"])
                if not default_permissions:
                    continue
                conn.executemany(
                    "INSERT OR IGNORE INTO user_permissions (user_id, permission_key) VALUES (?, ?)",
                    [(user_row["id"], key) for key in default_permissions],
                )

        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.close()
