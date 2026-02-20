"""
BananaWiki – Database layer (SQLite)
"""

import sqlite3
import os
import string
import random
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
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
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
        created_by  INTEGER NOT NULL REFERENCES users(id),
        created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
        expires_at  TEXT    NOT NULL,
        used_by     INTEGER REFERENCES users(id),
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
        last_edited_by INTEGER REFERENCES users(id),
        last_edited_at TEXT,
        created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS page_history (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        page_id     INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
        title       TEXT    NOT NULL,
        content     TEXT    NOT NULL,
        edited_by   INTEGER NOT NULL REFERENCES users(id),
        edit_message TEXT   NOT NULL DEFAULT '',
        created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS drafts (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        page_id     INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
        user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
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
        setup_done  INTEGER NOT NULL DEFAULT 0
    );

    INSERT OR IGNORE INTO site_settings (id) VALUES (1);
    """)

    # Ensure home page exists
    home = cur.execute("SELECT id FROM pages WHERE is_home=1").fetchone()
    if not home:
        cur.execute(
            "INSERT INTO pages (title, slug, content, is_home) VALUES (?, ?, ?, 1)",
            ("Home", "home", "# Welcome to your Wiki\n\nEdit this page to get started."),
        )

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
#  User helpers
# ---------------------------------------------------------------------------
def create_user(username, hashed_pw, role="user", invite_code=None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (username, password, role, invite_code) VALUES (?, ?, ?, ?)",
        (username, hashed_pw, role, invite_code),
    )
    user_id = cur.lastrowid
    conn.commit()
    conn.close()
    return user_id


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


_ALLOWED_USER_COLUMNS = {"username", "password", "role", "suspended"}


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
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))
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
    q += " ORDER BY id"
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
    code = "".join(random.choices(chars, k=4)) + "-" + "".join(random.choices(chars, k=4))
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
        "SELECT * FROM invite_codes WHERE code=? AND used_by IS NULL AND deleted=0",
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
    conn.execute(
        "UPDATE invite_codes SET used_by=?, used_at=? WHERE code=?",
        (user_id, now, code),
    )
    conn.commit()
    conn.close()


def delete_invite_code(code_id):
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    conn.execute("UPDATE invite_codes SET deleted=1, deleted_at=? WHERE id=?", (now, code_id))
    conn.commit()
    conn.close()


def list_invite_codes(active_only=True):
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    if active_only:
        rows = conn.execute(
            "SELECT ic.*, u.username AS creator_name FROM invite_codes ic "
            "JOIN users u ON ic.created_by=u.id "
            "WHERE ic.used_by IS NULL AND ic.deleted=0 AND ic.expires_at > ? "
            "ORDER BY ic.created_at DESC",
            (now,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT ic.*, u.username AS creator_name, u2.username AS used_by_name "
            "FROM invite_codes ic "
            "JOIN users u ON ic.created_by=u.id "
            "LEFT JOIN users u2 ON ic.used_by=u2.id "
            "ORDER BY ic.created_at DESC"
        ).fetchall()
    conn.close()
    return rows


def list_expired_codes():
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    rows = conn.execute(
        "SELECT ic.*, u.username AS creator_name, u2.username AS used_by_name "
        "FROM invite_codes ic "
        "JOIN users u ON ic.created_by=u.id "
        "LEFT JOIN users u2 ON ic.used_by=u2.id "
        "WHERE ic.used_by IS NOT NULL OR ic.deleted=1 OR ic.expires_at <= ? "
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


def delete_category(cat_id):
    conn = get_db()
    conn.execute("UPDATE pages SET category_id=NULL WHERE category_id=?", (cat_id,))
    conn.execute("UPDATE categories SET parent_id=NULL WHERE parent_id=?", (cat_id,))
    conn.execute("DELETE FROM categories WHERE id=?", (cat_id,))
    conn.commit()
    conn.close()


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


# ---------------------------------------------------------------------------
#  Page helpers
# ---------------------------------------------------------------------------
def create_page(title, slug, content="", category_id=None, user_id=None):
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    cur.execute(
        "INSERT INTO pages (title, slug, content, category_id, last_edited_by, last_edited_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (title, slug, content, category_id, user_id, now),
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
    conn.execute("UPDATE pages SET title=?, last_edited_by=?, last_edited_at=? WHERE id=?",
                 (title, user_id, now, page_id))
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
        "SELECT ph.*, u.username FROM page_history ph "
        "JOIN users u ON ph.edited_by=u.id "
        "WHERE ph.page_id=? ORDER BY ph.created_at DESC",
        (page_id,),
    ).fetchall()
    conn.close()
    return rows


def get_history_entry(entry_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM page_history WHERE id=?", (entry_id,)).fetchone()
    conn.close()
    return row


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
    """Transfer a draft from one user to another."""
    conn = get_db()
    draft = conn.execute(
        "SELECT * FROM drafts WHERE page_id=? AND user_id=?", (page_id, from_user)
    ).fetchone()
    if draft:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("DELETE FROM drafts WHERE page_id=? AND user_id=?", (page_id, to_user))
        conn.execute(
            "UPDATE drafts SET user_id=?, updated_at=? WHERE page_id=? AND user_id=?",
            (to_user, now, page_id, from_user),
        )
        conn.commit()
    conn.close()


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
    "text_color", "sidebar_color", "bg_color", "setup_done",
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
