# Deployment Readiness Assessment

**Short answer: The code is deployment-ready. The docs are not.**

All 538 automated tests pass. The application imports cleanly, every route is authenticated and rate-limited, CSRF protection is active on every form, and the database schema migrations are safe for existing installs. `gunicorn.conf.py` and `wsgi.py` wire up correctly with the current `config.py`.

---

## What is broken: the docs reference settings that no longer exist

`docs/configuration.md` and `docs/deployment.md` were written for an older version of `config.py`. That older version had four settings that have since been removed:

| Setting | Status |
|---|---|
| `USE_PUBLIC_IP` | **Removed.** Replaced by setting `HOST = "0.0.0.0"` directly. |
| `CUSTOM_DOMAIN` | **Removed.** Not used anywhere in the code. |
| `SSL_CERT` | **Removed.** `gunicorn.conf.py` no longer reads it. |
| `SSL_KEY` | **Removed.** `gunicorn.conf.py` no longer reads it. |

Every code example in the deployment guide shows blocks like:

```python
PORT = 5001
USE_PUBLIC_IP = False
CUSTOM_DOMAIN = "wiki.example.com"
PROXY_MODE = True
```

An admin following those examples will end up with a config file that silently ignores three out of four settings. The two cases where this causes real confusion:

1. **Cloudflare / IP-only sections** tell admins to set `USE_PUBLIC_IP = True`. Gunicorn still binds to `127.0.0.1` (the `HOST` default) because `gunicorn.conf.py` reads `HOST`, not `USE_PUBLIC_IP`. The app will be unreachable from the outside.

2. **"Direct HTTPS with Let's Encrypt"** tells admins to set `SSL_CERT` and `SSL_KEY` in `config.py`. Those settings are never read by `gunicorn.conf.py`, so Gunicorn serves plain HTTP on port 443, not HTTPS. This section describes a deployment mode that is entirely non-functional.

---

## What you need to do before handing the docs to an admin

1. **`docs/deployment.md`** — Replace all `USE_PUBLIC_IP` / `CUSTOM_DOMAIN` / `SSL_CERT` / `SSL_KEY` lines in every code example with the current equivalents:
   - Bind to a public IP → `HOST = "0.0.0.0"` in `config.py`
   - Custom domain → remove: this setting is no longer needed; just configure nginx/Cloudflare
   - Direct HTTPS → remove the entire "Direct HTTPS with Let's Encrypt" section; Gunicorn no longer supports `--certfile`/`--keyfile` via config.py; use nginx or Caddy for TLS instead

2. **`docs/configuration.md`** — Remove the `USE_PUBLIC_IP`, `CUSTOM_DOMAIN`, `SSL_CERT`, and `SSL_KEY` rows from the reference table and add `HOST` with its correct description (`"127.0.0.1"` default; change to `"0.0.0.0"` for direct exposure).

Nothing else. The code itself is fine.

---

## Summary

| Area | Ready? |
|---|---|
| Code (routes, auth, CSRF, rate limiting, DB) | ✅ Yes |
| All tests (538) | ✅ Pass |
| Gunicorn / WSGI startup | ✅ Clean |
| `docs/configuration.md` | ❌ References removed settings |
| `docs/deployment.md` | ❌ References removed settings; "Direct HTTPS" section is non-functional |

Fix the two doc files and the project is ready to hand to admins.
