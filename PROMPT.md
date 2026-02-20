# BananaWiki — Complete Rebuild Prompt

Build a self-contained, private wiki application called **BananaWiki** using Python and Flask. The application is a full-featured, invite-only wiki system with a dark professional theme, role-based access control, Markdown-based page editing with live preview, image uploads, page history, auto-save drafts, and a comprehensive admin panel. Below is every detail you need to rebuild it from scratch.

---

## Technology Stack

- **Python 3** with **Flask 3.1.0** as the web framework
- **Werkzeug 3.1.3** for password hashing (`generate_password_hash` / `check_password_hash`) and `secure_filename`
- **markdown 3.7** for rendering Markdown to HTML (extensions: `tables`, `fenced_code`, `toc`, `nl2br`)
- **bleach 6.2.0** for sanitizing rendered HTML to prevent XSS
- **Pillow 12.1.1** for validating uploaded images (open + verify to ensure they are genuine images)
- **SQLite3** (built-in) as the database, using WAL journal mode and foreign key enforcement
- No ORM — use raw SQL queries via `sqlite3`
- Jinja2 for templating (Flask built-in)
- Vanilla JavaScript (no frontend frameworks)
- CSS custom properties for theming

Create a `requirements.txt` with:
```
Flask==3.1.0
Werkzeug==3.1.3
markdown==3.7
bleach==6.2.0
Pillow==12.1.1
```

---

## Project Structure

```
BananaWiki/
├── app/
│   ├── templates/
│   │   ├── base.html
│   │   ├── account/
│   │   │   └── settings.html
│   │   ├── auth/
│   │   │   ├── login.html
│   │   │   ├── signup.html
│   │   │   └── setup.html
│   │   ├── wiki/
│   │   │   ├── page.html
│   │   │   ├── edit.html
│   │   │   ├── create_page.html
│   │   │   ├── history.html
│   │   │   ├── history_entry.html
│   │   │   ├── _category.html
│   │   │   ├── 404.html
│   │   │   └── 403.html
│   │   └── admin/
│   │       ├── users.html
│   │       ├── codes.html
│   │       ├── codes_expired.html
│   │       └── settings.html
│   └── static/
│       ├── css/
│       │   └── style.css
│       ├── js/
│       │   └── main.js
│       └── uploads/
│           └── .gitkeep
├── app.py
├── config.py
├── db.py
├── wiki_logger.py
├── requirements.txt
├── tests/
│   └── test_fixes.py
├── .gitignore
└── README.md
```

The Flask app is initialized in `app.py` with:
```python
app = Flask(__name__, template_folder="app/templates", static_folder="app/static")
```

---

## Configuration (`config.py`)

Create a configuration module with the following settings:

| Setting | Default | Description |
|---|---|---|
| `PORT` | `8080` | Server port |
| `USE_PUBLIC_IP` | `True` | Bind to `0.0.0.0` for network access |
| `USE_LOCAL_IP` | `True` | Also listen on localhost |
| `CUSTOM_DOMAIN` | `None` | Optional custom domain |
| `HOST` | `"0.0.0.0"` if `USE_PUBLIC_IP` else `"127.0.0.1"` | Derived binding address |
| `SECRET_KEY` | Auto-generated | Persistent secret key |
| `DATABASE_PATH` | `instance/bananawiki.db` | SQLite database path |
| `UPLOAD_FOLDER` | `app/static/uploads` | Image upload directory |
| `MAX_CONTENT_LENGTH` | `16 * 1024 * 1024` (16 MB) | Max upload size |
| `ALLOWED_EXTENSIONS` | `{"png", "jpg", "jpeg", "gif", "webp"}` | Allowed image types (NO SVG — security risk due to embedded scripts) |
| `LOGGING_ENABLED` | `True` | Enable/disable logging |
| `LOG_FILE` | `logs/bananawiki.log` | Log file path |
| `PAGE_HISTORY_ENABLED` | `False` | Toggle page history viewer and revert functionality |
| `INVITE_CODE_EXPIRY_HOURS` | `48` | Hours before invite codes expire |

### Secret Key Management

The secret key should follow this priority:
1. Check for `SECRET_KEY` environment variable
2. Check for a key stored in `instance/.secret_key` file
3. Generate a new key using `secrets.token_hex(32)`, save it to the file with `0o600` permissions

---

## Database Schema (`db.py`)

Use SQLite with `PRAGMA journal_mode=WAL` and `PRAGMA foreign_keys=ON`. All connections must set `row_factory = sqlite3.Row`.

### Tables

#### `users`
```sql
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
```

#### `invite_codes`
```sql
CREATE TABLE IF NOT EXISTS invite_codes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT    NOT NULL UNIQUE,
    created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    expires_at  TEXT    NOT NULL,
    used_by     INTEGER REFERENCES users(id),
    used_at     TEXT,
    deleted     INTEGER NOT NULL DEFAULT 0,
    deleted_at  TEXT
);
```

#### `categories`
```sql
CREATE TABLE IF NOT EXISTS categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    parent_id   INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
```

#### `pages`
```sql
CREATE TABLE IF NOT EXISTS pages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    slug        TEXT    NOT NULL UNIQUE,
    content     TEXT    NOT NULL DEFAULT '',
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    is_home     INTEGER NOT NULL DEFAULT 0,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    last_edited_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    last_edited_at TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
```

#### `page_history`
```sql
CREATE TABLE IF NOT EXISTS page_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id     INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    title       TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    edited_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    edit_message TEXT   NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
```

#### `drafts`
```sql
CREATE TABLE IF NOT EXISTS drafts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id     INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       TEXT    NOT NULL DEFAULT '',
    content     TEXT    NOT NULL DEFAULT '',
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(page_id, user_id)
);
```

#### `site_settings`
```sql
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
```

### Database Initialization

On `init_db()`, create all tables and ensure a home page exists:
```python
home = cur.execute("SELECT id FROM pages WHERE is_home=1").fetchone()
if not home:
    cur.execute(
        "INSERT INTO pages (title, slug, content, is_home) VALUES (?, ?, ?, 1)",
        ("Home", "home", "# Welcome to your Wiki\n\nEdit this page to get started."),
    )
```

### Database Helper Functions

Implement these functions in `db.py`:

**Users:**
- `create_user(username, hashed_pw, role="user", invite_code=None)` → returns user_id
- `get_user_by_id(user_id)` → row or None
- `get_user_by_username(username)` → row or None (use `COLLATE NOCASE`)
- `update_user(user_id, **kwargs)` — validate columns against a whitelist: `{"username", "password", "role", "suspended"}`
- `delete_user(user_id)` — first clear `invite_codes.used_by` references (`UPDATE invite_codes SET used_by=NULL WHERE used_by=?`), then delete the user. This is needed because the `used_by` FK has no `ON DELETE SET NULL`.
- `list_users(role_filter=None, status_filter=None)` — supports filtering by role and by status ("active"/"suspended")
- `count_admins()` — counts non-suspended admins

**Invite Codes:**
- `generate_invite_code(created_by)` → code string (format: `XXXX-XXXX`, uppercase alphanumeric, 4+4 characters)
- `validate_invite_code(code)` → row or None. Must check: `used_by IS NULL AND used_at IS NULL AND deleted=0`, and verify expiry using UTC datetime comparison
- `use_invite_code(code, user_id)` → bool. Atomic UPDATE with WHERE clause: `used_by IS NULL AND used_at IS NULL AND deleted=0`. Returns `True` if `rowcount > 0`
- `delete_invite_code(code_id)` — soft delete: `UPDATE SET deleted=1, deleted_at=<now>`
- `list_invite_codes(active_only=True)` — with joins for creator name
- `list_expired_codes()` — shows codes that are used, deleted, or expired (includes `WHERE used_by IS NOT NULL OR used_at IS NOT NULL OR deleted=1 OR expires_at <= <now>`)

**Categories:**
- `create_category(name, parent_id=None)` → cat_id
- `get_category(cat_id)` → row or None
- `update_category(cat_id, name)`
- `delete_category(cat_id)` — unlink pages (`SET category_id=NULL`), unlink child categories (`SET parent_id=NULL`), then delete
- `list_categories()` — ordered by `sort_order, name`
- `get_category_tree()` → `(roots, uncategorized_pages)`. Build nested structure of categories with their pages. Exclude the home page from the tree. Returns a list of root category dicts (each with `children` and `pages` lists) and a list of uncategorized page dicts.

**Pages:**
- `create_page(title, slug, content, category_id, user_id)` — also creates a page_history entry with message "Page created"
- `get_page(page_id)`, `get_page_by_slug(slug)`, `get_home_page()`
- `update_page(page_id, title, content, user_id, edit_message)` — updates the page and inserts a history entry
- `update_page_title(page_id, title, user_id)` — updates only the title, creates a history entry with message `"Title changed from '<old>' to '<new>'"`
- `update_page_category(page_id, category_id)`
- `delete_page(page_id)` — only deletes if `is_home=0`
- `get_page_history(page_id)` — join with users for username, ordered by `created_at DESC`. Show "deleted user" for null editors.
- `get_history_entry(entry_id)`

**Drafts:**
- `save_draft(page_id, user_id, title, content)` — upsert using `ON CONFLICT(page_id, user_id) DO UPDATE`
- `get_draft(page_id, user_id)` → row or None
- `get_drafts_for_page(page_id)` — join with users for username
- `delete_draft(page_id, user_id)`
- `transfer_draft(page_id, from_user, to_user)` — atomic: delete existing draft of `to_user`, then update `from_user`'s draft to belong to `to_user`

**Site Settings:**
- `get_site_settings()` → row
- `update_site_settings(**kwargs)` — validate columns against whitelist: `{"site_name", "primary_color", "secondary_color", "accent_color", "text_color", "sidebar_color", "bg_color", "setup_done"}`

---

## Logging Module (`wiki_logger.py`)

Create a logging module with:
- `get_logger()` — singleton that creates a logger named `"bananawiki"` with file handler (to `LOG_FILE`) and stream handler
- `log_request(request, user)` — logs HTTP requests: IP, method, path, username, user-agent
- `log_action(action, request, user, **details)` — logs specific actions with automatic redaction of sensitive fields: `{"password", "current_password", "new_password", "confirm_password", "secret", "token", "session"}` (replaced with `"***"`)

---

## Main Application (`app.py`)

### Initialization

```python
app = Flask(__name__, template_folder="app/templates", static_folder="app/static")
app.secret_key = config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH
```

At module load time, call `db.init_db()` and `get_logger()`.

### HTML Sanitization

Configure bleach with an extended set of allowed tags:
```python
ALLOWED_TAGS = list(bleach.ALLOWED_TAGS) + [
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "br", "hr", "pre", "code",
    "table", "thead", "tbody", "tr", "th", "td",
    "ul", "ol", "li", "dl", "dt", "dd",
    "img", "figure", "figcaption",
    "div", "span", "section",
    "del", "ins", "sup", "sub",
]
ALLOWED_ATTRS = {
    "*": ["class", "id"],
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title", "width", "height"],
    "td": ["align"],
    "th": ["align"],
}
```

### Helper Functions

- **`render_markdown(text)`** — Convert markdown to sanitized HTML using `markdown.markdown()` with extensions `["tables", "fenced_code", "toc", "nl2br"]`, then sanitize with `bleach.clean()`.
- **`slugify(text)`** — Lowercase, strip non-word chars (except hyphens and spaces), replace spaces/underscores with hyphens, strip leading/trailing hyphens, default to `"page"` if empty.
- **`allowed_file(filename)`** — Check extension against `config.ALLOWED_EXTENSIONS`.
- **`_is_valid_hex_color(value)`** — Validate 7-character hex color format like `#aabbcc` using regex `r"#[0-9a-fA-F]{6}"`.
- **`get_current_user()`** — Read `user_id` from session, return user row or None.
- **`time_ago(dt_str)`** — Convert ISO datetime string to human-readable relative time with correct pluralization: "just now", "1 minute ago", "5 minutes ago", "1 hour ago", "3 hours ago", "1 day ago", "7 days ago". Also handle future dates ("in a moment", "in X minute(s)", "in X hour(s)", "in X day(s)"). Return "never" for None, "unknown" for parse errors.

### Authentication Decorators

Implement three decorators:

1. **`@login_required`** — Check `session["user_id"]` exists, user exists in DB, user is not suspended. Redirect to login with flash message if any check fails. Clear session if user not found or suspended.

2. **`@editor_required`** — Check user has role `"editor"` or `"admin"`. Flash error and redirect to home if not.

3. **`@admin_required`** — Check user has role `"admin"`. Flash error and redirect to home if not.

### Timing Attack Prevention

Pre-compute a dummy hash at module load:
```python
_DUMMY_HASH = generate_password_hash("dummy-constant-time-check")
```

On login, if the username doesn't exist, still call `check_password_hash(_DUMMY_HASH, password)` before returning failure. This prevents timing-based username enumeration.

### Context Processor

Inject into all templates:
```python
@app.context_processor
def inject_globals():
    settings = db.get_site_settings()
    user = get_current_user()
    return {
        "current_user": user,
        "settings": settings,
        "time_ago": time_ago,
        "page_history_enabled": config.PAGE_HISTORY_ENABLED,
    }
```

### Before-Request Hook

On every request:
1. Check if setup is done. If not, redirect to `/setup` (except for the `setup` and `static` endpoints).
2. Log the request using `log_request()`.

---

## Routes

### First-Boot Setup — `GET/POST /setup`

- If setup is already done, redirect to home.
- On POST: validate username (3–50 chars), password (≥6 chars, must match confirm), create admin user, mark `setup_done=1`.
- Re-check `setup_done` before creating user to prevent race conditions.
- Handle `sqlite3.IntegrityError` for duplicate usernames.
- Render `auth/setup.html` (standalone page, not extending base.html).

### Authentication

**`GET/POST /login`**
- If setup not done, redirect to setup.
- On POST: check username exists, check password hash, check not suspended.
- Use dummy hash check when user not found (timing attack prevention).
- Set `session["user_id"]` on success, redirect to home.
- Render `auth/login.html` (standalone page).

**`GET/POST /signup`**
- Requires valid invite code (format `XXXX-XXXX`, uppercase alphanumeric).
- Validate: username (3–50 chars), password (≥6 chars, match confirm), invite code valid and not expired.
- Check username availability, then create user. Atomically use the invite code. If code usage fails (race condition), delete the created user and show error.
- Render `auth/signup.html` (standalone page).

**`GET /logout`**
- Clear session, flash "logged out", redirect to login.

### Account Settings — `GET/POST /account`

Requires `@login_required`. Three actions via hidden `action` form field:

1. **`change_username`** — Verify current password, validate new username (3–50 chars), check availability (case-insensitive), update. Handle `IntegrityError` for race conditions.
2. **`change_password`** — Verify current password, validate new password (≥6 chars, match confirm), update with hashed password.
3. **`delete_account`** — Verify password, check not last admin, delete user, clear session, redirect to login.

The settings page also shows: role badge, member-since time, and links to admin pages (for admin users).

### Wiki Pages

**`GET /` (Home)**
- `@login_required`
- Fetch home page, render Markdown, build category tree for sidebar, get editor info.

**`GET /page/<slug>`**
- `@login_required`
- Fetch page by slug, 404 if not found, render Markdown, show editor info, pass `all_categories` for the move modal.

**`GET /page/<slug>/history`**
- `@login_required`, abort 404 if `PAGE_HISTORY_ENABLED` is False.
- Show revision history table with date, editor, summary, and view/revert buttons.

**`GET /page/<slug>/history/<int:entry_id>`**
- `@login_required`, abort 404 if `PAGE_HISTORY_ENABLED` is False.
- View a specific historical revision rendered as HTML.
- Validate that the entry belongs to the page.

**`POST /page/<slug>/revert/<int:entry_id>`**
- `@login_required`, `@editor_required`, abort 404 if `PAGE_HISTORY_ENABLED` is False.
- Revert page to the historical revision's title and content.
- Create a new history entry with message `"Reverted to version from <timestamp>"`.

### Page Editing

**`GET/POST /page/<slug>/edit`**
- `@login_required`, `@editor_required`
- On GET: show editor with current page content or draft content (if draft exists). Show notices about other users' drafts.
- On POST: save title + content + edit_message, delete the user's draft, redirect. If home page, redirect to `/`.
- The editor includes: toolbar (bold, italic, strikethrough, H1–H3, bullet/numbered list, code block, link, blockquote, horizontal rule, attach image), drop zone for images, live preview pane, edit summary field.

**`POST /page/<slug>/edit/title`**
- `@login_required`, `@editor_required`
- Update only the title (max 200 chars). If home page, redirect to `/`.

### Page/Category CRUD

**`POST /create-page`** (also `GET` for the form)
- `@login_required`, `@editor_required`
- Validate title (required, max 200 chars), optional category.
- Generate slug from title. Ensure unique slug by appending `-1`, `-2`, etc. if needed.
- Preserve form data on validation errors.

**`POST /page/<slug>/delete`**
- `@login_required`, `@editor_required`
- Cannot delete the home page. Redirect to home after delete.

**`POST /page/<slug>/move`**
- `@login_required`, `@editor_required`
- Move page to a different category (or uncategorized).

**`POST /category/create`**
- `@login_required`, `@editor_required`
- Name required, max 100 chars, optional parent category. Redirect to referrer.

**`POST /category/<int:cat_id>/edit`**
- `@login_required`, `@editor_required`
- Rename category (max 100 chars). Redirect to referrer.

**`POST /category/<int:cat_id>/delete`**
- `@login_required`, `@editor_required`
- Delete category (pages become uncategorized, child categories become root). Redirect to referrer.

### API Endpoints

All API endpoints return `{"ok": true}` on success or `{"error": "description"}` on failure (with appropriate HTTP status codes: 400, 404, etc.).

**`POST /api/preview`** — `@login_required`
- Accept JSON `{"content": "..."}`, return `{"html": "..."}`
- Render Markdown to sanitized HTML.

**`POST /api/draft/save`** — `@login_required`, `@editor_required`
- Accept JSON `{"page_id": int, "title": str, "content": str}`
- Save/update draft. Return `{"ok": true}`.

**`GET /api/draft/load/<int:page_id>`** — `@login_required`, `@editor_required`
- Return draft content or `{"title": null, "content": null}`.

**`GET /api/draft/others/<int:page_id>`** — `@login_required`, `@editor_required`
- Return list of other users' drafts: `[{"username": ..., "user_id": ..., "updated_at": ...}]`.

**`POST /api/draft/transfer`** — `@login_required`, `@editor_required`
- Accept JSON `{"page_id": int, "from_user_id": int}`
- Cannot transfer from yourself. Transfer draft atomically.

**`POST /api/draft/delete`** — `@login_required`, `@editor_required`
- Accept JSON `{"page_id": int}`. Delete user's own draft.

**`POST /api/upload`** — `@login_required`, `@editor_required`
- Accept file upload via `multipart/form-data` (field name: `file`).
- Validate: file exists, allowed extension, genuine image (Pillow `Image.open` + `verify`).
- Save with UUID hex filename (e.g., `abc123def456.png`).
- Return `{"url": "/static/uploads/filename.ext", "filename": "filename.ext"}`.

**`POST /api/upload/delete`** — `@login_required`, `@editor_required`
- Accept JSON `{"filename": "..."}`. Use `secure_filename()` and validate non-empty result.
- Use `os.path.isfile()` (not `os.path.exists()`) before deleting.

### Admin — User Management

**`GET /admin/users`** — `@admin_required`
- List all users with filter tabs: All, Admins, Editors, Users, Active, Suspended.
- Inline create-user form with fields: username, password, confirm, role.

**`POST /admin/users/<int:user_id>/edit`** — `@admin_required`
- Actions via hidden `action` field:
  - `change_username` — validate 3–50 chars, check availability, handle IntegrityError
  - `change_password` — validate ≥6 chars, match confirm
  - `change_role` — validate role, cannot change own role, cannot demote last admin
  - `suspend` — cannot suspend self, cannot suspend last admin
  - `unsuspend`
  - `delete` — cannot delete self (from admin panel), cannot delete last admin

**`POST /admin/users/create`** — `@admin_required`
- Create user with specified role. Validate same as signup.

### Admin — Invite Codes

**`GET /admin/codes`** — `@admin_required`
- Show active (unused, not deleted, not expired) codes.

**`GET /admin/codes/expired`** — `@admin_required`
- Show used/expired/deleted codes with status badges.

**`POST /admin/codes/generate`** — `@admin_required`
- Generate new invite code, flash the code to the user.

**`POST /admin/codes/<int:code_id>/delete`** — `@admin_required`
- Soft-delete the code.

### Admin — Site Settings

**`GET/POST /admin/settings`** — `@admin_required`
- Configure: site name (max 100 chars, defaults to "BananaWiki"), and 6 theme colors.
- Validate all colors as proper 7-char hex format (`#aabbcc`).

### Error Handlers

- **404** — Render `wiki/404.html` with sidebar (category tree).
- **403** — Render `wiki/403.html` with sidebar.
- **413** — Flash "File too large. Maximum upload size is 16 MB." and redirect to referrer.

---

## Input Validation Rules

| Field | Min Length | Max Length | Notes |
|---|---|---|---|
| Username | 3 | 50 | Case-insensitive uniqueness |
| Password | 6 | — | Must match confirmation |
| Page title | 1 (required) | 200 | — |
| Category name | 1 (required) | 100 | — |
| Site name | — | 100 | Defaults to "BananaWiki" if empty |
| Colors | — | — | Must match `#[0-9a-fA-F]{6}` |
| Invite code | — | — | Format `XXXX-XXXX`, uppercase alphanumeric |

---

## Frontend

### Base Template (`base.html`)

All authenticated pages extend `base.html`. It provides:

1. **Topbar** (sticky, `z-index: 100`):
   - Left: hamburger toggle button (hidden on desktop, visible on mobile), site name as link to home
   - Right: username with role in parentheses, "Account" button, "Logout" button

2. **Sidebar** (left side, 250px default width, resizable 180–500px):
   - Header: "Explorer" label with "+ Folder" and "+ Page" buttons (editor/admin only)
   - Navigation: "Home" link, categories (recursive with `_category.html` partial), uncategorized pages section
   - Active page highlighted with left border (`2px solid var(--primary)`)
   - Category inline edit/delete controls (visible on hover)

3. **Sidebar Resize Handle** — 4px wide draggable handle between sidebar and content

4. **Sidebar Overlay** — semi-transparent overlay for mobile (z-index 49)

5. **Content Area** — flex-grow, max-width 900px, with flash messages

6. **Create Category Modal** — form with name and optional parent category

7. **CSS custom properties** set from site_settings:
   ```css
   :root {
       --primary: {{ settings.primary_color }};
       --secondary: {{ settings.secondary_color }};
       --accent: {{ settings.accent_color }};
       --text: {{ settings.text_color }};
       --sidebar: {{ settings.sidebar_color }};
       --bg: {{ settings.bg_color }};
   }
   ```

### Auth Pages (`login.html`, `signup.html`, `setup.html`)

Standalone pages (don't extend base.html). Centered auth box with:
- Site name heading, subtitle
- Flash messages
- Form fields with proper `autocomplete` attributes
- Link to alternate auth page (login ↔ signup)

The signup form has a pattern for invite code input: `[A-Za-z0-9]{4}-[A-Za-z0-9]{4}` with `text-transform: uppercase`.

### Page View (`page.html`)

- Page header with title, edit title button (modal), edit/move/delete buttons (editor/admin only, non-home pages)
- Rendered wiki content
- "Last edit by X, Y ago" footer with optional "View history" link (when `page_history_enabled`)
- Title edit modal and move-to-category modal

### Page Editor (`edit.html`)

Split-pane layout:
- **Left pane**: Markdown toolbar + drop zone + textarea
- **Right pane**: Live preview (updates on 400ms debounce)
- Draft notices (own draft, other users' drafts with transfer buttons)
- Edit summary field
- "Commit Changes" and "Cancel" buttons

Toolbar buttons: Bold, Italic, Strikethrough | H1, H2, H3 | Bullet List, Numbered List, Code Block, Link, Blockquote, Horizontal Rule | Attach Image

The `insertFormat(before, after)` function wraps selected text. `insertLine(prefix)` prepends to the current line.

### Category Partial (`_category.html`)

Recursive template for nested categories:
- Category name with inline edit/delete controls (shown on hover)
- Child pages as navigation links
- Nested children categories with indentation (`padding-left: depth * 0.75rem`)

### Admin Pages

**Users** — Table with ID, Username, Role (badge), Status, Invite Code, Created, Actions. Each row has an "Edit" button that toggles an expandable detail row (hidden by default) containing inline forms for: rename, set password, change role, suspend/unsuspend, delete.

**Codes** — Two tabs (Active / Expired). Active shows code, creator, created time, expiry, delete button. Expired shows code, creator, times, status badge (Used/Deleted/Expired), used-by name.

**Settings** — Site name input + 6 color pickers (each with paired text input, synced via `oninput`/`onchange`).

### CSS Theme

Dark professional theme using CSS custom properties. Key design elements:

- **Font**: System font stack (`-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif`)
- **Default colors**: primary `#7c8dc6`, secondary `#151520`, accent `#6e8aca`, text `#b8bcc8`, sidebar `#111118`, bg `#0d0d14`
- **Buttons**: Primary (colored bg, dark text), outline (transparent bg, border), danger (red `#c45c6a`)
- **Flash messages**: 4 types with colored borders/backgrounds: success (green), error (red), warning (amber), info (blue)
- **Badges**: Color-coded per role: admin (red), editor (blue), user (green), suspended (amber)
- **Editor**: Monospace font (`SFMono-Regular, Consolas, Liberation Mono, Menlo`), focus border highlight
- **Responsive**: At 768px breakpoint: hamburger menu, sidebar slides in from left (`left: -280px` to `left: 0`), single-column editor, hidden username in topbar

### JavaScript (`main.js`)

1. **Flash auto-dismiss** — Fade out after 5 seconds, remove after 300ms transition

2. **Sidebar toggle** — Mobile hamburger opens/closes sidebar with focus management:
   - Store last focused element before opening
   - Move focus into sidebar on open
   - Restore focus on close
   - Click overlay to close

3. **Sidebar resize** — Mousedown on handle starts resize, mousemove updates width (180–500px range), mouseup ends resize. Set `cursor: col-resize` and `user-select: none` during drag.

4. **Autosave (`initAutosave(pageId)`)** — Debounced (1500ms delay after last input) save to `/api/draft/save` on title/content input. Shows "Draft saved" indicator for 2 seconds, or "Save error" for 3 seconds on failure. Polls `/api/draft/others/<pageId>` every 10 seconds to detect other users editing — if found, displays a warning notice with each user's name and a "Transfer" button per draft.

5. **Draft management** — `transferDraft(pageId, fromUserId)` with confirmation prompt, `deleteDraft(pageId)` — both reload page after.

6. **Image upload (`initImageUpload(contentEl)`)** — Drag-and-drop on drop zone and textarea. File input via "Attach Image" button. Uploads via `FormData` to `/api/upload`. Inserts Markdown image syntax `![filename](url)` at cursor position. Dispatches `input` event for live preview update.

---

## Security Requirements

1. **Password hashing** — Use Werkzeug's `generate_password_hash` / `check_password_hash`
2. **Timing attack prevention** — Dummy hash check for non-existent usernames on login
3. **XSS prevention** — Bleach sanitization on all rendered Markdown
4. **Image validation** — Pillow verify to reject non-image files with image extensions
5. **No SVG uploads** — Explicitly disallowed due to embedded script risk
6. **Secure filenames** — UUID-based naming for uploads (`uuid.uuid4().hex`)
7. **File deletion safety** — `secure_filename()` validation + `os.path.isfile()` check (not `os.path.exists()`)
8. **SQL injection prevention** — Parameterized queries throughout
9. **Foreign key constraints** — Enforced via PRAGMA
10. **Column whitelists** — `update_user` and `update_site_settings` validate column names against hardcoded sets
11. **Race condition handling**:
    - Setup: re-check `setup_done` before creating admin
    - Signup: atomic invite code usage, rollback user creation on failure
    - Username changes: wrap in try/except `IntegrityError`
12. **Admin self-protection**:
    - Cannot change own role
    - Cannot suspend self
    - Cannot delete self from admin panel
    - Cannot demote/suspend/delete last admin
13. **Sensitive field redaction** in logs
14. **Session management** — Secret key persistence, session clearing on logout/suspension/deletion

---

## Testing (`tests/test_fixes.py`)

Use **pytest** with isolated temporary databases:

```python
@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(config, "DATABASE_PATH", db_path)
    monkeypatch.setattr(config, "LOGGING_ENABLED", False)
    import db as db_mod
    db_mod.init_db()
    yield db_path
```

Fixtures for `client` (Flask test client), `admin_user` (creates admin + marks setup done), and `logged_in_admin` (posts login).

Write tests covering the key features, security rules, and edge cases described above.

---

## `.gitignore`

```
__pycache__/
*.py[cod]
*.so
*.egg-info/
dist/
build/
*.egg
.env
instance/
logs/
app/static/uploads/*
!app/static/uploads/.gitkeep
venv/
.venv/
*.db
.pytest_cache/
```

---

## Running the Application

```bash
pip install -r requirements.txt
python app.py
```

The app initializes the database and starts on port 8080. On first visit, the user is redirected to `/setup` to create the initial admin account.
