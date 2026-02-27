# Is BananaWiki Ready for Deployment?

**Yes — the project is ready for deployment and actual admin usage.**

This is a full code-level review of every route, security layer, database function, test, and deployment file as of commit 6741131.

---

## Test results

All **499 tests pass** with zero failures:

| File | Tests | Covers |
|---|---|---|
| `test_fixes.py` | 349 | Regression cases, editor category access, link embedding, difficulty/custom tags |
| `test_production.py` | 71 | Core page/user/admin workflows, user data export |
| `test_sync.py` | 36 | Telegram backup/sync logic |
| `test_migration.py` | 19 | Site export/import across all three conflict modes |
| `test_networking.py` | 13 | Proxy, SSL, and host-binding logic |
| `test_rate_limiting.py` | 11 | Every mutation route and the global rate limit |

```bash
pip install -r requirements.txt pytest
python -m pytest tests/
```

---

## Security

| Concern | What is in place |
|---|---|
| **Authentication** | Session-based; every protected route uses `@login_required` |
| **Authorization** | Four-tier role system; `@editor_required` / `@admin_required` on every relevant route; editor category-access enforced on all page and category mutations |
| **CSRF** | Flask-WTF on all HTML forms and AJAX calls |
| **Rate limiting** | Per-route `@rate_limit` on all write endpoints; login limiting is DB-backed and cross-worker safe; global in-memory limit at 300 req/60 s |
| **Input sanitization** | Markdown → Bleach with an explicit tag + attribute allowlist |
| **Image uploads** | Extension whitelist (no SVG); Pillow validates actual content; path traversal blocked |
| **File attachments** | Stored outside `static/`; extension whitelist; 5 MB limit; auth required to download; category-access enforced |
| **Security headers** | `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Content-Security-Policy` on every response |
| **Secret key** | Auto-generated on first run, stored at `instance/.secret_key` (mode 0600); overridable via `SECRET_KEY` env var |
| **Constant-time login** | Dummy hash check prevents username enumeration via timing |
| **Audit log** | Every data-mutating route calls `log_action()` |
| **Data export** | Password hashes excluded from all export ZIPs |

---

## Features — all working

**Content**
- Markdown editor with live split-pane preview; divider drag-resizable
- Formatting toolbar with link dialog (pre-fills selected text, "open in new tab" option)
- Image drop zone with post-upload positioning modal (inline / float left / float right / center) and optional width
- Page revision history — every save snapshotted; one-click revert; reverts flagged with ↩ badge
- Draft autosave with simultaneous-editor conflict warning
- Orphaned image cleanup after every commit or draft deletion
- Page attachments — up to 5 MB each; "Download All as ZIP" when 2+; delete from edit view

**Organisation**
- Hierarchical categories, unlimited depth, collapsible sidebar
- Up/down reorder for pages and categories via in-site confirmation dialogs (no browser `confirm()` popups)
- Page movement between categories; circular-reference moves blocked

**Accounts & Access**
- Four-tier roles: `user` → `editor` → `admin` → `protected_admin`
- Editor category-based access restrictions (Admin → Manage Users → 🔒 Access)
- Protected admin — self-toggleable; other admins cannot demote, suspend, or delete
- Time-limited single-use invite codes (48-hour default)
- User data export — self-service and admin-initiated

**Admin**
- Announcement banners — five colour themes, three text sizes, per-audience visibility, expiry, Markdown
- Appearance — site name, six-field colour palette, preset and custom favicon
- Site timezone — all timestamps display in the configured zone
- Lockdown mode — blocks all non-admin access instantly
- Site migration — full export/import ZIP with three conflict modes (delete all / override / keep existing)
- Telegram backup sync — debounced, per-file upload tracking (off by default)

**Accessibility**
- Per-user: text size (6 steps), high-contrast (6 levels), line spacing, letter spacing, reduce-motion, six custom colour overrides, sidebar width
- Applied server-side on every page load — no flash of unstyled content

---

## One thing to know: `is_superuser`

The database has an `is_superuser` column on the `users` table and the code checks it in several places (account settings, admin user edit). However, **there is no UI or script that can set this flag** — it defaults to 0 for every user and can only be set by directly editing the database with a SQL client. In practice this means the `is_superuser` guard is never triggered. It does not break anything; it is simply dormant code that has no effect unless you manually `UPDATE users SET is_superuser=1 WHERE ...` via SQLite. It is not a blocker.

---

## Known trade-offs (not blockers)

1. **General `@rate_limit` is per-worker in-memory.** With multiple Gunicorn workers the effective limit is multiplied. Login limiting is DB-backed and truly cross-worker.
2. **SQLite in WAL mode.** Fast and correct for a single server. Not suitable for multi-server horizontal scaling.
3. **`zoneinfo` needs OS timezone data.** Always present on standard Linux distributions. On minimal containers (e.g. Alpine) install the `tzdata` OS package.

---

## Deployment files

| File | Status |
|---|---|
| `wsgi.py` | Ready |
| `gunicorn.conf.py` | Ready — reads `HOST`, `PORT`, `PROXY_MODE` from `config.py` |
| `bananawiki.service` | **Change `User=root` / `Group=root` to a non-root user** (e.g. `www-data`) before production use |
| `config.py` | Ready — all settings commented with safe defaults |
| `reset_password.py` | Ready — CLI tool for emergency password resets over SSH |

---

## What to do before going live

1. **Edit `config.py`** — set `PORT`, `USE_PUBLIC_IP`, `PROXY_MODE`, `CUSTOM_DOMAIN`.
2. **Edit `bananawiki.service`** — change `User` and `Group` from `root` to a dedicated non-root user.
3. **Pick a deployment method** — systemd + Nginx/Cloudflare is recommended; see `docs/deployment.md`.
4. **Optionally enable Telegram sync** — set `SYNC = True`, `SYNC_TOKEN`, `SYNC_USERID` in `config.py`.
5. **Start the app** — the first-run setup wizard will prompt you to create the initial admin account.

No code changes are required before deployment.

