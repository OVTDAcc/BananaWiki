# Feature Reference

This document summarizes the live feature set of BananaWiki as implemented in the current codebase.

## Wiki authoring

### Markdown and rendering

- Markdown pages render through Python-Markdown with `tables`, `fenced_code`, `toc`, and `nl2br`
- Sanitization is always applied after rendering using Bleach allowlists
- The `[TOC]` marker creates a heading table of contents
- Bare YouTube and Vimeo URLs on their own line can be embedded on page views

### Editor workflow

- split-pane editor with preview
- formatting toolbar for common syntax
- internal page autocomplete when inserting links
- image upload flow with alt text, alignment, and width controls
- attachment uploads with authenticated download routes
- difficulty tags with predefined or custom colorized labels
- edit summaries attached to history entries

## Organization and navigation

- hierarchical categories with unlimited nesting
- drag-to-reorder pages and categories
- move pages between categories without rewriting content
- per-category sequential navigation for Prev/Next reading
- deindex pages to hide them from navigation and search while keeping the direct URL active

## History, drafts, and change safety

- complete page history with rendered snapshot view
- one-click revert that creates a new history record instead of deleting older ones
- autosaved drafts stored server-side
- concurrent-draft awareness when another editor is already working on a page
- draft transfer support
- contributor attribution appended to edits when multiple people had drafts open
- orphaned upload cleanup after commits or draft deletion

## Search and discovery

- title and content search modes
- internal page search for the link picker
- deindexed content hidden from normal users but still visible to privileged users where permitted
- people directory with published profiles
- sidebar people widget for active users

## Accounts, roles, and permissions

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

### Category access control

Editors can be limited to specific categories for write access, and user/category access rules also affect visibility for pages and categories.

## Profiles and social features

- public profiles with real names, bios, and avatars
- publish/hide/delete profile states
- contribution heatmaps
- direct messages with unread counts and attachments
- group chats with owners, moderators, bans, and timeout support
- badge notifications shown in the main UI

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

## Data portability and backups

- user data export as ZIP from account settings
- full-site export/import with delete-all, override, or keep-existing modes
- optional Telegram backup sync for database, logs, uploads, and other runtime data

## Operationally important edge cases

- `PROXY_MODE` affects forwarded headers and secure session cookies
- page history can be disabled in `config.py`
- chat quotas and cleanup schedule are controlled from site settings, not hard-coded constants
- image uploads intentionally exclude SVG for security reasons
- page attachments and chat attachments are stored outside `app/static/`
