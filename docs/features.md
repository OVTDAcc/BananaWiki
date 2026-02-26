# Feature List

This document catalogues every feature in BananaWiki, ordered from the most visible and well-known down to the most obscure and undocumented internals. Each entry notes where the feature lives in the codebase.

## Contents

- [Content editing](#content-editing)
- [Navigation and organization](#navigation-and-organization)
- [Page history](#page-history)
- [Drafts and collaboration](#drafts-and-collaboration)
- [Image uploads](#image-uploads)
- [User accounts and roles](#user-accounts-and-roles)
- [Protected admin mode](#protected-admin-mode)
- [Invite codes](#invite-codes)
- [Announcements](#announcements)
- [Admin panel](#admin-panel)
- [Appearance customization](#appearance-customization)
- [Telegram backup sync](#telegram-backup-sync)
- [Security](#security)
- [Rate limiting](#rate-limiting)
- [Logging and auditing](#logging-and-auditing)
- [Networking and deployment](#networking-and-deployment)
- [Database internals](#database-internals)
- [Miscellaneous / Easter eggs](#miscellaneous--easter-eggs)

---

## Content editing

### Markdown rendering
Pages are written in Markdown and rendered to sanitized HTML. Enabled extensions: `tables`, `fenced_code`, `toc` (generates a `[TOC]` block), and `nl2br` (treats single newlines as `<br>`). All output is passed through Bleach with an explicit tag/attribute allowlist before being sent to the browser.

> `app.py` → `render_markdown()`, `ALLOWED_TAGS`, `ALLOWED_ATTRS`

### Split-pane editor with live preview
The edit page shows the raw Markdown source on the left and a rendered preview on the right. The preview updates automatically by posting to `/api/preview` a few seconds after the user stops typing. A formatting toolbar provides quick-insert buttons for common Markdown syntax.

> `app/templates/wiki/edit.html`, `app/static/js/main.js`, `app.py` → `api_preview`

### Image drop zone in the editor
Images can be dragged directly onto the editor pane or selected via a file picker. The file is uploaded immediately and the resulting Markdown image tag is inserted at the cursor position.

> `app/static/js/main.js`, `app.py` → `upload_image`

### Inline title editing
The page title can be changed without opening the full Markdown editor — a dedicated inline form posts to `/page/<slug>/edit/title`. The slug is not changed when the title is renamed, so existing links remain valid.

> `app.py` → `edit_page_title`

### URL slug auto-generation
When a new page is created, its URL slug is derived from the title: lowercased, stripped of special characters, and spaces turned into hyphens. If the resulting slug is already taken, a numeric suffix (`-1`, `-2`, …) is appended until a unique slug is found.

> `app.py` → `slugify()`, `create_page`

---

## Navigation and organization

### Hierarchical categories with collapsible sidebar
Categories form a tree structure with unlimited nesting depth. The sidebar renders the full tree; each branch can be expanded or collapsed. On mobile the sidebar can be toggled open/closed. On desktop it has a drag-to-resize handle.

> `db.py` → `get_category_tree()`, `app/templates/base.html`, `app/static/js/main.js`

### Category CRUD
Editors can create, rename, move (re-parent), and delete categories. When deleting a category the admin chooses what happens to its pages: uncategorize them, delete them, or move them to another category. Circular-reference moves (moving a category into one of its own descendants) are detected and blocked.

> `app.py` → `create_category`, `edit_category`, `move_category`, `delete_category_route`

### Page movement between categories
An editor can reassign a page to a different category (or to no category) from the page view without editing the content.

> `app.py` → `move_page`

### Drag-to-reorder pages and categories
Editors can drag pages and categories into a custom order within the sidebar. The new order is persisted immediately via `/api/reorder/pages` and `/api/reorder/categories`.

> `app.py` → `api_reorder_pages`, `api_reorder_categories`, `db.py` → `update_pages_sort_order`, `update_categories_sort_order`

---

## Page history

### Full revision history
Every time a page is saved a snapshot of the title, content, editor, edit message, and timestamp is stored in `page_history`. Nothing is ever deleted from history.

> `db.py` → `page_history` table, `get_page_history()`

### Edit summaries
When committing an edit the editor can type a short description of what changed. It is stored alongside the snapshot and shown in the history list.

> `app.py` → `edit_page` (reads `edit_message` from the form)

### Snapshot viewer
Any history entry can be opened to see the full rendered content at that point in time.

> `app.py` → `view_history_entry`, `app/templates/wiki/history_entry.html`

### One-click revert
Editors can revert a page to any past snapshot. A revert creates a new history entry rather than deleting newer ones, so the full chain of changes is always preserved.

> `app.py` → `revert_page`

### History attribution transfer (admin only)
An admin can reassign a single history entry to a different user — useful when content was imported or mistakenly committed under the wrong account.

> `app.py` → `transfer_attribution`

### Bulk history attribution transfer (admin only)
An admin can transfer all history entries on a given page from one user to another in a single operation.

> `app.py` → `bulk_transfer_attribution`, `db.py` → `bulk_transfer_history_attribution()`

### History feature flag
Page history can be globally disabled by setting `PAGE_HISTORY_ENABLED = False` in `config.py`. When disabled, all history routes (`/history`, `/revert`, `/history/<id>/transfer`, etc.) return 404 and the "View history" link is hidden in the UI. The default is `True` (history always on).

> `config.py` → `PAGE_HISTORY_ENABLED`, `app.py` (guards on every history route)

---

## Drafts and collaboration

### Auto-saving drafts
While editing, the browser saves a draft to the server every few seconds via `/api/draft/save`. On next visit the draft is restored automatically so unsaved work is never lost.

> `app.py` → `api_save_draft`, `api_load_draft`, `app/static/js/main.js`

### Concurrent edit conflict detection
When an editor opens a page that another user already has an open draft for, a conflict warning is displayed showing who the other editor is and when their draft was last updated.

> `app.py` → `api_other_drafts`, `edit_page`

### Draft transfer (take over another user's draft)
An editor can silently absorb another user's open draft into their own. The merge is recorded by appending the original author's username to the commit message as a contributor.

> `app.py` → `api_transfer_draft`, `db.py` → `transfer_draft()`

### Contributor tracking in commit messages
When a page is committed while other users have open drafts, their usernames are automatically appended to the edit message as `contributors: alice, bob`. This provides attribution without requiring a separate merge step.

> `app.py` → `edit_page` (contributor collection block)

### My drafts list
An editor can retrieve a list of all their pending drafts across all pages via `/api/draft/mine`, including the page title, slug, and last-saved timestamp.

> `app.py` → `api_my_drafts`

### Orphaned draft cleanup
When a draft is discarded or a page is committed, all drafts for that page are deleted. Immediately after, `cleanup_unused_uploads()` runs to remove any images that were uploaded during that session but are no longer referenced.

> `app.py` → `cleanup_unused_uploads()`, called from `edit_page`, `create_page`, `delete_page_route`, `api_delete_draft`

---

## Image uploads

### Drag-and-drop or file picker upload
Images can be uploaded from the editor via drag-and-drop or a file picker button. Supported formats: `png`, `jpg`, `jpeg`, `gif`, `webp`. SVG is intentionally excluded because it can contain embedded scripts.

> `config.py` → `ALLOWED_EXTENSIONS`, `app.py` → `upload_image`

### Pillow image validation
Every uploaded file is opened with Pillow (`img.verify()`) to confirm it is a genuine image, not just a renamed binary with an image extension.

> `app.py` → `upload_image`

### UUID-based filenames
Uploaded files are stored with a random UUID hex filename to prevent collisions and make filenames unpredictable.

> `app.py` → `upload_image`

### Automatic orphaned image cleanup
After any page commit, deletion, or draft cleanup, `cleanup_unused_uploads()` scans `pages.content` and all `page_history.content` rows for `/static/uploads/<filename>` references. Any file in the uploads folder that is not referenced anywhere is deleted. Images referenced only in history are preserved.

> `app.py` → `cleanup_unused_uploads()`, `db.py` → `get_all_referenced_image_filenames()`

### Upload size limit
The maximum upload size is 16 MB by default, enforced both by Flask's `MAX_CONTENT_LENGTH` and by a 413 error handler that shows a user-friendly flash message.

> `config.py` → `MAX_CONTENT_LENGTH`, `app.py` → `request_entity_too_large`

---

## User accounts and roles

### Four-tier role system
| Role | Permissions |
|---|---|
| **user** | View pages |
| **editor** | View, create, edit, and delete pages; manage categories; revert history; upload images |
| **admin** | Everything editors can do plus: manage users, generate invite codes, configure settings, post announcements |
| **protected_admin** | Same as admin, but the account is shielded from modifications by other admins (see [Protected admin mode](#protected-admin-mode)) |

> `app.py` → `login_required`, `editor_required`, `admin_required`

### Self-service account settings
Logged-in users can change their own username, change their own password, and permanently delete their own account — all from `/account`. Each action requires the current password as confirmation.

> `app.py` → `account_settings`

### Protection of the last admin account
The application refuses to delete, demote, or suspend the last remaining admin account. The same guard applies both in admin user management and in self-service account deletion.

> `app.py` → `admin_edit_user`, `account_settings`, `db.py` → `count_admins()`

### Superuser protection
A user whose `is_superuser` column is set to `1` directly in the database becomes immutable: their username, password, and role cannot be changed through any application route, and the account cannot be deleted. This flag cannot be set from the UI — only via the database.

> `db.py` → `users.is_superuser` column, `app.py` → `account_settings`, `admin_edit_user`

### User suspension
Admins can suspend a user account. Suspended users are logged out immediately on their next request and cannot log back in until unsuspended.

> `app.py` → `admin_edit_user` (suspend/unsuspend actions), `login_required`

### Last login tracking
The `last_login_at` timestamp is updated every time a user successfully logs in. It is visible in the admin user list.

> `db.py` → `users.last_login_at`, `app.py` → `login` (update on success)

### Username change history
Every username change — whether self-initiated or admin-initiated — is recorded in the `username_history` table with old name, new name, and timestamp. This history is visible from the per-user audit page.

> `db.py` → `username_history` table, `record_username_change()`, `get_username_history()`, `app.py` → `admin_user_audit`

### Case-insensitive unique usernames
The `username` column has `COLLATE NOCASE`, so `Alice` and `alice` are treated as the same username and cannot both exist.

> `db.py` → `CREATE TABLE users ... username TEXT COLLATE NOCASE`

### Random user IDs
User IDs are 8-character random alphanumeric strings (e.g. `62loi465`), not sequential integers, to avoid enumeration.

> `db.py` → `_gen_user_id()`

### Session persistence
Sessions are marked as permanent with a 7-day lifetime. Users stay logged in across browser restarts.

> `app.py` → `app.permanent_session_lifetime`, `session.permanent = True`

### Session fixation prevention
`session.clear()` is called before setting `user_id` on a successful login, ensuring the old pre-login session is destroyed.

> `app.py` → `login`

---

## Protected admin mode

### Self-toggleable account hardening
Any admin can opt into `protected_admin` mode from their account settings page. While this mode is active the account behaves exactly like a regular admin but gains the following extra protections:

- No other admin can change its username or password.
- No other admin can change its role, suspend it, or delete it.
- Only the account owner can perform any of those actions on the account.

The toggle requires the current password as confirmation and can be turned on or off at will by the account owner. Superuser accounts (set at the DB level) are a separate, stronger protection and cannot be toggled from the UI.

> `app.py` → `account_settings` (`toggle_protected_admin` action), `admin_edit_user` (guards on `protected_admin` target), `db.py` → `users.role` column (`'protected_admin'` value)

---

## Invite codes

### Single-use time-limited signup codes
New users cannot register without a valid invite code. Codes are generated by admins, expire after a configurable number of hours (default 48), and can only be used once.

> `app.py` → `signup`, `admin_generate_code`, `config.py` → `INVITE_CODE_EXPIRY_HOURS`

### Race condition guard
After a code is validated but before it is marked used, the server attempts to mark it used with a compare-and-swap (`use_invite_code()`). If two users attempt to use the same code simultaneously, only one succeeds; the other's newly created account is deleted and they are shown an error.

> `app.py` → `signup`, `db.py` → `use_invite_code()`

### Expired code archive
Used and expired codes are moved to an archive view at `/admin/codes/expired` rather than being deleted, so admins can see who used each code and when. Codes in the archive can be permanently removed if no longer needed.

> `app.py` → `admin_codes_expired`, `admin_hard_delete_code`

---

## Announcements

### Site-wide announcement banners
Admins can post banners that appear at the top of every page. Banners support Markdown content up to 2 000 characters.

> `app.py` → `admin_create_announcement`, `db.py` → `announcements` table

### Color themes
Each announcement can be colored `red`, `orange`, `yellow`, `blue`, or `green`.

> `db.py` → `announcements.color` column

### Text size options
Announcement text can be rendered at `small`, `normal`, or `large` size.

> `db.py` → `announcements.text_size` column

### Visibility targeting
An announcement can be shown to logged-in users only, logged-out visitors only, or both.

> `db.py` → `announcements.visibility` column, `app.py` → `view_announcement` (visibility check)

### Expiry dates
An announcement can be given an expiry datetime. Once past, it is automatically hidden without any manual action.

> `db.py` → `announcements.expires_at` column

### Active/inactive toggle
Announcements can be deactivated without deleting them, allowing drafts or seasonal messages to be prepared in advance.

> `db.py` → `announcements.is_active` column

### Full-page announcement view
Every announcement has a dedicated URL (`/announcements/<id>`) showing its full Markdown-rendered content. The banner can link to this page for longer content.

> `app.py` → `view_announcement`, `app/templates/wiki/announcement.html`

### Multi-announcement navigation
When several announcements are active at once, the banner shows them one at a time with navigation arrows to cycle through them.

> `app/static/js/main.js`, `app/templates/_announcements_bar.html`

---

## Admin panel

### User management
Admins can list all users (with optional role and status filters), change any user's username or password, promote or demote roles, suspend or unsuspend accounts, delete accounts, and create new accounts directly (bypassing the invite code flow).

> `app.py` → `admin_users`, `admin_edit_user`, `admin_create_user`

### Invite code management
Admins can generate new invite codes, revoke unused codes, and view/purge the archive of expired codes.

> `app.py` → `admin_codes`, `admin_generate_code`, `admin_delete_code`, `admin_codes_expired`, `admin_hard_delete_code`

### Site settings
The admin settings page exposes: site name, six color palette fields (primary, secondary, accent, text, sidebar, background), timezone, favicon, and lockdown mode.

> `app.py` → `admin_settings`

### Announcement manager
Admins can create, edit, toggle active state, and delete announcements from a dedicated page.

> `app.py` → `admin_announcements`, `admin_create_announcement`, `admin_edit_announcement`, `admin_delete_announcement`

### Per-user audit log
Admins can view a filtered list of log file entries for a specific user (up to 200 most recent), along with their full username change history.

> `app.py` → `admin_user_audit`, `_read_user_audit_log()`

### Lockdown mode
When lockdown mode is enabled from the admin settings page, all non-admin users are immediately logged out and redirected to a lockdown page. API endpoints return JSON 403 errors instead of HTML redirects. A custom lockdown message (up to 1 000 characters) can be displayed on the lockdown page.

> `app.py` → `before_request_hook`, `lockdown`, `db.py` → `site_settings.lockdown_mode` / `lockdown_message`

---

## Appearance customization

### Full color palette
Six CSS custom properties — primary, secondary, accent, text, sidebar, and background — can each be set to any valid hex color from the admin panel. All values are validated as `#RRGGBB` before being saved.

> `app.py` → `admin_settings`, `db.py` → `site_settings` color columns, `app/static/css/style.css`

### Preset favicon colors
Eight preset favicon color schemes are available: yellow, green, blue, red, orange, cyan, purple, and lime. Selecting one of these requires no file upload.

> `app.py` → `_VALID_FAVICON_TYPES`, `FAVICON_UPLOAD_FOLDER`

### Custom favicon upload
Admins can upload a custom favicon image (PNG, JPG, ICO, GIF, or WEBP). The file is validated with Pillow, stored with a UUID filename under `app/static/favicons/`, and the old custom favicon is deleted when a new one is uploaded.

> `app.py` → `admin_settings` (favicon upload block)

### Site name
The name shown in the browser tab, sidebar header, and other UI elements can be changed from the admin panel (maximum 100 characters).

> `app.py` → `admin_settings`, `db.py` → `site_settings.site_name`

### Timezone
All timestamps displayed in the UI (edit times, announcement dates, audit log entries) are converted to the site's configured timezone. The timezone is selected from a dropdown of all IANA timezone names. UTC is the default.

> `app.py` → `get_site_timezone()`, `format_datetime()`, `admin_settings`

---

## Telegram backup sync

### Automatic debounced backups
When `SYNC = True`, any significant change (page edit, user action, settings change, etc.) triggers a backup. The system waits 60 seconds after the last change before sending, and forces a backup after 10 minutes of continuous changes to prevent flooding.

> `sync.py` → `notify_change()`, background thread with debounce logic, `config.py` → `SYNC`

### Zip archive contents
Every backup zip always contains a `backup_manifest.json` file that records the timestamp, the list of changes that triggered this backup, and any files that were excluded (with size and reason). Setting `SYNC_INCLUDE_SENSITIVE = True` also includes the database, secret key, `config.py`, and log files in the zip. Uploaded images are never bundled in the zip — they are sent as individual Telegram messages (see below).

> `sync.py` → `_create_backup()`, `config.py` → `SYNC_INCLUDE_SENSITIVE`

### Individual image file sync
Uploaded images are sent as separate Telegram messages (not bundled in the zip) so they can be retrieved individually. Their Telegram message IDs are saved in `sync_upload_msgs.json` so they can be deleted from Telegram when the corresponding file is removed locally.

> `sync.py` → `notify_file_upload()`, `notify_file_deleted()`, `sync_upload_msgs.json`

### Retry with exponential backoff
If a Telegram send fails, the sync module makes up to 3 total attempts, waiting 5 s before the second attempt and 10 s before the third. A failure after all attempts is logged but does not crash the application. Backups are also rate-limited to at most one send per 5 minutes to avoid flooding the Telegram API.

> `sync.py` → `MAX_RETRIES`, `RETRY_BASE_DELAY`, `MIN_BACKUP_INTERVAL`, `_execute_backup()`

---

## Security

### CSRF protection
Flask-WTF CSRF protection is applied globally. Every state-changing form and every AJAX POST includes a CSRF token.

> `app.py` → `csrf = CSRFProtect(app)`

### HTML sanitization
Every Markdown-rendered page and announcement passes through Bleach with an explicit allowlist of permitted tags and attributes. This prevents XSS from user-supplied content.

> `app.py` → `render_markdown()`, `ALLOWED_TAGS`, `ALLOWED_ATTRS`

### Security headers on every response
The `set_security_headers` after-request hook adds:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: SAMEORIGIN`
- `Referrer-Policy: strict-origin-when-cross-origin`
- A `Content-Security-Policy` that restricts scripts, styles, images, fonts, objects, base URIs, and form actions.

> `app.py` → `set_security_headers`

### Secure file upload pipeline
1. `allowed_file()` checks the extension against the allowlist.
2. Pillow `img.verify()` confirms the file is a real image.
3. The file is saved with a UUID filename (original name discarded).
4. `os.path.normpath()` and `os.path.commonpath()` prevent path traversal attacks.

> `app.py` → `upload_image`, `delete_upload`

### Constant-time login checks
When the provided username does not exist, the code still calls `check_password_hash` against a pre-computed dummy hash. This ensures the response time is the same whether the username exists or not, preventing timing-based username enumeration.

> `app.py` → `_DUMMY_HASH`, `login`

### Referrer validation
`_safe_referrer()` checks that `request.referrer` matches the current host before using it as a redirect target, preventing open redirect attacks via the Referer header.

> `app.py` → `_safe_referrer()`

### Cookie security
Session cookies are set with `HttpOnly` and `SameSite=Lax`. When running with SSL or behind a proxy, `Secure` is also set.

> `app.py` → `app.config["SESSION_COOKIE_HTTPONLY"]`, `SESSION_COOKIE_SAMESITE`, `SESSION_COOKIE_SECURE`

### Password hashing
Passwords are hashed with Werkzeug's `generate_password_hash` (bcrypt-based). Plain-text passwords are never stored.

> `app.py` → `generate_password_hash`, `check_password_hash`

### Username character restrictions
Usernames may only contain letters, digits, underscores, and hyphens. This prevents log injection via control characters and eliminates Unicode look-alike confusion.

> `app.py` → `_is_valid_username()`, `_USERNAME_RE`

---

## Rate limiting

### Login rate limiting (cross-worker, DB-backed)
A maximum of 5 failed login attempts per IP per 60 seconds is enforced. Attempt records are stored in the `login_attempts` SQLite table so the limit is shared across all Gunicorn worker processes. Successful logins clear the attempt record.

> `app.py` → `_check_login_rate_limit()`, `_record_login_attempt()`, `_clear_login_attempts()`, `db.py` → `login_attempts` table

### Global rate limiting (in-memory, per-worker)
Every request (except static files) counts against a global limit of 300 requests per 60 seconds per IP. Exceeding this returns a 429 page (or JSON for API requests).

> `app.py` → `before_request_hook`, `_rl_check()`, `_RL_GLOBAL_MAX`, `_RL_GLOBAL_WINDOW`

### Per-route rate limiting
Sensitive routes carry tighter `@rate_limit` decorators on top of the global limit:
- `signup` — 10 per 60 s
- `account_settings` — 10 per 60 s
- `edit_page`, `create_page`, `edit_page_title`, `revert_page` — 20 per 60 s
- `transfer_attribution`, `bulk_transfer_attribution` — 20 per 60 s
- `delete_page_route` — 10 per 60 s
- `move_page`, `create_category`, `edit_category`, `move_category` — 20 per 60 s
- `delete_category_route` — 10 per 60 s
- `api_preview`, `api_save_draft`, `api_delete_draft`, `api_transfer_draft` — 30 per 60 s
- `upload_image`, `delete_upload` — 10 per 60 s
- `easter_egg_trigger` — 10 per 60 s
- `api_reorder_pages`, `api_reorder_categories` — 60 per 60 s

> `app.py` → `rate_limit()` decorator, individual route decorators

---

## Logging and auditing

### Request logging
Every HTTP request is logged with timestamp, IP address, HTTP method, path, authenticated username, and user agent.

> `wiki_logger.py` → `log_request()`

### Action audit logging
Every significant action (login, logout, page create/edit/delete/revert/title-edit, page and category reordering, category changes, user management, settings changes, file uploads/deletions, invite code operations, draft transfers, easter egg trigger) is logged with key-value details. Sensitive fields such as `password` and `token` are automatically redacted.

> `wiki_logger.py` → `log_action()`, called throughout `app.py`

### Log injection prevention
Control characters and newlines are stripped from all log values before writing, preventing log injection attacks.

> `wiki_logger.py` → log sanitization logic

### Log file configuration
Logging can be disabled entirely with `LOGGING_ENABLED = False`. The log file path defaults to `logs/bananawiki.log`. All log entries are also echoed to stdout.

> `config.py` → `LOGGING_ENABLED`, `LOG_FILE`, `wiki_logger.py`

### Password reset CLI script
`reset_password.py` is a standalone command-line script for resetting a user's password outside of the web interface — useful if an admin is locked out.

> `reset_password.py`

---

## Networking and deployment

### Reverse proxy and Cloudflare support
Setting `PROXY_MODE = True` wraps the app with Werkzeug's `ProxyFix` middleware so Flask reads the real client IP and protocol from `X-Forwarded-For` / `X-Forwarded-Proto` headers. Session cookies are also marked `Secure` automatically.

> `app.py` → proxy setup block, `config.py` → `PROXY_MODE`

### Direct SSL/TLS support
Providing paths to an SSL certificate and private key in `config.py` enables HTTPS without a separate reverse proxy. Not needed when Cloudflare handles TLS.

> `config.py` → `SSL_CERT`, `SSL_KEY`

### Flexible binding
`USE_PUBLIC_IP` controls whether Gunicorn binds to `0.0.0.0` (all interfaces) or `127.0.0.1` (localhost only). The derived `HOST` variable is read by `gunicorn.conf.py`.

> `config.py` → `USE_PUBLIC_IP`, `HOST`, `gunicorn.conf.py`

### systemd service file
`bananawiki.service` is a ready-to-use systemd unit file for running BananaWiki as a persistent background service on Linux.

> `bananawiki.service`

### First-boot setup wizard
On the very first run the application redirects every request to `/setup`, where an admin account and initial settings are created. The redirect is enforced in `before_request_hook`; once setup is complete the route is a no-op.

> `app.py` → `setup`, `before_request_hook`

---

## Database internals

### WAL mode SQLite
All database connections are opened with `PRAGMA journal_mode=WAL` and `PRAGMA foreign_keys=ON`. WAL mode allows concurrent reads and a single writer without blocking, making it suitable for multi-worker Gunicorn deployments.

> `db.py` → `get_db()`

### Schema migration via ALTER TABLE
`init_db()` checks `PRAGMA table_info(table_name)` for missing columns and adds them with `ALTER TABLE ... ADD COLUMN`. There is no external migration framework; the list of `if "column_name" not in cols` checks serves as the migration log.

> `db.py` → `init_db()` migration block

### Guaranteed home page
`init_db()` ensures a home page row (`is_home=1`) always exists. The home page cannot be deleted through the UI.

> `db.py` → home page `INSERT OR IGNORE`, `app.py` → `delete_page_route` (home guard)

---

## Miscellaneous / Easter eggs

### Konami code easter egg
Entering the Konami code (↑ ↑ ↓ ↓ ← → ← → B A) on any page triggers a celebration effect and records a one-way `easter_egg_found` flag on the user's account. The flag persists in the database and can be viewed at `/easter-egg`.

> `app/static/js/main.js` (Konami listener), `app.py` → `easter_egg`, `easter_egg_trigger`, `db.py` → `users.easter_egg_found`, `set_easter_egg_found()`
