"""Site settings."""

from ._connection import get_db


# ---------------------------------------------------------------------------
#  Site settings helpers
# ---------------------------------------------------------------------------
def get_site_settings():
    """Return the single site_settings row (id=1), or None if not initialised."""
    conn = get_db()
    row = conn.execute("SELECT * FROM site_settings WHERE id=1").fetchone()
    conn.close()
    return row


_ALLOWED_SETTINGS_COLUMNS = {
    "site_name", "primary_color", "secondary_color", "accent_color",
    "text_color", "sidebar_color", "bg_color",
    "light_primary_color", "light_secondary_color", "light_accent_color",
    "light_text_color", "light_sidebar_color", "light_bg_color",
    "default_theme_mode", "setup_done", "timezone",
    "favicon_enabled", "favicon_type", "favicon_custom",
    "lockdown_mode", "lockdown_message",
    "session_limit_enabled", "last_chat_cleanup_at",
    # Legacy chat settings (backwards compatibility)
    "chat_attachments_per_day_limit", "chat_auto_clear_messages",
    "chat_auto_clear_attachments", "chat_message_retention_days",
    "chat_attachment_retention_days",
    # Global chat settings
    "chat_max_message_length", "chat_attachments_enabled",
    "chat_max_attachment_size_mb",
    # DM-specific settings
    "chat_dm_enabled", "chat_allow_dm_creation",
    "chat_dm_auto_clear_messages", "chat_dm_auto_clear_attachments",
    "chat_dm_message_retention_days", "chat_dm_attachment_retention_days",
    # Group-specific settings
    "chat_group_enabled", "chat_allow_group_creation",
    "chat_group_auto_clear_messages", "chat_group_auto_clear_attachments",
    "chat_group_message_retention_days", "chat_group_attachment_retention_days",
    # Chat cleanup schedule settings
    "chat_cleanup_enabled", "chat_cleanup_frequency_days", "chat_cleanup_hour",
}


def update_site_settings(**kwargs):
    """Update one or more site settings columns by keyword argument.

    Only columns listed in ``_ALLOWED_SETTINGS_COLUMNS`` may be changed;
    any unknown column name raises :exc:`ValueError`.
    """
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
