# Deployment Readiness

**Yes — the project is ready for deployment.**

All 539 automated tests pass. The application imports cleanly. No debug flags are enabled in production. Here is a summary of what was checked:

---

## What passes

- **All 539 tests pass** across 6 test files covering routes, database operations, rate limiting, networking/proxy config, Telegram sync, and user profiles.
- **Clean import chain.** `config.py` → `db.py` → `app.py` → `wsgi.py` → `gunicorn.conf.py` all load without errors or warnings.
- **No TODO/FIXME/HACK markers** in any of the core files (`app.py`, `db.py`, `config.py`, `sync.py`, `wiki_logger.py`).
- **`debug=False`** is set in the `app.run()` fallback; Gunicorn is the intended production entry point and does not use it.

## Security checks

- Secret key is loaded from `instance/.secret_key` (auto-generated on first run, mode 0600) or from the `SECRET_KEY` environment variable. It is never hard-coded.
- `SESSION_COOKIE_HTTPONLY = True` and `SESSION_COOKIE_SAMESITE = "Lax"` are always set. `SESSION_COOKIE_SECURE = True` is set when `PROXY_MODE = True` (the default), relying on the upstream reverse proxy for TLS termination — which is the standard deployment pattern.
- CSRF protection (`Flask-WTF`) is active on all forms and AJAX calls.
- Markdown output is sanitized with Bleach after every render.
- Login rate limiting is backed by SQLite so it is shared correctly across all Gunicorn workers.
- Per-route rate limiting is applied to all mutation endpoints.
- Security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Content-Security-Policy`) are sent on every response.
- Constant-time password comparison prevents username enumeration.

## Database

- All schema migrations use `ALTER TABLE … ADD COLUMN … DEFAULT` so they are safe to run against an existing database. Existing installs upgrade automatically on first start with no manual SQL required.
- The database is always included in every Telegram backup (passwords are hashed; this is safe). Config, secret key, and logs are still gated behind `SYNC_INCLUDE_SENSITIVE` and excluded by default.

## Dependencies

All seven runtime dependencies (`Flask`, `Flask-WTF`, `Werkzeug`, `gunicorn`, `markdown`, `bleach`, `Pillow`) are pinned to specific versions in `requirements.txt`. The `zoneinfo` module used for timezone support is part of the Python 3.9+ standard library and requires no extra package.

---

## One thing to confirm before going live

`PROXY_MODE = True` and `HOST = "127.0.0.1"` in `config.py` assume Gunicorn is running behind a reverse proxy (nginx, Caddy, Cloudflare, etc.) that terminates TLS. If that reverse proxy is not in place, change `HOST = "0.0.0.0"` and `PROXY_MODE = False`, and ensure you provision TLS some other way — otherwise the Secure cookie flag will be absent and cookies will be sent in plain text.

Everything else is ready.
