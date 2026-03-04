"""Site settings."""

from ._connection import get_db


# ---------------------------------------------------------------------------
#  Site settings helpers
# ---------------------------------------------------------------------------
def get_site_settings():
    conn = get_db()
    row = conn.execute("SELECT * FROM site_settings WHERE id=1").fetchone()
    conn.close()
    return row


_ALLOWED_SETTINGS_COLUMNS = {
    "site_name", "primary_color", "secondary_color", "accent_color",
    "text_color", "sidebar_color", "bg_color", "setup_done", "timezone",
    "favicon_enabled", "favicon_type", "favicon_custom",
    "lockdown_mode", "lockdown_message",
    "session_limit_enabled",
}


def update_site_settings(**kwargs):
    for k in kwargs:
        if k not in _ALLOWED_SETTINGS_COLUMNS:
            raise ValueError(f"Invalid column: {k}")
    conn = get_db()
    try:
        sets = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values())
        conn.execute(f"UPDATE site_settings SET {sets} WHERE id=1", vals)
        conn.commit()
    finally:
        conn.close()

