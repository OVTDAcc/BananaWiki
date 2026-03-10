# Architecture and Security

This page explains how BananaWiki is structured and what safety guarantees the application tries to enforce.

## Application structure

### Flask entry point

`app.py` is responsible for:

- creating the Flask app
- applying proxy handling when `PROXY_MODE` is enabled
- enabling CSRF protection
- registering all route groups
- injecting shared template globals
- attaching response security headers
- enforcing setup completion, lockdown mode, session-limit checks, and global rate limiting

### Route organization

Feature routes are split under `routes/`:

- `auth.py` — login, logout, signup, setup, lockdown, session conflict
- `wiki.py` — pages, categories, history, reservations
- `users.py` — profiles, account tools, user data export
- `admin.py` — users, settings, migration, announcements, badges, moderation
- `chat.py` / `groups.py` — direct messages and group chat
- `api.py` — preview, search, drafts, reorder, accessibility, and other JSON endpoints
- `uploads.py` — image and attachment handling
- `errors.py` — common error handlers

### Database boundary

All SQL is meant to stay under `db/`.

Key patterns:

- `db/_schema.py` creates tables and applies safe `ALTER TABLE` migrations
- `db/_connection.py` owns connection creation
- feature tables and queries live in their corresponding `_*.py` modules
- callers import the public `db` package instead of using `sqlite3` directly in route handlers

### Frontend boundary

BananaWiki deliberately avoids a frontend toolchain:

- templates live in `app/templates/`
- styles live in `app/static/css/style.css`
- client behavior lives in `app/static/js/main.js`

This keeps the deployment footprint small and makes source-level debugging straightforward.

## Data flow

![Architecture overview](images/architecture-overview.png)

At runtime the typical request path is:

1. browser request reaches Flask/Gunicorn
2. `before_request` checks setup status, lockdown, session validity, and global rate limit
3. the route module performs authorization and database access through `db`
4. Markdown is rendered and sanitized when needed
5. Jinja templates render the response with shared context data
6. `after_request` adds response security headers

## Authentication and authorization

### Sessions

- session data stores `user_id`
- when session limits are enabled, a per-user `session_token` must match the browser session
- mismatches redirect to `/session-conflict`

### Roles and permissions

BananaWiki combines role-based access and per-user permissions:

- role defaults define the baseline
- optional permission overrides provide granular control
- category-level read/write access further constrains visibility and editing

Helpers such as `login_required`, `editor_required`, `admin_required`, `editor_has_category_access`, `user_can_view_page`, and `user_can_view_category` are used throughout the route layer.

## Security controls

### CSRF protection

Forms and AJAX mutations are protected with Flask-WTF CSRF tokens.

### Markdown sanitization

User content is rendered through the Markdown helper and sanitized with Bleach allowlists. Raw user HTML should not bypass that pipeline.

### Upload restrictions

- SVG is intentionally excluded from image uploads
- filenames are sanitized
- attachments are stored outside `app/static/`
- downloads are routed through authenticated views instead of public direct links

### Rate limiting

BananaWiki uses two layers:

- login attempt rate limiting to slow brute-force attempts
- broader per-route and global request throttling for mutation and abuse resistance

### Response headers

`app.py` sets:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: SAMEORIGIN`
- `Referrer-Policy: strict-origin-when-cross-origin`
- a Content Security Policy that restricts scripts, styles, images, forms, and iframe sources

## Storage layout

### Tracked source tree

- application code
- templates, CSS, JavaScript, favicons
- tests and scripts
- documentation

### Runtime-only data

- `instance/bananawiki.db`
- `instance/.secret_key`
- `instance/attachments/`
- `instance/chat_attachments/`
- `logs/bananawiki.log`

These should be backed up but not committed.

## Design choices worth knowing

### SQLite first

BananaWiki is intentionally optimized around SQLite rather than an external database server. That keeps installation simple and makes backup/export workflows easier.

### No build step

The project uses server-rendered templates and plain static assets. If you can edit a Python file, a template, CSS, or JavaScript, you can work on the app without a compilation pipeline.

### Two layers of setup

There are two different setup concepts:

- `/setup` inside the main Flask app creates the first administrator account
- `setup.py` is a separate provisioning wizard for server-level deployment tasks

Documenting that distinction prevents one of the most common operator misunderstandings.
