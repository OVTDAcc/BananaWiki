# Project Audit Report

## 1. Executive Summary

**Production-ready: YES** — with one pre-deployment configuration prerequisite.

All 606 automated tests pass across 9 test files. The import chain is clean with no errors or warnings. The security posture is solid: CSRF protection, Bleach HTML sanitization, parameterized SQL, secure session cookies, constant-time password comparisons, and layered rate limiting are all correctly implemented. Documentation is thorough and accurate. Dependencies are pinned to exact versions.

The single prerequisite before going live is to confirm that `PROXY_MODE = True` (the default) is only used when a reverse proxy (nginx, Caddy, Cloudflare) actually sits in front of Gunicorn and terminates TLS. If deployed without a proxy, `HOST` must be changed to `"0.0.0.0"` and `PROXY_MODE` to `False`; otherwise the `Secure` cookie flag is set but TLS is absent.

---

## 2. Critical Issues (Must Fix Before Deployment)

- **`PROXY_MODE = True` requires a confirmed reverse proxy** (`config.py`, `gunicorn.conf.py`).  
  The default configuration binds Gunicorn to `127.0.0.1` and sets `SESSION_COOKIE_SECURE = True`, which both assume a TLS-terminating reverse proxy is in front of the app. If Gunicorn is instead exposed directly on a public interface without TLS, session cookies will be transmitted without encryption despite carrying the `Secure` flag. Additionally, `forwarded_allow_ips = "*"` in `gunicorn.conf.py` means Gunicorn trusts `X-Forwarded-For` headers from any source; without the proxy in place, an attacker who can reach Gunicorn directly could spoof their IP address and bypass IP-based rate limiting.  
  **Action required:** Before going live, confirm the reverse proxy is in place and serving HTTPS. This is already documented in `READY.md` and `docs/deployment.md` — it must be operationally verified, not just read.

- **`Content-Security-Policy` uses `'unsafe-inline'` for both `script-src` and `style-src`** (`app.py`, lines 625–626).  
  The CSP is set on every response:
  ```
  script-src 'self' 'unsafe-inline';
  style-src 'self' 'unsafe-inline';
  ```
  `'unsafe-inline'` permits execution of any inline `<script>` or `<style>` block, which is the most common XSS injection vector. While Bleach sanitization removes inline event handlers and `<script>` tags from *rendered Markdown*, `'unsafe-inline'` in the policy means a CSP bypass via a separate injection path would succeed. This is the standard trade-off when templates rely on inline scripts and styles — and this codebase does use inline scripts and styles extensively — but it remains a known CSP weakness.  
  **Mitigation already in place:** Bleach sanitization strips all `<script>` tags and event attributes from user-provided Markdown before it reaches the browser. The risk is partially mitigated.  
  **Recommended action:** As a future hardening step, move inline `<script>` blocks to external `.js` files and inline `<style>` overrides to external `.css` files or CSS custom properties, then remove `'unsafe-inline'` from the policy.

---

## 3. Major Structural Improvements Recommended

- **`app.py` is a 3,296-line monolith** (`app.py`).  
  All routes, middleware, helpers, rate limiting, and decorators live in a single file. This works correctly today and all tests pass, but it makes navigation, code review, and future feature additions harder than necessary. The natural split would be Flask Blueprints: one each for `auth`, `wiki`, `account`, `users`, `admin`, `api`, and `category`. The `db.py` layer is already cleanly separated, so this refactor would be incremental.

- **General rate limiting is in-memory and per-worker** (`app.py`, line 118: `_RL_STORE`).  
  Login rate limiting uses the SQLite `login_attempts` table and is correctly shared across all Gunicorn workers. The general route rate limiter (`_RL_STORE`) is a `defaultdict` in process memory. With the default of up to 4 Gunicorn workers (`min(cpu_count * 2 + 1, 4)`), a determined client can make up to 4× the configured request cap before triggering a 429 — because each worker independently tracks its own counter. Under moderate traffic this is acceptable; under targeted abuse it is a bypass vector.  
  **Recommended fix:** Back the general rate limiter with the same SQLite table pattern used for login attempts, or add Redis/Memcached, to share counters across workers.

- **No Docker/container deployment option**.  
  The project ships a `bananawiki.service` systemd unit, a `setup.py` provisioning wizard, and detailed `docs/deployment.md` instructions for systemd + nginx/Caddy. No `Dockerfile` or `docker-compose.yml` is provided. This is not a blocker for the intended deployment model, but containerization would simplify repeatable deployments and CI-based testing.

---

## 4. Minor Improvements & Cleanup Suggestions

- **`_RL_STORE` keys accumulate indefinitely** (`app.py`, line 118).  
  The `_rl_check` function correctly prunes *timestamps* older than the window for each `(ip, bucket)` key, but it never removes keys whose timestamp list becomes empty. Under continuous traffic from many distinct IPs, the dict grows without bound and is never reclaimed until the worker restarts. In practice this is unlikely to cause an OOM on a typical wiki, but it is a minor memory leak. Adding a `if not _RL_STORE[key]: del _RL_STORE[key]` cleanup after pruning would fix it.

- **Telegram sync stores `config.py` and the secret key in every backup** (`sync.py`, docstring and implementation).  
  The backup zip always includes `config.py` (which contains `SYNC_TOKEN` and `SYNC_USERID`) and `instance/.secret_key`. This means the Telegram chat that receives backups will accumulate copies of the bot token and session secret. Anyone with access to that Telegram chat (or its backup) gains the secret key and can forge Flask sessions. This is documented behaviour and an accepted trade-off for operators who understand it, but it should be called out more prominently in the configuration docs.

- **`edit_page_title` route should be verified for empty-title validation** (`app.py`, `edit_page_title` route) — confirm that title sanitization and minimum-length checks are consistently enforced across both the inline title-edit route (`POST /page/<slug>/edit/title`) and the full edit form, to prevent blank or whitespace-only page titles from being saved.

- **Session lifetime is fixed at 7 days** (`app.py`, line 47: `timedelta(days=7)`).  
  There is no admin-configurable session expiry or "remember me" toggle. This is a minor usability/security concern for wikis on shared machines.

- **`APP_DEBUG` / `debug=False` is hardcoded** (`app.py`, line 3296).  
  The fallback `app.run()` block (used only for local development with `python app.py`) explicitly passes `debug=False`. A developer might inadvertently flip this to `True` during debugging. Consider removing the fallback `app.run()` block entirely and requiring Gunicorn even for local development, or adding an environment-variable guard (`debug=os.environ.get("FLASK_DEBUG") == "1"`).

---

## 5. Dead Code / Redundancies Found

- **`_LOGIN_ATTEMPTS = _RateLimitStore()` dict is never used as a backing store** (`app.py`, lines 82–90).  
  `_RateLimitStore` is a `dict` subclass whose only purpose is to override `clear()` so that test fixtures can reset the login-attempt counter by calling `_LOGIN_ATTEMPTS.clear()`. The dict itself never stores any data — all rate-limit reads and writes go directly to the SQLite `login_attempts` table. The `_RateLimitStore` class and the `_LOGIN_ATTEMPTS` instance are a test-compat shim rather than real application state. This is harmless but confusing; a comment or renaming would clarify intent.

- **`is_superuser` column is a parallel concept to `protected_admin` role** (`db.py` lines 183–184, `app.py` lines 907, 936, 956, 1109, 1215, 2582; templates `account/settings.html`, `admin/users.html`).  
  The codebase has both a `protected_admin` *role* (the primary mechanism for admin protection) and an `is_superuser` *flag* (which blocks username changes, password changes, and account deletion). These appear to be two independent hardening mechanisms that partially overlap. The `is_superuser` flag is never set through the UI and can only be set directly in the database. If `is_superuser` is intentionally a server-level override (set by the operator at the database level), this should be documented explicitly. If it is a leftover from an earlier design, it should be removed or merged into the `protected_admin` role.

- **`easter_egg_found` column and easter egg route** (`db.py` migration line 182, `app.py` easter egg routes, `app/templates/wiki/easter_egg.html`).  
  The easter egg feature (Konami code in `main.js`, `/easter-egg` route, `/api/easter-egg/trigger` endpoint, `easter_egg_found` DB column) is fully functional. It is not dead code — it is an intentional hidden feature — but it is worth acknowledging as undocumented functionality that ships in the production build.

---

## 6. Documentation Improvements Required

The documentation is comprehensive and largely accurate. The following targeted improvements would raise it to the highest standard:

- **`docs/configuration.md` should warn about the `config.py`-in-backup risk** — specifically that `SYNC_TOKEN`, `SYNC_USERID`, and the secret key are included in every Telegram backup zip. Operators should be aware that Telegram chat access implies access to these credentials.

- **`docs/deployment.md` should include a pre-flight checklist** — a short bullet list of items to verify before first boot (reverse proxy confirmed, TLS active, `PROXY_MODE` matches environment, `SECRET_KEY` not hard-coded, `SYNC` configured if backups are desired). `READY.md` covers this from a developer perspective, but a deployment-facing checklist in `deployment.md` would help operators.

- **`docs/architecture.md` should explain `is_superuser`** — the flag is present in the schema table and used in multiple routes, but it is not mentioned in either `docs/architecture.md` or `docs/features.md`. An operator who discovers it in the database would have no documentation to explain its purpose.

- **`README.md` references the repository URL as `github.com/ovtdadt/BananaWiki`** (Quick Start `git clone` command). If the canonical repository URL changes (e.g., transferred to an organization), this will point users to the wrong location.

- **`docs/features.md` does not document `is_superuser`, `easter_egg`, or the sequential navigation Prev/Next UI** in as much depth as other features. The easter egg section in `features.md` exists but the `is_superuser` flag has no entry.

---

## 7. Exact Action Plan to Reach Production Readiness

This checklist is ordered by priority. Items 1–3 are required before going live; items 4 onwards are improvements to address post-launch.

- [x] **Verify all 606 tests pass** — `python -m pytest tests/ -v` — confirmed passing.
- [ ] **1. Confirm reverse proxy is deployed and serving HTTPS** before starting Gunicorn. Verify `PROXY_MODE = True` is set if and only if a TLS-terminating proxy (nginx, Caddy, Cloudflare) is in front of the app. If deploying without a proxy, set `HOST = "0.0.0.0"` and `PROXY_MODE = False` and ensure TLS is handled at the OS/infrastructure level instead.
- [ ] **2. Set up Telegram backup** (`config.py`: `SYNC = True`, `SYNC_TOKEN`, `SYNC_USERID`) — strongly recommended before storing real data, so that the database and uploads are continuously backed up. Acknowledge the security implication: the Telegram chat will hold copies of `config.py` and the secret key.
- [ ] **3. Review and restrict Gunicorn `forwarded_allow_ips`** (`gunicorn.conf.py`, line 37) — change `"*"` to the actual IP(s) of the upstream proxy (e.g., `"127.0.0.1"`) to prevent IP spoofing if Gunicorn is ever reachable on a non-loopback interface. With `HOST = "127.0.0.1"` (the default) this is already safe; the change provides defense in depth.
- [ ] **4. Clarify or document `is_superuser`** — either add a documentation entry in `docs/architecture.md` explaining its purpose and how to set it, or remove it and fold its protection guarantees into `protected_admin`.
- [ ] **5. Add deployment pre-flight checklist to `docs/deployment.md`** — a brief list of items to confirm before first boot (proxy, TLS, `PROXY_MODE`, `SECRET_KEY` source, backup config).
- [ ] **6. Document backup security implication in `docs/configuration.md`** — warn that `SYNC_TOKEN` and the secret key are included in backup zips sent to Telegram.
- [ ] **7. Fix `_RL_STORE` key leak** (`app.py`) — delete empty timestamp lists after pruning to prevent unbounded memory growth under high-diversity IP traffic.
- [ ] **8. (Future) Replace in-memory general rate limiter with a shared store** — use the existing SQLite pattern (or Redis) so that all Gunicorn workers share a single rate-limit counter, closing the per-worker bypass gap.
- [ ] **9. (Future) Remove `'unsafe-inline'` from CSP** — migrate inline `<script>` blocks and inline `<style>` overrides to external files, then tighten the `Content-Security-Policy` header.
- [ ] **10. (Future) Split `app.py` into Flask Blueprints** — `auth`, `wiki`, `account`, `users`, `admin`, `api`, `category` — to improve maintainability as the codebase grows.
