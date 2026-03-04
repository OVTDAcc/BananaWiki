"""
BananaWiki – JSON API routes (search, preview, drafts, accessibility, reorder).
"""

import re

from flask import request, jsonify, session
import db
import config
from helpers import (
    login_required, editor_required, admin_required, get_current_user,
    get_user_from_api_token,
    render_markdown, rate_limit, format_datetime,
)
import wiki_logger
from sync import notify_change
from routes.uploads import cleanup_unused_uploads


def register_api_routes(app):
    """Register JSON API routes on the Flask app."""

    @app.route("/api/pages/search")
    @login_required
    @rate_limit(60, 60)
    def api_pages_search():
        query = request.args.get("q", "").strip()
        if not query:
            return jsonify([])
        user = get_current_user()
        include_deindexed = user and user["role"] in ("editor", "admin", "protected_admin")
        results = db.search_pages(query, include_deindexed=include_deindexed)
        return jsonify([{"title": r["title"], "slug": r["slug"]} for r in results])

    # -----------------------------------------------------------------------
    #  Live preview API
    # -----------------------------------------------------------------------
    @app.route("/api/preview", methods=["POST"])
    @login_required
    @rate_limit(30, 60)
    def api_preview():
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "Invalid request: missing or malformed JSON"}), 400
        content = data.get("content", "")
        html = render_markdown(content, embed_videos=True)
        return jsonify({"html": html})

    # -----------------------------------------------------------------------
    #  Drafts / autosave API
    # -----------------------------------------------------------------------
    @app.route("/api/draft/save", methods=["POST"])
    @login_required
    @editor_required
    @rate_limit(30, 60)
    def api_save_draft():
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "invalid request"}), 400
        page_id = data.get("page_id")
        if page_id is None:
            return jsonify({"error": "missing page_id"}), 400
        try:
            page_id = int(page_id)
        except (TypeError, ValueError):
            return jsonify({"error": "invalid page_id"}), 400
        title = data.get("title", "")
        content = data.get("content", "")
        user = get_current_user()
        page = db.get_page(page_id)
        if not page:
            return jsonify({"error": "page not found"}), 404
        db.save_draft(page_id, user["id"], title, content)
        return jsonify({"ok": True})

    @app.route("/api/draft/load/<int:page_id>")
    @login_required
    @editor_required
    def api_load_draft(page_id):
        user = get_current_user()
        draft = db.get_draft(page_id, user["id"])
        if draft:
            return jsonify({"title": draft["title"], "content": draft["content"],
                            "updated_at": draft["updated_at"]})
        return jsonify({"title": None, "content": None})

    @app.route("/api/draft/others/<int:page_id>")
    @login_required
    @editor_required
    def api_other_drafts(page_id):
        user = get_current_user()
        page = db.get_page(page_id)
        if not page:
            return jsonify({"error": "page not found"}), 404
        drafts = db.get_drafts_for_page(page_id)
        others = [{"username": d["username"], "user_id": d["user_id"],
                   "updated_at": d["updated_at"]} for d in drafts if d["user_id"] != user["id"]]
        return jsonify({"drafts": others, "page_last_edited_at": page["last_edited_at"]})

    @app.route("/api/draft/transfer", methods=["POST"])
    @login_required
    @editor_required
    @rate_limit(30, 60)
    def api_transfer_draft():
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "invalid request"}), 400
        page_id = data.get("page_id")
        from_user = data.get("from_user_id")
        try:
            page_id = int(page_id)
        except (TypeError, ValueError):
            return jsonify({"error": "invalid page_id or from_user_id"}), 400
        if not from_user:
            return jsonify({"error": "invalid page_id or from_user_id"}), 400
        user = get_current_user()
        # Only admins may transfer another user's draft
        if user["role"] not in ("admin", "protected_admin"):
            return jsonify({"error": "admin access required"}), 403
        if from_user == user["id"]:
            return jsonify({"error": "cannot transfer draft from yourself"}), 400
        source_draft = db.get_draft(page_id, from_user)
        if not source_draft:
            return jsonify({"error": "draft not found"}), 404
        db.transfer_draft(page_id, from_user, user["id"])
        wiki_logger.log_action("transfer_draft", request, user=user, page_id=page_id, from_user=from_user)
        return jsonify({"ok": True})

    @app.route("/api/draft/delete", methods=["POST"])
    @login_required
    @editor_required
    @rate_limit(30, 60)
    def api_delete_draft():
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "invalid request"}), 400
        page_id = data.get("page_id")
        if page_id is None:
            return jsonify({"error": "missing page_id"}), 400
        try:
            page_id = int(page_id)
        except (TypeError, ValueError):
            return jsonify({"error": "invalid page_id"}), 400
        user = get_current_user()
        db.delete_draft(page_id, user["id"])
        cleanup_unused_uploads()
        return jsonify({"ok": True})

    @app.route("/api/draft/mine")
    @login_required
    @editor_required
    def api_my_drafts():
        """List all pending drafts for the current user."""
        user = get_current_user()
        drafts = db.list_user_drafts(user["id"])
        return jsonify([
            {
                "page_id": d["page_id"],
                "page_title": d["page_title"],
                "page_slug": d["page_slug"],
                "title": d["title"],
                "updated_at": d["updated_at"],
                "updated_at_formatted": format_datetime(d["updated_at"]),
            }
            for d in drafts
        ])

    # -----------------------------------------------------------------------
    #  Accessibility settings API
    # -----------------------------------------------------------------------
    _VALID_FONT_SCALES = {0.85, 0.9, 1.0, 1.1, 1.2, 1.35}
    _VALID_CONTRASTS = {0, 1, 2, 3, 4, 5}
    _VALID_LINE_HEIGHTS = {0, 1, 2}
    _VALID_LETTER_SPACINGS = {0, 1, 2}

    @app.route("/api/accessibility", methods=["GET"])
    @login_required
    def api_get_accessibility():
        user = get_current_user()
        return jsonify(db.get_user_accessibility(user["id"]))

    @app.route("/api/accessibility", methods=["POST"])
    @login_required
    @rate_limit(60, 60)
    def api_save_accessibility():
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "invalid request"}), 400
        user = get_current_user()
        current = db.get_user_accessibility(user["id"])

        font_scale = data.get("font_scale", current["font_scale"])
        try:
            font_scale = float(font_scale)
        except (TypeError, ValueError):
            font_scale = 1.0
        if font_scale not in _VALID_FONT_SCALES:
            font_scale = min(_VALID_FONT_SCALES, key=lambda x: abs(x - font_scale))

        contrast = data.get("contrast", current["contrast"])
        try:
            contrast = int(contrast)
        except (TypeError, ValueError):
            contrast = 0
        if contrast not in _VALID_CONTRASTS:
            contrast = 0

        sidebar_width = data.get("sidebar_width", current["sidebar_width"])
        try:
            sidebar_width = int(sidebar_width)
            sidebar_width = max(180, min(500, sidebar_width))
        except (TypeError, ValueError):
            sidebar_width = 250

        content_max_width = data.get("content_max_width", current.get("content_max_width", 0))
        try:
            content_max_width = int(content_max_width)
            if content_max_width < 0:
                content_max_width = 0
        except (TypeError, ValueError):
            content_max_width = 0

        editor_pane_width = data.get("editor_pane_width", current.get("editor_pane_width", 0))
        try:
            editor_pane_width = float(editor_pane_width)
            editor_pane_width = max(15, min(85, editor_pane_width)) if editor_pane_width > 0 else 0
        except (TypeError, ValueError):
            editor_pane_width = 0

        editor_height = data.get("editor_height", current.get("editor_height", 0))
        try:
            editor_height = int(editor_height)
            editor_height = max(300, min(2000, editor_height)) if editor_height > 0 else 0
        except (TypeError, ValueError):
            editor_height = 0

        def _clean_color(val):
            val = str(val).strip()
            if not val:
                return ""
            if re.match(r'^#[0-9a-fA-F]{3,8}$', val):
                return val
            if re.match(r'^rgb\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)$', val):
                return val
            return ""

        prefs = {
            "font_scale": font_scale,
            "contrast": contrast,
            "sidebar_width": sidebar_width,
            "content_max_width": content_max_width,
            "editor_pane_width": editor_pane_width,
            "editor_height": editor_height,
            "custom_bg": _clean_color(data.get("custom_bg", current.get("custom_bg", ""))),
            "custom_text": _clean_color(data.get("custom_text", current.get("custom_text", ""))),
            "custom_primary": _clean_color(data.get("custom_primary", current.get("custom_primary", ""))),
            "custom_secondary": _clean_color(data.get("custom_secondary", current.get("custom_secondary", ""))),
            "custom_accent": _clean_color(data.get("custom_accent", current.get("custom_accent", ""))),
            "custom_sidebar": _clean_color(data.get("custom_sidebar", current.get("custom_sidebar", ""))),
        }

        line_height = data.get("line_height", current.get("line_height", 0))
        try:
            line_height = int(line_height)
        except (TypeError, ValueError):
            line_height = 0
        if line_height not in _VALID_LINE_HEIGHTS:
            line_height = 0
        prefs["line_height"] = line_height

        letter_spacing = data.get("letter_spacing", current.get("letter_spacing", 0))
        try:
            letter_spacing = int(letter_spacing)
        except (TypeError, ValueError):
            letter_spacing = 0
        if letter_spacing not in _VALID_LETTER_SPACINGS:
            letter_spacing = 0
        prefs["letter_spacing"] = letter_spacing

        reduce_motion = data.get("reduce_motion", current.get("reduce_motion", 0))
        try:
            reduce_motion = 1 if reduce_motion else 0
        except (TypeError, ValueError):
            reduce_motion = 0
        prefs["reduce_motion"] = reduce_motion
        db.save_user_accessibility(user["id"], prefs)
        return jsonify({"ok": True})

    @app.route("/api/accessibility/reset", methods=["POST"])
    @login_required
    @rate_limit(10, 60)
    def api_reset_accessibility():
        user = get_current_user()
        db.save_user_accessibility(user["id"], dict(db._A11Y_DEFAULTS))
        return jsonify({"ok": True, "defaults": db._A11Y_DEFAULTS})

    # -----------------------------------------------------------------------
    #  Reorder API
    # -----------------------------------------------------------------------
    @app.route("/api/reorder/pages", methods=["POST"])
    @login_required
    @editor_required
    @rate_limit(60, 60)
    def api_reorder_pages():
        """Persist a new page sort order. Body: {"ids": [<page_id>, ...]}"""
        data = request.get_json(silent=True)
        if not data or not isinstance(data.get("ids"), list):
            return jsonify({"error": "invalid request"}), 400
        try:
            ids = [int(i) for i in data["ids"]]
        except (TypeError, ValueError):
            return jsonify({"error": "invalid ids"}), 400
        db.update_pages_sort_order(ids)
        user = get_current_user()
        wiki_logger.log_action("reorder_pages", request, user=user, count=len(ids))
        notify_change("pages_reorder", "Page order updated")
        return jsonify({"ok": True})

    @app.route("/api/reorder/categories", methods=["POST"])
    @login_required
    @editor_required
    @rate_limit(60, 60)
    def api_reorder_categories():
        """Persist a new category sort order. Body: {"ids": [<cat_id>, ...]}"""
        data = request.get_json(silent=True)
        if not data or not isinstance(data.get("ids"), list):
            return jsonify({"error": "invalid request"}), 400
        try:
            ids = [int(i) for i in data["ids"]]
        except (TypeError, ValueError):
            return jsonify({"error": "invalid ids"}), 400
        db.update_categories_sort_order(ids)
        user = get_current_user()
        wiki_logger.log_action("reorder_categories", request, user=user, count=len(ids))
        notify_change("categories_reorder", "Category order updated")
        return jsonify({"ok": True})

    # -----------------------------------------------------------------------
    #  Public API v1 – read-only, token auth optional
    # -----------------------------------------------------------------------

    def _resolve_api_user():
        """Return user from session or API token, whichever is available."""
        user = get_current_user()
        if user:
            return user
        return get_user_from_api_token()

    def _has_elevated_access(user):
        """Return True if *user* has editor/admin access."""
        return bool(user and user["role"] in ("editor", "admin", "protected_admin"))

    @app.route("/api/v1/pages")
    @rate_limit(120, 60)
    def api_v1_pages():
        """List all pages.

        Authenticated editors and admins also see de-indexed pages.
        No authentication required for public pages.
        """
        user = _resolve_api_user()
        pages = db.list_pages(include_deindexed=_has_elevated_access(user))
        return jsonify([
            {
                "id": p["id"],
                "title": p["title"],
                "slug": p["slug"],
                "category_id": p["category_id"],
                "last_edited_at": p["last_edited_at"],
            }
            for p in pages
        ])

    @app.route("/api/v1/pages/<slug>")
    @rate_limit(120, 60)
    def api_v1_page(slug):
        """Get a single page by slug."""
        page = db.get_page_by_slug(slug)
        if not page:
            return jsonify({"error": "page not found"}), 404
        user = _resolve_api_user()
        if page["is_deindexed"] and not _has_elevated_access(user):
            return jsonify({"error": "page not found"}), 404
        return jsonify({
            "id": page["id"],
            "title": page["title"],
            "slug": page["slug"],
            "content": page["content"],
            "category_id": page["category_id"],
            "last_edited_at": page["last_edited_at"],
            "created_at": page["created_at"],
        })

    @app.route("/api/v1/search")
    @rate_limit(60, 60)
    def api_v1_search():
        """Search pages by title/content."""
        query = request.args.get("q", "").strip()
        if not query:
            return jsonify([])
        user = _resolve_api_user()
        results = db.search_pages(query, include_deindexed=_has_elevated_access(user))
        return jsonify([{"title": r["title"], "slug": r["slug"]} for r in results])

    @app.route("/api/v1/categories")
    @rate_limit(120, 60)
    def api_v1_categories():
        """List all categories."""
        cats = db.list_categories()
        return jsonify([
            {
                "id": c["id"],
                "name": c["name"],
                "parent_id": c["parent_id"],
                "sort_order": c["sort_order"],
            }
            for c in cats
        ])

    @app.route("/api/v1/me")
    @rate_limit(60, 60)
    def api_v1_me():
        """Return the authenticated user's basic profile.

        Requires a valid API token (or active session).
        """
        user = _resolve_api_user()
        if not user:
            return jsonify({"error": "authentication required"}), 401
        return jsonify({
            "id": user["id"],
            "username": user["username"],
            "role": user["role"],
        })
