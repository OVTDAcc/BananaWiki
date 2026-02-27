# Is BananaWiki Ready for Deployment?

**Yes — the project is ready for deployment and actual admin usage.**

This is a full code-level review covering all routes, security layers, tests, deployment files, and documentation as of the current state of the repository.

---

## Test suite

All **494 tests pass** with zero failures across six test files:

| File | Tests | What it covers |
|---|---|---|
| `test_fixes.py` | 344 | Regression cases, bug fixes, editor category access, link embedding, difficulty tag |
| `test_production.py` | 71 | Core page/user/admin workflows, user data export |
| `test_sync.py` | 36 | Telegram backup/sync logic |
| `test_migration.py` | 19 | Site export/import: all three conflict modes, HTTP routes, error paths |
| `test_networking.py` | 13 | Proxy, SSL, and host-binding logic |
| `test_rate_limiting.py` | 11 | Every mutation route and the global rate limit |

Run with:
```bash
pip install -r requirements.txt pytest
python -m pytest tests/
```

---

## Security

Every layer that handles user input or data mutation is protected:

| Concern | What is in place |
|---|---|
| **Authentication** | Session-based; all protected routes use `@login_required` |
| **Authorization** | Four-tier role system (`user` / `editor` / `admin` / `protected_admin`); `@editor_required` and `@admin_required` decorators on every relevant route; editor category-access restrictions enforced on all page and category mutation routes |
| **Rate limiting** | Per-route `@rate_limit` on all sensitive write endpoints. Login rate limiting is DB-backed and shared across all Gunicorn workers. The general in-memory rate limit is per-worker — a known, accepted trade-off for a small wiki |
| **Input sanitization** | Markdown rendered through Bleach with an explicit tag + attribute allowlist — no raw HTML reaches the browser unsanitized |
| **Image uploads** | Extension whitelist (`png`, `jpg`, `jpeg`, `gif`, `webp`); SVG excluded to prevent XSS; Pillow validates the file is a genuine image; path traversal checked before every write |
| **File attachments** | Stored in `instance/attachments/` — outside the `static/` folder, never served as raw static URLs; extension whitelist enforced; 5 MB per-file limit enforced server-side via streaming; path traversal blocked; download routes require authentication; editors restricted to their permitted categories |
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
- Formatting toolbar with link dialog: prompts for link text, URL, and "open in new tab"; pre-fills selected text
- Image drop zone in the editor
- Page revision history — every save is snapshotted; one-click revert
- Draft autosave with conflict warning when two editors open the same page simultaneously
- Image uploads with Pillow validation; orphaned images cleaned up after each commit or draft deletion
- **Page attachments** — editors can upload files (up to 5 MB each) to any page; readers see per-file download buttons below the page content; a "Download All as ZIP" button appears when there are two or more attachments; editors can delete attachments from the edit view
- **Difficulty tag** — editors can tag any page with an optional difficulty level (`Beginner` / `Easy` / `Intermediate` / `Expert` / `Extra`, or none); rendered as a colored badge next to the page title; settable from a modal on the page view or from the edit form

**Organisation**
- Hierarchical categories with collapsible sidebar and unlimited nesting depth
- Up/down arrow reorder for pages and categories — every move shows an in-site confirmation dialog (no browser popups)
- Page movement between categories; circular-reference moves detected and blocked

**Accounts & Access**
- Four-tier role system: `user` (read-only) → `editor` → `admin` → `protected_admin`
- Editor category-based access — admins can restrict individual editors to specific categories (see `Admin → Manage Users → 🔒 Access`)
- Protected admin mode — self-toggleable; other admins cannot demote, suspend, or delete a protected admin
- Time-limited single-use invite codes
- User data export (self-service from Account Settings; admin-initiated from user management)
- Site migration — full export/import of all site data as a ZIP with three conflict-resolution modes (delete all, override, keep existing)

**Admin**
- Announcement banners — five colour themes, three text sizes, per-audience visibility, expiry, and Markdown support
- Appearance customisation — site name, six-field colour palette, preset and custom favicon
- Site timezone setting — all timestamps displayed in the configured timezone
- Lockdown mode — instantly blocks all non-admin access with a configurable message
- Telegram backup sync with debounce and per-file upload tracking (optional, off by default)

**UI / UX**
- All destructive or irreversible actions (delete page, delete user, revert history, discard draft, etc.) are guarded by an in-site modal confirmation dialog — no browser native `confirm()` popups
- Flash messages with dismiss buttons on all forms

**Accessibility**
- Per-user preferences: text size (6 steps), high-contrast mode (6 levels Off/Slight/Low/Med/High/Max), line spacing (3 steps), letter spacing (3 steps), reduce-motion toggle, six custom color overrides (background, text, primary, secondary, accent, sidebar), and sidebar width
- Settings saved to account and applied server-side with no visible flash
- Reset to defaults from the panel or Account Settings

---

## Known limitations (not blockers)

These are design trade-offs that are acceptable for a self-hosted small-team wiki:

1. **General `@rate_limit` is per-worker in-memory.** With multiple Gunicorn workers the effective limit is multiplied per route. Login rate limiting is DB-backed and truly cross-worker safe.

2. **SQLite in WAL mode.** Correct and fast for a single server. Not suitable for horizontal scaling across multiple simultaneous app servers. A PostgreSQL backend would be needed for that scenario.

3. **`zoneinfo` requires timezone data on the host.** Python 3.9+ ships `zoneinfo` as stdlib, but the actual timezone database (`/usr/share/zoneinfo`) must be installed on the server. Standard Linux VPS/VM distributions (Ubuntu, Debian, CentOS) always have it. On stripped-down Docker images (e.g. Alpine) it may not — install the `tzdata` OS package if deploying to a minimal container.

---

## Deployment files

| File | Status |
|---|---|
| `wsgi.py` | Ready — clean WSGI entry point |
| `gunicorn.conf.py` | Ready — reads `HOST`, `PORT`, `PROXY_MODE` from `config.py` automatically |
| `bananawiki.service` | Ready — `User=root` and `Group=root` are template defaults; change to a non-root user (e.g. `www-data`) before production use |
| `config.py` | Ready — fully commented; all settings have safe defaults |
| `reset_password.py` | Ready — CLI tool for emergency password resets over SSH |

A complete deployment guide (`docs/deployment.md`) covers systemd, manual Gunicorn, Cloudflare, Nginx, Caddy, direct Let's Encrypt, and IP-only access.

---

## What to do before going live

1. **Edit `config.py`** — set `PORT`, `USE_PUBLIC_IP`, `PROXY_MODE`, and `CUSTOM_DOMAIN` for your environment.
2. **Edit `bananawiki.service`** — change `User=root` / `Group=root` to a non-root system user (e.g. `www-data`).
3. **Choose a deployment method** — systemd + Nginx (or Cloudflare) is the recommended production setup; follow `docs/deployment.md`.
4. **Optionally enable Telegram sync** — set `SYNC = True` and supply `SYNC_TOKEN` + `SYNC_USERID` in `config.py` for automatic off-site backups.
5. **Run the first-time setup wizard** — on first startup, visit the site to create the initial admin account.

No code changes are required before deployment.

