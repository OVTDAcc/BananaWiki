"""
BananaWiki – Wiki page and category routes.
"""

import os

from flask import (
    render_template, request, redirect, url_for, session, flash, jsonify, abort,
)

import db
import config
from helpers import (
    login_required, editor_required, admin_required, get_current_user,
    editor_has_category_access, user_can_view_page, render_markdown, compute_char_diff,
    compute_diff_html, compute_formatted_diff_html, slugify, rate_limit,
    _is_valid_hex_color, format_datetime, ROLE_LABELS,
    _safe_referrer, time_ago,
)
from wiki_logger import log_action
from sync import notify_change, notify_file_deleted
from routes.uploads import cleanup_unused_uploads


def register_wiki_routes(app):
    """Register wiki page and category routes on the Flask app."""

    _EDITOR_ROLES = ("editor", "admin", "protected_admin")
    _ADMIN_ROLES = ("admin", "protected_admin")

    def _page_reservations_enabled():
        """Return True when the page reservation feature is enabled."""
        return db.reservations_enabled()

    def _get_reservation_context(page, user):
        """Return reservation metadata for *page* as seen by *user*."""
        if not page or page["is_home"] or not user or user["role"] not in _EDITOR_ROLES:
            return None
        if not _page_reservations_enabled():
            return None
        status = db.get_page_reservation_status(page["id"], user["id"])
        reserved_by_other = status["is_reserved"] and status["reserved_by"] != user["id"]
        admin_override = reserved_by_other and user["role"] in _ADMIN_ROLES
        return {
            "status": status,
            "reserved_by_other": reserved_by_other,
            "edit_locked": reserved_by_other and not admin_override,
            "admin_override": admin_override,
        }

    def _reservation_block_message(status, action_text):
        """Build the flash message shown when a reservation blocks an action."""
        reserved_by = status["reserved_by_username"] or "another editor"
        return (
            f"You cannot {action_text} because this page is currently reserved by {reserved_by}. "
            "Only administrators can override active reservations. Please wait for the reservation "
            "to expire or ask them to release it."
        )

    def _guard_destructive_page_edit(page, user, action_text):
        """Redirect away from a destructive edit action when reservations forbid it."""
        reservation_context = _get_reservation_context(page, user)
        if reservation_context and reservation_context["edit_locked"]:
            flash(_reservation_block_message(reservation_context["status"], action_text), "error")
            return redirect(url_for("view_page", slug=page["slug"]))
        return None

    def _abort_if_page_hidden(page, user):
        """Abort when the current user cannot view *page* under the current policy."""
        if not user_can_view_page(user, page):
            abort(403)

    def _build_reservable_page(page, category_label, user):
        """Return template-ready reservation data for a page list entry."""
        reservation_context = _get_reservation_context(page, user)
        return {
            "id": page["id"],
            "slug": page["slug"],
            "title": page["title"],
            "category_label": category_label,
            "reservation_status": reservation_context["status"] if reservation_context else None,
        }

    def _iter_reservable_pages(category_nodes, uncategorized, user):
        """Flatten category trees into a filtered list of reservable pages."""
        pages = []

        def visit(nodes, parent_label=""):
            """Recursively collect reservable pages from nested category nodes."""
            for node in nodes:
                category_label = f"{parent_label} / {node['name']}" if parent_label else node["name"]
                for page in node["pages"]:
                    if editor_has_category_access(user, page["category_id"]):
                        pages.append(_build_reservable_page(page, category_label, user))
                visit(node["children"], category_label)

        visit(category_nodes)
        for page in uncategorized:
            if editor_has_category_access(user, page["category_id"]):
                pages.append(_build_reservable_page(page, "Uncategorized", user))
        return pages

    @app.route("/")
    @login_required
    def home():
        """Render the wiki home page."""
        page = db.get_home_page()
        user = get_current_user()
        content_html = render_markdown(page["content"], embed_videos=True) if page else ""
        categories, uncategorized = db.get_category_tree()

        editor_info = None
        if page and page["last_edited_by"]:
            editor = db.get_user_by_id(page["last_edited_by"])
            if editor:
                editor_info = {
                    "username": editor["username"],
                    "time_ago": time_ago(page["last_edited_at"]),
                    "edited_at": format_datetime(page["last_edited_at"]),
                }

        log_action("view_page", request, user=user, page="home")
        return render_template(
            "wiki/page.html",
            page=page,
            content_html=content_html,
            categories=categories,
            uncategorized=uncategorized,
            editor_info=editor_info,
        )

    @app.route("/page/<slug>")
    @login_required
    def view_page(slug):
        """Render a wiki page identified by its URL slug."""
        page = db.get_page_by_slug(slug)
        if not page:
            abort(404)
        user = get_current_user()
        # Enforce the current page-visibility rules, including category access
        # restrictions and deindexed-page permissions.
        if not user_can_view_page(user, page):
            abort(403)
        content_html = render_markdown(page["content"], embed_videos=True)
        categories, uncategorized = db.get_category_tree()

        editor_info = None
        if page["last_edited_by"]:
            editor = db.get_user_by_id(page["last_edited_by"])
            if editor:
                editor_info = {
                    "username": editor["username"],
                    "time_ago": time_ago(page["last_edited_at"]),
                    "edited_at": format_datetime(page["last_edited_at"]),
                }

        log_action("view_page", request, user=user, page=slug)
        attachments = db.get_page_attachments(page["id"])
        prev_page, next_page = db.get_adjacent_pages(page["id"])

        # Get reservation status if user is an editor
        reservation_status = None
        reservation_context = _get_reservation_context(page, user)
        if reservation_context:
            reservation_status = reservation_context["status"]

        return render_template(
            "wiki/page.html",
            page=page,
            content_html=content_html,
            categories=categories,
            uncategorized=uncategorized,
            editor_info=editor_info,
            attachments=attachments,
            prev_page=prev_page,
            next_page=next_page,
            reservation_status=reservation_status,
            reservation_context=reservation_context,
        )

    @app.route("/reservations")
    @login_required
    @editor_required
    def reservation_directory():
        """List reservable pages and their current reservation state."""
        if not _page_reservations_enabled():
            flash("Page reservations are currently disabled.", "error")
            return redirect(url_for("home"))
        user = get_current_user()
        categories, uncategorized = db.get_category_tree()
        reservable_pages = _iter_reservable_pages(categories, uncategorized, user)
        return render_template(
            "wiki/reservations.html",
            reservable_pages=reservable_pages,
            categories=categories,
            uncategorized=uncategorized,
        )

    @app.route("/page/<slug>/reserve", methods=["POST"])
    @login_required
    @editor_required
    @rate_limit(30, 60)
    def reserve_page_route(slug):
        """Reserve a page from the standard web UI."""
        if not _page_reservations_enabled():
            flash("Page reservations are currently disabled.", "error")
            return redirect(_safe_referrer() or url_for("home"))
        page = db.get_page_by_slug(slug)
        if not page:
            abort(404)
        if page["is_home"]:
            flash("The home page cannot be reserved.", "error")
            return redirect(url_for("home"))
        user = get_current_user()
        if not editor_has_category_access(user, page["category_id"]):
            flash("You do not have permission to edit pages in this category.", "error")
            return redirect(url_for("view_page", slug=slug))
        try:
            db.reserve_page(page["id"], user["id"])
        except ValueError as exc:
            flash(str(exc), "error")
        else:
            log_action("reserve_page", request, user=user, page=slug)
            notify_change("page_reservation", f"Page '{page['title']}' reserved by {user['username']}")
            flash("Page has been successfully reserved for your editing.", "success")
        return redirect(_safe_referrer() or url_for("view_page", slug=slug))

    @app.route("/page/<slug>/reservation/release", methods=["POST"])
    @login_required
    @editor_required
    @rate_limit(30, 60)
    def release_page_reservation_route(slug):
        """Release a page reservation from the standard web UI."""
        if not _page_reservations_enabled():
            flash("Page reservations are currently disabled.", "error")
            return redirect(_safe_referrer() or url_for("home"))
        page = db.get_page_by_slug(slug)
        if not page:
            abort(404)
        user = get_current_user()
        if not editor_has_category_access(user, page["category_id"]):
            flash("You do not have permission to edit pages in this category.", "error")
            return redirect(url_for("view_page", slug=slug))
        if db.release_page_reservation(page["id"], user["id"]):
            log_action("release_page_reservation", request, user=user, page=slug)
            notify_change("page_reservation", f"Page '{page['title']}' reservation released by {user['username']}")
            flash("Page reservation has been successfully released.", "success")
        else:
            flash("You do not currently hold an active reservation for this page.", "error")
        return redirect(_safe_referrer() or url_for("view_page", slug=slug))

    @app.route("/page/<slug>/history")
    @login_required
    def page_history(slug):
        """Display the revision history for a wiki page."""
        if not config.PAGE_HISTORY_ENABLED:
            abort(404)
        page = db.get_page_by_slug(slug)
        if not page:
            abort(404)
        current_user = get_current_user()
        _abort_if_page_hidden(page, current_user)
        history = db.get_page_history(page["id"])
        all_users = db.list_users() if current_user and current_user["role"] in ("admin", "protected_admin") else []
        categories, uncategorized = db.get_category_tree()
        # Compute per-entry char diffs (compare each entry to the next older one)
        history_list = list(history)
        diff_stats = {}
        for idx, entry in enumerate(history_list):
            prev_content = history_list[idx + 1]["content"] if idx + 1 < len(history_list) else ""
            added, deleted = compute_char_diff(prev_content, entry["content"])
            diff_stats[entry["id"]] = {"added": added, "deleted": deleted}
        return render_template(
            "wiki/history.html",
            page=page,
            history=history_list,
            diff_stats=diff_stats,
            all_users=all_users,
            categories=categories,
            uncategorized=uncategorized,
        )

    @app.route("/page/<slug>/history/<int:entry_id>")
    @login_required
    def view_history_entry(slug, entry_id):
        """Display a specific historical revision of a wiki page with diff view."""
        if not config.PAGE_HISTORY_ENABLED:
            abort(404)
        page = db.get_page_by_slug(slug)
        if not page:
            abort(404)
        _abort_if_page_hidden(page, get_current_user())
        entry = db.get_history_entry(entry_id)
        if not entry or entry["page_id"] != page["id"]:
            abort(404)
        # Find the previous (older) history entry to diff against
        history = db.get_page_history(page["id"])
        history_list = list(history)
        prev_content = None
        for idx, h in enumerate(history_list):
            if h["id"] == entry_id and idx + 1 < len(history_list):
                prev_content = history_list[idx + 1]["content"]
                break
        if prev_content is not None:
            diff_html = compute_diff_html(prev_content, entry["content"])
            formatted_diff_html = compute_formatted_diff_html(prev_content, entry["content"])
        else:
            diff_html = None
            formatted_diff_html = None
        content_html = render_markdown(entry["content"])
        categories, uncategorized = db.get_category_tree()
        return render_template(
            "wiki/history_entry.html",
            page=page,
            entry=entry,
            content_html=content_html,
            diff_html=diff_html,
            formatted_diff_html=formatted_diff_html,
            raw_content=entry["content"],
            categories=categories,
            uncategorized=uncategorized,
        )

    @app.route("/page/<slug>/revert/<int:entry_id>", methods=["POST"])
    @login_required
    @editor_required
    @rate_limit(20, 60)
    def revert_page(slug, entry_id):
        """Revert a wiki page to a specific historical revision."""
        if not config.PAGE_HISTORY_ENABLED:
            abort(404)
        page = db.get_page_by_slug(slug)
        if not page:
            abort(404)
        user = get_current_user()
        _abort_if_page_hidden(page, user)
        entry = db.get_history_entry(entry_id)
        if not entry or entry["page_id"] != page["id"]:
            abort(404)
        if not editor_has_category_access(user, page["category_id"]):
            flash("You do not have permission to edit pages in this category.", "error")
            return redirect(url_for("view_page", slug=slug))
        db.update_page(page["id"], entry["title"], entry["content"], user["id"],
                       f"Reverted to version from {entry['created_at']}", is_revert=True)
        log_action("revert_page", request, user=user, page=slug, entry_id=entry_id)
        notify_change("page_revert", f"Page '{slug}' reverted")
        flash("Page has been successfully reverted to the selected version.", "success")
        return redirect(url_for("view_page", slug=slug))

    @app.route("/page/<slug>/history/<int:entry_id>/transfer", methods=["POST"])
    @login_required
    @admin_required
    @rate_limit(20, 60)
    def transfer_attribution(slug, entry_id):
        """Transfer authorship of a single history entry to a different user."""
        if not config.PAGE_HISTORY_ENABLED:
            abort(404)
        page = db.get_page_by_slug(slug)
        if not page:
            abort(404)
        entry = db.get_history_entry(entry_id)
        if not entry or entry["page_id"] != page["id"]:
            abort(404)
        new_user_id = request.form.get("new_user_id", "").strip()
        target_user = db.get_user_by_id(new_user_id) if new_user_id else None
        if not target_user:
            flash("The selected user is invalid. Please choose a valid user.", "error")
            return redirect(url_for("page_history", slug=slug))
        user = get_current_user()
        db.transfer_history_attribution(entry_id, new_user_id)
        log_action("transfer_attribution", request, user=user, page=slug,
                   entry_id=entry_id, new_user=target_user["username"])
        notify_change("transfer_attribution",
                      f"Attribution of entry {entry_id} on '{slug}' transferred to '{target_user['username']}'")
        flash(f"Attribution has been successfully transferred to {target_user['username']}.", "success")
        return redirect(url_for("page_history", slug=slug))

    @app.route("/page/<slug>/history/bulk-transfer", methods=["POST"])
    @login_required
    @admin_required
    @rate_limit(20, 60)
    def bulk_transfer_attribution(slug):
        """Transfer all history attributions on a page from one user to another."""
        if not config.PAGE_HISTORY_ENABLED:
            abort(404)
        page = db.get_page_by_slug(slug)
        if not page:
            abort(404)
        from_user_id = request.form.get("from_user_id", "").strip()
        new_user_id = request.form.get("new_user_id", "").strip()
        from_user = db.get_user_by_id(from_user_id) if from_user_id else None
        target_user = db.get_user_by_id(new_user_id) if new_user_id else None
        if not from_user or not target_user:
            flash("The selected users are invalid. Please verify your selection.", "error")
            return redirect(url_for("page_history", slug=slug))
        user = get_current_user()
        count = db.bulk_transfer_history_attribution(page["id"], from_user_id, new_user_id)
        log_action("bulk_transfer_attribution", request, user=user, page=slug,
                   from_user=from_user["username"], to_user=target_user["username"], count=count)
        notify_change("bulk_transfer_attribution",
                      f"Bulk attribution on '{slug}' transferred from '{from_user['username']}' to '{target_user['username']}'")
        flash(f"Successfully transferred {count} contribution(s) to {target_user['username']}.", "success")
        return redirect(url_for("page_history", slug=slug))

    @app.route("/page/<slug>/history/<int:entry_id>/deattribute", methods=["POST"])
    @login_required
    @admin_required
    @rate_limit(20, 60)
    def deattribute_entry(slug, entry_id):
        """Admin: remove attribution from a single page history entry."""
        if not config.PAGE_HISTORY_ENABLED:
            abort(404)
        page = db.get_page_by_slug(slug)
        if not page:
            abort(404)
        entry = db.get_history_entry(entry_id)
        if not entry or entry["page_id"] != page["id"]:
            abort(404)
        user = get_current_user()
        db.deattribute_contribution(entry_id)
        log_action("deattribute_entry", request, user=user, page=slug,
                   entry_id=entry_id)
        notify_change("deattribute_entry",
                      f"Attribution removed from entry {entry_id} on '{slug}'")
        flash("Attribution removed.", "success")
        return redirect(url_for("page_history", slug=slug))

    @app.route("/page/<slug>/history/<int:entry_id>/delete", methods=["POST"])
    @login_required
    @admin_required
    @rate_limit(20, 60)
    def delete_history_entry(slug, entry_id):
        """Admin: delete a single page history entry."""
        if not config.PAGE_HISTORY_ENABLED:
            abort(404)
        page = db.get_page_by_slug(slug)
        if not page:
            abort(404)
        entry = db.get_history_entry(entry_id)
        if not entry or entry["page_id"] != page["id"]:
            abort(404)
        user = get_current_user()
        db.delete_history_entry(entry_id)
        log_action("delete_history_entry", request, user=user, page=slug,
                   entry_id=entry_id)
        notify_change("delete_history_entry",
                      f"History entry {entry_id} deleted from '{slug}'")
        flash("History entry has been successfully deleted.", "success")
        return redirect(url_for("page_history", slug=slug))

    @app.route("/page/<slug>/history/clear", methods=["POST"])
    @login_required
    @admin_required
    @rate_limit(20, 60)
    def clear_page_history(slug):
        """Admin: delete all history entries for a page."""
        if not config.PAGE_HISTORY_ENABLED:
            abort(404)
        page = db.get_page_by_slug(slug)
        if not page:
            abort(404)
        user = get_current_user()
        count = db.clear_page_history(page["id"])
        log_action("clear_page_history", request, user=user, page=slug, count=count)
        notify_change("clear_page_history",
                      f"All history ({count} entries) cleared for '{slug}'")
        flash(f"All page history has been cleared ({count} entries removed).", "success")
        return redirect(url_for("page_history", slug=slug))

    # ---------------------------------------------------------------------------
    #  Page editing
    # ---------------------------------------------------------------------------
    @app.route("/page/<slug>/edit", methods=["GET", "POST"])
    @login_required
    @editor_required
    @rate_limit(20, 60)
    def edit_page(slug):
        """Display and handle submission of the page editing form."""
        page = db.get_page_by_slug(slug)
        if not page:
            abort(404)
        user = get_current_user()
        if not editor_has_category_access(user, page["category_id"]):
            flash("You do not have permission to edit pages in this category.", "error")
            return redirect(url_for("view_page", slug=slug))

        # Check reservation status
        reservation_context = _get_reservation_context(page, user)
        reservation_status = reservation_context["status"] if reservation_context else None

        if reservation_context and reservation_context["edit_locked"]:
            flash(_reservation_block_message(reservation_status, "edit this page"), "error")
            return redirect(url_for("view_page", slug=slug))

        categories, uncategorized = db.get_category_tree()

        # Check for existing drafts from other users
        other_drafts = [
            d for d in db.get_drafts_for_page(page["id"]) if d["user_id"] != user["id"]
        ]

        if request.method == "POST":
            # Verify user still has edit access (reservation may have expired)
            reservation_context = _get_reservation_context(page, user)
            reservation_status = reservation_context["status"] if reservation_context else None
            if reservation_context and reservation_context["edit_locked"]:
                flash(_reservation_block_message(reservation_status, "save changes to this page"), "error")
                return redirect(url_for("view_page", slug=slug))

            title = request.form.get("title", page["title"]).strip()
            content = request.form.get("content", "")
            edit_message = request.form.get("edit_message", "").strip()
            if not title:
                title = page["title"]

            # Collect contributor names from other users' drafts
            all_drafts = db.get_drafts_for_page(page["id"])
            contributors = [d["username"] for d in all_drafts if d["user_id"] != user["id"]]

            # Build commit message with contributors
            if contributors:
                contributor_list = ", ".join(contributors)
                if edit_message:
                    edit_message = f"{edit_message} (contributors: {contributor_list})"
                else:
                    edit_message = f"Contributors: {contributor_list}"

            db.update_page(page["id"], title, content, user["id"], edit_message)

            # Update category if provided and changed
            new_cat_id = request.form.get("category_id")
            try:
                new_cat_id = int(new_cat_id) if new_cat_id else None
            except (TypeError, ValueError):
                new_cat_id = page["category_id"]
            if new_cat_id != page["category_id"]:
                if new_cat_id and not db.get_category(new_cat_id):
                    flash("Category update skipped: the selected category no longer exists.", "error")
                elif not editor_has_category_access(user, new_cat_id):
                    flash("Category update skipped: you do not have permission to move pages into this category.", "error")
                else:
                    db.update_page_category(page["id"], new_cat_id)
                    log_action("move_page", request, user=user, page=slug, category_id=new_cat_id)

            # Update difficulty tag if provided
            tag = request.form.get("difficulty_tag", "").strip().lower()
            if tag in db.VALID_DIFFICULTY_TAGS:
                custom_label = ""
                custom_color = ""
                if tag == "custom":
                    custom_label = request.form.get("tag_custom_label", "").strip()[:50]
                    custom_color = request.form.get("tag_custom_color", "").strip()
                    if not custom_label:
                        flash("Custom tag requires a label to be specified.", "error")
                        tag = ""
                    elif not _is_valid_hex_color(custom_color):
                        flash("Custom tag requires a valid hex color code.", "error")
                        tag = ""
                if tag in db.VALID_DIFFICULTY_TAGS:
                    db.update_page_tag(page["id"], tag, custom_label, custom_color)
            elif tag:
                flash("Invalid difficulty tag.", "error")

            # Clean up all drafts for this page (committer + contributors)
            db.delete_draft(page["id"], user["id"])
            for d in all_drafts:
                if d["user_id"] != user["id"]:
                    db.delete_draft(page["id"], d["user_id"])

            cleanup_unused_uploads()
            log_action("edit_page", request, user=user, page=slug, message=edit_message)
            notify_change("page_edit", f"Page '{slug}' edited")

            # Check and award auto-triggered badges
            newly_awarded = db.check_and_award_auto_badges(user["id"])
            if newly_awarded:
                session["badge_notifications"] = session.get("badge_notifications", 0) + len(newly_awarded)

            # Reserve page if the editor requested it
            if _page_reservations_enabled() and request.form.get("reserve_after_commit") == "1" and not page["is_home"]:
                try:
                    db.reserve_page(page["id"], user["id"])
                    flash("Page has been successfully updated and reserved for your editing.", "success")
                except ValueError:
                    flash("Page has been successfully updated (reservation failed: page may already be reserved).", "success")
            else:
                flash("Page has been successfully updated.", "success")
            if page["is_home"]:
                return redirect(url_for("home"))
            return redirect(url_for("view_page", slug=slug))

        # Load draft if exists
        draft = db.get_draft(page["id"], user["id"])
        attachments = db.get_page_attachments(page["id"])
        return render_template(
            "wiki/edit.html",
            page=page,
            draft=draft,
            other_drafts=other_drafts,
            categories=categories,
            uncategorized=uncategorized,
            attachments=attachments,
            reservation_status=reservation_status,
            reservation_context=reservation_context,
        )

    @app.route("/page/<slug>/edit/title", methods=["POST"])
    @login_required
    @editor_required
    @rate_limit(20, 60)
    def edit_page_title(slug):
        """Inline title edit: update the title of a page without opening the full editor."""
        page = db.get_page_by_slug(slug)
        if not page:
            abort(404)
        user = get_current_user()
        if not editor_has_category_access(user, page["category_id"]):
            flash("You do not have permission to edit pages in this category.", "error")
            if page["is_home"]:
                return redirect(url_for("home"))
            return redirect(url_for("view_page", slug=slug))
        blocked_response = _guard_destructive_page_edit(page, user, "change this page title")
        if blocked_response:
            return blocked_response
        new_title = request.form.get("title", "").strip()
        if not new_title:
            flash("Title is required.", "error")
        elif len(new_title) > 200:
            flash("Page title cannot exceed 200 characters.", "error")
        else:
            db.update_page_title(page["id"], new_title, user["id"])
            log_action("edit_page_title", request, user=user, page=slug, new_title=new_title)
            notify_change("page_title_edit", f"Page '{slug}' title changed to '{new_title}'")
            flash("Page title has been successfully updated.", "success")
        if page["is_home"]:
            return redirect(url_for("home"))
        return redirect(url_for("view_page", slug=slug))

    # ---------------------------------------------------------------------------
    #  Page/Category CRUD (editors/admins)
    # ---------------------------------------------------------------------------
    @app.route("/create-page", methods=["GET", "POST"])
    @login_required
    @editor_required
    @rate_limit(20, 60)
    def create_page():
        """Display the new-page form and handle page creation."""
        user = get_current_user()
        categories, uncategorized = db.get_category_tree()

        if request.method == "POST":
            title = request.form.get("title", "").strip()
            content = request.form.get("content", "")
            cat_id = request.form.get("category_id")
            form_data = {
                "title": title, "content": content, "category_id": cat_id or "",
                "difficulty_tag": request.form.get("difficulty_tag", ""),
                "tag_custom_label": request.form.get("tag_custom_label", ""),
                "tag_custom_color": request.form.get("tag_custom_color", "#4a90d9"),
            }
            try:
                cat_id = int(cat_id) if cat_id else None
            except (TypeError, ValueError):
                flash("Invalid category.", "error")
                return render_template("wiki/create_page.html", categories=categories,
                                       uncategorized=uncategorized, form=form_data)
            if not title:
                flash("Title is required.", "error")
                return render_template("wiki/create_page.html", categories=categories,
                                       uncategorized=uncategorized, form=form_data)
            if len(title) > 200:
                flash("Page title cannot exceed 200 characters.", "error")
                return render_template("wiki/create_page.html", categories=categories,
                                       uncategorized=uncategorized, form=form_data)
            if cat_id and not db.get_category(cat_id):
                flash("Selected category does not exist.", "error")
                return render_template("wiki/create_page.html", categories=categories,
                                       uncategorized=uncategorized, form=form_data)
            if not editor_has_category_access(user, cat_id):
                flash("You do not have permission to create pages in this category.", "error")
                return render_template("wiki/create_page.html", categories=categories,
                                       uncategorized=uncategorized, form=form_data)
            slug = slugify(title)
            # ensure unique slug
            base_slug = slug
            counter = 1
            while db.get_page_by_slug(slug):
                slug = f"{base_slug}-{counter}"
                counter += 1
            db.create_page(title, slug, content, cat_id, user["id"])
            # Apply initial difficulty tag if specified
            tag = request.form.get("difficulty_tag", "").strip().lower()
            if tag in db.VALID_DIFFICULTY_TAGS and tag:
                custom_label = ""
                custom_color = ""
                if tag == "custom":
                    custom_label = request.form.get("tag_custom_label", "").strip()[:50]
                    custom_color = request.form.get("tag_custom_color", "").strip()
                    if not custom_label or not _is_valid_hex_color(custom_color):
                        tag = ""
                if tag:
                    page_id = db.get_page_by_slug(slug)["id"]
                    db.update_page_tag(page_id, tag, custom_label, custom_color)
            cleanup_unused_uploads()
            log_action("create_page", request, user=user, page=slug)
            notify_change("page_create", f"Page '{slug}' created")

            # Check and award auto-triggered badges
            newly_awarded = db.check_and_award_auto_badges(user["id"])
            if newly_awarded:
                session["badge_notifications"] = session.get("badge_notifications", 0) + len(newly_awarded)

            flash("Page has been successfully created. You can now open it to start editing with Markdown.", "success")
            return redirect(url_for("view_page", slug=slug))

        return render_template("wiki/create_page.html", categories=categories,
                               uncategorized=uncategorized)

    @app.route("/page/<slug>/delete", methods=["POST"])
    @login_required
    @editor_required
    @rate_limit(10, 60)
    def delete_page_route(slug):
        """Delete a wiki page (non-home pages only)."""
        page = db.get_page_by_slug(slug)
        if not page:
            abort(404)
        if page["is_home"]:
            flash("Cannot delete the home page.", "error")
            return redirect(url_for("view_page", slug=slug))
        user = get_current_user()
        if not editor_has_category_access(user, page["category_id"]):
            flash("You do not have permission to delete pages in this category.", "error")
            return redirect(url_for("view_page", slug=slug))
        blocked_response = _guard_destructive_page_edit(page, user, "delete this page")
        if blocked_response:
            return blocked_response
        db.delete_page(page["id"])
        cleanup_unused_uploads()
        log_action("delete_page", request, user=user, page=slug)
        notify_change("page_delete", f"Page '{slug}' deleted")
        flash("Page deleted.", "success")
        return redirect(url_for("home"))

    @app.route("/page/<slug>/move", methods=["POST"])
    @login_required
    @editor_required
    @rate_limit(20, 60)
    def move_page(slug):
        """Move a wiki page to a different category."""
        page = db.get_page_by_slug(slug)
        if not page:
            abort(404)
        cat_id = request.form.get("category_id")
        try:
            cat_id = int(cat_id) if cat_id else None
        except (TypeError, ValueError):
            flash("Invalid category.", "error")
            return redirect(url_for("view_page", slug=slug))
        if cat_id and not db.get_category(cat_id):
            flash("Selected category does not exist.", "error")
            return redirect(url_for("view_page", slug=slug))
        user = get_current_user()
        if not editor_has_category_access(user, page["category_id"]):
            flash("You do not have permission to move pages from this category.", "error")
            return redirect(url_for("view_page", slug=slug))
        if not editor_has_category_access(user, cat_id):
            flash("You do not have permission to move pages into this category.", "error")
            return redirect(url_for("view_page", slug=slug))
        db.update_page_category(page["id"], cat_id)
        log_action("move_page", request, user=user, page=slug, category_id=cat_id)
        notify_change("page_move", f"Page '{slug}' moved")
        flash("Page moved.", "success")
        return redirect(url_for("view_page", slug=slug))

    @app.route("/page/<slug>/tag", methods=["POST"])
    @login_required
    @editor_required
    @rate_limit(20, 60)
    def update_page_tag(slug):
        """Set or update the difficulty tag for a wiki page."""
        page = db.get_page_by_slug(slug)
        if not page:
            abort(404)
        user = get_current_user()
        if not editor_has_category_access(user, page["category_id"]):
            flash("You do not have permission to edit pages in this category.", "error")
            if page["is_home"]:
                return redirect(url_for("home"))
            return redirect(url_for("view_page", slug=slug))
        blocked_response = _guard_destructive_page_edit(page, user, "change this page tag")
        if blocked_response:
            return blocked_response
        tag = request.form.get("difficulty_tag", "").strip().lower()
        if tag not in db.VALID_DIFFICULTY_TAGS:
            flash("Invalid difficulty tag.", "error")
            if page["is_home"]:
                return redirect(url_for("home"))
            return redirect(url_for("view_page", slug=slug))
        custom_label = ""
        custom_color = ""
        if tag == "custom":
            custom_label = request.form.get("tag_custom_label", "").strip()[:50]
            custom_color = request.form.get("tag_custom_color", "").strip()
            if not custom_label:
                flash("Custom tag requires a label to be specified.", "error")
                if page["is_home"]:
                    return redirect(url_for("home"))
                return redirect(url_for("view_page", slug=slug))
            if not _is_valid_hex_color(custom_color):
                flash("Custom tag requires a valid hex color code.", "error")
                if page["is_home"]:
                    return redirect(url_for("home"))
                return redirect(url_for("view_page", slug=slug))
        db.update_page_tag(page["id"], tag, custom_label, custom_color)
        log_action("update_page_tag", request, user=user, page=slug, tag=tag)
        notify_change("page_tag", f"Page '{slug}' tag updated to '{tag}'")
        flash("Tag updated.", "success")
        if page["is_home"]:
            return redirect(url_for("home"))
        return redirect(url_for("view_page", slug=slug))

    @app.route("/category/create", methods=["POST"])
    @login_required
    @editor_required
    @rate_limit(20, 60)
    def create_category():
        """Create a new category, optionally nested under a parent category."""
        user = get_current_user()
        access = db.get_editor_access(user["id"])
        if access["restricted"]:
            flash("You do not have permission to create categories.", "error")
            return redirect(_safe_referrer() or url_for("home"))
        name = request.form.get("name", "").strip()
        parent_id = request.form.get("parent_id")
        try:
            parent_id = int(parent_id) if parent_id else None
        except (TypeError, ValueError):
            flash("Invalid parent category.", "error")
            return redirect(_safe_referrer() or url_for("home"))
        if not name:
            flash("Category name is required.", "error")
            return redirect(_safe_referrer() or url_for("home"))
        if len(name) > 100:
            flash("Category name cannot exceed 100 characters.", "error")
            return redirect(_safe_referrer() or url_for("home"))
        if parent_id and not db.get_category(parent_id):
            flash("Selected parent category does not exist.", "error")
            return redirect(_safe_referrer() or url_for("home"))
        db.create_category(name, parent_id)
        log_action("create_category", request, user=user, category=name)
        notify_change("category_create", f"Category '{name}' created")
        flash("Category has been successfully created.", "success")
        return redirect(_safe_referrer() or url_for("home"))

    @app.route("/category/<int:cat_id>/edit", methods=["POST"])
    @login_required
    @editor_required
    @rate_limit(20, 60)
    def edit_category(cat_id):
        """Rename an existing category."""
        cat = db.get_category(cat_id)
        if not cat:
            abort(404)
        user = get_current_user()
        if db.get_editor_access(user["id"])["restricted"]:
            flash("You do not have permission to edit categories.", "error")
            return redirect(_safe_referrer() or url_for("home"))
        name = request.form.get("name", "").strip()
        if not name:
            flash("Category name is required.", "error")
            return redirect(_safe_referrer() or url_for("home"))
        if len(name) > 100:
            flash("Category name cannot exceed 100 characters.", "error")
            return redirect(_safe_referrer() or url_for("home"))
        db.update_category(cat_id, name)
        log_action("edit_category", request, user=user, category_id=cat_id, new_name=name)
        notify_change("category_edit", f"Category {cat_id} renamed to '{name}'")
        flash("Category has been successfully updated.", "success")
        return redirect(_safe_referrer() or url_for("home"))

    @app.route("/category/<int:cat_id>/move", methods=["POST"])
    @login_required
    @editor_required
    @rate_limit(20, 60)
    def move_category(cat_id):
        """Move a category under a different parent in the hierarchy."""
        cat = db.get_category(cat_id)
        if not cat:
            abort(404)
        user = get_current_user()
        if db.get_editor_access(user["id"])["restricted"]:
            flash("You do not have permission to move categories.", "error")
            return redirect(_safe_referrer() or url_for("home"))
        parent_id = request.form.get("parent_id")
        try:
            parent_id = int(parent_id) if parent_id else None
        except (TypeError, ValueError):
            parent_id = None
        # Prevent moving a category into itself or a descendant (circular ref)
        if parent_id == cat_id:
            flash("Cannot move a category into itself.", "error")
            return redirect(_safe_referrer() or url_for("home"))
        if parent_id and not db.get_category(parent_id):
            flash("The target category no longer exists.", "error")
            return redirect(_safe_referrer() or url_for("home"))
        if parent_id and db.is_descendant_of(cat_id, parent_id):
            flash("Cannot move a category into one of its own subcategories.", "error")
            return redirect(_safe_referrer() or url_for("home"))
        db.update_category_parent(cat_id, parent_id)
        log_action("move_category", request, user=user, category_id=cat_id, new_parent=parent_id)
        notify_change("category_move", f"Category {cat_id} moved to parent {parent_id}")
        flash("Category has been successfully moved.", "success")
        return redirect(_safe_referrer() or url_for("home"))

    @app.route("/category/<int:cat_id>/delete", methods=["POST"])
    @login_required
    @editor_required
    @rate_limit(10, 60)
    def delete_category_route(cat_id):
        """Delete a category and handle its pages according to the chosen action."""
        cat = db.get_category(cat_id)
        if not cat:
            abort(404)
        user = get_current_user()
        if db.get_editor_access(user["id"])["restricted"]:
            flash("You do not have permission to delete categories.", "error")
            return redirect(_safe_referrer() or url_for("home"))
        page_action = request.form.get("page_action", "uncategorize")
        target_cat = request.form.get("target_category_id")
        try:
            target_cat = int(target_cat) if target_cat else None
        except (TypeError, ValueError):
            target_cat = None
        if page_action not in ("uncategorize", "delete", "move"):
            page_action = "uncategorize"
        if page_action == "move" and (not target_cat or target_cat == cat_id
                                      or not db.get_category(target_cat)):
            page_action = "uncategorize"
        db.delete_category(cat_id, page_action=page_action, target_category_id=target_cat)
        log_action("delete_category", request, user=user, category_id=cat_id, page_action=page_action)
        notify_change("category_delete", f"Category {cat_id} deleted")
        flash("Category has been successfully deleted.", "success")
        return redirect(_safe_referrer() or url_for("home"))

    @app.route("/page/<slug>/rename", methods=["POST"])
    @login_required
    @editor_required
    @rate_limit(10, 60)
    def rename_page_slug(slug):
        """Rename the URL slug of a page and rewrite all internal links atomically."""
        page = db.get_page_by_slug(slug)
        if not page:
            abort(404)
        if page["is_home"]:
            flash("Cannot change the URL of the home page.", "error")
            return redirect(url_for("home"))
        user = get_current_user()
        if not editor_has_category_access(user, page["category_id"]):
            flash("You do not have permission to edit pages in this category.", "error")
            return redirect(url_for("view_page", slug=slug))
        new_slug = request.form.get("new_slug", "").strip()
        if not new_slug:
            flash("New URL slug is required.", "error")
            return redirect(url_for("view_page", slug=slug))
        new_slug = slugify(new_slug)
        if not new_slug:
            flash("Invalid slug.", "error")
            return redirect(url_for("view_page", slug=slug))
        if new_slug == slug:
            flash("New URL is the same as the current one.", "info")
            return redirect(url_for("view_page", slug=slug))
        if db.get_page_by_slug(new_slug):
            flash("That URL slug is already in use by another page.", "error")
            return redirect(url_for("view_page", slug=slug))
        db.update_page_slug(page["id"], new_slug)
        log_action("rename_page_slug", request, user=user, page=slug, new_slug=new_slug)
        notify_change("page_rename", f"Page '{slug}' renamed to '{new_slug}'")
        flash("Page URL updated. All internal links have been updated automatically.", "success")
        return redirect(url_for("view_page", slug=new_slug))

    @app.route("/page/<slug>/deindex", methods=["POST"])
    @login_required
    @editor_required
    @rate_limit(20, 60)
    def toggle_page_deindex(slug):
        """Toggle the deindexed flag on a wiki page (hide from sidebar and search)."""
        page = db.get_page_by_slug(slug)
        if not page:
            abort(404)
        if page["is_home"]:
            flash("The home page cannot be deindexed.", "error")
            return redirect(url_for("home"))
        user = get_current_user()
        if not editor_has_category_access(user, page["category_id"]):
            flash("You do not have permission to edit pages in this category.", "error")
            return redirect(url_for("view_page", slug=slug))
        new_state = not bool(page["is_deindexed"])
        db.set_page_deindexed(page["id"], new_state)
        action = "deindexed" if new_state else "reindexed"
        log_action(f"page_{action}", request, user=user, page=slug)
        notify_change("page_deindex", f"Page '{slug}' {action}")
        flash(f"Page {action}.", "success")
        updated_page = db.get_page(page["id"])
        if user_can_view_page(user, updated_page):
            return redirect(url_for("view_page", slug=slug))
        return redirect(url_for("home"))

    @app.route("/category/<int:cat_id>/sequential-nav", methods=["POST"])
    @login_required
    @editor_required
    @rate_limit(20, 60)
    def toggle_category_sequential_nav(cat_id):
        """Toggle sequential (Prev/Next) navigation for pages in a category."""
        cat = db.get_category(cat_id)
        if not cat:
            abort(404)
        user = get_current_user()
        if db.get_editor_access(user["id"])["restricted"]:
            flash("You do not have permission to modify categories.", "error")
            return redirect(_safe_referrer() or url_for("home"))
        enabled = request.form.get("sequential_nav", "0") == "1"
        db.update_category_sequential_nav(cat_id, enabled)
        log_action("toggle_sequential_nav", request, user=user, category_id=cat_id, enabled=enabled)
        notify_change("category_sequential_nav", f"Category {cat_id} sequential navigation {'enabled' if enabled else 'disabled'}")
        flash("Sequential navigation setting updated.", "success")
        return redirect(_safe_referrer() or url_for("home"))
