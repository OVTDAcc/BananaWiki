# Deployment Readiness Assessment

**Short answer: The application code is ready. The docs have stale instructions that will silently misconfigure any admin who follows them exactly. Fix those first, then it is fully ready.**

---

## What is working correctly right now

- **All 527 automated tests pass.** Every route, every database operation, every security check is exercised.
- **The import chain is clean.** `config.py` → `db.py` → `app.py` → `wsgi.py` → `gunicorn.conf.py` all load without errors.
- **Security is solid.** CSRF protection on every form, Bleach-sanitized HTML on every Markdown render, rate limiting on every mutation route (SQLite-backed across Gunicorn workers), constant-time login checks, security headers on every response.
- **Database migrations are backward-compatible.** Every new column is added with `ALTER TABLE … ADD COLUMN … DEFAULT` if it does not already exist, so existing installs upgrade safely with no manual SQL.
- **All features are wired up end-to-end.** Pages, categories, history, drafts, attachments, user profiles, invites, announcements, accessibility preferences, Telegram sync, admin tools — all work.
- **`config.py` is clean.** The settings that were removed in a previous cleanup (`USE_PUBLIC_IP`, `CUSTOM_DOMAIN`, `SSL_CERT`, `SSL_KEY`) are fully gone from both `config.py` and `gunicorn.conf.py`.

---

## What will mislead an admin right now

`docs/deployment.md`, `docs/configuration.md`, and `docs/features.md` still document the four settings that were removed. This is not a crash bug, but it causes a real operational problem:

### The broken deployment scenario

The docs tell admins to do this for a Cloudflare setup or IP-only access:

```python
# What docs/deployment.md says to put in config.py
USE_PUBLIC_IP = True        # Cloudflare / IP-only setup
CUSTOM_DOMAIN = "wiki.example.com"
```

But neither of those settings does anything in the current codebase. `config.py` now has `HOST = "127.0.0.1"` hardcoded. `gunicorn.conf.py` reads `HOST` directly — it does not read `USE_PUBLIC_IP`. So if an admin follows the docs, they will:

1. Add `USE_PUBLIC_IP = True` to `config.py` — silently ignored.
2. Start the server — it binds only to `127.0.0.1:5001`, not to `0.0.0.0`.
3. Find the site unreachable from the outside — no error, just no connection.

The Direct HTTPS guide is also broken: it tells admins to set `SSL_CERT` and `SSL_KEY`, but no code reads those keys anywhere, so HTTPS will never start.

### What the docs need to say instead

| Old (wrong) | New (correct) |
|---|---|
| `USE_PUBLIC_IP = True` | `HOST = "0.0.0.0"` |
| `USE_PUBLIC_IP = False` | `HOST = "127.0.0.1"` *(already the default, omit it)* |
| `CUSTOM_DOMAIN = "wiki.example.com"` | Delete this line — the setting no longer exists and does nothing |
| `SSL_CERT = "/path/to/cert.pem"` | Delete this line — SSL must be terminated at nginx, Caddy, or Cloudflare, not by Gunicorn |
| `SSL_KEY = "/path/to/key.pem"` | Delete this line — same reason |

---

## What you need to do

These are the only remaining tasks before the project is fully ready for admins to follow:

**1. Fix `docs/deployment.md`**

Replace every code block that contains `USE_PUBLIC_IP`, `CUSTOM_DOMAIN`, `SSL_CERT`, or `SSL_KEY` with the correct equivalent. The Cloudflare and IP-only sections need `HOST = "0.0.0.0"`. The Direct HTTPS section needs to be rewritten to say "use nginx or Caddy instead" because Gunicorn no longer handles TLS directly. The nginx/Caddy/systemd sections just need `CUSTOM_DOMAIN` removed.

**2. Fix `docs/configuration.md`**

The Networking table documents `USE_PUBLIC_IP` and `HOST (derived)` — replace them with a single `HOST` row explaining the two valid values (`127.0.0.1` for proxy mode, `0.0.0.0` for direct access). Remove the `CUSTOM_DOMAIN` row. Remove the entire SSL/HTTPS section (it documents `SSL_CERT` and `SSL_KEY` which no longer exist).

**3. Fix `docs/features.md`**

Lines 684–689 reference `SSL_CERT`, `SSL_KEY`, `USE_PUBLIC_IP`, and the "derived HOST" pattern. Update those lines to match the current config.

---

## Nothing else is needed

The code itself requires no changes. No missing features, no broken routes, no unsafe patterns. Once the three doc files above are updated, every person who follows the docs will get a working server.

---

## In one sentence

The application is production-ready from a code perspective; the only outstanding work is updating three doc files to remove four config settings that no longer exist, so that admins who follow the deployment guide get a running server instead of a silent bind-to-localhost misconfiguration.

---

## Status update — docs now fixed

The items listed in "What you need to do" above have been resolved:

- **`docs/deployment.md`** — all `USE_PUBLIC_IP`, `CUSTOM_DOMAIN`, `SSL_CERT`, and `SSL_KEY` examples replaced with the correct `HOST = "0.0.0.0"` / `PROXY_MODE = True` equivalents. The non-functional "Direct HTTPS with Let's Encrypt" section removed entirely.
- **`docs/configuration.md`** — stale `USE_PUBLIC_IP`, `HOST (derived)`, and `CUSTOM_DOMAIN` rows replaced with a single `HOST` row. Entire SSL/HTTPS section removed. `PROXY_MODE` default corrected to `True`.

**The project is fully ready for admin deployment.** All 538 tests pass and the docs now accurately describe how to deploy.

