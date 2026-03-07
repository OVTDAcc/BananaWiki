# BananaWiki – GitHub Copilot Instructions

## Project overview

BananaWiki is a self-hosted wiki application built with **Flask 3.1** and **SQLite**. It is a private, lightweight knowledge-base platform with no external database or cloud dependencies. The application supports Markdown editing, hierarchical page organization, user roles, direct messaging, group chats, a badge system, Telegram backups, and rich admin tooling.

---

## Tech stack

| Layer | Technology |
|---|---|
| Language | Python 3.9+ |
| Web framework | Flask 3.1 |
| WSGI server | Gunicorn |
| Database | SQLite (WAL mode) via the standard `sqlite3` module |
| Markdown | Python-Markdown with `tables`, `fenced_code`, `toc`, `nl2br` extensions |
| HTML sanitisation | Bleach — every Markdown render passes through `ALLOWED_TAGS` / `ALLOWED_ATTRS` |
| Image validation | Pillow |
| CSRF protection | Flask-WTF (token on every form and AJAX call) |
| Frontend | Vanilla HTML + CSS + JavaScript (no build step, no framework) |

---

## Repository layout

```
BananaWiki/
├── app.py                  # Flask app factory — registers middleware, hooks, and blueprints
├── wsgi.py                 # Gunicorn WSGI entry point
├── config.py               # All configuration; edit this to customise an instance
├── sync.py                 # Telegram backup / sync module
├── wiki_logger.py          # Structured request and action logging
├── reset_password.py       # CLI tool for out-of-band password resets
├── setup.py                # One-shot server provisioning wizard
├── gunicorn.conf.py        # Gunicorn worker / bind settings
│
├── db/                     # Database layer — ALL database access goes here
│   ├── __init__.py         # Re-exports every public symbol from sub-modules
│   ├── _connection.py      # get_db() — shared SQLite connection factory
│   ├── _schema.py          # init_db() — CREATE TABLE + all ALTER TABLE migrations
│   ├── _users.py           # User CRUD, accessibility prefs, login attempts
│   ├── _invites.py         # Invite code generation and consumption
│   ├── _categories.py      # Category CRUD, tree building, drag-to-reorder
│   ├── _pages.py           # Page CRUD, history, search, attachments, difficulty tags
│   ├── _drafts.py          # Draft autosave
│   ├── _settings.py        # Site-wide settings (single row)
│   ├── _announcements.py   # Announcement banners and contribution tracking
│   ├── _migration.py       # Full-site ZIP export / import
│   ├── _profiles.py        # User profiles and contribution heatmap
│   ├── _chats.py           # Direct messaging between users
│   ├── _groups.py          # Group chats
│   ├── _badges.py          # Badge types, user awards, auto-trigger logic
│   ├── _reservations.py    # Page checkout / reservation system
│   ├── _permissions.py     # Custom per-user editor category permissions
│   └── _audit.py           # Role history, custom user tags
│
├── helpers/                # Pure utility functions (no Flask context required)
│   ├── __init__.py         # Re-exports all public symbols
│   ├── _constants.py       # ALLOWED_TAGS, ALLOWED_ATTRS, ROLE_LABELS, _USERNAME_RE
│   ├── _rate_limiting.py   # Login and general per-route rate limiting
│   ├── _markdown.py        # render_markdown(), video embedding
│   ├── _diff.py            # Diff computation for page history
│   ├── _text.py            # slugify()
│   ├── _validation.py      # allowed_file(), allowed_attachment(), hex color, username
│   ├── _auth.py            # login_required, editor_required, admin_required decorators
│   └── _time.py            # Timezone helpers, time_ago(), format_datetime()
│
├── routes/                 # Flask route handlers — one file per feature area
│   ├── __init__.py         # register_all_routes(app) — called from app.py
│   ├── auth.py             # /login, /logout, /signup, /setup, /lockdown
│   ├── wiki.py             # Wiki pages, categories, history, attachments
│   ├── users.py            # User accounts, profiles, badge notifications
│   ├── admin.py            # Admin panel — users, codes, settings, announcements
│   ├── chat.py             # Direct messaging routes
│   ├── groups.py           # Group chat routes
│   ├── api.py              # JSON API (search, Markdown preview, drafts, accessibility)
│   ├── uploads.py          # Image / attachment upload and download
│   └── errors.py           # 403, 404, 429, 500 error handlers
│
├── app/
│   ├── templates/          # Jinja2 templates
│   │   ├── base.html       # Base layout — sidebar, announcement bar, topbar
│   │   ├── auth/           # login, signup, setup, lockdown, session_conflict
│   │   ├── wiki/           # page, edit, create_page, history, history_entry
│   │   ├── admin/          # users, codes, settings, announcements, audit, badges, chats, groups
│   │   ├── account/        # settings
│   │   ├── users/          # profile, list, badge_notifications
│   │   ├── chats/          # chat, list, new
│   │   └── groups/         # chat, list, new, join
│   └── static/
│       ├── css/style.css   # All styles — "Industrial Theme" (steel/grey palette)
│       ├── js/main.js      # All client-side JS — editor, sidebar, drafts, etc.
│       ├── favicons/       # Eight preset banana-colour favicons
│       └── uploads/        # Runtime user uploads (gitignored)
│
├── tests/                  # pytest test suite
│   ├── conftest.py         # Shared fixtures: isolated_db, client, admin_user, etc.
│   └── test_*.py           # Feature-specific test files
│
└── docs/                   # Markdown documentation
    ├── architecture.md
    ├── features.md
    ├── configuration.md
    ├── deployment.md
    ├── permissions.md
    ├── badge_system.md
    └── updates.md
```

---

## Architecture and key patterns

### Database access
- **Never** import `sqlite3` directly in route handlers or helpers. Use functions from the `db` package instead.
- All SQL lives inside the `db/` sub-modules. `db/__init__.py` re-exports every public function so callers can do `import db; db.get_page(slug)`.
- Schema changes (new columns, new tables) go into `db/_schema.py`. Add a migration block using the `ALTER TABLE … ADD COLUMN IF NOT EXISTS` pattern so the migration is safe to re-run on existing databases.
- Rows are returned as `sqlite3.Row` objects; access columns by name: `row["column_name"]`.

### Routes
- Route handlers are grouped in `routes/` by feature area. Register new routes inside the `register_*_routes(app)` function in the relevant file, then call that function from `routes/__init__.py`.
- Use the helper decorators from `helpers/_auth.py` to guard routes: `@login_required`, `@editor_required`, `@admin_required`.
- Apply `@rate_limit` from `helpers/_rate_limiting.py` to every mutation endpoint.

### User roles (four tiers, from least to most privileged)
| Role | Constant | Description |
|---|---|---|
| `user` | `"user"` | Read-only access |
| `editor` | `"editor"` | Read + create/edit/delete pages, manage categories |
| `admin` | `"admin"` | Everything + user management, settings, announcements |
| `protected_admin` | `"protected_admin"` | Same as admin, immune to modification by other admins |

### Authentication & sessions
- Session key `session["user_id"]` holds the logged-in user's ID.
- `get_current_user()` from `helpers/_auth.py` returns the full user row or `None`.
- Passwords are hashed with `werkzeug.security.generate_password_hash` / `check_password_hash`.
- Constant-time login checks use `_DUMMY_HASH` (defined in `helpers/_constants.py`) to prevent username enumeration.

### CSRF
- All forms must include `{{ csrf_token() }}` or use Flask-WTF's automatic injection.
- AJAX calls must send the CSRF token in the `X-CSRFToken` request header.

### Markdown & HTML sanitisation
- Always render user content with `render_markdown()` from `helpers/_markdown.py`.
- HTML output from `render_markdown()` is already sanitised by Bleach using `ALLOWED_TAGS` and `ALLOWED_ATTRS`.
- **Never** mark raw user content as `Markup` or bypass sanitisation.

### Flash messages
- Use consistent phrasing: success → `"X has been successfully …"`, permission errors → `"You do not have the required permissions to …"`, validation limits → `"X cannot exceed …"`.

### Text & slugs
- Use `slugify()` from `helpers/_text.py` to generate URL slugs from page titles.

### Logging
- Log user actions with `log_action(action, request, user=user, **kwargs)` from `wiki_logger`.
- Five log levels: `off`, `minimal`, `medium`, `verbose` (default), `debug`.

### Telegram sync
- After any significant data change, call `notify_change(change_type, priority)` from `sync.py`.
- Four priority levels: `IMMEDIATE`, `HIGH`, `NORMAL`, `LOW`.

---

## Configuration (`config.py`)

Key settings (edit `config.py` to customise):

| Setting | Default | Purpose |
|---|---|---|
| `PORT` | `5001` | Gunicorn bind port |
| `HOST` | `"127.0.0.1"` | Gunicorn bind address |
| `PROXY_MODE` | `True` | Enable `ProxyFix` for nginx/reverse proxy |
| `DATABASE_PATH` | `instance/bananawiki.db` | SQLite database file |
| `UPLOAD_FOLDER` | `app/static/uploads` | User image uploads |
| `ATTACHMENT_FOLDER` | `instance/attachments` | Page attachments (authenticated route) |
| `CHAT_ATTACHMENT_FOLDER` | `instance/chat_attachments` | Chat file attachments |
| `LOGGING_LEVEL` | `"verbose"` | Log verbosity |
| `PAGE_HISTORY_ENABLED` | `True` | Toggle page revision history |
| `INVITE_CODE_EXPIRY_HOURS` | `48` | Invite code lifetime |
| `SYNC` | `False` | Enable Telegram backup |

---

## Frontend conventions

- **No JavaScript framework or build step.** All JS is in `app/static/js/main.js`.
- **No CSS preprocessor.** All styles are in `app/static/css/style.css`.
- The **Industrial Theme** uses a steel/grey palette: thick borders (2–3 px), sharp corners (1–2 px radius), high contrast, bold typography (700 weight).
- Default theme colours (stored in `db/_schema.py`): primary `#6b7c9e`, background `#22222c`, sidebar `#8d99b5`, text `#e0e2e8`, card `#1c1c24`, deep `#0a0a0f`.
- Accessibility preferences (text size, contrast, spacing, colour overrides) are stored per-user in the `users` table and applied at render time.
- Unread badge notifications are displayed as red counters stored in `badge_notifications` and surfaced via `session['badge_notifications']`.

---

## Testing

- Tests live in `tests/` and use **pytest**.
- Run the full suite: `python -m pytest tests/ -v`
- Every test gets a fresh, isolated SQLite database via the `isolated_db` fixture in `conftest.py`.
- The `client` fixture provides a Flask test client with CSRF disabled.
- Standard fixtures: `admin_user`, `editor_user`, `regular_user`, `logged_in_admin`, `logged_in_editor`, `logged_in_user`.
- Prefer testing through the HTTP client rather than calling `db.*` functions directly.

---

## Development and deployment

| Command | What it does |
|---|---|
| `make dev` / `./dev.sh` | Start Flask dev server on port 5001 (venv auto-created) |
| `make start` / `./start.sh` | Start Gunicorn production server |
| `sudo make install` / `sudo ./install.sh` | Automated production install (systemd + nginx + SSL) |
| `./update.sh` | Safe update: backup → pull → deps → migrate → verify |
| `python -m pytest tests/ -v` | Run the full test suite |
| `python reset_password.py` | Reset a user password from the CLI |

On first visit the app redirects to a one-time setup wizard at `/setup` to create the first admin account.

---

## Security guidelines

- CSRF tokens are **required** on all forms and AJAX mutations.
- All Markdown output **must** go through Bleach sanitisation.
- SVG uploads are **intentionally blocked** (XSS risk).
- Rate limiting (`@rate_limit`) is **required** on all mutation routes.
- Use `werkzeug.security` for password hashing — never store plain-text passwords.
- Security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Content-Security-Policy`, `Referrer-Policy`) are set on every response in `app.py`.
- Do not write SQL strings using f-strings or `%` formatting — always use parameterised queries (`?` placeholders).
- Page attachments and chat attachments are stored outside `app/static/` and served through authenticated routes so they are not directly accessible by URL.
