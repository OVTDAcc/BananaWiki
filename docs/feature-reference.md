# Feature Reference

This document summarizes the live feature set of BananaWiki as implemented in the current codebase. It is based on the active Flask routes, database layer, helpers, and the dedicated pytest coverage that exercises the major workflows. Treat it as the authoritative feature inventory for the systematic audit work tracked in [`docs/legacy_feature_audit.md`](legacy_feature_audit.md).

## Wiki authoring

### Markdown and rendering

- Markdown pages render through Python-Markdown with `tables`, `fenced_code`, `toc`, and `nl2br`
- Sanitization is always applied after rendering using Bleach allowlists
- The `[TOC]` marker creates a heading table of contents
- Bare YouTube and Vimeo URLs on their own line can be embedded on page views
- Stored `[[video ...]]` shortcodes can preserve alignment, width, and aspect-ratio preferences
- Markdown preview uses the same sanitized rendering path as saved content

### Editor workflow

- split-pane editor with preview
- formatting toolbar for common syntax
- internal page autocomplete when inserting links
- image upload flow with alt text, alignment, and width controls
- attachment uploads with authenticated download routes
- difficulty tags with predefined or custom colorized labels
- edit summaries attached to history entries
- page slug renaming without recreating the page
- page reservation indicators in the sidebar and editor flow when reservations are enabled
- page creation and editing respect category write-access rules for restricted editors

## Organization and navigation

- hierarchical categories with unlimited nesting
- drag-to-reorder pages and categories
- move pages between categories without rewriting content
- per-category sequential navigation for Prev/Next reading
- deindex pages to hide them from navigation and search while keeping the direct URL active
- dedicated home page support alongside ordinary slug-based pages
- uncategorized content is still handled in navigation and admin views

## History, drafts, and change safety

- complete page history with rendered snapshot view
- one-click revert that creates a new history record instead of deleting older ones
- autosaved drafts stored server-side
- concurrent-draft awareness when another editor is already working on a page
- draft transfer support
- contributor attribution appended to edits when multiple people had drafts open
- orphaned upload cleanup after commits or draft deletion
- attribution transfer and de-attribution workflows for correcting history ownership
- page reservations can block destructive editing while still allowing some safe actions
- a dedicated reservations view lists active checkouts and their effective expiry state

## Search and discovery

- title and content search modes
- internal page search for the link picker
- deindexed content hidden from normal users but still visible to privileged users where permitted
- people directory with published profiles
- sidebar people widget for active users
- permission-aware page and category visibility filtering
- profile discovery only exposes published profiles instead of every account

## Authentication, onboarding, and access safety

- first-run setup wizard that creates the initial administrator account
- invite-code signup flow for normal account creation
- invite-code administration with active, expired, used, soft-deleted, and permanently deleted records
- login password hashing through Werkzeug helpers
- failed-login throttling backed by the database
- per-route mutation rate limits and a global request rate limit for the app
- optional one-session-per-user enforcement with a dedicated `/session-conflict` recovery flow
- lockdown mode that immediately redirects non-admin users to a maintenance page with a custom message
- safe same-origin referrer handling for redirect-back flows

## Accounts, roles, permissions, and governance

### Roles

BananaWiki uses four built-in roles:

- `user` — read-only by default
- `editor` — content and category maintenance
- `admin` — site administration and moderation
- `protected_admin` — admin with self-protection against modification by other admins

### Fine-grained permissions

The permission system extends role defaults with per-user settings. Key groups include:

- page viewing, creation, editing, deletion, metadata, and deindexing
- category creation, editing, deletion, reorder, and sequential navigation
- history viewing, revert, and attribution transfer
- draft creation and transfer
- attachment upload and deletion
- profile access
- chat and search access
- invite and moderation-related capabilities through admin tools and per-user settings

### Category access control

Editors can be limited to specific categories for write access, and user/category access rules also affect visibility for pages and categories.

### Administration and governance

- admin settings cover theme palettes, timezone, favicon choice/upload, lockdown behavior, session-limit toggles, chat controls, and reservation timing
- admin user management includes role changes, suspension/unsuspension, password resets, accessibility/profile moderation, and protected-admin safeguards
- per-user custom tags can be created, recolored, reordered, and removed
- user audit pages show recent activity log entries together with username history
- account exports can be downloaded by the user or by an admin on the user's behalf

## Profiles and social features

- public profiles with real names, bios, and avatars
- publish/hide/delete profile states
- contribution heatmaps
- direct messages with unread counts and attachments
- group chats with owners, moderators, bans, and timeout support
- badge notifications shown in the main UI
- direct messages can be disabled globally or per-user, can be exported, and can be cleared without deleting the rest of the account
- group chats support invite-code join links, invite regeneration, owner/moderator roles, chat exports, message deletion, and admin monitoring pages
- global group chats can auto-join users while keeping moderation reserved for site admins
- chat quotas, retention windows, and cleanup scheduling are configurable from site settings
- users can receive custom profile tags and published profile cards in shared UI widgets

## Announcements and badges

### Announcements

Announcements support:

- Markdown content
- color themes
- text size options
- audience targeting for logged-in/logged-out users
- expiry dates
- optional countdown displays
- non-removable notices for critical messages

### Badge system

Badges can be:

- manually awarded or revoked
- auto-awarded for triggers such as first edit, contribution thresholds, category counts, member age, and easter egg discovery
- configured with custom icon, color, description, thresholds, and repeatability
- surfaced as unread notification counters until the recipient visits the badge notifications page

## Page reservations

When page reservations are enabled from site settings:

- editors can reserve pages before destructive changes
- admins can set the reservation timeout in hours from **Admin → Settings** (default: 48)
- reservations expire automatically using the configured timeout
- admins can set the cooldown in hours from **Admin → Settings** (default: 24)
- a cooldown prevents immediate re-reservation by the same user
- admins can override or release reservations
- some non-destructive actions remain available while a reservation is active

## Accessibility and theming

Per-user customization includes:

- theme mode preference overriding the site default
- text size and contrast controls
- line spacing and letter spacing
- reduced motion
- custom color overrides
- sidebar width adjustments

Site-wide defaults include:

- dark and light theme palettes
- default theme mode
- site name and timezone
- preset or uploaded favicon
- high-contrast-friendly color overrides managed in the same settings surface as other accessibility preferences

## Data portability and backups

- user data export as ZIP from account settings
- full-site export/import with delete-all, override, or keep-existing modes
- optional Telegram backup sync for database, logs, uploads, and other runtime data
- site migration archives include runtime assets such as uploads, attachments, chat attachments, and custom favicons
- group and direct chat export flows can package messages alone or bundle attachments into ZIP files
- experimental Obsidian sync can pull accessible wiki content into a local vault and push edited Markdown back into BananaWiki
- Obsidian sync preserves category paths, copies assets into vault directories, records manifest metadata, and writes history entries on push

## CLI commands, automation, and integrations

- `reset_password.py` provides an interactive SSH-friendly password reset workflow for existing accounts
- `scripts/seed_badges.py` seeds the default badge catalog into an initialized database
- `scripts/obsidian_sync.py` exposes the experimental Obsidian pull/push workflow from the command line
- `setup.py` runs the standalone deployment/provisioning wizard
- `install.sh`, `start.sh`, `dev.sh`, and `update.sh` cover the supported development, production, and maintenance entry points
- Telegram backup sync batches change notifications and runtime backups through `sync.py` when the integration is enabled

## Operationally important edge cases

- `PROXY_MODE` affects forwarded headers and secure session cookies
- page history can be disabled in `config.py`
- chat quotas and cleanup schedule are controlled from site settings, not hard-coded constants
- image uploads intentionally exclude SVG for security reasons
- page attachments and chat attachments are stored outside `app/static/`
- user IDs are random text identifiers rather than autoincrement integers
- security headers are applied to every response, including CSP rules that explicitly allow the supported video embed hosts

## Verification snapshot

The repository includes dedicated pytest modules that exercise the major feature areas documented above, including:

- `tests/test_permissions.py` for roles, permissions, and access restrictions
- `tests/test_chats.py` and `tests/test_group_chats.py` for messaging, moderation, exports, quotas, and cleanup behavior
- `tests/test_page_reservations.py` and `tests/test_sequential_nav.py` for editing safety and navigation flows
- `tests/test_deindex.py` for hidden-but-accessible page behavior
- `tests/test_rate_limiting.py` and `tests/test_video_embedding_and_session_limit.py` for request throttling, video embeds, and session-limit enforcement
- `tests/test_obsidian_sync.py` for the experimental vault import/export workflow
- `tests/test_migration.py`, `tests/test_sync.py`, and `tests/test_synchronize.py` for site export/import, backup-related behaviors, and broader regression coverage

The current verification baseline for this inventory is a full local run of `. venv/bin/activate && python -m pytest tests/ -q`, which completed with `1329 passed`.
