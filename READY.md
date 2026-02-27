# Is BananaWiki Ready for Deployment?

**Yes — the project is ready for deployment and actual admin usage.**

This is a full review of the codebase as of the current branch, including all recent changes (site migration, editor category-based access control).

---

## Test suite

All **487 tests pass** with zero failures across six test files:

| File | Tests | What it covers |
|---|---|---|
| `test_fixes.py` | 337 | Regression cases, bug fixes, and the new editor category access feature (20 tests) |
| `test_production.py` | 71 | Core page/user/admin workflows, user data export |
| `test_sync.py` | 36 | Telegram backup/sync logic |
| `test_migration.py` | 19 | Site export/import: all three conflict modes, HTTP routes, error paths |
| `test_networking.py` | 13 | Proxy, SSL, and host-binding logic |
| `test_rate_limiting.py` | 11 | Every mutation route and the global rate limit |

---

## Security

Every layer that handles user input or data mutation is protected:

| Concern | What is in place |
|---|---|
| **Authentication** | Session-based; all protected routes use `@login_required` |
| **Authorization** | Four-tier role system (`user` / `editor` / `admin` / `protected_admin`); `@editor_required` and `@admin_required` decorators enforced on every relevant route; editor category access enforced on all page and category mutation routes |
| **Rate limiting** | Per-route `@rate_limit` on all sensitive write endpoints (10–60 req/60 s); 300 req/60 s global limit per IP. Login rate limiting is DB-backed, shared across all Gunicorn workers. The general in-memory rate limit is per-worker — a known trade-off for a small wiki |
| **Input sanitization** | Markdown rendered through Bleach with an explicit tag + attribute allowlist — no raw HTML reaches the browser |
| **File uploads** | Extension whitelist (`png`, `jpg`, `jpeg`, `gif`, `webp`); SVG excluded to prevent XSS; Pillow validates the file is a genuine image; path traversal checked before every write |
| **CSRF** | Flask-WTF CSRF protection on all HTML forms and AJAX calls |
| **Security headers** | `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Content-Security-Policy` on every response |
| **Secret key** | Auto-generated on first run, persisted to `instance/.secret_key` (mode 0600), overridable via `SECRET_KEY` env var |
| **Constant-time login** | Dummy hash check prevents username enumeration via timing |
| **Audit log** | Every route that mutates permanent data calls `log_action()` |
| **Data export** | Password hashes explicitly excluded from all export ZIPs; export routes require authentication |

---

## Features implemented and working

All features are code-complete, passing tests, and accessible in the UI:

**Content**
- Markdown editing with live split-pane preview (divider is drag-resizable)
- Formatting toolbar, image drop zone in the editor
- Page revision history — every save is snapshotted; one-click revert
- Draft autosave with conflict warning when two editors open the same page simultaneously
- Image uploads with Pillow validation; orphaned images cleaned up after each commit or draft deletion

**Organisation**
- Hierarchical categories with collapsible sidebar and unlimited nesting depth
- Drag-to-reorder pages and categories within the sidebar
- Page movement between categories; circular-reference moves detected and blocked

**Accounts & Access**
- Four-tier role system: `user` (read-only) → `editor` → `admin` → `protected_admin`
- **Editor category-based access** — admins can restrict individual editors to specific categories; restricted editors cannot edit pages in other categories, cannot create/rename/move/delete categories, and are not auto-granted new categories (see `Admin → Manage Users → 🔒 Access`)
- Protected admin mode — account owner can self-toggle; other admins cannot demote, suspend, or delete a protected admin
- Time-limited single-use invite codes
- User data export (self-service from Account Settings; admin-initiated from user management)
- **Site migration** — full export/import of all site data as a ZIP with three conflict-resolution modes (delete all, override, keep existing)

**Admin**
- Announcement banners — five colour themes, three text sizes, per-audience visibility, expiry, and Markdown support
- Appearance customisation — site name, six-field colour palette, preset and custom favicon
- Lockdown mode — instantly blocks all non-admin access with a configurable message
- Optional Telegram backup sync with debounce and per-file upload tracking

**Accessibility**
- Per-user preferences: text size (6 steps), high-contrast mode (5 levels), custom colours, sidebar width
- Settings saved to account and applied server-side with no visible flash
- Reset to defaults from the panel or Account Settings

**Security**
- CSRF, Bleach sanitization, login rate limiting (DB-backed), per-route rate limits, security headers, constant-time login

---

## Known limitations (not blockers)

These are design trade-offs acceptable for a self-hosted small-team wiki:

1. **General `@rate_limit` is per-worker in-memory.** With 4 Gunicorn workers the effective limit is 4× the configured value per route. Login rate limiting is DB-backed and truly cross-worker safe.

2. **SQLite in WAL mode.** Correct and fast for a single server. Not suitable for horizontal scaling (multiple simultaneous app servers). A PostgreSQL backend would be needed for that scenario.

---

## Documentation gaps (not deployment blockers)

These features work correctly but are not yet documented in `docs/features.md` or `README.md`:

- **Site migration** (`Admin → Migration`) — export/import with three conflict-resolution modes
- **Editor category-based access** (`Admin → Manage Users → 🔒 Access`) — per-editor category allowlists

The `README.md` also lists "453 tests across 5 files" which is outdated; the correct count is **487 tests across 6 files**.

---

## Deployment

A complete deployment guide (`docs/deployment.md`) covers:

- **systemd** service (recommended for production)
- Manual **Gunicorn**
- **Cloudflare** (free SSL + custom domain)
- **Nginx** reverse proxy with TLS
- **Caddy** reverse proxy
- Direct HTTPS via Let's Encrypt
- IP-only access (no domain needed)

`config.py` is thoroughly commented and covers every setting to configure before going live.

---

## What to do before going live

1. **Edit `config.py`** — set `PORT`, `USE_PUBLIC_IP`, `PROXY_MODE`, and `CUSTOM_DOMAIN` for your environment.
2. **Choose a deployment method** — systemd + nginx (or Cloudflare) is the recommended production setup.
3. **Optionally enable Telegram sync** — set `SYNC = True` and supply `SYNC_TOKEN` + `SYNC_USERID` for automatic off-site backups.
4. **Run the first-time setup wizard** — on first startup, visit the site to create the initial admin account.

**No code changes are required before deployment.** The documentation gaps above (site migration and editor category access) are purely missing entries in the docs; both features are fully implemented and tested.

