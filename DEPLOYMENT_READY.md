# Deployment Readiness Assessment

**Short answer: Yes, the project is deployment-ready from a code standpoint — with one important documentation gap to be aware of.**

---

## What works correctly

All 527 automated tests pass. Every route has authentication guards, CSRF protection, and rate limiting. The database migration is safe for existing installs (new columns are added via `ALTER TABLE` if they don't already exist, and every new column has a sensible default). The import chain (`config → db → app → wsgi → gunicorn.conf.py`) loads cleanly with no errors.

The features added in the recent PR are all wired up end-to-end:

- **Category change during edit** — the edit form sends a `category_id` field; the route validates access and applies the move inline alongside the content save.
- **Tag and category at page creation** — the Create Page form now includes the full difficulty-tag selector; the route saves the tag immediately after inserting the page.
- **Slug rename with auto-relink** — `POST /page/<slug>/rename` calls `db.update_page_slug()`, which rewrites every `/page/<old-slug>` string in all other pages' content and open drafts in a single transaction before redirecting to the new URL.
- **Internal link picker** — the link dialog in the editor has External/Wiki-Page tabs; the Wiki Page tab queries `/api/pages/search` (login-required, rate-limited) for autocomplete and inserts a standard Markdown internal link.
- **Sequential prev/next navigation** — `sequential_nav` defaults to `0` (disabled) on every category. When an editor enables it through the category manage modal, `db.get_adjacent_pages()` finds the surrounding pages by `sort_order` and the page template renders the Prev/Next buttons. Nothing is shown on pages where it is disabled.
- **Simplified config** — `USE_PUBLIC_IP`, `SSL_CERT`, `SSL_KEY`, and `CUSTOM_DOMAIN` have been removed. The new defaults (`HOST = "127.0.0.1"`, `PROXY_MODE = True`) match the standard nginx deployment described in the systemd service file.

---

## The one gap: the docs are out of date

`docs/configuration.md`, `docs/deployment.md`, and `docs/features.md` still document the removed settings (`USE_PUBLIC_IP`, `CUSTOM_DOMAIN`, `SSL_CERT`, `SSL_KEY`) and do not mention the five new features listed above. This does not affect runtime behaviour — it only affects human readers following the docs.

If an admin reads the deployment guide and tries to set `USE_PUBLIC_IP = True`, Python will raise `AttributeError` when `gunicorn.conf.py` tries to read it. So the doc pages for *configuration* and *deployment* should be updated before pointing anyone at them. The code itself is fine.

---

## What you need to do before pointing users at the docs

1. Remove references to `USE_PUBLIC_IP`, `CUSTOM_DOMAIN`, `SSL_CERT`, and `SSL_KEY` from `docs/configuration.md` and `docs/deployment.md`. The correct way to bind to a public IP now is to set `HOST = "0.0.0.0"` directly in `config.py`; SSL termination should always go through nginx or Cloudflare.
2. Add entries for the five new features (category during edit, tag at creation, slug rename, internal link picker, sequential nav) to `docs/features.md`.
3. Update `docs/architecture.md` to mention the three new routes (`/page/<slug>/rename`, `/category/<id>/sequential-nav`, `/api/pages/search`) and the two new DB helpers (`db.update_page_slug`, `db.get_adjacent_pages`, `db.search_pages`).

None of these are blockers for the application running — they are purely documentation tasks.

---

## Summary

The application is production-ready. The code is clean, all paths are authenticated and rate-limited, the database migrates safely, and all new features work end-to-end. The only thing outstanding is bringing the docs directory in sync with what the code actually does.
