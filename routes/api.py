"""
BananaWiki – JSON API routes (search, preview, drafts, accessibility, reorder).
"""

import re

from flask import request, jsonify, session, flash
import db
import config
from helpers import (
    login_required, editor_required, admin_required, get_current_user,
    render_markdown, rate_limit, format_datetime, editor_has_category_access,
    user_can_view_page,
)
import wiki_logger
from sync import notify_change
from routes.uploads import cleanup_unused_uploads


def register_api_routes(app):
    """Register JSON API routes on the Flask app."""

    def _get_editable_page_or_response(page_id, user):
        """Return ``(page, None)`` for allowed editors or an error response tuple.

        Draft-related editor APIs should enforce the same category write-access
        checks as the full edit page route so restricted editors cannot bypass
        category restrictions through background AJAX calls.
        """
        page = db.get_page(page_id)
        if not page:
            return None, (jsonify({"error": "page not found"}), 404)
        if not editor_has_category_access(user, page["category_id"]):
            return None, (
                jsonify({"error": "You do not have permission to edit pages in this category"}),
                403,
            )
        return page, None

    def _get_reorder_pages_error_response(page_ids, user):
        """Return an error response when *user* cannot reorder *page_ids*."""
        for page_id in page_ids:
            _, error = _get_editable_page_or_response(page_id, user)
            if error:
                return error
        return None

    def _get_reorder_categories_error_response(category_ids, user):
        """Return an error response when *user* cannot reorder *category_ids*."""
        for category_id in category_ids:
            category = db.get_category(category_id)
            if not category:
                return jsonify({"error": "Category not found"}), 404
            if not editor_has_category_access(user, category_id):
                return jsonify({"error": "You do not have permission to edit categories."}), 403
        return None

    @app.route("/api/pages/search")
    @login_required
    @rate_limit(60, 60)
    def api_pages_search():
        """Search wiki pages by title; returns JSON list of ``{title, slug}`` objects."""
        query = request.args.get("q", "").strip()
        if not query:
            return jsonify([])
        user = get_current_user()
        include_deindexed = bool(user and db.has_permission(user, "page.view_deindexed"))
        results = db.search_pages(query, include_deindexed=include_deindexed)
        filtered = [r for r in results if user_can_view_page(user, r)]
        return jsonify([{"title": r["title"], "slug": r["slug"]} for r in filtered])

    @app.route("/api/sidebar/search")
    @login_required
    @rate_limit(60, 60)
    def api_sidebar_search():
        """Sidebar search: returns matching categories and pages as JSON.

        Query parameters:
          q             – search term (required, min 1 char)
          scope         – "title" (default) or "content" (also searches page body)

        Response::

            {
              "categories": [{"id": 1, "name": "...", "parent_id": null}, ...],
              "pages":       [{"id": 1, "title": "...", "slug": "...", "category_id": null}, ...]
            }
        """
        query = request.args.get("q", "").strip()
        if not query:
            return jsonify({"categories": [], "pages": []})
        scope = request.args.get("scope", "title")
        search_content = scope == "content"
        user = get_current_user()
        include_deindexed = bool(user and db.has_permission(user, "page.view_deindexed"))
        pages = db.search_pages_full(query, include_deindexed=include_deindexed,
                                     search_content=search_content)
        categories = db.search_categories(query)
        filtered_pages = [p for p in pages if user_can_view_page(user, p)]
        reservation_map = db.get_active_page_reservations_map(
            user["id"] if user else None,
            [p["id"] for p in filtered_pages],
        )
        return jsonify({
            "categories": categories,
            "pages": [
                {
                    **p,
                    "is_reserved": bool(reservation_map.get(p["id"], {}).get("is_reserved")),
                    "reserved_by_current_user": bool(
                        reservation_map.get(p["id"], {}).get("reserved_by_current_user")
                    ),
                    "reservation_label": reservation_map.get(p["id"], {}).get("reservation_label"),
                    "user_in_cooldown": bool(
                        reservation_map.get(p["id"], {}).get("user_in_cooldown")
                    ),
                    "cooldown_label": reservation_map.get(p["id"], {}).get("cooldown_label"),
                }
                for p in filtered_pages
            ],
        })

    # -----------------------------------------------------------------------
    #  Live preview API
    # -----------------------------------------------------------------------
    @app.route("/api/preview", methods=["POST"])
    @login_required
    @rate_limit(30, 60)
    def api_preview():
        """Render a Markdown string and return the sanitised HTML as JSON."""
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
        """Autosave: insert or update the current user's draft for a page."""
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
        _, error_response = _get_editable_page_or_response(page_id, user)
        if error_response:
            return error_response
        db.save_draft(page_id, user["id"], title, content)
        return jsonify({"ok": True, "message": "Draft saved successfully."})

    @app.route("/api/draft/load/<int:page_id>")
    @login_required
    @editor_required
    def api_load_draft(page_id):
        """Return the current user's saved draft for *page_id*, or nulls if none exists."""
        user = get_current_user()
        _, error_response = _get_editable_page_or_response(page_id, user)
        if error_response:
            return error_response
        draft = db.get_draft(page_id, user["id"])
        if draft:
            return jsonify({"title": draft["title"], "content": draft["content"],
                            "updated_at": draft["updated_at"]})
        return jsonify({"title": None, "content": None})

    @app.route("/api/draft/others/<int:page_id>")
    @login_required
    @editor_required
    def api_other_drafts(page_id):
        """Return a list of other editors' drafts for *page_id* (conflict detection)."""
        user = get_current_user()
        page, error_response = _get_editable_page_or_response(page_id, user)
        if error_response:
            return error_response
        drafts = db.get_drafts_for_page(page_id)
        others = [{"username": d["username"], "user_id": d["user_id"],
                   "updated_at": d["updated_at"]} for d in drafts if d["user_id"] != user["id"]]
        return jsonify({"drafts": others, "page_last_edited_at": page["last_edited_at"]})

    @app.route("/api/draft/transfer", methods=["POST"])
    @login_required
    @editor_required
    @rate_limit(30, 60)
    def api_transfer_draft():
        """Transfer another editor's draft to the current user (editor or admin)."""
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
        _, error_response = _get_editable_page_or_response(page_id, user)
        if error_response:
            return error_response
        if from_user == user["id"]:
            return jsonify({"error": "cannot transfer draft from yourself"}), 400
        source_draft = db.get_draft(page_id, from_user)
        if not source_draft:
            return jsonify({"error": "draft not found"}), 404
        db.transfer_draft(page_id, from_user, user["id"])
        wiki_logger.log_action("transfer_draft", request, user=user, page_id=page_id, from_user=from_user)
        flash("Draft has been successfully transferred to your account.", "success")
        return jsonify({"ok": True, "message": "Draft has been successfully transferred to your account."})

    @app.route("/api/draft/delete", methods=["POST"])
    @login_required
    @editor_required
    @rate_limit(30, 60)
    def api_delete_draft():
        """Delete the current user's draft for the given page."""
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
        _, error_response = _get_editable_page_or_response(page_id, user)
        if error_response:
            return error_response
        db.delete_draft(page_id, user["id"])
        cleanup_unused_uploads()
        flash("Draft has been successfully deleted.", "success")
        return jsonify({"ok": True, "message": "Draft has been successfully deleted."})

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
            if editor_has_category_access(user, d["page_category_id"])
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
        """Return the current user's accessibility preferences as JSON."""
        user = get_current_user()
        return jsonify(db.get_user_accessibility(user["id"]))

    @app.route("/api/accessibility", methods=["POST"])
    @login_required
    @rate_limit(60, 60)
    def api_save_accessibility():
        """Save the current user's accessibility preferences from a JSON body."""
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
            """Return *val* unchanged if it is a valid CSS hex or rgb() color; otherwise return empty string."""
            val = str(val).strip()
            if not val:
                return ""
            if re.match(r'^#[0-9a-fA-F]{6}$', val):
                return val
            if re.match(r'^rgb\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)$', val):
                return val
            return ""

        theme_mode = str(data.get("theme_mode", current.get("theme_mode", "default"))).strip().lower()
        if theme_mode not in {"default", "dark", "light"}:
            theme_mode = "default"

        prefs = {
            "theme_mode": theme_mode,
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
        return jsonify({"ok": True, "message": "Customization settings saved successfully."})

    @app.route("/api/accessibility/reset", methods=["POST"])
    @login_required
    @rate_limit(10, 60)
    def api_reset_accessibility():
        """Reset the current user's accessibility preferences to the system defaults."""
        user = get_current_user()
        db.save_user_accessibility(user["id"], dict(db._A11Y_DEFAULTS))
        return jsonify({
            "ok": True,
            "message": "Customization settings have been reset to default.",
            "defaults": db._A11Y_DEFAULTS,
        })

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
        user = get_current_user()
        error = _get_reorder_pages_error_response(ids, user)
        if error:
            return error
        db.update_pages_sort_order(ids)
        wiki_logger.log_action("reorder_pages", request, user=user, count=len(ids))
        notify_change("pages_reorder", "Page order updated")
        return jsonify({"ok": True, "message": "Page order saved successfully."})

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
        user = get_current_user()
        error = _get_reorder_categories_error_response(ids, user)
        if error:
            return error
        db.update_categories_sort_order(ids)
        wiki_logger.log_action("reorder_categories", request, user=user, count=len(ids))
        notify_change("categories_reorder", "Category order updated")
        return jsonify({"ok": True, "message": "Category order saved successfully."})

    # -----------------------------------------------------------------------
    #  Page Reservation API
    # -----------------------------------------------------------------------
    @app.route("/api/pages/<int:page_id>/reservation/status")
    @login_required
    @editor_required
    def api_page_reservation_status(page_id):
        """Get current reservation status for a page."""
        user = get_current_user()
        if not db.reservations_enabled():
            return jsonify({"error": "Page reservations are currently disabled"}), 403
        page = db.get_page(page_id)
        if not page:
            return jsonify({"error": "Page not found"}), 404

        # Check if user has category access
        if not editor_has_category_access(user, page["category_id"]):
            return jsonify({"error": "You do not have permission to access this page"}), 403

        status = db.get_page_reservation_status(page_id, user["id"])

        # Format time remaining for display
        response = {
            "is_reserved": status["is_reserved"],
            "reserved_by": status["reserved_by"],
            "reserved_by_username": status["reserved_by_username"],
            "reserved_at": status["reserved_at"],
            "expires_at": status["expires_at"],
            "user_in_cooldown": status.get("user_in_cooldown", False),
            "cooldown_until": status.get("cooldown_until"),
        }

        # Add human-readable time remaining
        if status["time_remaining"]:
            total_seconds = int(status["time_remaining"].total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            response["time_remaining_text"] = f"{hours}h {minutes}m"
        else:
            response["time_remaining_text"] = None

        # Add human-readable cooldown remaining
        if status.get("cooldown_remaining"):
            total_seconds = int(status["cooldown_remaining"].total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            response["cooldown_remaining_text"] = f"{hours}h {minutes}m"
        else:
            response["cooldown_remaining_text"] = None

        return jsonify(response)

    @app.route("/api/pages/<int:page_id>/reservation", methods=["POST"])
    @login_required
    @editor_required
    @rate_limit(30, 60)
    def api_reserve_page(page_id):
        """Reserve a page for exclusive editing."""
        user = get_current_user()
        if not db.reservations_enabled():
            return jsonify({"error": "Page reservations are currently disabled"}), 403
        page = db.get_page(page_id)
        if not page:
            return jsonify({"error": "Page not found"}), 404

        # Check if user has category access
        if not editor_has_category_access(user, page["category_id"]):
            return jsonify({"error": "You do not have permission to edit pages in this category"}), 403

        try:
            reservation = db.reserve_page(page_id, user["id"])
            wiki_logger.log_action("reserve_page", request, user=user, page_id=page_id)
            notify_change("page_reservation", f"Page '{page['title']}' reserved by {user['username']}")
            return jsonify({
                "ok": True,
                "message": "Page has been successfully reserved for your editing.",
                "reservation": {
                    "page_id": reservation["page_id"],
                    "reserved_at": reservation["reserved_at"],
                    "expires_at": reservation["expires_at"],
                }
            })
        except ValueError as e:
            return jsonify({"error": str(e)}), 409

    @app.route("/api/pages/<int:page_id>/reservation", methods=["DELETE"])
    @login_required
    @editor_required
    @rate_limit(30, 60)
    def api_release_page_reservation(page_id):
        """Release a page reservation."""
        user = get_current_user()
        if not db.reservations_enabled():
            return jsonify({"error": "Page reservations are currently disabled"}), 403
        page = db.get_page(page_id)
        if not page:
            return jsonify({"error": "Page not found"}), 404

        # Check if user has category access
        if not editor_has_category_access(user, page["category_id"]):
            return jsonify({"error": "You do not have permission to edit pages in this category"}), 403

        # Release the reservation (only if user holds it)
        released = db.release_page_reservation(page_id, user["id"])
        if released:
            wiki_logger.log_action("release_page_reservation", request, user=user, page_id=page_id)
            notify_change("page_reservation", f"Page '{page['title']}' reservation released by {user['username']}")
            return jsonify({"ok": True, "message": "Page reservation has been successfully released."})
        else:
            return jsonify({"error": "No active reservation found for this page by you"}), 404
