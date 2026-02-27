# Is BananaWiki Ready for Deployment?

**Yes — the project is ready for deployment and actual admin usage.**

Here is the evidence behind that conclusion, based on a full review of the codebase including all recent changes.

---

## Test suite

All **472 tests pass** with zero failures or errors across six test files:

- `test_production.py` — core page/user/admin workflows, including user data export
- `test_rate_limiting.py` — every mutation route and the global rate limit
- `test_fixes.py` — regression cases for previously reported bugs and edge cases
- `test_networking.py` — proxy, SSL, and host-binding logic
- `test_sync.py` — Telegram backup/sync logic
- `test_migration.py` — new site export/import feature (all three conflict modes, HTTP routes, error paths)

---

## Security

Every layer that handles user input or data mutation is protected:

| Concern | What is in place |
|---|---|
| **Authentication** | Session-based; all protected routes use `@login_required` |
| **Authorization** | Four-tier role system (user / editor / admin / protected_admin); `@editor_required` and `@admin_required` decorators enforced on every relevant route |
| **Rate limiting** | Per-route `@rate_limit` decorator on all sensitive write endpoints (10–60 req/60 s); global limit of 300 req/60 s per IP on every route. Login rate limiting is backed by the database so it is shared across all Gunicorn workers; the general in-memory `@rate_limit` is per-worker (effectively multiplied by worker count — a known design trade-off for a small wiki) |
| **Input sanitization** | Markdown rendered through Bleach with an explicit tag + attribute allowlist — no raw HTML reaches the browser |
| **File uploads** | Extension whitelist (`png`, `jpg`, `jpeg`, `gif`, `webp`); SVG intentionally excluded to prevent XSS via embedded scripts; Pillow validates the file is a genuine image |
| **CSRF** | Flask-WTF CSRF protection active on all HTML forms and AJAX calls |
| **Security headers** | `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Content-Security-Policy` set on every response |
| **Secret key** | Auto-generated on first run, persisted to `instance/.secret_key` (mode 0600), overridable via `SECRET_KEY` environment variable |
| **Constant-time login** | Dummy hash check prevents username enumeration via timing |
| **Audit log** | Every route that mutates permanent data calls `log_action()` |
| **Data export** | Password hashes explicitly excluded from all export ZIP files; export routes require authentication |
| **Path traversal** | All file uploads and favicon saves validate the resolved path is within the upload root before writing |

---

## Features

All features are implemented, working, and covered by tests:

- Markdown editing with live split-pane preview (divider is drag-resizable)
- Hierarchical categories with collapsible sidebar; drag-to-reorder pages and categories
- Full page revision history with snapshot viewer and one-click revert
- Draft autosave with conflict detection when two editors open the same page
- Image upload with drag-and-drop; orphaned images cleaned up automatically
- Role-based access (user / editor / admin / protected_admin)
- Time-limited single-use invite codes
- Announcement banners with five colour themes, three text sizes, per-audience visibility, expiry, and Markdown
- Appearance customisation (site name, six-field colour palette, preset and custom favicon)
- Lockdown mode with configurable message
- Per-user accessibility preferences (font scale, high-contrast, custom colours, sidebar width)
- User data export (self-service and admin-initiated)
- **Site migration** — full export/import of all site data as a ZIP with three conflict-resolution modes (delete all, override, keep)
- Optional Telegram backup sync with debounce and per-file upload tracking
- Login rate limiting (DB-backed, cross-worker safe)
- Security headers on every response

---

## Known limitations (not blockers)

These are design trade-offs that are acceptable for a small self-hosted wiki, but worth being aware of:

1. **General `@rate_limit` is per-worker in-memory.** With 4 Gunicorn workers, the effective per-route limit is 4× the configured value. Login rate limiting is the exception — it is DB-backed and truly shared across workers. For a typical small team wiki this is fine.

2. **SQLite in WAL mode.** Works well for a single server. If you ever need to run multiple app servers simultaneously (horizontal scaling), you would need to switch to PostgreSQL or MySQL.

3. **New site migration feature is not yet documented** in `README.md` or `docs/features.md`. Everything works correctly and is tested; it just needs a documentation entry.

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

`config.py` is thoroughly commented and covers every setting you need to touch before going live.

---

## What to do before going live

1. **Edit `config.py`** — set your `PORT`, `USE_PUBLIC_IP`, `PROXY_MODE`, and `CUSTOM_DOMAIN` for your environment.
2. **Choose a deployment method** — systemd + nginx (or Cloudflare) is the recommended production setup.
3. **Optionally enable Telegram sync** — set `SYNC = True` and supply `SYNC_TOKEN` + `SYNC_USERID` for automatic off-site backups.
4. **Run the first-time setup wizard** — on first startup, visit the site to create the initial admin account. All subsequent users are added via invite codes or the admin panel.

No code changes are required before deployment.

