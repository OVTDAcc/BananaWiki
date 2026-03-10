"""Schema initialisation and migrations."""

from ._connection import get_db


# ---------------------------------------------------------------------------
#  Schema initialisation
# ---------------------------------------------------------------------------
def init_db():
    """Create tables if they do not exist."""
    conn = get_db()
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id          TEXT    PRIMARY KEY,
        username    TEXT    NOT NULL UNIQUE COLLATE NOCASE,
        password    TEXT    NOT NULL,
        role        TEXT    NOT NULL DEFAULT 'user'
                            CHECK(role IN ('user','editor','admin','protected_admin')),
        suspended   INTEGER NOT NULL DEFAULT 0,
        invite_code TEXT,
        created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS invite_codes (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        code        TEXT    NOT NULL UNIQUE,
        created_by  TEXT REFERENCES users(id) ON DELETE SET NULL,
        created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
        expires_at  TEXT    NOT NULL,
        used_by     TEXT REFERENCES users(id) ON DELETE SET NULL,
        used_at     TEXT,
        deleted     INTEGER NOT NULL DEFAULT 0,
        deleted_at  TEXT
    );

    CREATE TABLE IF NOT EXISTS categories (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT    NOT NULL,
        parent_id   INTEGER REFERENCES categories(id) ON DELETE SET NULL,
        sort_order  INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS pages (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        title       TEXT    NOT NULL,
        slug        TEXT    NOT NULL UNIQUE,
        content     TEXT    NOT NULL DEFAULT '',
        category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
        is_home     INTEGER NOT NULL DEFAULT 0,
        sort_order  INTEGER NOT NULL DEFAULT 0,
        last_edited_by TEXT REFERENCES users(id) ON DELETE SET NULL,
        last_edited_at TEXT,
        created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS page_history (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        page_id     INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
        title       TEXT    NOT NULL,
        content     TEXT    NOT NULL,
        edited_by   TEXT REFERENCES users(id) ON DELETE SET NULL,
        edit_message TEXT   NOT NULL DEFAULT '',
        is_revert   INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS drafts (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        page_id     INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
        user_id     TEXT    NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        title       TEXT    NOT NULL DEFAULT '',
        content     TEXT    NOT NULL DEFAULT '',
        updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),
        UNIQUE(page_id, user_id)
    );

    CREATE TABLE IF NOT EXISTS site_settings (
        id          INTEGER PRIMARY KEY CHECK (id = 1),
        site_name   TEXT    NOT NULL DEFAULT 'BananaWiki',
        primary_color    TEXT NOT NULL DEFAULT '#8fa0d4',
        secondary_color  TEXT NOT NULL DEFAULT '#1e1e2c',
        accent_color     TEXT NOT NULL DEFAULT '#7e9ada',
        text_color       TEXT NOT NULL DEFAULT '#c8ccd8',
        sidebar_color    TEXT NOT NULL DEFAULT '#1a1a24',
        bg_color         TEXT NOT NULL DEFAULT '#16161f',
        light_primary_color   TEXT NOT NULL DEFAULT '#4b63b6',
        light_secondary_color TEXT NOT NULL DEFAULT '#ffffff',
        light_accent_color    TEXT NOT NULL DEFAULT '#3553c7',
        light_text_color      TEXT NOT NULL DEFAULT '#202534',
        light_sidebar_color   TEXT NOT NULL DEFAULT '#e9edf5',
        light_bg_color        TEXT NOT NULL DEFAULT '#f6f7fb',
        default_theme_mode    TEXT NOT NULL DEFAULT 'dark'
                              CHECK(default_theme_mode IN ('dark','light')),
        setup_done  INTEGER NOT NULL DEFAULT 0,
        timezone    TEXT    NOT NULL DEFAULT 'UTC',
        session_limit_enabled INTEGER NOT NULL DEFAULT 1,
        about_page_initialized INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS login_attempts (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        ip           TEXT NOT NULL,
        attempted_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS announcements (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        content         TEXT    NOT NULL DEFAULT '',
        color           TEXT    NOT NULL DEFAULT 'orange'
                                CHECK(color IN ('red','orange','yellow','blue','green')),
        text_size       TEXT    NOT NULL DEFAULT 'normal'
                                CHECK(text_size IN ('small','normal','large')),
        visibility      TEXT    NOT NULL DEFAULT 'both'
                                CHECK(visibility IN ('logged_in','logged_out','both')),
        expires_at      TEXT,
        is_active       INTEGER NOT NULL DEFAULT 1,
        not_removable   INTEGER NOT NULL DEFAULT 1,
        show_countdown  INTEGER NOT NULL DEFAULT 1,
        created_by      TEXT REFERENCES users(id) ON DELETE SET NULL,
        created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    INSERT OR IGNORE INTO site_settings (id) VALUES (1);

    CREATE TABLE IF NOT EXISTS username_history (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     TEXT    NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        old_username TEXT   NOT NULL,
        new_username TEXT   NOT NULL,
        changed_at  TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS editor_category_access (
        user_id     TEXT    PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        restricted  INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS editor_allowed_categories (
        user_id     TEXT    NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
        UNIQUE(user_id, category_id)
    );

    CREATE TABLE IF NOT EXISTS page_attachments (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        page_id         INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
        filename        TEXT    NOT NULL,
        original_name   TEXT    NOT NULL,
        file_size       INTEGER NOT NULL DEFAULT 0,
        uploaded_by     TEXT REFERENCES users(id) ON DELETE SET NULL,
        uploaded_at     TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS user_profiles (
        user_id         TEXT    PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        real_name       TEXT    NOT NULL DEFAULT '',
        bio             TEXT    NOT NULL DEFAULT '',
        avatar_filename TEXT    NOT NULL DEFAULT '',
        page_published  INTEGER NOT NULL DEFAULT 0,
        page_disabled_by_admin INTEGER NOT NULL DEFAULT 0,
        updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS chats (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user1_id    TEXT    NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        user2_id    TEXT    NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
        UNIQUE(user1_id, user2_id)
    );

    CREATE TABLE IF NOT EXISTS chat_messages (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id     INTEGER NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
        sender_id   TEXT    NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        content     TEXT    NOT NULL DEFAULT '',
        is_deleted  INTEGER NOT NULL DEFAULT 0,
        deleted_at  TEXT,
        ip_address  TEXT    NOT NULL DEFAULT '',
        created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS chat_attachments (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id      INTEGER NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
        filename        TEXT    NOT NULL,
        original_name   TEXT    NOT NULL,
        file_size       INTEGER NOT NULL DEFAULT 0,
        created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS group_chats (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT    NOT NULL,
        creator_id  TEXT    REFERENCES users(id) ON DELETE SET NULL,
        invite_code TEXT    NOT NULL UNIQUE,
        is_global   INTEGER NOT NULL DEFAULT 0,
        is_active   INTEGER NOT NULL DEFAULT 1,
        created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS group_members (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id        INTEGER NOT NULL REFERENCES group_chats(id) ON DELETE CASCADE,
        user_id         TEXT    NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        role            TEXT    NOT NULL DEFAULT 'member'
                        CHECK(role IN ('member','moderator','owner')),
        timed_out_until TEXT,
        joined_at       TEXT    NOT NULL DEFAULT (datetime('now')),
        UNIQUE(group_id, user_id)
    );

    CREATE TABLE IF NOT EXISTS group_messages (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id    INTEGER NOT NULL REFERENCES group_chats(id) ON DELETE CASCADE,
        sender_id   TEXT    REFERENCES users(id) ON DELETE SET NULL,
        content     TEXT    NOT NULL DEFAULT '',
        is_system   INTEGER NOT NULL DEFAULT 0,
        is_deleted  INTEGER NOT NULL DEFAULT 0,
        deleted_at  TEXT,
        ip_address  TEXT    NOT NULL DEFAULT '',
        created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS group_attachments (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id      INTEGER NOT NULL REFERENCES group_messages(id) ON DELETE CASCADE,
        filename        TEXT    NOT NULL,
        original_name   TEXT    NOT NULL,
        file_size       INTEGER NOT NULL DEFAULT 0,
        created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS role_history (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     TEXT    NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        old_role    TEXT    NOT NULL,
        new_role    TEXT    NOT NULL,
        changed_by  TEXT REFERENCES users(id) ON DELETE SET NULL,
        changed_at  TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS user_custom_tags (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     TEXT    NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        label       TEXT    NOT NULL,
        color       TEXT    NOT NULL DEFAULT '#9b59b6',
        sort_order  INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS user_permissions (
        user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        permission_key  TEXT NOT NULL,
        UNIQUE(user_id, permission_key)
    );

    CREATE TABLE IF NOT EXISTS user_category_access (
        user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        access_type TEXT NOT NULL CHECK(access_type IN ('read','write')),
        restricted  INTEGER NOT NULL DEFAULT 0,
        UNIQUE(user_id, access_type)
    );

    CREATE TABLE IF NOT EXISTS user_allowed_categories (
        user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
        access_type TEXT NOT NULL CHECK(access_type IN ('read','write')),
        UNIQUE(user_id, category_id, access_type)
    );

    CREATE TABLE IF NOT EXISTS badge_types (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        name            TEXT    NOT NULL UNIQUE,
        description     TEXT    NOT NULL DEFAULT '',
        icon            TEXT    NOT NULL DEFAULT '🏆',
        color           TEXT    NOT NULL DEFAULT '#ffd700',
        enabled         INTEGER NOT NULL DEFAULT 1,
        auto_trigger    INTEGER NOT NULL DEFAULT 0,
        trigger_type    TEXT    NOT NULL DEFAULT ''
                                CHECK(trigger_type IN ('','category_count','contribution_count','first_edit','member_days','easter_egg','reading_time','article_count')),
        trigger_threshold INTEGER NOT NULL DEFAULT 0,
        allow_multiple  INTEGER NOT NULL DEFAULT 0,
        created_by      TEXT REFERENCES users(id) ON DELETE SET NULL,
        created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS user_badges (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         TEXT    NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        badge_type_id   INTEGER NOT NULL REFERENCES badge_types(id) ON DELETE CASCADE,
        earned_at       TEXT    NOT NULL DEFAULT (datetime('now')),
        awarded_by      TEXT REFERENCES users(id) ON DELETE SET NULL,
        revoked         INTEGER NOT NULL DEFAULT 0,
        revoked_at      TEXT,
        revoked_by      TEXT REFERENCES users(id) ON DELETE SET NULL,
        UNIQUE(user_id, badge_type_id)
    );

    CREATE TABLE IF NOT EXISTS badge_notifications (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id         TEXT    NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        badge_type_id   INTEGER NOT NULL REFERENCES badge_types(id) ON DELETE CASCADE,
        notified        INTEGER NOT NULL DEFAULT 0,
        created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS page_reservations (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        page_id         INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
        user_id         TEXT    NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        reserved_at     TEXT    NOT NULL,
        expires_at      TEXT    NOT NULL,
        released_at     TEXT,
        UNIQUE(page_id)
    );

    CREATE TABLE IF NOT EXISTS user_page_cooldowns (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        page_id         INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
        user_id         TEXT    NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        cooldown_until  TEXT    NOT NULL,
        UNIQUE(page_id, user_id)
    );
    """)

    # -- Migrations: add columns to existing tables --
    # Add last_login_at to users if missing
    cols = [r[1] for r in cur.execute("PRAGMA table_info(users)").fetchall()]
    if "last_login_at" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN last_login_at TEXT")
    if "easter_egg_found" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN easter_egg_found INTEGER NOT NULL DEFAULT 0")
    if "is_superuser" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN is_superuser INTEGER NOT NULL DEFAULT 0")

    # Add timezone / favicon columns to site_settings if missing
    ss_cols = [r[1] for r in cur.execute("PRAGMA table_info(site_settings)").fetchall()]
    if "timezone" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN timezone TEXT NOT NULL DEFAULT 'UTC'")
    if "favicon_enabled" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN favicon_enabled INTEGER NOT NULL DEFAULT 0")
    if "favicon_type" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN favicon_type TEXT NOT NULL DEFAULT 'yellow'")
    if "favicon_custom" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN favicon_custom TEXT NOT NULL DEFAULT ''")
    if "lockdown_mode" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN lockdown_mode INTEGER NOT NULL DEFAULT 0")
    if "lockdown_message" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN lockdown_message TEXT NOT NULL DEFAULT ''")
    if "session_limit_enabled" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN session_limit_enabled INTEGER NOT NULL DEFAULT 1")
    if "about_page_initialized" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN about_page_initialized INTEGER NOT NULL DEFAULT 0")
    if "light_primary_color" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN light_primary_color TEXT NOT NULL DEFAULT '#4b63b6'")
    if "light_secondary_color" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN light_secondary_color TEXT NOT NULL DEFAULT '#ffffff'")
    if "light_accent_color" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN light_accent_color TEXT NOT NULL DEFAULT '#3553c7'")
    if "light_text_color" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN light_text_color TEXT NOT NULL DEFAULT '#202534'")
    if "light_sidebar_color" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN light_sidebar_color TEXT NOT NULL DEFAULT '#e9edf5'")
    if "light_bg_color" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN light_bg_color TEXT NOT NULL DEFAULT '#f6f7fb'")
    if "default_theme_mode" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN default_theme_mode TEXT NOT NULL DEFAULT 'dark'")

    # Migrate old default colors to improved, more readable defaults.
    # Column names come from a hardcoded list – validated against the allowed
    # settings columns before building the query to prevent SQL injection.
    _ALLOWED_COLOR_COLS = {
        "bg_color", "sidebar_color", "secondary_color",
        "text_color", "primary_color", "accent_color",
    }
    color_migrations = [
        ("bg_color",        "#0d0d14", "#16161f"),
        ("sidebar_color",   "#111118", "#1a1a24"),
        ("secondary_color", "#151520", "#1e1e2c"),
        ("text_color",      "#b8bcc8", "#c8ccd8"),
        ("primary_color",   "#7c8dc6", "#8fa0d4"),
        ("accent_color",    "#6e8aca", "#7e9ada"),
    ]
    for col, old_val, new_val in color_migrations:
        if col not in _ALLOWED_COLOR_COLS:
            continue
        cur.execute(
            f"UPDATE site_settings SET {col}=? WHERE id=1 AND {col}=?",  # noqa: S608
            (new_val, old_val),
        )

    # Add session_token column to users if missing
    if "session_token" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN session_token TEXT")

    # Add accessibility column to users if missing
    if "accessibility" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN accessibility TEXT")

    # Add last_chat_cleanup_at to site_settings if missing
    if "last_chat_cleanup_at" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN last_chat_cleanup_at TEXT")

    # Add chat_disabled column to users if missing
    if "chat_disabled" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN chat_disabled INTEGER NOT NULL DEFAULT 0")

    # Add banned column to group_members if missing
    gm_cols = [r[1] for r in cur.execute("PRAGMA table_info(group_members)").fetchall()]
    if "banned" not in gm_cols:
        cur.execute("ALTER TABLE group_members ADD COLUMN banned INTEGER NOT NULL DEFAULT 0")

    # Add is_active column to group_chats if missing
    gc_cols = [r[1] for r in cur.execute("PRAGMA table_info(group_chats)").fetchall()]
    if "is_active" not in gc_cols:
        cur.execute("ALTER TABLE group_chats ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")

    # Add description column to group_chats if missing
    if "description" not in gc_cols:
        cur.execute("ALTER TABLE group_chats ADD COLUMN description TEXT NOT NULL DEFAULT ''")

    # Add chat configuration columns to site_settings if missing
    if "chat_attachments_per_day_limit" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN chat_attachments_per_day_limit INTEGER NOT NULL DEFAULT 10")
    if "chat_auto_clear_messages" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN chat_auto_clear_messages INTEGER NOT NULL DEFAULT 0")
    if "chat_auto_clear_attachments" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN chat_auto_clear_attachments INTEGER NOT NULL DEFAULT 1")
    if "chat_message_retention_days" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN chat_message_retention_days INTEGER NOT NULL DEFAULT 0")
    if "chat_attachment_retention_days" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN chat_attachment_retention_days INTEGER NOT NULL DEFAULT 7")

    # Add separate DM and Group chat settings
    if "chat_dm_enabled" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN chat_dm_enabled INTEGER NOT NULL DEFAULT 1")
    if "chat_dm_auto_clear_messages" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN chat_dm_auto_clear_messages INTEGER NOT NULL DEFAULT 0")
    if "chat_dm_auto_clear_attachments" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN chat_dm_auto_clear_attachments INTEGER NOT NULL DEFAULT 1")
    if "chat_dm_message_retention_days" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN chat_dm_message_retention_days INTEGER NOT NULL DEFAULT 0")
    if "chat_dm_attachment_retention_days" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN chat_dm_attachment_retention_days INTEGER NOT NULL DEFAULT 7")

    if "chat_group_enabled" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN chat_group_enabled INTEGER NOT NULL DEFAULT 1")
    if "chat_group_auto_clear_messages" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN chat_group_auto_clear_messages INTEGER NOT NULL DEFAULT 0")
    if "chat_group_auto_clear_attachments" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN chat_group_auto_clear_attachments INTEGER NOT NULL DEFAULT 1")
    if "chat_group_message_retention_days" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN chat_group_message_retention_days INTEGER NOT NULL DEFAULT 0")
    if "chat_group_attachment_retention_days" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN chat_group_attachment_retention_days INTEGER NOT NULL DEFAULT 7")

    # Add additional chat customization options
    if "chat_max_message_length" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN chat_max_message_length INTEGER NOT NULL DEFAULT 5000")
    if "chat_attachments_enabled" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN chat_attachments_enabled INTEGER NOT NULL DEFAULT 1")
    if "chat_max_attachment_size_mb" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN chat_max_attachment_size_mb INTEGER NOT NULL DEFAULT 5")
    if "chat_allow_dm_creation" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN chat_allow_dm_creation INTEGER NOT NULL DEFAULT 1")
    if "chat_allow_group_creation" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN chat_allow_group_creation INTEGER NOT NULL DEFAULT 1")

    # Add chat cleanup schedule settings (moved from config.py to allow admin configuration)
    if "chat_cleanup_enabled" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN chat_cleanup_enabled INTEGER NOT NULL DEFAULT 1")
    if "chat_cleanup_frequency_days" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN chat_cleanup_frequency_days INTEGER NOT NULL DEFAULT 7")
    if "chat_cleanup_hour" not in ss_cols:
        cur.execute("ALTER TABLE site_settings ADD COLUMN chat_cleanup_hour INTEGER NOT NULL DEFAULT 3")

    # Add unread_count column to chats if missing
    chat_cols = [r[1] for r in cur.execute("PRAGMA table_info(chats)").fetchall()]
    if "unread_count_user1" not in chat_cols:
        cur.execute("ALTER TABLE chats ADD COLUMN unread_count_user1 INTEGER NOT NULL DEFAULT 0")
    if "unread_count_user2" not in chat_cols:
        cur.execute("ALTER TABLE chats ADD COLUMN unread_count_user2 INTEGER NOT NULL DEFAULT 0")

    chat_msg_cols = [r[1] for r in cur.execute("PRAGMA table_info(chat_messages)").fetchall()]
    if "is_deleted" not in chat_msg_cols:
        cur.execute("ALTER TABLE chat_messages ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0")
    if "deleted_at" not in chat_msg_cols:
        cur.execute("ALTER TABLE chat_messages ADD COLUMN deleted_at TEXT")

    # Add unread_count to group_members if missing
    if "unread_count" not in gm_cols:
        cur.execute("ALTER TABLE group_members ADD COLUMN unread_count INTEGER NOT NULL DEFAULT 0")

    group_msg_cols = [r[1] for r in cur.execute("PRAGMA table_info(group_messages)").fetchall()]
    if "is_deleted" not in group_msg_cols:
        cur.execute("ALTER TABLE group_messages ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0")
    if "deleted_at" not in group_msg_cols:
        cur.execute("ALTER TABLE group_messages ADD COLUMN deleted_at TEXT")

    # Add sequential_nav to categories if missing
    cat_cols = [r[1] for r in cur.execute("PRAGMA table_info(categories)").fetchall()]
    if "sequential_nav" not in cat_cols:
        cur.execute("ALTER TABLE categories ADD COLUMN sequential_nav INTEGER NOT NULL DEFAULT 0")

    # Add difficulty_tag / custom-tag columns to pages if missing
    page_cols = [r[1] for r in cur.execute("PRAGMA table_info(pages)").fetchall()]
    if "difficulty_tag" not in page_cols:
        cur.execute("ALTER TABLE pages ADD COLUMN difficulty_tag TEXT NOT NULL DEFAULT ''")
    if "tag_custom_label" not in page_cols:
        cur.execute("ALTER TABLE pages ADD COLUMN tag_custom_label TEXT NOT NULL DEFAULT ''")
    if "tag_custom_color" not in page_cols:
        cur.execute("ALTER TABLE pages ADD COLUMN tag_custom_color TEXT NOT NULL DEFAULT ''")
    if "is_deindexed" not in page_cols:
        cur.execute("ALTER TABLE pages ADD COLUMN is_deindexed INTEGER NOT NULL DEFAULT 0")

    # Add not_removable and show_countdown columns to announcements if missing
    ann_cols = [r[1] for r in cur.execute("PRAGMA table_info(announcements)").fetchall()]
    if "not_removable" not in ann_cols:
        cur.execute("ALTER TABLE announcements ADD COLUMN not_removable INTEGER NOT NULL DEFAULT 1")
    if "show_countdown" not in ann_cols:
        cur.execute("ALTER TABLE announcements ADD COLUMN show_countdown INTEGER NOT NULL DEFAULT 1")

    # Add is_revert column to page_history if missing
    hist_cols = [r[1] for r in cur.execute("PRAGMA table_info(page_history)").fetchall()]
    if "is_revert" not in hist_cols:
        cur.execute("ALTER TABLE page_history ADD COLUMN is_revert INTEGER NOT NULL DEFAULT 0")

    # Migrate users.id from INTEGER to TEXT if needed
    user_id_type = next(
        (r[2] for r in cur.execute("PRAGMA table_info(users)").fetchall() if r[1] == 'id'),
        None,
    )
    if user_id_type and 'INT' in user_id_type.upper():
        _migrate_user_id_to_text(conn, cur)

    # Migrate role CHECK constraint to include 'protected_admin' if not already present
    schema_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()
    if schema_row and "protected_admin" not in schema_row[0]:
        _migrate_role_add_protected_admin(conn, cur)

    # Ensure home page exists
    home = cur.execute("SELECT id FROM pages WHERE is_home=1").fetchone()
    if not home:
        cur.execute(
            "INSERT INTO pages (title, slug, content, is_home) VALUES (?, ?, ?, 1)",
            ("Home", "home", "# Welcome to your Wiki\n\nEdit this page to get started."),
        )

    # Ensure About page exists (only on fresh install, never after deletion)
    # Use about_page_initialized flag to track if we've ever tried to create it
    settings = cur.execute("SELECT about_page_initialized FROM site_settings WHERE id=1").fetchone()
    about_initialized = settings[0] if settings else 0

    if not about_initialized:
        # Check if About page exists
        about = cur.execute("SELECT id FROM pages WHERE slug=?", ("about",)).fetchone()
        if not about:
            # Create the About page only if it doesn't exist
            about_content = """# About BananaWiki

BananaWiki is a lightweight, self-hosted wiki platform designed for simplicity and ease of use.

## Features

- **Markdown Support**: Write content using simple Markdown syntax
- **Categories**: Organize your pages into hierarchical categories
- **User Management**: Role-based access control (User, Editor, Admin)
- **Page History**: Track all changes with full revision history
- **Direct Messaging**: Built-in chat system for user communication
- **Group Chats**: Create and manage group conversations
- **Customization**: Personalize colors and appearance

## Getting Started

As an administrator, you can:
- Create new pages and categories
- Manage users and permissions
- Customize site settings
- Monitor system activity

Feel free to edit or delete this page as needed!

---

*This page was automatically created during installation. You can safely edit or delete it.*
"""
            cur.execute(
                "INSERT INTO pages (title, slug, content, sort_order) VALUES (?, ?, ?, ?)",
                ("About", "about", about_content, -1),
            )
        # Mark as initialized whether the page was created or already existed
        cur.execute("UPDATE site_settings SET about_page_initialized=1 WHERE id=1")

    conn.commit()
    conn.close()


def _migrate_role_add_protected_admin(conn, cur):
    """Expand the role CHECK constraint to include 'protected_admin'.

    SQLite does not support ALTER TABLE … ALTER COLUMN, so we recreate the
    users table with an updated constraint while preserving all data.
    Also renames any existing 'superadmin' values to 'protected_admin'.
    """
    conn.execute("PRAGMA foreign_keys=OFF")
    cols = [r[1] for r in cur.execute("PRAGMA table_info(users)").fetchall()]
    col_list = ", ".join(cols)
    cur.execute(f"""
        CREATE TABLE users_migrate_protected_admin AS
        SELECT {col_list} FROM users
    """)
    cur.execute("DROP TABLE users")
    cur.execute(f"""
        CREATE TABLE users (
            id              TEXT    PRIMARY KEY,
            username        TEXT    NOT NULL UNIQUE COLLATE NOCASE,
            password        TEXT    NOT NULL,
            role            TEXT    NOT NULL DEFAULT 'user'
                                    CHECK(role IN ('user','editor','admin','protected_admin')),
            suspended       INTEGER NOT NULL DEFAULT 0,
            invite_code     TEXT,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
            last_login_at   TEXT,
            easter_egg_found INTEGER NOT NULL DEFAULT 0,
            is_superuser    INTEGER NOT NULL DEFAULT 0
        )
    """)
    cur.execute(
        f"INSERT INTO users SELECT {col_list} FROM users_migrate_protected_admin"
    )
    # Rename any pre-existing 'superadmin' rows to 'protected_admin'
    cur.execute("UPDATE users SET role='protected_admin' WHERE role='superadmin'")
    cur.execute("DROP TABLE users_migrate_protected_admin")
    conn.execute("PRAGMA foreign_keys=ON")


def _migrate_user_id_to_text(conn, cur):
    """Migrate users.id from INTEGER AUTOINCREMENT to TEXT.

    Existing integer IDs are kept as their string representations (e.g. 1 → '1').
    All foreign-key columns that reference users(id) are likewise changed to TEXT.
    """
    conn.execute("PRAGMA foreign_keys=OFF")

    # ---- users ----
    cur.execute("""
        CREATE TABLE users_new (
            id              TEXT    PRIMARY KEY,
            username        TEXT    NOT NULL UNIQUE COLLATE NOCASE,
            password        TEXT    NOT NULL,
            role            TEXT    NOT NULL DEFAULT 'user'
                                    CHECK(role IN ('user','editor','admin','protected_admin')),
            suspended       INTEGER NOT NULL DEFAULT 0,
            invite_code     TEXT,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
            last_login_at   TEXT,
            easter_egg_found INTEGER NOT NULL DEFAULT 0,
            is_superuser    INTEGER NOT NULL DEFAULT 0
        )
    """)
    cur.execute("""
        INSERT INTO users_new
        SELECT CAST(id AS TEXT), username, password, role, suspended,
               invite_code, created_at, last_login_at,
               COALESCE(easter_egg_found, 0),
               COALESCE(is_superuser, 0)
        FROM users
    """)
    cur.execute("DROP TABLE users")
    cur.execute("ALTER TABLE users_new RENAME TO users")

    # ---- invite_codes ----
    cur.execute("""
        CREATE TABLE invite_codes_new (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            code        TEXT    NOT NULL UNIQUE,
            created_by  TEXT REFERENCES users(id) ON DELETE SET NULL,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
            expires_at  TEXT    NOT NULL,
            used_by     TEXT REFERENCES users(id) ON DELETE SET NULL,
            used_at     TEXT,
            deleted     INTEGER NOT NULL DEFAULT 0,
            deleted_at  TEXT
        )
    """)
    cur.execute("""
        INSERT INTO invite_codes_new
        SELECT id, code, CAST(created_by AS TEXT), created_at, expires_at,
               CAST(used_by AS TEXT), used_at, deleted, deleted_at
        FROM invite_codes
    """)
    cur.execute("DROP TABLE invite_codes")
    cur.execute("ALTER TABLE invite_codes_new RENAME TO invite_codes")

    # ---- announcements ----
    # Check which columns exist in the old table so we can preserve them
    ann_old_cols = {r[1] for r in cur.execute("PRAGMA table_info(announcements)").fetchall()}
    cur.execute("""
        CREATE TABLE announcements_new (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            content         TEXT    NOT NULL DEFAULT '',
            color           TEXT    NOT NULL DEFAULT 'orange'
                                    CHECK(color IN ('red','orange','yellow','blue','green')),
            text_size       TEXT    NOT NULL DEFAULT 'normal'
                                    CHECK(text_size IN ('small','normal','large')),
            visibility      TEXT    NOT NULL DEFAULT 'both'
                                    CHECK(visibility IN ('logged_in','logged_out','both')),
            expires_at      TEXT,
            is_active       INTEGER NOT NULL DEFAULT 1,
            not_removable   INTEGER NOT NULL DEFAULT 1,
            show_countdown  INTEGER NOT NULL DEFAULT 1,
            created_by      TEXT REFERENCES users(id) ON DELETE SET NULL,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)
    nr_expr = "not_removable" if "not_removable" in ann_old_cols else "1"
    sc_expr = "show_countdown" if "show_countdown" in ann_old_cols else "1"
    cur.execute(f"""
        INSERT INTO announcements_new
        SELECT id, content, color, text_size, visibility, expires_at, is_active,
               {nr_expr}, {sc_expr},
               CAST(created_by AS TEXT), created_at
        FROM announcements
    """)
    cur.execute("DROP TABLE announcements")
    cur.execute("ALTER TABLE announcements_new RENAME TO announcements")

    # ---- pages (last_edited_by: INT → TEXT) ----
    cur.execute("""
        CREATE TABLE pages_new (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            title           TEXT    NOT NULL,
            slug            TEXT    NOT NULL UNIQUE,
            content         TEXT    NOT NULL DEFAULT '',
            category_id     INTEGER REFERENCES categories(id) ON DELETE SET NULL,
            is_home         INTEGER NOT NULL DEFAULT 0,
            sort_order      INTEGER NOT NULL DEFAULT 0,
            last_edited_by  TEXT REFERENCES users(id) ON DELETE SET NULL,
            last_edited_at  TEXT,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)
    cur.execute("""
        INSERT INTO pages_new
        SELECT id, title, slug, content, category_id, is_home, sort_order,
               CAST(last_edited_by AS TEXT), last_edited_at, created_at
        FROM pages
    """)

    # ---- page_history (edited_by: INT → TEXT) ----
    cur.execute("""
        CREATE TABLE page_history_new (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            page_id      INTEGER NOT NULL REFERENCES pages_new(id) ON DELETE CASCADE,
            title        TEXT    NOT NULL,
            content      TEXT    NOT NULL,
            edited_by    TEXT REFERENCES users(id) ON DELETE SET NULL,
            edit_message TEXT    NOT NULL DEFAULT '',
            created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)
    cur.execute("""
        INSERT INTO page_history_new
        SELECT id, page_id, title, content,
               CAST(edited_by AS TEXT), edit_message, created_at
        FROM page_history
    """)

    # ---- drafts (user_id: INT → TEXT) ----
    cur.execute("""
        CREATE TABLE drafts_new (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            page_id     INTEGER NOT NULL REFERENCES pages_new(id) ON DELETE CASCADE,
            user_id     TEXT    NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title       TEXT    NOT NULL DEFAULT '',
            content     TEXT    NOT NULL DEFAULT '',
            updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),
            UNIQUE(page_id, user_id)
        )
    """)
    cur.execute("""
        INSERT INTO drafts_new
        SELECT id, page_id, CAST(user_id AS TEXT), title, content, updated_at
        FROM drafts
    """)

    # Drop old tables (FK off so order doesn't matter) and rename
    cur.execute("DROP TABLE drafts")
    cur.execute("DROP TABLE page_history")
    cur.execute("DROP TABLE pages")
    cur.execute("ALTER TABLE pages_new RENAME TO pages")
    cur.execute("ALTER TABLE page_history_new RENAME TO page_history")
    cur.execute("ALTER TABLE drafts_new RENAME TO drafts")

    conn.execute("PRAGMA foreign_keys=ON")
