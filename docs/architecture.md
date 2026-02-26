# Architecture Overview

This document explains how BananaWiki is structured and how the main pieces fit together.

## Contents

- [Tech stack](#tech-stack)
- [Entry points](#entry-points)
- [app.py — routes and request handling](#apppy--routes-and-request-handling)
- [db.py — database layer](#dbpy--database-layer)
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

## Entry points

| File | Purpose |
|---|---|
| `wsgi.py` | WSGI entry point. Imports `app` from `app.py`, calls `db.init_db()`, and hands the app to Gunicorn. |
| `app.py` | The Flask application — creates the `app` object, registers all routes, and contains all middleware. |
| `gunicorn.conf.py` | Reads `HOST`, `PORT`, and `PROXY_MODE` from `config.py` and sets Gunicorn's bind address and worker count. |

---

## app.py — routes and request handling

`app.py` is organized into clearly separated sections with comment banners. Reading it top-to-bottom:

1. **Imports & app creation** — Flask app, secret key, session config, SSL/proxy setup, and CSRF initialization.
2. **Bleach allowlists** — `ALLOWED_TAGS` and `ALLOWED_ATTRS` define which HTML is permitted after Markdown rendering.
3. **Login rate limiting** — Per-IP login throttling backed by the `login_attempts` SQLite table so limits are shared across all Gunicorn workers.
4. **General rate limiting** — In-memory per-worker throttling via `_RL_STORE`. A global limit (300 req/60 s per IP) applies to all routes, plus per-route `@rate_limit` decorators on sensitive endpoints.
5. **Helpers** — `render_markdown()`, `slugify()`, `allowed_file()`, `time_ago()`, `format_datetime()`, and validation utilities used across routes.
6. **Decorators** — `@login_required`, `@editor_required`, `@admin_required` wrap route functions to enforce access control.
7. **Context processors** — `inject_globals()` runs before every template render and injects `current_user`, `settings`, `active_announcements`, `all_categories`, and the `time_ago`/`format_datetime` helpers.
8. **Request hooks** — `before_request_hook` redirects to `/setup` until setup is complete and applies the global rate limit. `set_security_headers` adds security headers to every response.
9. **Routes** — grouped by area:
   - `/setup`, `/login`, `/signup`, `/logout` — authentication
   - `/account` — account settings (username, password, delete account)
   - `/`, `/page/<slug>`, `/page/<slug>/history`, etc. — wiki page viewing and editing
   - `/create-page`, `/page/<slug>/delete`, `/page/<slug>/move` — page management
   - `/category/*` — category CRUD and reordering
   - `/api/preview`, `/api/draft/*`, `/api/upload`, `/api/upload/delete`, `/api/easter-egg/trigger` — internal JSON API
   - `/admin/users`, `/admin/codes`, `/admin/settings`, `/admin/announcements` — admin panel
   - `/announcements/<id>` — public full-content announcement page
   - `/easter-egg` — easter egg page

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

## db.py — database layer

`db.py` is the only file that talks to SQLite. All other modules call functions here — nothing else runs raw SQL.

- `get_db()` — opens a connection with WAL mode and foreign keys enabled.
- `init_db()` — called at startup. Creates all tables if they don't exist, then runs column-level migrations (ALTER TABLE ADD COLUMN) for new fields added in later versions. Also ensures a home page row exists.
- Helper functions are grouped by area: users, login attempts, invite codes, categories, pages, page history, drafts, site settings, announcements, audit log.

### Schema migrations

Migrations are simple: `init_db()` reads `PRAGMA table_info(table_name)` and adds missing columns with `ALTER TABLE ... ADD COLUMN`. There is no migration framework — the list of `if "column_name" not in cols` checks at the bottom of `init_db()` serves as the migration log.

---

## config.py — configuration

A plain Python file. All settings are module-level variables. The secret key is loaded from `instance/.secret_key` (auto-generated on first run) or the `SECRET_KEY` environment variable. See [configuration.md](configuration.md) for a full reference.

---

## sync.py — Telegram backup

When `SYNC = True`, a background thread watches for change events and sends a zip archive of runtime data to a Telegram chat.

**Debounce logic:** After a change is reported via `notify_change()`, the thread waits 60 seconds for more changes before sending. If changes keep arriving continuously, a backup is forced after 10 minutes. This prevents backup floods during heavy editing sessions.

**File uploads:** Images are sent as separate Telegram messages (not in the zip) via `notify_file_upload()`. Their message IDs are saved in `sync_upload_msgs.json` so they can be deleted when the corresponding file is removed.

**What's in the zip:** By default the zip contains only uploads. If `SYNC_INCLUDE_SENSITIVE = True`, the database, secret key, `config.py`, and logs are also included.

---

## wiki_logger.py — logging

Two public functions:

- `log_request(request, user)` — logs every HTTP request: IP, method, path, user, and user agent.
- `log_action(action, request, user, **details)` — logs named actions with key-value detail pairs. Sensitive fields (`password`, `token`, etc.) are automatically redacted. Control characters are stripped to prevent log injection.

Logging writes to `logs/bananawiki.log` (if `LOGGING_ENABLED = True`) and always echoes to stdout.

---

## Templates

Templates live in `app/templates/` and use Jinja2.

| Path | Contents |
|---|---|
| `base.html` | Main layout: sidebar with category tree, header, flash messages, announcement bar. All page templates extend this. |
| `_announcements_bar.html` | Announcement banner partial — included in `base.html` and auth pages. |
| `auth/` | `login.html`, `signup.html`, `setup.html`, `lockdown.html` |
| `wiki/` | `page.html`, `edit.html`, `create_page.html`, `history.html`, `history_entry.html`, `announcement.html`, `easter_egg.html`, `403.html`, `404.html`, `429.html`, `500.html` |
| `account/settings.html` | Account settings page |
| `admin/` | `users.html`, `codes.html`, `codes_expired.html`, `settings.html`, `announcements.html`, `audit.html` |

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

---

## Static assets

| Path | Contents |
|---|---|
| `app/static/css/style.css` | All styles — layout, sidebar, editor, theme variables, responsive rules |
| `app/static/js/main.js` | All client-side JS — sidebar toggle, drag-to-resize, Markdown toolbar, draft autosave, announcement navigation, Konami code easter egg |
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
| Password hashing | `werkzeug.security.generate_password_hash` (bcrypt) |
| CSRF protection | Flask-WTF, applied to all POST forms and AJAX requests |
| HTML sanitization | Bleach with an explicit tag/attribute allowlist after every Markdown render |
| Session fixation prevention | `session.clear()` before setting `user_id` on login |
| Login rate limiting | `login_attempts` SQLite table, 5 attempts per 60 s per IP, shared across workers |
| General rate limiting | In-memory `_RL_STORE`, 300 req/60 s global + per-route decorators |
| Secure file uploads | `secure_filename()` + UUID rename + Pillow verify + path traversal check |
| Security headers | `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Content-Security-Policy` on every response |
| Invite-only signup | Valid, unexpired invite code required; codes are single-use with a race condition guard |

---

## Database schema

| Table | Purpose |
|---|---|
| `users` | User accounts: username, hashed password, role, suspended flag, last login |
| `invite_codes` | Single-use time-limited signup tokens |
| `categories` | Hierarchical category tree; `parent_id` is self-referencing |
| `pages` | Wiki pages: title, slug, content, category, home flag, last editor |
| `page_history` | Every committed version of every page; never deleted |
| `drafts` | One in-progress draft per (page, user) pair |
| `site_settings` | Single-row table (id=1): site name, color palette, timezone, favicon, setup flag |
| `login_attempts` | Failed login records used for per-IP rate limiting across workers |
| `announcements` | Site-wide banner content, color, visibility, expiry, active flag |
| `username_history` | Every username change (old name, new name, timestamp) per user |

All timestamps are stored as UTC ISO-8601 strings (`datetime.now(timezone.utc).isoformat()`). The `format_datetime()` helper converts them to the site's configured timezone for display.
