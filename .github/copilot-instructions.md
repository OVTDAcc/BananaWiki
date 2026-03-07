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
├── app.py                  # Flask app factory — registers middleware, hooks, and routes
├── wsgi.py                 # Gunicorn WSGI entry point
├── config.py               # All configuration; edit this to customise an instance
├── sync.py                 # Telegram backup / sync module
├── wiki_logger.py          # Structured request and action logging
├── reset_password.py       # CLI tool for out-of-band password resets
├── setup.py                # One-shot server provisioning wizard
├── gunicorn.conf.py        # Gunicorn worker / bind settings
├── bananawiki.service      # systemd service file for production deployments
│
├── db/                     # Database layer — ALL database access goes here
│   ├── __init__.py         # Re-exports every public symbol from sub-modules
│   ├── _connection.py      # get_db() — shared SQLite connection factory
│   ├── _schema.py          # init_db() — CREATE TABLE + all ALTER TABLE migrations
│   ├── _users.py           # User CRUD, accessibility prefs, login attempts, generate_random_id()
│   ├── _invites.py         # Invite code generation and consumption
│   ├── _categories.py      # Category CRUD, tree building, drag-to-reorder, sequential nav
│   ├── _pages.py           # Page CRUD, history, search, attachments, difficulty tags, deindex
│   ├── _drafts.py          # Draft autosave
│   ├── _settings.py        # Site-wide settings (single row, id=1)
│   ├── _announcements.py   # Announcement banners and contribution tracking
│   ├── _migration.py       # Full-site ZIP export / import (three conflict modes)
│   ├── _profiles.py        # User profiles and contribution heatmap
│   ├── _chats.py           # Direct messaging — messages, attachments, unread counts, cleanup
│   ├── _groups.py          # Group chats — members, roles, timeouts, unread counts, cleanup
│   ├── _badges.py          # Badge types, user awards, auto-trigger logic
│   ├── _reservations.py    # Page checkout / reservation system with cooldowns
│   ├── _permissions.py     # Custom per-user permission set and category access rules
│   └── _audit.py           # Role history, custom user tags, contribution tracking
│
├── helpers/                # Pure utility functions (no Flask context required)
│   ├── __init__.py         # Re-exports all public symbols
│   ├── _constants.py       # ALLOWED_TAGS, ALLOWED_ATTRS, ROLE_LABELS, _USERNAME_RE, _DUMMY_HASH
│   ├── _rate_limiting.py   # Login and general per-route rate limiting
│   ├── _markdown.py        # render_markdown(text, embed_videos=False), video embedding
│   ├── _diff.py            # Diff computation for page history
│   ├── _text.py            # slugify()
│   ├── _validation.py      # allowed_file(), allowed_attachment(), _is_valid_hex_color(),
│   │                       #   _is_valid_username(), _safe_referrer()
│   ├── _auth.py            # login_required, editor_required, admin_required,
│   │                       #   get_current_user(), editor_has_category_access(),
│   │                       #   user_can_view_page(), user_can_view_category()
│   ├── _permissions.py     # PERMISSIONS dict, get_default_permissions(), get_all_permission_keys()
│   └── _time.py            # get_site_timezone(), time_ago(), format_datetime(),
│                           #   get_time_since_last_chat_cleanup(), get_time_until_next_chat_cleanup()
│
├── routes/                 # Flask route handlers — one file per feature area
│   ├── __init__.py         # register_all_routes(app) — called from app.py
│   ├── auth.py             # /login, /logout, /signup, /setup, /lockdown, /session-conflict
│   ├── wiki.py             # Wiki pages, categories, history, attachments, reservations
│   ├── users.py            # User accounts, profiles, badge notifications, user data export
│   ├── admin.py            # Admin panel — users, codes, settings, announcements, badges,
│   │                       #   editor access, migration, audit, chat/group moderation
│   ├── chat.py             # Direct messaging routes + chat cleanup scheduler
│   ├── groups.py           # Group chat routes (create, join, manage, moderate)
│   ├── api.py              # JSON API (search, Markdown preview, drafts, accessibility)
│   ├── uploads.py          # Image / attachment upload and download, cleanup_unused_uploads()
│   └── errors.py           # 403, 404, 429, 500 error handlers
│
├── scripts/
│   └── seed_badges.py      # CLI script to seed the database with default badge types
│
├── app/
│   ├── templates/          # Jinja2 templates
│   │   ├── base.html       # Base layout — sidebar, announcement bar, badge bar, topbar
│   │   ├── _announcements_bar.html   # Announcement banner partial
│   │   ├── _badge_notifications_bar.html  # Badge notification banner partial
│   │   ├── auth/           # login, signup, setup, lockdown, session_conflict
│   │   ├── wiki/           # page, edit, create_page, history, history_entry,
│   │   │                   #   announcement, easter_egg, _category (recursive sidebar partial),
│   │   │                   #   403, 404, 429, 500
│   │   ├── admin/          # users, codes, codes_expired, settings, announcements, audit,
│   │   │                   #   badges, edit_badge, chats, chat_view, groups, group_view,
│   │   │                   #   migration, editor_access, user_permissions
│   │   ├── account/        # settings (account settings + user data export)
│   │   ├── users/          # profile, list, badge_notifications
│   │   ├── chats/          # chat, list, new
│   │   └── groups/         # chat, list, new, join
│   └── static/
│       ├── css/style.css   # All styles — "Industrial Theme" (steel/grey palette)
│       ├── js/main.js      # All client-side JS — editor, sidebar, drafts, accessibility, etc.
│       ├── favicons/       # Eight preset banana-colour favicons (yellow, blue, green, …)
│       └── uploads/        # Runtime user uploads (gitignored)
│
├── tests/                  # pytest test suite
│   ├── conftest.py         # Shared fixtures: isolated_db, client, admin_user, etc.
│   ├── test_badges.py
│   ├── test_chats.py
│   ├── test_deindex.py
│   ├── test_edge_cases.py
│   ├── test_feature_drift_fixes.py
│   ├── test_fixes.py
│   ├── test_group_chats.py
│   ├── test_migration.py
│   ├── test_missing_coverage.py
│   ├── test_modularity.py
│   ├── test_networking.py
│   ├── test_page_reservations.py
│   ├── test_permissions.py
│   ├── test_production.py
│   ├── test_random_id.py
│   ├── test_rate_limiting.py
│   ├── test_sequential_nav.py
│   ├── test_sync.py
│   ├── test_synchronize.py
│   ├── test_user_profiles.py
│   └── test_video_embedding_and_session_limit.py
│
├── docs/                   # Markdown documentation
│   ├── architecture.md
│   ├── features.md
│   ├── configuration.md
│   ├── deployment.md
│   ├── permissions.md
│   ├── badge_system.md
│   ├── updates.md
│   └── random_id_migration.md  # Plan for migrating sequential IDs to random TEXT IDs
│
├── instance/               # Created at runtime — gitignored
│   ├── bananawiki.db       # SQLite database
│   ├── .secret_key         # Flask secret key (auto-generated on first run)
│   ├── attachments/        # Page file attachments (served via authenticated route)
│   └── chat_attachments/   # Chat file attachments (served via authenticated route)
│
└── logs/                   # Created at runtime — gitignored
    └── bananawiki.log      # Application log file
```

---

## Architecture and key patterns

### Database access
- **Never** import `sqlite3` directly in route handlers or helpers. Use functions from the `db` package instead.
- All SQL lives inside the `db/` sub-modules. `db/__init__.py` re-exports every public function so callers can do `import db; db.get_page(slug)`.
- Schema changes (new columns, new tables) go into `db/_schema.py`. Add a migration block using the pattern `if "column" not in cols: cur.execute("ALTER TABLE … ADD COLUMN …")` so migrations are safe to re-run on existing databases.
- Rows are returned as `sqlite3.Row` objects; access columns by name: `row["column_name"]`.

### User IDs
- **User IDs are random 8-character alphanumeric TEXT strings** (e.g. `abc12345`), generated with `_gen_user_id()` in `db/_users.py` — **not** integer autoincrement.
- Most other entities (pages, categories, groups, messages) still use `INTEGER PRIMARY KEY AUTOINCREMENT`. See `docs/random_id_migration.md` for the future plan.
- Use `db.generate_random_id(length=12)` when creating new entities that should use random TEXT IDs.

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
- **Session limit**: when `session_limit_enabled` is on, each login stores a `session_token` in the `users` table. Any session whose token does not match the stored one is invalidated and redirected to `/session-conflict`. This enforces one active session per user.
- **Lockdown mode**: when `lockdown_mode` is on in `site_settings`, all non-admin users are immediately kicked out and redirected to `/lockdown`. Both checks run in `app.py → before_request_hook()`.

### Custom permission system
- Fine-grained permissions are defined in `helpers/_permissions.py` as a `PERMISSIONS` dict, grouped into categories: `pages`, `categories`, `history`, `drafts`, `attachments`, `tags`, `profiles`, `chat`, `search`, `invites`.
- Each permission has a key (e.g. `"page.create"`), label, description, and default values for `editor` and `user` roles.
- Permissions for individual users are stored in the `user_permissions` table. Check with `db.has_permission(user, "permission.key")`.
- Category-level read/write access is stored in `user_category_access` and `user_allowed_categories`.
- Use `editor_has_category_access(user, category_id)` from `helpers/_auth.py` to check write access; `user_can_view_page(user, page)` and `user_can_view_category(user, category_id)` for read access.

### CSRF
- All forms must include `{{ csrf_token() }}` or use Flask-WTF's automatic injection.
- AJAX calls must send the CSRF token in the `X-CSRFToken` request header.

### Markdown & HTML sanitisation
- Always render user content with `render_markdown(text, embed_videos=False)` from `helpers/_markdown.py`.
- Pass `embed_videos=True` on wiki page views to auto-embed bare YouTube and Vimeo URLs as responsive iframes.
- HTML output from `render_markdown()` is already sanitised by Bleach using `ALLOWED_TAGS` and `ALLOWED_ATTRS`.
- **Never** mark raw user content as `Markup` or bypass sanitisation.
- In templates, use the `render_md` Jinja2 filter: `{{ page.content | render_md }}`.

### Template context processor
`app.py → inject_globals()` injects the following into **every** template automatically — you do not need to pass them from route handlers:
- `current_user` — logged-in user row or `None`
- `settings` — site settings row (site name, colors, flags)
- `time_ago`, `format_datetime`, `format_datetime_local_input` — formatting helpers
- `page_history_enabled` — from `config.PAGE_HISTORY_ENABLED`
- `all_categories` — full category list for sidebar rendering
- `active_announcements` — currently active announcement banners
- `user_accessibility` — per-user accessibility preferences dict
- `sidebar_people` — up to 19 published user profiles for the people widget
- `current_user_profile` — profile row for the logged-in user
- `utcnow` — current UTC ISO timestamp
- `time_since_last_chat_cleanup`, `time_until_next_chat_cleanup` — chat cleanup countdown callables

### Flash messages
- Use consistent phrasing: success → `"X has been successfully …"`, permission errors → `"You do not have the required permissions to …"`, validation limits → `"X cannot exceed …"`, required fields → `"X is required to continue"`.

### Text & slugs
- Use `slugify()` from `helpers/_text.py` to generate URL slugs from page titles.
- Use `_safe_referrer()` from `helpers/_validation.py` when you need to redirect back to the previous page — it validates the referrer is same-origin.

### Logging
- Log user actions with `log_action(action, request, user=user, **kwargs)` from `wiki_logger`.
- Five log levels: `off`, `minimal` (critical only), `medium` (critical + important auth/admin), `verbose` (all user actions, default), `debug` (all + HTTP requests).
- Action categories: `CRITICAL_ACTIONS`, `IMPORTANT_ACTIONS`, `USER_ACTIONS` (see `wiki_logger.py`).

### Telegram sync
- After any significant data change, call `notify_change(change_type, priority)` from `sync.py`.
- When a file is deleted from the uploads folder, call `notify_file_deleted(filepath)` from `sync.py`.
- Four priority levels with smart batching delays: `IMMEDIATE` (0 s), `HIGH` (30 s), `NORMAL` (60 s), `LOW` (120 s).
- The sync module uses an exponential-backoff retry (up to `MAX_RETRIES = 3`) and respects a 5-minute minimum interval between sends.

---

## Feature areas

### Page deindexing
- Pages can be marked `is_deindexed = 1` to hide them from the sidebar and search results while keeping them accessible via their URL.
- Admins and editors with the `page.view_deindexed` permission can still navigate to and edit deindexed pages.
- Check `db.has_permission(user, "page.view_deindexed")` before showing deindexed content to users.

### Sequential navigation
- Categories can have `sequential_nav` enabled. When enabled, wiki pages in that category show Prev / Next buttons to walk through pages in `sort_order`.
- Use `db.get_adjacent_pages(page_id)` to retrieve the previous and next page rows.
- Toggle with `db.update_category_sequential_nav(cat_id, enabled)`.

### Page reservations (checkout system)
- Editors can "reserve" (check out) a page for exclusive editing. Reservations expire after `config.PAGE_RESERVATION_DURATION_HOURS` (default 48 h).
- After a reservation ends, a cooldown of `config.PAGE_RESERVATION_COOLDOWN_HOURS` (default 72 h) prevents the same user from immediately re-reserving.
- Reservation attempts use `BEGIN IMMEDIATE` transactions to prevent race conditions.
- Key functions: `db.reserve_page(page_id, user_id)`, `db.release_reservation(page_id, user_id)`, `db.get_active_reservation(page_id)`.

### Badge system
- Badge types are stored in `badge_types` with optional auto-trigger logic.
- Auto-trigger types: `first_edit`, `contribution_count`, `category_count`, `member_days`, `easter_egg`.
- `db.check_and_award_auto_badges(user_id)` is called on login and after page edits/creates.
- Unread badge notifications appear as a red counter banner; users clear them at `/badges/notifications`.
- Admins manage badge types at `/admin/badges`; seed defaults with `python scripts/seed_badges.py`.

### Chat cleanup scheduling
- A background scheduler in `routes/chat.py` runs cleanup weekly (every `CHAT_CLEANUP_FREQUENCY_DAYS` days) at `CHAT_CLEANUP_HOUR` (3 AM by default).
- Separate DM and group settings control whether messages and/or attachments are auto-deleted and after how many retention days.
- If DM-specific settings are `None`/`0`, the system falls back to the legacy `chat_auto_clear_messages` setting for backwards compatibility.
- Chat pages show countdown banners via `time_until_next_chat_cleanup()` and `time_since_last_chat_cleanup()` template helpers.

### Group chat roles
- Group members have one of three roles stored in `group_members.role`: `member`, `moderator`, `owner`.
- Owners and admins can kick, ban, time-out (`timed_out_until`), and promote/demote members.
- Groups can be marked `is_global = 1` (auto-join all users) or `is_active = 0` (archived/disabled).
- Group invite codes allow users to join via a shareable link.

### Site migration
- Full-site export/import available at `/admin/migration` as a ZIP file.
- Three import conflict modes: **delete all** (wipe and replace), **override** (update existing, add new), **keep existing** (only add new).

### Easter egg
- A hidden easter egg page is accessible when `users.easter_egg_found = 1`.
- Finding the easter egg auto-awards the `easter_egg` badge trigger.

### User data export
- Users can download all their personal data (account info, contributions, drafts, history) as a ZIP from Account Settings (`/account/settings`).

---

## Configuration (`config.py`)

All settings (edit `config.py` to customise):

| Setting | Default | Purpose |
|---|---|---|
| `PORT` | `5001` | Gunicorn bind port |
| `HOST` | `"127.0.0.1"` | Gunicorn bind address |
| `PROXY_MODE` | `True` | Enable `ProxyFix` for nginx/reverse proxy |
| `DATABASE_PATH` | `instance/bananawiki.db` | SQLite database file |
| `UPLOAD_FOLDER` | `app/static/uploads` | User image uploads |
| `MAX_CONTENT_LENGTH` | `16 MB` | Max upload size (Flask) |
| `ALLOWED_EXTENSIONS` | `{png, jpg, jpeg, gif, webp}` | Permitted image types (SVG intentionally excluded) |
| `ATTACHMENT_FOLDER` | `instance/attachments` | Page attachments (authenticated route) |
| `MAX_ATTACHMENT_SIZE` | `5 MB` | Per-attachment size cap |
| `ATTACHMENT_ALLOWED_EXTENSIONS` | see config.py | Permitted attachment types |
| `CHAT_ATTACHMENT_FOLDER` | `instance/chat_attachments` | Chat file attachments |
| `MAX_CHAT_ATTACHMENT_SIZE` | `5 MB` | Per-chat-attachment size cap |
| `MAX_CHAT_ATTACHMENTS_PER_DAY` | `10` | Daily chat attachment limit per user |
| `CHAT_ALLOWED_EXTENSIONS` | see config.py | Permitted chat attachment types |
| `CHAT_CLEANUP_ENABLED` | `True` | Master switch for automatic chat cleanup |
| `CHAT_CLEANUP_FREQUENCY_DAYS` | `7` | How often cleanup runs (days) |
| `CHAT_CLEANUP_HOUR` | `3` | Hour of day (0–23) cleanup runs |
| `CHAT_CLEANUP_RETENTION_DAYS` | `30` | Default message retention period |
| `LOGGING_LEVEL` | `"verbose"` | Log verbosity (`off`, `minimal`, `medium`, `verbose`, `debug`) |
| `LOG_FILE` | `logs/bananawiki.log` | Log file path |
| `PAGE_HISTORY_ENABLED` | `True` | Toggle page revision history |
| `INVITE_CODE_EXPIRY_HOURS` | `48` | Invite code lifetime |
| `PAGE_RESERVATION_DURATION_HOURS` | `48` | How long a page reservation lasts |
| `PAGE_RESERVATION_COOLDOWN_HOURS` | `72` | Cooldown after a reservation ends |
| `SYNC` | `False` | Enable Telegram backup |
| `SYNC_TOKEN` | `""` | Telegram Bot API token |
| `SYNC_USERID` | `""` | Telegram user/chat ID for backups |
| `SYNC_SPLIT_THRESHOLD` | `45 MB` | Split backup ZIP if it exceeds this size |
| `SYNC_COMPRESS_LEVEL` | `9` | ZIP compression level (0–9) |
| `SYNC_INCLUDE_CHAT_ATTACHMENTS` | `True` | Include chat attachments in backups |

---

## Frontend conventions

- **No JavaScript framework or build step.** All JS is in `app/static/js/main.js`.
- **No CSS preprocessor.** All styles are in `app/static/css/style.css`.
- The **Industrial Theme** uses a steel/grey palette: thick borders (2–3 px), sharp corners (1–2 px radius), high contrast, bold typography (700 weight).
- Default theme colours (stored in `db/_schema.py`): primary `#8fa0d4`, background `#16161f`, sidebar `#1a1a24`, text `#c8ccd8`, card `#1e1e2c`, deep `#0a0a0f`.
- Theme colours are site-configurable from **Admin → Settings** and stored in `site_settings`.
- Accessibility preferences (text size, contrast, spacing, colour overrides, sidebar width) are stored as JSON in `users.accessibility` and served via `db.get_user_accessibility(user_id)`.
- Badge notifications are displayed as red counters stored in `badge_notifications` and surfaced via `session['badge_notifications']` in the topbar.
- Eight preset favicons in `app/static/favicons/`; admins can also upload a custom favicon.

---

## Testing

- Tests live in `tests/` and use **pytest**.
- Run the full suite: `python -m pytest tests/ -v` (or `make test`).
- Every test gets a fresh, isolated SQLite database via the `isolated_db` fixture in `conftest.py` — it monkey-patches `config.DATABASE_PATH` to a temp file.
- The `client` fixture provides a Flask test client with CSRF disabled (`WTF_CSRF_ENABLED = False`).
- Standard fixtures: `admin_user`, `editor_user`, `regular_user`, `logged_in_admin`, `logged_in_editor`, `logged_in_user`.
- Prefer testing through the HTTP client rather than calling `db.*` functions directly.
- `LOGGING_LEVEL` is set to `"off"` inside tests to suppress log output.

---

## Development and deployment

| Command | What it does |
|---|---|
| `make dev` / `./dev.sh` | Start Flask dev server on port 5001 (venv auto-created) |
| `make start` / `./start.sh` | Start Gunicorn production server |
| `sudo make install` / `sudo ./install.sh` | Automated production install (systemd + nginx + SSL) |
| `sudo make update` / `sudo ./update.sh` | Safe update: backup → pull → deps → migrate → verify (auto-rollback on failure) |
| `make test` / `python -m pytest tests/ -v` | Run the full test suite |
| `make clean` | Remove venv, `__pycache__`, `.pytest_cache` |
| `python reset_password.py` | Reset a user password from the CLI |
| `python scripts/seed_badges.py` | Seed the database with default badge types |

On first visit the app redirects to a one-time setup wizard at `/setup` to create the first admin account. The `setup_done` flag in `site_settings` gates this.

---

## Database schema highlights

Key facts about the schema (see `db/_schema.py` for the full definition):

- **`users.id`** — random 8-character alphanumeric TEXT (e.g. `abc12345`), not integer.
- **`users.session_token`** — set on login; used by the one-session-per-user enforcement.
- **`users.accessibility`** — JSON blob storing per-user accessibility preferences.
- **`users.easter_egg_found`** — boolean flag set when the user discovers the easter egg.
- **`site_settings`** — single-row table (always `id = 1`); holds site name, colours, feature flags.
- **`pages.is_deindexed`** — hides page from sidebar and search when `1`.
- **`pages.difficulty_tag`**, **`tag_custom_label`**, **`tag_custom_color`** — optional difficulty badge.
- **`categories.sequential_nav`** — enables Prev/Next sequential navigation within that category.
- **`group_members.role`** — `member`, `moderator`, or `owner`.
- **`group_members.timed_out_until`** — ISO datetime; user cannot post until this time passes.
- All datetimes are stored as **UTC ISO strings** (e.g. `2024-01-15T10:30:00`); use `format_datetime()` to display in the configured site timezone.
- Schema migrations use `PRAGMA table_info` + `ALTER TABLE … ADD COLUMN` (safe to re-run; idempotent).

---

## Security guidelines

- CSRF tokens are **required** on all forms and AJAX mutations.
- All Markdown output **must** go through Bleach sanitisation (`render_markdown()`).
- SVG uploads are **intentionally blocked** (XSS risk).
- Rate limiting (`@rate_limit`) is **required** on all mutation routes.
- Use `werkzeug.security` for password hashing — never store plain-text passwords.
- Security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Content-Security-Policy`, `Referrer-Policy`) are set on every response in `app.py → set_security_headers()`.
- Do not write SQL strings using f-strings or `%` formatting — always use parameterised queries (`?` placeholders).
- Page attachments and chat attachments are stored outside `app/static/` and served through authenticated routes so they are not directly accessible by URL.
- When redirecting based on user-supplied URLs, always use `_safe_referrer()` to validate the referrer is same-origin.
