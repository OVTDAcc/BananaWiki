"""
BananaWiki – Database layer (SQLite)
"""

import re
import sqlite3
import os
import string
import secrets
from datetime import datetime, timedelta, timezone

import config


def get_db():
    """Return a new database connection."""
    os.makedirs(os.path.dirname(config.DATABASE_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


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
                            CHECK(role IN ('user','editor','admin')),
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
        used_by     TEXT REFERENCES users(id),
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
        primary_color    TEXT NOT NULL DEFAULT '#7c8dc6',
        secondary_color  TEXT NOT NULL DEFAULT '#151520',
        accent_color     TEXT NOT NULL DEFAULT '#6e8aca',
        text_color       TEXT NOT NULL DEFAULT '#b8bcc8',
        sidebar_color    TEXT NOT NULL DEFAULT '#111118',
        bg_color         TEXT NOT NULL DEFAULT '#0d0d14',
        setup_done  INTEGER NOT NULL DEFAULT 0,
        timezone    TEXT    NOT NULL DEFAULT 'UTC'
    );

    CREATE TABLE IF NOT EXISTS login_attempts (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        ip           TEXT NOT NULL,
        attempted_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS announcements (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        content     TEXT    NOT NULL DEFAULT '',
        color       TEXT    NOT NULL DEFAULT 'orange'
                            CHECK(color IN ('red','orange','yellow','blue','green')),
        text_size   TEXT    NOT NULL DEFAULT 'normal'
                            CHECK(text_size IN ('small','normal','large')),
        visibility  TEXT    NOT NULL DEFAULT 'both'
                            CHECK(visibility IN ('logged_in','logged_out','both')),
        expires_at  TEXT,
        is_active   INTEGER NOT NULL DEFAULT 1,
        created_by  TEXT REFERENCES users(id) ON DELETE SET NULL,
        created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    INSERT OR IGNORE INTO site_settings (id) VALUES (1);
    """)

    # -- Migrations: add columns to existing tables --
    # Add last_login_at to users if missing
    cols = [r[1] for r in cur.execute("PRAGMA table_info(users)").fetchall()]
    if "last_login_at" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN last_login_at TEXT")
    if "easter_egg_found" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN easter_egg_found INTEGER NOT NULL DEFAULT 0")

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

    # Migrate users.id from INTEGER to TEXT if needed
    user_id_type = next(
        (r[2] for r in cur.execute("PRAGMA table_info(users)").fetchall() if r[1] == 'id'),
        None,
    )
    if user_id_type and 'INT' in user_id_type.upper():
        _migrate_user_id_to_text(conn, cur)

    # Ensure home page exists
    home = cur.execute("SELECT id FROM pages WHERE is_home=1").fetchone()
    if not home:
        cur.execute(
            "INSERT INTO pages (title, slug, content, is_home) VALUES (?, ?, ?, 1)",
            ("Home", "home", "# Welcome to your Wiki\n\nEdit this page to get started."),
        )

    conn.commit()
    conn.close()


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
                                    CHECK(role IN ('user','editor','admin')),
            suspended       INTEGER NOT NULL DEFAULT 0,
            invite_code     TEXT,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
            last_login_at   TEXT,
            easter_egg_found INTEGER NOT NULL DEFAULT 0
        )
    """)
    cur.execute("""
        INSERT INTO users_new
        SELECT CAST(id AS TEXT), username, password, role, suspended,
               invite_code, created_at, last_login_at,
               COALESCE(easter_egg_found, 0)
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
            used_by     TEXT REFERENCES users(id),
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
    cur.execute("""
        CREATE TABLE announcements_new (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            content     TEXT    NOT NULL DEFAULT '',
            color       TEXT    NOT NULL DEFAULT 'orange'
                                CHECK(color IN ('red','orange','yellow','blue','green')),
            text_size   TEXT    NOT NULL DEFAULT 'normal'
                                CHECK(text_size IN ('small','normal','large')),
            visibility  TEXT    NOT NULL DEFAULT 'both'
                                CHECK(visibility IN ('logged_in','logged_out','both')),
            expires_at  TEXT,
            is_active   INTEGER NOT NULL DEFAULT 1,
            created_by  TEXT REFERENCES users(id) ON DELETE SET NULL,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)
    cur.execute("""
        INSERT INTO announcements_new
        SELECT id, content, color, text_size, visibility, expires_at, is_active,
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


# ---------------------------------------------------------------------------
#  User helpers
# ---------------------------------------------------------------------------
def _gen_user_id():
    """Generate a random 8-character alphanumeric lowercase user ID."""
    chars = string.ascii_lowercase + string.digits
    return ''.join(secrets.choice(chars) for _ in range(8))


def create_user(username, hashed_pw, role="user", invite_code=None):
    conn = get_db()
    cur = conn.cursor()
    uid = _gen_user_id()
    while conn.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
        uid = _gen_user_id()
    cur.execute(
        "INSERT INTO users (id, username, password, role, invite_code) VALUES (?, ?, ?, ?, ?)",
        (uid, username, hashed_pw, role, invite_code),
    )
    conn.commit()
    conn.close()
    return uid


def get_user_by_id(user_id):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return user


def get_user_by_username(username):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone()
    conn.close()
    return user


_ALLOWED_USER_COLUMNS = {"username", "password", "role", "suspended", "last_login_at"}


def update_user(user_id, **kwargs):
    for k in kwargs:
        if k not in _ALLOWED_USER_COLUMNS:
            raise ValueError(f"Invalid column: {k}")
    conn = get_db()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [user_id]
    conn.execute(f"UPDATE users SET {sets} WHERE id=?", vals)
    conn.commit()
    conn.close()


def delete_user(user_id):
    conn = get_db()
    conn.execute("UPDATE invite_codes SET used_by=NULL WHERE used_by=?", (user_id,))
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()


def set_easter_egg_found(user_id):
    """Mark that the user has found the easter egg (one-way: 0 -> 1 only)."""
    conn = get_db()
    conn.execute(
        "UPDATE users SET easter_egg_found=1 WHERE id=? AND easter_egg_found=0",
        (user_id,),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
#  Login attempt helpers (shared rate limiting across workers)
# ---------------------------------------------------------------------------
def record_login_attempt(ip):
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("INSERT INTO login_attempts (ip, attempted_at) VALUES (?, ?)", (ip, now))
    conn.commit()
    conn.close()


def count_recent_login_attempts(ip, window_seconds):
    """Return count of attempts from IP within the last window_seconds."""
    conn = get_db()
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=window_seconds)).isoformat()
    # Prune old entries to keep table small
    conn.execute("DELETE FROM login_attempts WHERE attempted_at < ?", (cutoff,))
    cnt = conn.execute(
        "SELECT COUNT(*) FROM login_attempts WHERE ip=? AND attempted_at >= ?",
        (ip, cutoff),
    ).fetchone()[0]
    conn.commit()
    conn.close()
    return cnt


def clear_login_attempts(ip):
    conn = get_db()
    conn.execute("DELETE FROM login_attempts WHERE ip=?", (ip,))
    conn.commit()
    conn.close()


def clear_all_login_attempts():
    conn = get_db()
    conn.execute("DELETE FROM login_attempts")
    conn.commit()
    conn.close()


def list_users(role_filter=None, status_filter=None):
    conn = get_db()
    q = "SELECT * FROM users WHERE 1=1"
    params = []
    if role_filter:
        q += " AND role=?"
        params.append(role_filter)
    if status_filter == "active":
        q += " AND suspended=0"
    elif status_filter == "suspended":
        q += " AND suspended=1"
    q += " ORDER BY created_at"
    users = conn.execute(q, params).fetchall()
    conn.close()
    return users


def count_admins():
    conn = get_db()
    cnt = conn.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND suspended=0").fetchone()[0]
    conn.close()
    return cnt


# ---------------------------------------------------------------------------
#  Invite code helpers
# ---------------------------------------------------------------------------
def generate_invite_code(created_by):
    chars = string.ascii_uppercase + string.digits
    code = "".join(secrets.choice(chars) for _ in range(4)) + "-" + "".join(secrets.choice(chars) for _ in range(4))
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=config.INVITE_CODE_EXPIRY_HOURS)
    conn = get_db()
    conn.execute(
        "INSERT INTO invite_codes (code, created_by, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (code, created_by, now.isoformat(), expires.isoformat()),
    )
    conn.commit()
    conn.close()
    return code


def validate_invite_code(code):
    """Return the invite row if valid, else None."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM invite_codes WHERE code=? AND used_by IS NULL AND used_at IS NULL AND deleted=0",
        (code,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    expires = datetime.fromisoformat(row["expires_at"]).replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires:
        return None
    return row


def use_invite_code(code, user_id):
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    cur = conn.execute(
        "UPDATE invite_codes SET used_by=?, used_at=? WHERE code=? AND used_by IS NULL AND used_at IS NULL AND deleted=0",
        (user_id, now, code),
    )
    conn.commit()
    updated = cur.rowcount > 0
    conn.close()
    return updated


def delete_invite_code(code_id):
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    conn.execute("UPDATE invite_codes SET deleted=1, deleted_at=? WHERE id=?", (now, code_id))
    conn.commit()
    conn.close()


def hard_delete_invite_code(code_id):
    """Permanently remove an expired/used/deleted invite code record."""
    conn = get_db()
    conn.execute("DELETE FROM invite_codes WHERE id=?", (code_id,))
    conn.commit()
    conn.close()


def list_invite_codes(active_only=True):
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    if active_only:
        rows = conn.execute(
            "SELECT ic.*, COALESCE(u.username, 'deleted user') AS creator_name FROM invite_codes ic "
            "LEFT JOIN users u ON ic.created_by=u.id "
            "WHERE ic.used_by IS NULL AND ic.deleted=0 AND ic.expires_at > ? "
            "ORDER BY ic.created_at DESC",
            (now,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT ic.*, COALESCE(u.username, 'deleted user') AS creator_name, u2.username AS used_by_name "
            "FROM invite_codes ic "
            "LEFT JOIN users u ON ic.created_by=u.id "
            "LEFT JOIN users u2 ON ic.used_by=u2.id "
            "ORDER BY ic.created_at DESC"
        ).fetchall()
    conn.close()
    return rows


def list_expired_codes():
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    rows = conn.execute(
        "SELECT ic.*, COALESCE(u.username, 'deleted user') AS creator_name, u2.username AS used_by_name "
        "FROM invite_codes ic "
        "LEFT JOIN users u ON ic.created_by=u.id "
        "LEFT JOIN users u2 ON ic.used_by=u2.id "
        "WHERE ic.used_by IS NOT NULL OR ic.used_at IS NOT NULL OR ic.deleted=1 OR ic.expires_at <= ? "
        "ORDER BY ic.created_at DESC",
        (now,),
    ).fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
#  Category helpers
# ---------------------------------------------------------------------------
def create_category(name, parent_id=None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO categories (name, parent_id) VALUES (?, ?)", (name, parent_id))
    cat_id = cur.lastrowid
    conn.commit()
    conn.close()
    return cat_id


def get_category(cat_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM categories WHERE id=?", (cat_id,)).fetchone()
    conn.close()
    return row


def update_category(cat_id, name):
    conn = get_db()
    conn.execute("UPDATE categories SET name=? WHERE id=?", (name, cat_id))
    conn.commit()
    conn.close()


def is_descendant_of(cat_id, ancestor_id):
    """Return True if ancestor_id is a descendant of cat_id (circular ref check)."""
    conn = get_db()
    current = ancestor_id
    visited = set()
    while current is not None:
        if current == cat_id:
            conn.close()
            return True
        if current in visited:
            break
        visited.add(current)
        row = conn.execute("SELECT parent_id FROM categories WHERE id=?",
                           (current,)).fetchone()
        current = row["parent_id"] if row else None
    conn.close()
    return False


def update_category_parent(cat_id, parent_id):
    """Move a category under a different parent (or to top level if parent_id is None)."""
    conn = get_db()
    conn.execute("UPDATE categories SET parent_id=? WHERE id=?", (parent_id, cat_id))
    conn.commit()
    conn.close()


def delete_category(cat_id, page_action="uncategorize", target_category_id=None):
    """Delete a category and handle its pages.

    page_action:
        "uncategorize" - move pages to uncategorized (default, backward-compatible)
        "delete"       - delete all pages in this category
        "move"         - move pages to target_category_id
    """
    conn = get_db()
    if page_action == "delete":
        # Delete pages (and their history/drafts via CASCADE)
        conn.execute("DELETE FROM pages WHERE category_id=? AND is_home=0", (cat_id,))
    elif page_action == "move" and target_category_id:
        conn.execute("UPDATE pages SET category_id=? WHERE category_id=?",
                     (target_category_id, cat_id))
    else:
        conn.execute("UPDATE pages SET category_id=NULL WHERE category_id=?", (cat_id,))
    conn.execute("UPDATE categories SET parent_id=NULL WHERE parent_id=?", (cat_id,))
    conn.execute("DELETE FROM categories WHERE id=?", (cat_id,))
    conn.commit()
    conn.close()


def count_pages_in_category(cat_id):
    conn = get_db()
    cnt = conn.execute("SELECT COUNT(*) FROM pages WHERE category_id=? AND is_home=0",
                       (cat_id,)).fetchone()[0]
    conn.close()
    return cnt


def list_categories():
    conn = get_db()
    rows = conn.execute("SELECT * FROM categories ORDER BY sort_order, name").fetchall()
    conn.close()
    return rows


def get_category_tree():
    """Return nested category structure with pages."""
    cats = list_categories()
    conn = get_db()
    pages = conn.execute("SELECT * FROM pages WHERE is_home=0 ORDER BY sort_order, title").fetchall()
    conn.close()

    cat_map = {}
    for c in cats:
        cat_map[c["id"]] = {"id": c["id"], "name": c["name"], "parent_id": c["parent_id"], "children": [], "pages": []}

    for p in pages:
        if p["category_id"] and p["category_id"] in cat_map:
            cat_map[p["category_id"]]["pages"].append(dict(p))

    roots = []
    uncategorized_pages = [dict(p) for p in pages if not p["category_id"]]

    for cid, cat in cat_map.items():
        if cat["parent_id"] and cat["parent_id"] in cat_map:
            cat_map[cat["parent_id"]]["children"].append(cat)
        else:
            roots.append(cat)

    return roots, uncategorized_pages


def update_pages_sort_order(ordered_ids):
    """Assign sort_order 0, 1, 2, … to pages given in the specified order."""
    conn = get_db()
    for i, page_id in enumerate(ordered_ids):
        conn.execute("UPDATE pages SET sort_order=? WHERE id=?", (i, page_id))
    conn.commit()
    conn.close()


def update_categories_sort_order(ordered_ids):
    """Assign sort_order 0, 1, 2, … to categories given in the specified order."""
    conn = get_db()
    for i, cat_id in enumerate(ordered_ids):
        conn.execute("UPDATE categories SET sort_order=? WHERE id=?", (i, cat_id))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
#  Page helpers
# ---------------------------------------------------------------------------
def create_page(title, slug, content="", category_id=None, user_id=None):
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    # New pages go to the bottom: pick max sort_order + 1 within the same category scope
    max_row = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) FROM pages WHERE is_home=0 AND category_id IS ?"
        if category_id is None else
        "SELECT COALESCE(MAX(sort_order), -1) FROM pages WHERE is_home=0 AND category_id=?",
        (category_id,),
    ).fetchone()
    next_sort = (max_row[0] + 1) if max_row else 0
    cur.execute(
        "INSERT INTO pages (title, slug, content, category_id, last_edited_by, last_edited_at, sort_order) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (title, slug, content, category_id, user_id, now, next_sort),
    )
    page_id = cur.lastrowid
    if user_id:
        cur.execute(
            "INSERT INTO page_history (page_id, title, content, edited_by, edit_message) "
            "VALUES (?, ?, ?, ?, ?)",
            (page_id, title, content, user_id, "Page created"),
        )
    conn.commit()
    conn.close()
    return page_id


def get_page(page_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM pages WHERE id=?", (page_id,)).fetchone()
    conn.close()
    return row


def get_page_by_slug(slug):
    conn = get_db()
    row = conn.execute("SELECT * FROM pages WHERE slug=?", (slug,)).fetchone()
    conn.close()
    return row


def get_home_page():
    conn = get_db()
    row = conn.execute("SELECT * FROM pages WHERE is_home=1").fetchone()
    conn.close()
    return row


def update_page(page_id, title, content, user_id, edit_message=""):
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE pages SET title=?, content=?, last_edited_by=?, last_edited_at=? WHERE id=?",
        (title, content, user_id, now, page_id),
    )
    conn.execute(
        "INSERT INTO page_history (page_id, title, content, edited_by, edit_message) "
        "VALUES (?, ?, ?, ?, ?)",
        (page_id, title, content, user_id, edit_message),
    )
    conn.commit()
    conn.close()


def update_page_title(page_id, title, user_id):
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    page = conn.execute("SELECT title, content FROM pages WHERE id=?", (page_id,)).fetchone()
    conn.execute("UPDATE pages SET title=?, last_edited_by=?, last_edited_at=? WHERE id=?",
                 (title, user_id, now, page_id))
    if page:
        conn.execute(
            "INSERT INTO page_history (page_id, title, content, edited_by, edit_message) "
            "VALUES (?, ?, ?, ?, ?)",
            (page_id, title, page["content"], user_id, f"Title changed from '{page['title']}' to '{title}'"),
        )
    conn.commit()
    conn.close()


def update_page_category(page_id, category_id):
    conn = get_db()
    conn.execute("UPDATE pages SET category_id=? WHERE id=?", (category_id, page_id))
    conn.commit()
    conn.close()


def delete_page(page_id):
    conn = get_db()
    conn.execute("DELETE FROM pages WHERE id=? AND is_home=0", (page_id,))
    conn.commit()
    conn.close()


def get_page_history(page_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT ph.*, COALESCE(u.username, 'deleted user') AS username FROM page_history ph "
        "LEFT JOIN users u ON ph.edited_by=u.id "
        "WHERE ph.page_id=? ORDER BY ph.created_at DESC, ph.id DESC",
        (page_id,),
    ).fetchall()
    conn.close()
    return rows


def get_history_entry(entry_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM page_history WHERE id=?", (entry_id,)).fetchone()
    conn.close()
    return row


_UPLOAD_REF_RE = re.compile(r'/static/uploads/([^\s)"\']+)')


def get_all_referenced_image_filenames():
    """Return a set of upload filenames referenced in any page content or history.

    Scans both the live ``pages.content`` and every ``page_history.content``
    entry so that images still present in the revision history are never
    removed.
    """
    conn = get_db()
    filenames = set()
    for row in conn.execute("SELECT content FROM pages").fetchall():
        filenames.update(_UPLOAD_REF_RE.findall(row["content"]))
    for row in conn.execute("SELECT content FROM page_history").fetchall():
        filenames.update(_UPLOAD_REF_RE.findall(row["content"]))
    conn.close()
    return filenames


# ---------------------------------------------------------------------------
#  Draft helpers
# ---------------------------------------------------------------------------
def save_draft(page_id, user_id, title, content):
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO drafts (page_id, user_id, title, content, updated_at) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(page_id, user_id) DO UPDATE SET title=?, content=?, updated_at=?",
        (page_id, user_id, title, content, now, title, content, now),
    )
    conn.commit()
    conn.close()


def get_draft(page_id, user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM drafts WHERE page_id=? AND user_id=?", (page_id, user_id)
    ).fetchone()
    conn.close()
    return row


def get_drafts_for_page(page_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT d.*, u.username FROM drafts d JOIN users u ON d.user_id=u.id WHERE d.page_id=?",
        (page_id,),
    ).fetchall()
    conn.close()
    return rows


def delete_draft(page_id, user_id):
    conn = get_db()
    conn.execute("DELETE FROM drafts WHERE page_id=? AND user_id=?", (page_id, user_id))
    conn.commit()
    conn.close()


def transfer_draft(page_id, from_user, to_user):
    """Transfer a draft from one user to another (atomic).

    Deletes the target user's existing draft (if any) and transfers the
    source user's draft.
    """
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("DELETE FROM drafts WHERE page_id=? AND user_id=?", (page_id, to_user))
    conn.execute(
        "UPDATE drafts SET user_id=?, updated_at=? WHERE page_id=? AND user_id=?",
        (to_user, now, page_id, from_user),
    )
    conn.commit()
    conn.close()


def get_user_draft_count(user_id):
    """Return number of pending drafts for a user across all pages."""
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM drafts WHERE user_id=?", (user_id,)
    ).fetchone()
    conn.close()
    return row["cnt"] if row else 0


def list_user_drafts(user_id):
    """Return all drafts belonging to a user, with page info."""
    conn = get_db()
    rows = conn.execute(
        "SELECT d.*, p.title AS page_title, p.slug AS page_slug "
        "FROM drafts d JOIN pages p ON d.page_id = p.id "
        "WHERE d.user_id=? ORDER BY d.updated_at DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    return rows


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
}


def update_site_settings(**kwargs):
    for k in kwargs:
        if k not in _ALLOWED_SETTINGS_COLUMNS:
            raise ValueError(f"Invalid column: {k}")
    conn = get_db()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values())
    conn.execute(f"UPDATE site_settings SET {sets} WHERE id=1", vals)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
#  Announcement helpers
# ---------------------------------------------------------------------------
def create_announcement(content, color, text_size, visibility, expires_at, user_id):
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    cur.execute(
        "INSERT INTO announcements (content, color, text_size, visibility, expires_at, is_active, created_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
        (content, color, text_size, visibility, expires_at or None, user_id, now),
    )
    ann_id = cur.lastrowid
    conn.commit()
    conn.close()
    return ann_id


def get_announcement(ann_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM announcements WHERE id=?", (ann_id,)).fetchone()
    conn.close()
    return row


def list_announcements():
    conn = get_db()
    rows = conn.execute(
        "SELECT a.*, COALESCE(u.username, 'deleted user') AS creator_name "
        "FROM announcements a LEFT JOIN users u ON a.created_by=u.id "
        "ORDER BY a.created_at DESC"
    ).fetchall()
    conn.close()
    return rows


_ALLOWED_ANN_COLUMNS = {"content", "color", "text_size", "visibility", "expires_at", "is_active"}


def update_announcement(ann_id, **kwargs):
    for k in kwargs:
        if k not in _ALLOWED_ANN_COLUMNS:
            raise ValueError(f"Invalid column: {k}")
    conn = get_db()
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [ann_id]
    conn.execute(f"UPDATE announcements SET {sets} WHERE id=?", vals)
    conn.commit()
    conn.close()


def delete_announcement(ann_id):
    conn = get_db()
    conn.execute("DELETE FROM announcements WHERE id=?", (ann_id,))
    conn.commit()
    conn.close()


def get_active_announcements(is_logged_in):
    """Return active, non-expired announcements matching the user's login state."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    logged_in_int = 1 if is_logged_in else 0
    rows = conn.execute(
        "SELECT * FROM announcements "
        "WHERE is_active=1 "
        "  AND (expires_at IS NULL OR expires_at > ?) "
        "  AND (visibility='both' "
        "       OR (visibility='logged_in' AND ?=1) "
        "       OR (visibility='logged_out' AND ?=0)) "
        "ORDER BY created_at DESC",
        (now, logged_in_int, logged_in_int),
    ).fetchall()
    conn.close()
    return rows
