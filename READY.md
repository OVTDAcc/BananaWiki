# Is BananaWiki Ready for Deployment?

**Yes — the project is ready for deployment and actual admin usage.**

Here is the evidence behind that conclusion.

---

## Test suite

All **444 tests pass** with zero failures or errors across five test files:

- `test_production.py` — core page/user/admin workflows
- `test_rate_limiting.py` — every mutation route is covered
- `test_fixes.py` — regression cases for previously reported bugs
- `test_networking.py` — proxy, SSL, and host-binding logic
- `test_sync.py` — Telegram backup / sync logic

---

## Security

Every layer that handles user input or data mutation is protected:

| Concern | What is in place |
|---|---|
| **Authentication** | Flask-Login sessions; all protected routes use `@login_required` |
| **Authorization** | Four-tier role system (user / editor / admin / protected_admin); `@editor_required` and `@admin_required` decorators enforced on every relevant route |
| **Rate limiting** | Custom `@rate_limit` decorator applied to every write/mutation route (10–30 requests per 60 s depending on sensitivity) |
| **Input sanitization** | Markdown rendered through Bleach with an explicit tag + attribute allowlist — no raw HTML reaches the browser |
| **File uploads** | Extension whitelist (`png`, `jpg`, `jpeg`, `gif`, `webp`); SVG intentionally excluded to prevent XSS via embedded scripts |
| **CSRF** | Flask-WTF CSRF protection active on all HTML forms |
| **Secret key** | Auto-generated on first run, persisted to `instance/.secret_key` (mode 0600), overridable via `SECRET_KEY` environment variable |
| **Audit log** | Every route that mutates permanent data calls `log_action()`; upload routes additionally call `notify_file_upload` / `notify_file_deleted` |

---

## Features

All advertised features are implemented and working:

- Markdown editing with live split-pane preview
- Hierarchical categories with collapsible sidebar
- Full page revision history with snapshot viewer and one-click revert
- Draft autosave with conflict detection
- Image upload with drag-and-drop
- Role-based access (user / editor / admin / protected_admin)
- Time-limited invite codes
- Announcement banners with colour themes, expiry, and Markdown
- Appearance customisation (site name, full colour palette)
- Optional Telegram backup sync
- Lockdown mode, page-history toggle, and other admin controls
- Mobile-responsive layout

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
