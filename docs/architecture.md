# Architecture Overview

This document explains how BananaWiki is structured and how the main pieces fit together.

## Contents

- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Entry points](#entry-points)
- [app.py — routes and request handling](#apppy--routes-and-request-handling)
- [db/ — database layer](#db--database-layer)
- [helpers/ — utility functions](#helpers--utility-functions)
- [config.py — configuration](#configpy--configuration)
- [sync.py — Telegram backup](#syncpy--telegram-backup)
- [wiki_logger.py — logging](#wiki_loggerpy--logging)
- [Templates](#templates)
- [Static assets](#static-assets)
- [Request lifecycle](#request-lifecycle)
- [Security model](#security-model)
- [Database schema](#database-schema)

---

## Tech stack

| Layer | Technology |
|---|---|
| Web framework | [Flask 3.1](https://flask.palletsprojects.com/) |
| WSGI server | [Gunicorn](https://gunicorn.org/) |
| Database | SQLite in WAL mode |
| Markdown rendering | [Python-Markdown](https://python-markdown.github.io/) |
| HTML sanitization | [Bleach](https://bleach.readthedocs.io/) |
| Image validation | [Pillow](https://pillow.readthedocs.io/) |
| CSRF protection | [Flask-WTF](https://flask-wtf.readthedocs.io/) |
| Frontend | Vanilla HTML, CSS, and JavaScript |

---

## Project structure

```
BananaWiki/
├── app.py                  # Flask application entry point
├── wsgi.py                 # WSGI entry point for Gunicorn
├── config.py               # Configuration settings
├── gunicorn.conf.py        # Gunicorn server configuration
├── sync.py                 # Telegram backup module
├── wiki_logger.py          # Logging module
├── reset_password.py       # CLI password-reset tool
├── setup.py                # One-shot setup wizard
│
├── db/                     # Database layer (SQLite)
│   ├── __init__.py         # Re-exports all public symbols
│   ├── _connection.py      # get_db() — connection factory
│   ├── _schema.py          # init_db() — table creation & migrations
│   ├── _users.py           # User CRUD, accessibility, login attempts
│   ├── _invites.py         # Invite code management
│   ├── _categories.py      # Category CRUD, tree, ordering
│   ├── _pages.py           # Page CRUD, history, search, attachments
│   ├── _drafts.py          # Draft management
│   ├── _settings.py        # Site settings
│   ├── _announcements.py   # Announcements and contributions
│   ├── _migration.py       # Site data import/export
│   ├── _profiles.py        # User profiles, contribution heatmap
│   ├── _chats.py           # Direct messaging
│   ├── _groups.py          # Group chat
│   └── _audit.py           # Role history, custom tags, contributions
│
├── helpers/                # Shared utility functions
│   ├── __init__.py         # Re-exports all public symbols
│   ├── _constants.py       # Shared constants (ALLOWED_TAGS, ROLE_LABELS, etc.)
│   ├── _rate_limiting.py   # Login and general rate limiting
│   ├── _markdown.py        # Markdown rendering, video embedding
│   ├── _diff.py            # Diff computation utilities
│   ├── _text.py            # Text processing (slugify)
│   ├── _validation.py      # File, input, and URL validation
│   ├── _auth.py            # Authentication decorators and helpers
│   └── _time.py            # Timezone and datetime formatting
│
├── routes/                 # Route handlers grouped by feature
│   ├── __init__.py         # register_all_routes()
│   ├── auth.py             # Login, signup, logout, setup, lockdown
│   ├── wiki.py             # Wiki pages and categories
│   ├── users.py            # User accounts and profiles
│   ├── admin.py            # Admin panel
│   ├── chat.py             # Direct messaging
│   ├── groups.py           # Group chat
│   ├── api.py              # JSON API (search, preview, drafts, etc.)
│   ├── uploads.py          # File uploads/downloads, easter egg
│   └── errors.py           # HTTP error handlers
│
├── app/
│   ├── templates/          # Jinja2 templates
│   └── static/             # CSS, JS, uploads, favicons
│
├── tests/                  # Test suite
├── docs/                   # Documentation
└── requirements.txt        # Python dependencies
```

### Importing modules

Both `db` and `helpers` are packages that re-export all public symbols from their sub-modules via `__init__.py`. Existing import patterns continue to work:

```python
import db
db.get_user_by_id(uid)          # Works — re-exported from db._users

from helpers import login_required, render_markdown
```

For internal cross-references within a package, sub-modules use relative imports:

```python
# Inside db/_pages.py
from ._connection import get_db

# Inside helpers/_diff.py
from ._markdown import render_markdown
```

---

## Entry points

| File | Purpose |
|---|---|
| `wsgi.py` | WSGI entry point. Imports `app` from `app.py` (which calls `db.init_db()` at module level) and hands the app to Gunicorn. |
| `app.py` | The Flask application — creates the `app` object, registers all routes, and contains all middleware. |
| `gunicorn.conf.py` | Reads `HOST`, `PORT`, and `PROXY_MODE` from `config.py` and sets Gunicorn's bind address and worker count. |

---

## app.py — routes and request handling

`app.py` is organized into clearly separated sections with comment banners. Reading it top-to-bottom:

1. **Imports & app creation** — Flask app, secret key, session config, SSL/proxy setup, and CSRF initialization.
2. **Re-exports** — Symbols from `helpers` and `routes.uploads` are re-exported for backward compatibility with the test suite.
3. **Template filters** — `render_md` Jinja2 filter.
4. **Context processors** — `inject_globals()` runs before every template render and injects `current_user`, `settings`, `active_announcements`, `all_categories`, and the `time_ago`/`format_datetime` helpers.
5. **Request hooks** — `before_request_hook` redirects to `/setup` until setup is complete, enforces lockdown mode (kicking out non-admin users), validates the per-user session token when session limiting is enabled, and applies the global rate limit. `set_security_headers` adds security headers to every response.
6. **Route registration** — Calls `register_all_routes(app)` from the `routes` package.
7. **Initialisation** — `db.init_db()` and `get_logger()` run at import time.

### Decorators and permissions

| Decorator | Requirement |
|---|---|
| `@login_required` | User must be logged in and not suspended. |
| `@editor_required` | Role must be `editor`, `admin`, or `protected_admin`. |
| `@admin_required` | Role must be `admin` or `protected_admin`. |

### Draft system

When an editor opens a page for editing, any unsaved content is stored as a draft (`/api/draft/save`). Drafts auto-save every few seconds from the browser. On page load, the editor checks for the user's own draft and loads it automatically.

If another user has an open draft on the same page, a conflict warning is shown. The current editor can transfer that draft to themselves (merging) or ignore it. When a page is committed, all drafts for that page are deleted and `cleanup_unused_uploads()` runs to remove any orphaned image files.

### Upload pipeline

1. The browser POSTs a file to `/api/upload`.
2. Pillow validates the file is a genuine image (not just a renamed binary).
3. The file is saved with a UUID filename to `app/static/uploads/`.
4. The JSON response includes the URL, which the editor inserts as a Markdown image tag.
5. When a page is committed or a draft is deleted, `cleanup_unused_uploads()` scans all page content and history for `/static/uploads/<filename>` references and deletes any files that no longer appear anywhere.

---

## db/ — database layer

The `db` package is the only code that talks to SQLite. All other modules call functions here — nothing else runs raw SQL. The package is split into domain-specific sub-modules:

| Sub-module | Responsibility |
|---|---|
| `_connection.py` | `get_db()` — opens a connection with WAL mode and foreign keys enabled. |
| `_schema.py` | `init_db()` — creates all tables if they don't exist, then runs column-level migrations. |
| `_users.py` | User CRUD, accessibility preferences, login attempt tracking, editor access. |
| `_invites.py` | Invite code generation, validation, and lifecycle. |
| `_categories.py` | Category CRUD, hierarchical tree, sort ordering. |
| `_pages.py` | Page CRUD, history, search, sequential navigation, attachments. |
| `_drafts.py` | Draft save/load/transfer/delete. |
| `_settings.py` | Site settings (single-row table). |
| `_announcements.py` | Announcements, user contributions. |
| `_migration.py` | Full site data import and export. |
| `_profiles.py` | User profiles, contribution heatmap data. |
| `_chats.py` | Direct messaging between users. |
| `_groups.py` | Group chat rooms. |
| `_audit.py` | Role history, custom tags, contribution management. |

The `__init__.py` re-exports every public symbol so that `import db` and `db.function_name()` work as before.

### Schema migrations

Migrations are simple: `init_db()` reads `PRAGMA table_info(table_name)` and adds missing columns with `ALTER TABLE ... ADD COLUMN`. There is no migration framework — the list of `if "column_name" not in cols` checks at the bottom of `init_db()` serves as the migration log.

---

## helpers/ — utility functions

The `helpers` package contains shared utility functions, constants, and decorators used across route handlers and the application core. The package is split by concern:

| Sub-module | Responsibility |
|---|---|
| `_constants.py` | Shared constants: `ALLOWED_TAGS`, `ALLOWED_ATTRS`, `_DUMMY_HASH`, `ROLE_LABELS`, `_USERNAME_RE`. |
| `_rate_limiting.py` | Per-IP login throttling (backed by DB) and in-memory general rate limiting (`_RL_STORE`), plus the `@rate_limit` decorator. |
| `_markdown.py` | `render_markdown()` — Markdown to sanitised HTML conversion, plus YouTube/Vimeo video embedding. |
| `_diff.py` | `compute_char_diff()`, `compute_diff_html()`, `compute_formatted_diff_html()` — word-level diff utilities for page history. |
| `_text.py` | `slugify()` — URL-safe slug generation. |
| `_validation.py` | File extension validation (`allowed_file`, `allowed_attachment`), input validation (`_is_valid_hex_color`, `_is_valid_username`), and URL safety (`_safe_referrer`). |
| `_auth.py` | `get_current_user()`, `@login_required`, `@editor_required`, `@admin_required`, `editor_has_category_access()`. |
| `_time.py` | `get_site_timezone()`, `time_ago()`, `format_datetime()`, `format_datetime_local_input()`. |

The `__init__.py` re-exports every public symbol so that `from helpers import login_required` works as before.

---

## config.py — configuration

A plain Python file. All settings are module-level variables. The secret key is loaded from `instance/.secret_key` (auto-generated on first run) or the `SECRET_KEY` environment variable. See [configuration.md](configuration.md) for a full reference.

---

## sync.py — Telegram backup

When `SYNC = True`, a background thread watches for change events and sends a zip archive of runtime data to a Telegram chat.

**Debounce logic:** After a change is reported via `notify_change()`, the thread waits 60 seconds for more changes before sending. If changes keep arriving continuously, a backup is forced after 10 minutes. This prevents backup floods during heavy editing sessions.

**File uploads:** Images are sent as separate Telegram messages (not in the zip) via `notify_file_upload()`. Their message IDs are saved in `sync_upload_msgs.json` so they can be deleted when the corresponding file is removed.

**What's in the zip:** Every backup zip always contains the database, `config.py`, the secret key, log files, and a `backup_manifest.json` listing the changes that triggered the backup and any files excluded due to size limits. The only reason a file is excluded is if including it would push the archive over Telegram's 50 MB limit.

---

## wiki_logger.py — logging

Two public functions:

- `log_request(request, user)` — logs every HTTP request: IP, method, path, user, and user agent.
- `log_action(action, request, user, **details)` — logs named actions with key-value detail pairs. Sensitive fields (`password`, `token`, etc.) are automatically redacted. Control characters are stripped to prevent log injection.

Logging writes to `logs/bananawiki.log` (controlled by `LOGGING_LEVEL` config) and always echoes to stdout.

---

## Templates

Templates live in `app/templates/` and use Jinja2.

| Path | Contents |
|---|---|
| `base.html` | Main layout: sidebar with category tree, header, flash messages, announcement bar. All page templates extend this. |
| `_announcements_bar.html` | Announcement banner partial — included in `base.html` and auth pages. |
| `auth/` | `login.html`, `signup.html`, `setup.html`, `lockdown.html`, `session_conflict.html` |
| `wiki/` | `page.html`, `edit.html`, `create_page.html`, `history.html`, `history_entry.html`, `announcement.html`, `easter_egg.html`, `_category.html` (recursive sidebar partial), `403.html`, `404.html`, `429.html`, `500.html` |
| `account/settings.html` | Account settings page |
| `admin/` | `users.html`, `codes.html`, `codes_expired.html`, `settings.html`, `announcements.html`, `audit.html`, `editor_access.html`, `migration.html`, `chats.html`, `chat_view.html`, `groups.html`, `group_view.html` |
| `chats/` | `list.html` (DM conversation list), `new.html` (start new DM), `chat.html` (conversation view) |
| `groups/` | `list.html` (group list), `new.html` (create group), `join.html` (join via invite code), `chat.html` (group conversation view) |
| `users/` | `list.html` (People directory), `profile.html` (individual user profile with contribution heatmap) |

Template variables injected on every request (via `inject_globals`):

| Variable | Value |
|---|---|
| `current_user` | Logged-in user row, or `None` |
| `settings` | Site settings row (name, colors, timezone, etc.) |
| `active_announcements` | List of active, non-expired announcement rows visible to the current user |
| `all_categories` | Flat list of all categories (used for move/assign dropdowns) |
| `time_ago` | Helper function: converts a UTC ISO timestamp to a relative string like "3 hours ago" |
| `format_datetime` | Helper function: converts a UTC ISO timestamp to a formatted local time string |
| `page_history_enabled` | Boolean from `config.PAGE_HISTORY_ENABLED` |
| `user_accessibility` | Dict of the logged-in user's accessibility preferences (font scale, contrast, sidebar width, custom colors), or `{}` for unauthenticated requests |
| `sidebar_people` | List of up to 19 users with published profiles (used for the sidebar People widget); empty list when no one is logged in |
| `current_user_profile` | The logged-in user's `user_profiles` row (or `None` if they have no profile), used in the topbar and account settings to show avatar/profile status without an extra DB query |

---

## Static assets

| Path | Contents |
|---|---|
| `app/static/css/style.css` | All styles — layout, sidebar, editor, theme variables, responsive rules, accessibility panel and contrast modes |
| `app/static/js/main.js` | All client-side JS — sidebar toggle, drag-to-resize, Markdown toolbar, draft autosave, announcement navigation, accessibility panel (`initAccessibility`, `initEditorResize`), Konami code easter egg |
| `app/static/uploads/` | User-uploaded images (runtime, gitignored) |
| `app/static/favicons/` | Preset and custom favicon files |

---

## Request lifecycle

For a typical page view (`GET /page/<slug>`):

1. Gunicorn receives the request and calls the Flask WSGI app.
2. `before_request_hook` runs: checks setup, enforces the global rate limit, logs the request.
3. `@login_required` checks the session and redirects to `/login` if not authenticated.
4. The route function calls `db.get_page_by_slug(slug)`, renders the Markdown, and passes data to `render_template`.
5. Jinja2 renders the template; `inject_globals` provides `current_user`, `settings`, etc.
6. `set_security_headers` adds security headers to the response.
7. The response is returned to Gunicorn and sent to the client.

---

## Security model

| Mechanism | Where |
|---|---|
| Password hashing | `werkzeug.security.generate_password_hash` / `check_password_hash` |
| CSRF protection | Flask-WTF, applied to all POST forms and AJAX requests |
| HTML sanitization | Bleach with an explicit tag/attribute allowlist after every Markdown render |
| Session fixation prevention | `session.clear()` before setting `user_id` on login |
| Login rate limiting | `login_attempts` SQLite table, 5 attempts per 60 s per IP, shared across workers |
| General rate limiting | In-memory `_RL_STORE`, 300 req/60 s global + per-route decorators |
| Secure file uploads | `secure_filename()` + UUID rename + Pillow verify + path traversal check |
| Security headers | `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Content-Security-Policy` on every response |
| Invite-only signup | Valid, unexpired invite code required; codes are single-use with a race condition guard |
| `is_superuser` flag | Per-account database flag (set by the operator directly in SQLite) that prevents username changes, password changes, and account deletion even by an admin — used to protect the primary admin account from being accidentally modified through the UI |

---

## Database schema

| Table | Purpose |
|---|---|
| `users` | User accounts: username, hashed password, role, suspended flag, last login, session token, accessibility preferences (JSON), chat disabled flag, `is_superuser` flag (operator-set; blocks username/password changes and account deletion) |
| `invite_codes` | Single-use time-limited signup tokens |
| `categories` | Hierarchical category tree; `parent_id` is self-referencing; `sequential_nav` enables Prev/Next navigation for pages in the category |
| `pages` | Wiki pages: title, slug, content, category, home flag, last editor, `difficulty_tag` (predefined level or `'custom'`), `tag_custom_label`, `tag_custom_color` (used when `difficulty_tag='custom'`), `is_deindexed` (hidden from sidebar and search for regular users) |
| `page_history` | Every committed version of every page; never deleted |
| `drafts` | One in-progress draft per (page, user) pair |
| `site_settings` | Single-row table (id=1): site name, color palette, timezone, favicon, lockdown mode and message, session limit toggle, setup flag |
| `login_attempts` | Failed login records used for per-IP rate limiting across workers |
| `announcements` | Site-wide banner content, color, text size, visibility, expiry, active flag, not-removable flag, countdown toggle |
| `username_history` | Every username change (old name, new name, timestamp) per user |
| `editor_category_access` | Per-editor restricted-access flag (one row per editor with category restrictions enabled) |
| `editor_allowed_categories` | Category IDs an editor with restrictions is permitted to access |
| `page_attachments` | Files attached to a page: stored filename (UUID), original name, size, uploader, upload time |
| `user_profiles` | Optional public profile per user: `real_name`, `bio`, `avatar_filename`, `page_published` flag, `page_disabled_by_admin` flag |
| `chats` | Direct message conversations between two users (unique pair) |
| `chat_messages` | Messages in direct message conversations, with IP address tracking |
| `chat_attachments` | File attachments on direct messages: stored filename (UUID), original name, file size |
| `group_chats` | Group chat rooms: name, creator, invite code, global flag |
| `group_members` | Group membership with role (`owner`, `moderator`, `member`), timeout, and ban tracking |
| `group_messages` | Messages in group chats, with system message support and IP address tracking |
| `group_attachments` | File attachments on group messages: stored filename (UUID), original name, file size |
| `role_history` | Audit log of user role changes: old role, new role, who made the change, timestamp |
| `user_custom_tags` | Admin-managed custom tags per user: label, color, sort order |

All timestamps are stored as UTC ISO-8601 strings (`datetime.now(timezone.utc).isoformat()`). The `format_datetime()` helper converts them to the site's configured timezone for display.
