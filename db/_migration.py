"""Site data export and import."""

from datetime import datetime, timezone

from ._connection import get_db


# ---------------------------------------------------------------------------
#  Site migration – export / import
# ---------------------------------------------------------------------------
_MIGRATION_VERSION = 1

# Tables exported in dependency order (parents before children).
_EXPORT_TABLES = [
    "users",
    "invite_codes",
    "categories",
    "pages",
    "page_checkouts",
    "page_history",
    "drafts",
    "announcements",
    "username_history",
    "editor_category_access",
    "editor_allowed_categories",
    "site_settings",
    "user_profiles",
]


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
    for table in _EXPORT_TABLES:
        assert table in _EXPORT_TABLES  # noqa: S608 – table is from a hardcoded allowlist
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

        if mode == "delete_all":
            # Delete in reverse dependency order to avoid FK violations even
            # though FK enforcement is off – keeps things tidy.
            for table in reversed(_EXPORT_TABLES):
                if table == "site_settings":
                    # Keep the singleton row; we will update it below.
                    continue
                assert table in _EXPORT_TABLES  # table is from a hardcoded allowlist
                conn.execute(f"DELETE FROM {table}")  # noqa: S608

        insert_prefix = {
            "delete_all": "INSERT OR REPLACE",
            "override": "INSERT OR REPLACE",
            "keep": "INSERT OR IGNORE",
        }[mode]

        for table in _EXPORT_TABLES:
            rows = data.get(table, [])
            if not rows:
                continue

            # Derive column list from the first row; skip unknown columns so
            # that exports from older schema versions still load gracefully.
            conn_cols = {
                r[1]
                for r in conn.execute(
                    f"PRAGMA table_info({table})"  # noqa: S608
                ).fetchall()
            }
            import_cols = [c for c in rows[0].keys() if c in conn_cols]
            if not import_cols:
                continue

            col_str = ", ".join(import_cols)
            placeholders = ", ".join("?" for _ in import_cols)
            sql = (
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

        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.close()
