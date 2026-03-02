# Feature List

This document catalogues every feature in BananaWiki, ordered from the most visible and well-known down to the most obscure and undocumented internals. Each entry notes where the feature lives in the codebase.

## Contents

- [Content editing](#content-editing)
- [Navigation and organization](#navigation-and-organization)
- [Page history](#page-history)
- [Drafts and collaboration](#drafts-and-collaboration)
- [Image uploads](#image-uploads)
- [Page attachments](#page-attachments)
- [User accounts and roles](#user-accounts-and-roles)
- [User profiles and People page](#user-profiles-and-people-page)
- [Protected admin mode](#protected-admin-mode)
- [Invite codes](#invite-codes)
- [Announcements](#announcements)
- [Admin panel](#admin-panel)
- [Appearance customization](#appearance-customization)
- [Accessibility preferences](#accessibility-preferences)
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
Images can be dragged directly onto the editor pane or selected via a file picker (the **Attach Image** button in the toolbar). After the file is uploaded, an **image options modal** appears so the editor can set:

- **Alt text / Caption** — pre-filled from the filename; used as both the image alt attribute and the `<figcaption>` text
- **Position** — `Inline` (default, standard Markdown), `Float Left`, `Float Right`, or `Center`
- **Width (px)** — optional; limits the rendered image width

For the default inline position without a custom width, a standard Markdown `![alt](url)` tag is inserted. For all other combinations, the editor inserts the appropriate HTML (`<figure class="wiki-img-{align}">` or `<img width="…">`), which passes through the Bleach allowlist unchanged.

> `app/static/js/main.js` → `initImageUpload`, `openImageOptionsModal`, `confirmImageInsert`  
> `app.py` → `upload_image`  
> `app/templates/wiki/edit.html` → `#image-options-modal`  
> `app/static/css/style.css` → `.wiki-img-left`, `.wiki-img-right`, `.wiki-img-center`

### Inline title editing
The page title can be changed without opening the full Markdown editor — a dedicated inline form posts to `/page/<slug>/edit/title`. The slug is not changed when the title is renamed, so existing links remain valid.

> `app.py` → `edit_page_title`

### Difficulty tag
Editors can tag any page with an optional difficulty level displayed as a colored badge next to the title. Available predefined values: `Beginner` (blue), `Easy` (green), `Intermediate` (yellow), `Expert` (red), `Extra` (purple). A **Custom** option lets the editor type any label and choose any color via a hex input or one of 16 color presets. Setting it to `None` hides the badge entirely. The tag can be set from a modal on the page view or from the edit form's dropdown.

> `app.py` → `update_page_tag`, `edit_page` (reads `difficulty_tag`, `tag_custom_label`, `tag_custom_color`), `db.py` → `update_page_tag()`, `VALID_DIFFICULTY_TAGS`, `app/templates/wiki/page.html` (badge + tagModal with color picker), `app/templates/wiki/edit.html` (dropdown + color picker), `app/static/css/style.css` (`.difficulty-tag-*` classes, `.color-swatch`, `.color-preset-grid`)

### URL slug auto-generation
When a new page is created, its URL slug is derived from the title: lowercased, stripped of special characters, and spaces turned into hyphens. If the resulting slug is already taken, a numeric suffix (`-1`, `-2`, …) is appended until a unique slug is found.

> `app.py` → `slugify()`, `create_page`

### Page URL slug rename
Editors can change a page's URL slug after creation via a form on the page view. The rename operation atomically rewrites every `/page/<old-slug>` reference in all other pages' content and all open drafts before redirecting to the new URL — no broken internal links.

> `app.py` → `rename_page_slug`, `db.py` → `update_page_slug()`

### Internal link picker
The Markdown editor's link dialog has two tabs: **External URL** and **Wiki Page**. The Wiki Page tab queries `/api/pages/search` as the editor types and inserts a standard `[Title](/page/slug)` Markdown link when selected.

> `app.py` → `api_pages_search`, `db.py` → `search_pages()`, `app/static/js/main.js` → link dialog, `app/templates/wiki/edit.html`

---

## Navigation and organization

### Hierarchical categories with collapsible sidebar
Categories form a tree structure with unlimited nesting depth. The sidebar renders the full tree; each branch can be expanded or collapsed. On mobile the sidebar can be toggled open/closed. On desktop it has a drag-to-resize handle.

> `db.py` → `get_category_tree()`, `app/templates/base.html`, `app/static/js/main.js`

### Category CRUD
Editors can create, rename, move (re-parent), and delete categories. When deleting a category the admin chooses what happens to its pages: uncategorize them, delete them, or move them to another category. Circular-reference moves (moving a category into one of its own descendants) are detected and blocked.

> `app.py` → `create_category`, `edit_category`, `move_category`, `delete_category_route`

### Sequential navigation
Each category can have sequential Prev/Next navigation enabled. When turned on, every page in that category shows Prev and Next buttons based on `sort_order`, letting readers walk through the category like a book. The setting is toggled by editors from the category management UI.

> `app.py` → `toggle_category_sequential_nav`, `db.py` → `update_category_sequential_nav()`, `get_adjacent_pages()`

### Page movement between categories
An editor can reassign a page to a different category (or to no category) from the page view without editing the content.

> `app.py` → `move_page`

### Drag-to-reorder pages and categories
Editors can drag pages and categories into a custom order within the sidebar. The new order is persisted immediately via `/api/reorder/pages` and `/api/reorder/categories`.

> `app.py` → `api_reorder_pages`, `api_reorder_categories`, `db.py` → `update_pages_sort_order`, `update_categories_sort_order`

### Page deindexing
Editors and admins can deindex any page (except the home page) with a single button click on the page view. A deindexed page:
- is hidden from the sidebar category tree for regular users (editors and admins still see it with its title struck through)
- is excluded from the internal link picker autocomplete search for regular users (editors/admins still see it in results)
- remains fully accessible via its direct URL to all logged-in users

The `is_deindexed` flag is toggled by `POST /page/<slug>/deindex` and respects the same category access restrictions as other editor actions. The home page is protected from deindexing.

> `app.py` → `toggle_page_deindex`, `api_pages_search` (role-aware `include_deindexed`), `db.py` → `set_page_deindexed()`, `search_pages()` (`include_deindexed` parameter), `get_adjacent_pages()` (skips deindexed pages), `app/templates/wiki/page.html` (Deindex/Reindex button + badge), `app/templates/base.html` (sidebar hides/strikes-through deindexed pages)

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

## Page attachments

### File attachments on wiki pages
Editors can upload arbitrary files (PDFs, spreadsheets, archives, etc.) directly to any wiki page from the edit view. Attachments are stored in `instance/attachments/` (outside `static/`) so they are never served directly — every download goes through an authenticated route that checks the user's session.

> `app.py` → `upload_attachment`, `delete_attachment`, `download_attachment`, `download_all_attachments`  
> `config.py` → `ATTACHMENT_FOLDER`, `MAX_ATTACHMENT_SIZE`, `ATTACHMENT_ALLOWED_EXTENSIONS`  
> `db.py` → `page_attachments` table, `add_page_attachment`, `get_page_attachments`, `get_page_attachment`, `delete_page_attachment`

### Attachment size limit
Each attachment is limited to 5 MB (configurable in `config.py` via `MAX_ATTACHMENT_SIZE`). The server enforces this before writing to disk.

> `app.py` → `upload_attachment` (stream-length check), `config.py` → `MAX_ATTACHMENT_SIZE`

### Authenticated attachment download
Attachment files are read from `instance/attachments/` and sent via `send_file()` with the original filename as the download name. No unauthenticated URL can reach the stored file.

> `app.py` → `download_attachment`

### Download all attachments as a ZIP
When a page has two or more attachments, a "Download All as ZIP" link appears. The server assembles an in-memory ZIP and streams it to the client.

> `app.py` → `download_all_attachments`

### Attachment permission check
Uploading and deleting attachments requires `editor` role or higher. Additionally, category-access restrictions are enforced for editors: they can only attach files to pages in categories they are permitted to access.

> `app.py` → `upload_attachment` (`editor_has_category_access` check), `delete_attachment`

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

### User data export
Any logged-in user can download all their own data as a ZIP file from the Account Settings page (`/account/export`). The ZIP contains:

| File | Contents |
|---|---|
| `account.json` | Profile fields — id, username, role, created_at, last_login_at, suspended, easter_egg_found, is_superuser. Password hash is **not** included. |
| `contributions.json` | All page history entries authored by the user, with page title, slug, edit message, and timestamp. |
| `drafts.json` | Active unsaved drafts (page title, slug, draft content, last updated). |
| `username_history.json` | Full log of every username change: old name, new name, and timestamp. |
| `accessibility.json` | Saved accessibility preferences (font scale, contrast, sidebar width, custom colors). |

> `app.py` → `export_own_data`, `_build_user_export_zip()`, `db.py` → `get_user_contributions()`

---

## User profiles and People page

### Public profile pages
Every user can optionally create a public profile page at `/users/<username>`. The profile displays:

- Profile picture (avatar)
- Username and optional real name
- Optional bio (up to 500 characters)
- Role badge
- GitHub-style contribution heatmap for the last 365 days
- List of the 50 most recent wiki edits

Users who have not created a profile, or who have set their page to private, return a 404 to public visitors. Admins and the user themselves can always view the page regardless of its published state.

> `app.py` → `user_profile`, `db.py` → `get_user_profile()`, `get_contributions_by_day()`, `get_user_contributions()`  
> `app/templates/users/profile.html`

### People directory (`/users`)
A searchable member directory lists all users with published profiles. Searching by name or username filters the list in real time via a query parameter. Admins see all users (including those with private or disabled profiles), with status badges indicating their profile state.

> `app.py` → `users_list`, `db.py` → `list_published_profiles()`, `list_all_users_with_profiles()`  
> `app/templates/users/list.html`

### Profile self-management
From **Account Settings → Profile Page**, a user can:

- Set or update their real name and bio
- Upload or remove a profile picture (PNG/JPG/GIF/WebP, maximum 1 MB; validated with Pillow)
- Publish their profile page (make it public)
- Hide their profile page (make it private; contributions are still tracked)
- Delete their profile page completely (the profile data is removed but contribution history is always preserved in `page_history`)

> `app.py` → `account_settings` (actions `update_profile`, `publish_profile`, `unpublish_profile`, `delete_profile`, `remove_avatar`)  
> `app/templates/account/settings.html` (Profile Page section)

### Contribution heatmap
The profile page includes a GitHub-style yearly heatmap showing the number of wiki edits per day for the last 365 days. The grid is rendered entirely in vanilla JavaScript by reading a `data-contributions` JSON attribute injected by the server.

> `app/templates/users/profile.html` (inline `<script>` block)  
> `db.py` → `get_contributions_by_day()`

### Contributions always preserved
Contribution history (stored in `page_history`) is never tied to profile existence. Whether a user hides their page, deletes it, or never creates one, their edit records remain in the database. The heatmap and contribution list are rebuilt from `page_history` on every profile view.

> `db.py` → `page_history` table, `get_user_contributions()`, `get_contributions_by_day()`

### Sidebar People widget
When at least one published profile exists, a "People" section appears at the bottom of the sidebar showing up to 19 user avatars (or initial placeholders) in a 5×4 grid with a "More" link to the full directory. The list is injected on every page via `inject_globals`.

> `app/templates/base.html` (People widget)  
> `app.py` → `inject_globals` (`sidebar_people`)  
> `db.py` → `list_published_profiles()`

### Admin profile moderation
Admins can access a profile moderation panel from a user's profile page (`/users/<username>`) or directly from **Admin → Manage Users → Profile**. Available actions:

- Edit real name and bio
- Remove the user's avatar
- Disable the profile page (prevents the user from re-publishing until re-enabled by an admin)
- Re-enable a previously disabled profile
- Delete the profile entirely

> `app.py` → `admin_moderate_profile`  
> `app/templates/users/profile.html` (admin moderation form section)

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

### Export any user's data
Admins can download a ZIP archive of any user's data directly from the user management table (`/admin/users/<id>/export`). The ZIP has the same structure as the self-service export (account info, contributions, drafts, username history, accessibility preferences) but password hashes are always excluded.

> `app.py` → `admin_export_user_data`, `_build_user_export_zip()`

### Lockdown mode
When lockdown mode is enabled from the admin settings page, all non-admin users are immediately logged out and redirected to a lockdown page. API endpoints return JSON 403 errors instead of HTML redirects. A custom lockdown message (up to 1 000 characters) can be displayed on the lockdown page.

> `app.py` → `before_request_hook`, `lockdown`, `db.py` → `site_settings.lockdown_mode` / `lockdown_message`

### Site migration (export / import)
Admins can export the entire site — pages, categories, users, settings, announcements, invite codes, and full edit history — as a single ZIP containing a JSON file. The export can be imported onto a fresh or existing instance with three conflict-resolution modes:

| Mode | Behaviour |
|---|---|
| `delete_all` | Wipe all existing data first, then restore from the file. Full replacement. |
| `override` | Keep existing data; when an imported record has the same ID as an existing one, the file's version wins. |
| `keep` | Keep existing data; when there is a conflict, the existing record is preserved unchanged. |

The feature is accessible at **Admin → Site Migration** (`/admin/migration`). Export and import are both protected by CSRF tokens.

> `app.py` → `admin_migration`, `admin_migration_export`, `admin_migration_import`, `db.py` → `export_site_data()`, `import_site_data()`, `app/templates/admin/migration.html`

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
Every backup zip always contains the database, `config.py`, the secret key, log files, and a `backup_manifest.json` that records the timestamp, the list of changes that triggered this backup, and any files that were excluded (with size and reason). The only reason a file is excluded from the zip is if including it would push the archive over Telegram's 50 MB limit. Uploaded images are never bundled in the zip — they are sent as individual Telegram messages (see below).

> `sync.py` → `_create_backup()`

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
- `easter_egg_trigger`, `api_reset_accessibility` — 10 per 60 s
- `api_reorder_pages`, `api_reorder_categories` — 60 per 60 s
- `api_save_accessibility` — 60 per 60 s

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

### Flexible binding
Set `HOST = "0.0.0.0"` in `config.py` to bind Gunicorn to all network interfaces (required for IP-only direct access or when Cloudflare/nginx connects to the server's public IP directly). The default `"127.0.0.1"` is correct for the standard nginx/Caddy proxy setup. `gunicorn.conf.py` reads `HOST` directly.

> `config.py` → `HOST`, `gunicorn.conf.py`

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

## Accessibility preferences

### Per-user accessibility panel
A persistent ♿ "Accessibility" button in the topbar opens a right-side drawer panel available on every page including the editor. Settings are saved automatically to the user's account (debounced 600 ms) and applied server-side on the next page load to prevent any visible flash or reflow.

> `app/templates/base.html` (panel markup), `app/static/js/main.js` → `initAccessibility()`, `app.py` → `api_get_accessibility`, `api_save_accessibility`, `app/static/css/style.css`

### Text size scaling
Six text size steps (×0.85 → ×1.35) scale wiki page content, the Markdown editor, and the live preview panel uniformly via the `--a11y-font-scale` CSS custom property.

> `app/static/css/style.css` → `.wiki-content`, `.preview-content`, `.editor-area` font-size rules, `app/static/js/main.js` → `applyA11yPrefs()`

### High-contrast modes (6 levels)
Six contrast options are available: 0 (off / default) through 5. Levels 1–3 progressively apply CSS `filter: contrast()` to the whole page. Levels 4 and 5 additionally override the `--bg` and `--text` CSS variables to near-black and near-white, producing a stark black-and-white reading mode.

> `app/static/css/style.css` → `.a11y-contrast-1` … `.a11y-contrast-5`, `app/static/js/main.js` → `applyA11yPrefs()`

### Custom color overrides
Users can override all six CSS color variables — background (`--bg`), text (`--text`), primary (`--primary`), secondary (`--secondary`), accent (`--accent`), and sidebar (`--sidebar`) — with any hex color. Each field has an individual reset button to revert to the site default. Color values are validated server-side with a regex before being stored.

> `app.py` → `api_save_accessibility` (`_clean_color()` validation), `app/static/js/main.js` → `initAccessibility()` color input handlers

### Line spacing
Three line-spacing steps (Default / Wide / Extra) apply the `--a11y-line-height` CSS variable to `.wiki-content`, helping readers with dyslexia or visual-processing differences.

> `app/static/css/style.css` → `.wiki-content` line-height rule, `app/static/js/main.js` → `applyA11yPrefs()`

### Letter spacing
Three letter-spacing steps (Normal / Wide / Extra) apply the `--a11y-letter-spacing` CSS variable to `.wiki-content`, improving readability for some users.

> `app/static/css/style.css` → `.wiki-content` letter-spacing rule, `app/static/js/main.js` → `applyA11yPrefs()`

### Reduce Motion
A toggle switch that adds the `.a11y-reduce-motion` class to `<body>`, which disables all CSS animations and transitions site-wide. Important for users with vestibular disorders or motion sensitivity.

> `app/static/css/style.css` → `.a11y-reduce-motion *` rule, `app/static/js/main.js` → `applyA11yPrefs()`

### Sidebar width persistence
When an editor drags the sidebar resize handle, the new width is saved as an accessibility preference and restored on the next visit. The persisted width overrides the CSS default (250 px).

> `app/static/js/main.js` → sidebar resize `mouseup` handler calling `saveA11ySetting('sidebar_width', w)`

### Reset to default
The "Reset All to Default" button inside the panel and the equivalent button on the Account Settings page both call `POST /api/accessibility/reset`, which writes the default values back to the database and immediately applies them in the UI without a page reload.

> `app.py` → `api_reset_accessibility`, `app/templates/account/settings.html`

### Resizable editor split panes
In the Markdown editor, the divider between the edit textarea and the live preview panel is now a draggable resize handle. Either pane can be expanded from 15 % to 85 % of the container width.

> `app/static/js/main.js` → `initEditorResize()`, `app/templates/wiki/edit.html`

---

## Miscellaneous / Easter eggs

### Konami code easter egg
Entering the Konami code (↑ ↑ ↓ ↓ ← → ← → B A) on any page triggers a celebration effect and records a one-way `easter_egg_found` flag on the user's account. The flag persists in the database and can be viewed at `/easter-egg`.

> `app/static/js/main.js` (Konami listener), `app.py` → `easter_egg`, `easter_egg_trigger`, `db.py` → `users.easter_egg_found`, `set_easter_egg_found()`
