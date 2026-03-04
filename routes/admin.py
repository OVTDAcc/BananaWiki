"""
BananaWiki – Admin panel routes (user management, settings, invites, announcements, migration).
"""

from flask import (render_template, request, redirect, url_for, session, flash, send_file, jsonify, abort)
import os, io, json, zipfile, re, uuid, sqlite3
from datetime import datetime, timezone
from urllib.parse import urlparse
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash
from PIL import Image
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones
import db
import config
from helpers import (
    login_required, admin_required, get_current_user,
    _is_valid_hex_color, _is_valid_username, rate_limit, ROLE_LABELS,
    allowed_file, format_datetime_local_input, render_markdown,
    get_site_timezone,
)
from wiki_logger import log_action, get_logger
from sync import notify_change, notify_file_upload, notify_file_deleted
from routes.users import build_user_export_zip


FAVICON_UPLOAD_FOLDER = None  # Set during register_admin_routes()


def register_admin_routes(app):
    """Register admin panel routes on the Flask app."""
    global FAVICON_UPLOAD_FOLDER

    _VALID_FAVICON_TYPES = {'yellow', 'green', 'blue', 'red', 'orange', 'cyan', 'purple', 'lime', 'custom'}
    _FAVICON_ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "ico", "gif", "webp"}
    FAVICON_UPLOAD_FOLDER = os.path.join(app.static_folder, "favicons")

    _VALID_ANN_COLORS = {"red", "orange", "yellow", "blue", "green"}
    _VALID_ANN_SIZES = {"small", "normal", "large"}
    _VALID_ANN_VISIBILITY = {"logged_in", "logged_out", "both"}

    def _allowed_favicon_file(filename):
        """Return True if *filename* has a permitted favicon extension."""
        return "." in filename and filename.rsplit(".", 1)[1].lower() in _FAVICON_ALLOWED_EXTENSIONS

    def _read_user_audit_log(username, max_entries=200):
        """Read log entries for a specific user from the log file."""
        log_file = config.LOG_FILE
        if not os.path.exists(log_file):
            return []
        entries = []
        search_term = f"user={username} "
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if search_term in line:
                        entries.append(line.strip())
            # Return most recent entries first
            return entries[-max_entries:][::-1]
        except OSError:
            return []

    # -------------------------------------------------------------------
    #  Admin – Profile moderation
    # -------------------------------------------------------------------

    @app.route("/admin/users/<string:user_id>/profile", methods=["POST"])
    @login_required
    @admin_required
    def admin_moderate_profile(user_id):
        """Admin: edit or disable a user's profile page."""
        target = db.get_user_by_id(user_id)
        if not target:
            abort(404)
        current_user = get_current_user()
        action = request.form.get("action", "")

        if target["is_superuser"]:
            flash("This account is protected and cannot be modified.", "error")
            return redirect(url_for("admin_users"))

        if target["role"] == "protected_admin" and user_id != current_user["id"]:
            flash("Protected admin accounts can only be edited by their owner.", "error")
            return redirect(url_for("admin_users"))

        if action == "edit_profile":
            real_name = request.form.get("real_name", "").strip()[:100]
            bio = request.form.get("bio", "").strip()[:500]
            db.upsert_user_profile(user_id, real_name=real_name, bio=bio)
            log_action("admin_edit_profile", request, user=current_user,
                       target_user=target["username"])
            notify_change("admin_edit_profile", f"Profile of '{target['username']}' edited")
            flash("Profile updated.", "success")

        elif action == "remove_avatar":
            profile = db.get_user_profile(user_id)
            if profile and profile["avatar_filename"]:
                old_path = os.path.join(config.UPLOAD_FOLDER, profile["avatar_filename"])
                if os.path.isfile(old_path):
                    os.remove(old_path)
                notify_file_deleted(profile["avatar_filename"])
                db.upsert_user_profile(user_id, avatar_filename="")
            log_action("admin_remove_avatar", request, user=current_user,
                       target_user=target["username"])
            notify_change("admin_remove_avatar", f"Avatar removed for '{target['username']}'")
            flash("Avatar removed.", "success")

        elif action == "disable_profile":
            db.upsert_user_profile(user_id, page_disabled_by_admin=True, page_published=False)
            log_action("admin_disable_profile", request, user=current_user,
                       target_user=target["username"])
            notify_change("admin_disable_profile", f"Profile of '{target['username']}' disabled")
            flash("Profile disabled.", "success")

        elif action == "enable_profile":
            db.upsert_user_profile(user_id, page_disabled_by_admin=False)
            log_action("admin_enable_profile", request, user=current_user,
                       target_user=target["username"])
            notify_change("admin_enable_profile", f"Profile of '{target['username']}' re-enabled")
            flash("Profile re-enabled.", "success")

        elif action == "delete_profile":
            profile = db.get_user_profile(user_id)
            if profile and profile["avatar_filename"]:
                old_path = os.path.join(config.UPLOAD_FOLDER, profile["avatar_filename"])
                if os.path.isfile(old_path):
                    os.remove(old_path)
                notify_file_deleted(profile["avatar_filename"])
            db.delete_user_profile(user_id)
            log_action("admin_delete_profile", request, user=current_user,
                       target_user=target["username"])
            notify_change("admin_delete_profile", f"Profile of '{target['username']}' deleted")
            flash("Profile deleted.", "success")

        return redirect(url_for("admin_users"))

    # -------------------------------------------------------------------
    #  Admin – User tags
    # -------------------------------------------------------------------

    @app.route("/admin/users/<string:user_id>/tags", methods=["POST"])
    @login_required
    @admin_required
    def admin_manage_user_tags(user_id):
        """Admin: add, update, delete, or reorder custom tags for a user."""
        target = db.get_user_by_id(user_id)
        if not target:
            abort(404)
        current_user = get_current_user()
        action = request.form.get("action", "")

        if target["is_superuser"]:
            flash("This account is protected and cannot be modified.", "error")
            return redirect(url_for("user_profile", username=target["username"]))

        if target["role"] == "protected_admin" and user_id != current_user["id"]:
            flash("Protected admin accounts can only be edited by their owner.", "error")
            return redirect(url_for("user_profile", username=target["username"]))

        if action == "add_tag":
            label = request.form.get("tag_label", "").strip()[:50]
            color = request.form.get("tag_color", "#9b59b6").strip()
            if not label:
                flash("Tag label is required.", "error")
            elif not _is_valid_hex_color(color):
                flash("Invalid tag color.", "error")
            else:
                db.add_user_custom_tag(user_id, label, color)
                log_action("admin_add_user_tag", request, user=current_user,
                           target_user=target["username"])
                flash("Tag added.", "success")

        elif action == "update_tag":
            tag_id = request.form.get("tag_id", type=int)
            tag = db.get_user_custom_tag(tag_id) if tag_id and tag_id > 0 else None
            if not tag or tag["user_id"] != user_id:
                flash("Tag not found.", "error")
            else:
                label = request.form.get("tag_label", "").strip()[:50]
                color = request.form.get("tag_color", "").strip()
                if not label:
                    flash("Tag label is required.", "error")
                elif not _is_valid_hex_color(color):
                    flash("Invalid tag color.", "error")
                else:
                    db.update_user_custom_tag(tag_id, label=label, color=color)
                    log_action("admin_update_user_tag", request, user=current_user,
                               target_user=target["username"])
                    flash("Tag updated.", "success")

        elif action == "delete_tag":
            tag_id = request.form.get("tag_id", type=int)
            tag = db.get_user_custom_tag(tag_id) if tag_id and tag_id > 0 else None
            if not tag or tag["user_id"] != user_id:
                flash("Tag not found.", "error")
            else:
                db.delete_user_custom_tag(tag_id)
                log_action("admin_delete_user_tag", request, user=current_user,
                           target_user=target["username"])
                flash("Tag deleted.", "success")

        elif action == "reorder_tags":
            order_str = request.form.get("tag_order", "")
            try:
                tag_ids = [int(x) for x in order_str.split(",") if x.strip()]
            except ValueError:
                tag_ids = []
            if tag_ids:
                # Validate all tag IDs belong to this user
                user_tags = db.get_user_custom_tags(user_id)
                valid_ids = {t["id"] for t in user_tags}
                if all(tid in valid_ids for tid in tag_ids):
                    db.reorder_user_custom_tags(user_id, tag_ids)
                    flash("Tag order updated.", "success")
                else:
                    flash("Invalid tag IDs.", "error")

        return redirect(url_for("user_profile", username=target["username"]))

    # -------------------------------------------------------------------
    #  Admin – Attributions
    # -------------------------------------------------------------------

    @app.route("/admin/users/<string:user_id>/attributions", methods=["POST"])
    @login_required
    @admin_required
    def admin_manage_attributions(user_id):
        """Admin: deattribute contributions or delete role history entries for a user."""
        target = db.get_user_by_id(user_id)
        if not target:
            abort(404)
        current_user = get_current_user()
        action = request.form.get("action", "")

        if target["is_superuser"]:
            flash("This account is protected and cannot be modified.", "error")
            return redirect(url_for("user_profile", username=target["username"]))

        if target["role"] == "protected_admin" and user_id != current_user["id"]:
            flash("Protected admin accounts can only be edited by their owner.", "error")
            return redirect(url_for("user_profile", username=target["username"]))

        if action == "deattribute_contribution":
            entry_id = request.form.get("entry_id", type=int)
            if not entry_id or entry_id < 1:
                flash("Invalid entry.", "error")
            else:
                entry = db.get_history_entry(entry_id)
                if not entry or entry["edited_by"] != user_id:
                    flash("Entry not found or does not belong to this user.", "error")
                else:
                    db.deattribute_contribution(entry_id)
                    log_action("admin_deattribute_contribution", request, user=current_user,
                               target_user=target["username"], entry_id=entry_id)
                    flash("Contribution deattributed.", "success")

        elif action == "deattribute_all":
            count = db.deattribute_all_user_contributions(user_id)
            log_action("admin_deattribute_all", request, user=current_user,
                       target_user=target["username"], count=count)
            notify_change("admin_deattribute_all",
                          f"All contributions ({count}) deattributed from '{target['username']}'")
            flash(f"Deattributed {count} contribution(s).", "success")

        elif action == "mass_reattribute":
            to_user_id = request.form.get("to_user_id", "").strip()
            to_user = db.get_user_by_id(to_user_id) if to_user_id else None
            if not to_user:
                flash("Invalid target user.", "error")
            elif to_user_id == user_id:
                flash("Cannot reattribute to the same user.", "error")
            else:
                count = db.mass_reattribute_contributions(user_id, to_user_id)
                log_action("admin_mass_reattribute", request, user=current_user,
                           from_user=target["username"], to_user=to_user["username"], count=count)
                notify_change("admin_mass_reattribute",
                              f"Mass reattribution: {count} entries from '{target['username']}' to '{to_user['username']}'")
                flash(f"Reattributed {count} contribution(s) to {to_user['username']}.", "success")

        elif action == "delete_role_history_entry":
            entry_id = request.form.get("entry_id", type=int)
            if not entry_id or entry_id < 1:
                flash("Invalid entry.", "error")
            else:
                rh = db.get_role_history_entry(entry_id)
                if not rh or rh["user_id"] != user_id:
                    flash("Role history entry not found.", "error")
                else:
                    db.delete_role_history_entry(entry_id)
                    log_action("admin_delete_role_history_entry", request, user=current_user,
                               target_user=target["username"], entry_id=entry_id)
                    flash("Role history entry deleted.", "success")

        elif action == "delete_all_role_history":
            count = db.delete_all_role_history(user_id)
            log_action("admin_delete_all_role_history", request, user=current_user,
                       target_user=target["username"], count=count)
            flash(f"Deleted {count} role history entries.", "success")

        return redirect(url_for("user_profile", username=target["username"]))

    # -------------------------------------------------------------------
    #  Admin – User list & editing
    # -------------------------------------------------------------------

    @app.route("/admin/users")
    @login_required
    @admin_required
    def admin_users():
        """List all registered users with optional role and status filters."""
        role_filter = request.args.get("role")
        status_filter = request.args.get("status")
        users = db.list_users(role_filter=role_filter, status_filter=status_filter)
        categories, uncategorized = db.get_category_tree()
        return render_template("admin/users.html", users=users,
                               role_filter=role_filter, status_filter=status_filter,
                               categories=categories, uncategorized=uncategorized)

    @app.route("/admin/users/<string:user_id>/edit", methods=["POST"])
    @login_required
    @admin_required
    def admin_edit_user(user_id):
        """Process all user-management actions (role change, suspend, password reset, etc.) for a single user."""
        target = db.get_user_by_id(user_id)
        if not target:
            abort(404)
        action = request.form.get("action", "")
        current_user = get_current_user()

        if target["is_superuser"]:
            flash("This account is protected and cannot be modified.", "error")
            return redirect(url_for("admin_users"))

        if action == "change_username":
            if target["role"] == "protected_admin" and user_id != current_user["id"]:
                flash("Protected admin accounts can only be edited by their owner.", "error")
                return redirect(url_for("admin_users"))
            new_name = request.form.get("username", "").strip()
            if not new_name or len(new_name) < 3:
                flash("Username must be at least 3 characters.", "error")
            elif len(new_name) > 50:
                flash("Username must be 50 characters or fewer.", "error")
            elif not _is_valid_username(new_name):
                flash("Username may only contain letters, digits, underscores and hyphens.", "error")
            else:
                existing = db.get_user_by_username(new_name)
                if existing and existing["id"] != user_id:
                    flash("Username already taken.", "error")
                else:
                    try:
                        db.update_user(user_id, username=new_name)
                    except sqlite3.IntegrityError:
                        flash("Username already taken.", "error")
                        return redirect(url_for("admin_users"))
                    else:
                        db.record_username_change(user_id, target["username"], new_name)
                        log_action("admin_change_username", request, user=current_user,
                                   target_user=target["username"], new_username=new_name)
                        notify_change("admin_change_username", f"User '{target['username']}' renamed to '{new_name}'")
                        flash("Username updated.", "success")

        elif action == "change_password":
            if target["role"] == "protected_admin" and user_id != current_user["id"]:
                flash("Protected admin accounts can only be edited by their owner.", "error")
                return redirect(url_for("admin_users"))
            new_pw = request.form.get("password", "")
            confirm_pw = request.form.get("confirm_password", "")
            if len(new_pw) < 6:
                flash("Password must be at least 6 characters.", "error")
            elif new_pw != confirm_pw:
                flash("Passwords do not match.", "error")
            else:
                db.update_user(user_id, password=generate_password_hash(new_pw))
                log_action("admin_change_password", request, user=current_user,
                           target_user=target["username"])
                notify_change("admin_change_password", f"Password changed for '{target['username']}'")
                flash("Password updated.", "success")

        elif action == "change_role":
            new_role = request.form.get("role", "")
            if new_role not in ("user", "editor", "admin"):
                flash("Invalid role.", "error")
            elif target["role"] == "protected_admin":
                flash("Protected admin status can only be changed by the account owner.", "error")
            elif user_id == current_user["id"] and new_role != current_user["role"]:
                flash("Cannot change your own role.", "error")
            elif target["role"] in ("admin", "protected_admin") and new_role not in ("admin", "protected_admin") and db.count_admins() <= 1:
                flash("Cannot demote the last admin.", "error")
            else:
                db.update_user(user_id, role=new_role)
                db.record_role_change(user_id, target["role"], new_role, changed_by=current_user["id"])
                log_action("admin_change_role", request, user=current_user,
                           target_user=target["username"], new_role=new_role)
                notify_change("admin_change_role", f"User '{target['username']}' role changed to '{new_role}'")
                flash("Role updated.", "success")

        elif action == "suspend":
            if user_id == current_user["id"]:
                flash("Cannot suspend your own account.", "error")
            elif target["role"] == "protected_admin":
                flash("Protected admin accounts cannot be suspended by other admins.", "error")
            elif target["role"] in ("admin", "protected_admin") and db.count_admins() <= 1:
                flash("Cannot suspend the last admin.", "error")
            else:
                db.update_user(user_id, suspended=1)
                log_action("admin_suspend", request, user=current_user,
                           target_user=target["username"])
                notify_change("admin_suspend", f"User '{target['username']}' suspended")
                flash("User suspended.", "success")

        elif action == "unsuspend":
            db.update_user(user_id, suspended=0)
            log_action("admin_unsuspend", request, user=current_user,
                       target_user=target["username"])
            notify_change("admin_unsuspend", f"User '{target['username']}' unsuspended")
            flash("User unsuspended.", "success")

        elif action == "delete":
            if user_id == current_user["id"]:
                flash("Cannot delete your own account from here. Use account settings instead.", "error")
            elif target["role"] == "protected_admin":
                flash("Protected admin accounts cannot be deleted by other admins.", "error")
            elif target["role"] in ("admin", "protected_admin") and db.count_admins() <= 1:
                flash("Cannot delete the last admin.", "error")
            else:
                admin_del_profile = db.get_user_profile(user_id)
                db.delete_user(user_id)
                log_action("admin_delete_user", request, user=current_user,
                           target_user=target["username"])
                notify_change("admin_delete_user", f"User '{target['username']}' deleted")
                if admin_del_profile and admin_del_profile["avatar_filename"]:
                    old_path = os.path.join(config.UPLOAD_FOLDER, admin_del_profile["avatar_filename"])
                    if os.path.isfile(old_path):
                        os.remove(old_path)
                    notify_file_deleted(admin_del_profile["avatar_filename"])
                flash("User deleted.", "success")

        return redirect(url_for("admin_users"))

    # -------------------------------------------------------------------
    #  Admin – Editor access
    # -------------------------------------------------------------------

    @app.route("/admin/users/<string:user_id>/editor-access", methods=["GET", "POST"])
    @login_required
    @admin_required
    def admin_editor_access(user_id):
        """Manage category-based access restrictions for an editor account."""
        target = db.get_user_by_id(user_id)
        if not target:
            abort(404)
        if target["role"] not in ("editor",):
            flash("Category access can only be configured for editor accounts.", "error")
            return redirect(url_for("admin_users"))

        current_user = get_current_user()
        all_categories = db.list_categories()

        if request.method == "POST":
            restricted = request.form.get("restricted") == "1"
            selected_ids = [
                int(v) for v in request.form.getlist("category_ids")
                if v.isdigit()
            ]
            db.set_editor_access(user_id, restricted, selected_ids if restricted else [])
            log_action(
                "admin_set_editor_access", request, user=current_user,
                target_user=target["username"],
                restricted=restricted,
                category_ids=selected_ids if restricted else [],
            )
            notify_change("admin_editor_access", f"Editor access updated for '{target['username']}'")
            flash("Editor access settings updated.", "success")
            return redirect(url_for("admin_editor_access", user_id=user_id))

        access = db.get_editor_access(user_id)
        categories, uncategorized = db.get_category_tree()
        return render_template(
            "admin/editor_access.html",
            target=target,
            access=access,
            all_categories=all_categories,
            categories=categories,
            uncategorized=uncategorized,
        )

    # -------------------------------------------------------------------
    #  Admin – Create user
    # -------------------------------------------------------------------

    @app.route("/admin/users/create", methods=["POST"])
    @login_required
    @admin_required
    def admin_create_user():
        """Admin: create a new user account with the specified username, password, and role."""
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        role = request.form.get("role", "user")

        if not username or not password:
            flash("Username and password are required.", "error")
        elif len(username) < 3:
            flash("Username must be at least 3 characters.", "error")
        elif len(username) > 50:
            flash("Username must be 50 characters or fewer.", "error")
        elif not _is_valid_username(username):
            flash("Username may only contain letters, digits, underscores and hyphens.", "error")
        elif password != confirm:
            flash("Passwords do not match.", "error")
        elif len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
        elif role not in ("user", "editor", "admin"):
            flash("Invalid role.", "error")
        elif db.get_user_by_username(username):
            flash("Username already taken.", "error")
        else:
            hashed = generate_password_hash(password)
            try:
                db.create_user(username, hashed, role=role)
            except sqlite3.IntegrityError:
                flash("Username already taken.", "error")
                return redirect(url_for("admin_users"))
            current_user = get_current_user()
            log_action("admin_create_user", request, user=current_user,
                       new_username=username, role=role)
            notify_change("admin_create_user", f"User '{username}' created with role '{role}'")
            flash(f"User '{username}' created.", "success")

        return redirect(url_for("admin_users"))

    # -------------------------------------------------------------------
    #  Admin – Invite codes
    # -------------------------------------------------------------------

    @app.route("/admin/codes")
    @login_required
    @admin_required
    def admin_codes():
        """Display the active invite codes management page."""
        codes = db.list_invite_codes(active_only=True)
        categories, uncategorized = db.get_category_tree()
        return render_template("admin/codes.html", codes=codes,
                               categories=categories, uncategorized=uncategorized)

    @app.route("/admin/codes/expired")
    @login_required
    @admin_required
    def admin_codes_expired():
        """Display the expired/used invite codes management page."""
        codes = db.list_expired_codes()
        categories, uncategorized = db.get_category_tree()
        return render_template("admin/codes_expired.html", codes=codes,
                               categories=categories, uncategorized=uncategorized)

    @app.route("/admin/codes/generate", methods=["POST"])
    @login_required
    @admin_required
    def admin_generate_code():
        """Generate a new invite code and redirect to the codes list."""
        user = get_current_user()
        code = db.generate_invite_code(user["id"])
        log_action("generate_invite_code", request, user=user, code=code)
        notify_change("invite_code_generate", f"Invite code '{code}' generated")
        flash(f"Invite code generated: {code}", "success")
        return redirect(url_for("admin_codes"))

    @app.route("/admin/codes/<int:code_id>/delete", methods=["POST"])
    @login_required
    @admin_required
    def admin_delete_code(code_id):
        """Soft-delete (deactivate) an active invite code."""
        user = get_current_user()
        db.delete_invite_code(code_id)
        log_action("delete_invite_code", request, user=user, code_id=code_id)
        notify_change("invite_code_delete", f"Invite code {code_id} deleted")
        flash("Invite code deleted.", "success")
        return redirect(url_for("admin_codes"))

    @app.route("/admin/codes/expired/<int:code_id>/delete", methods=["POST"])
    @login_required
    @admin_required
    def admin_hard_delete_code(code_id):
        """Permanently remove an expired or used invite code from the database."""
        user = get_current_user()
        db.hard_delete_invite_code(code_id)
        log_action("hard_delete_invite_code", request, user=user, code_id=code_id)
        notify_change("invite_code_hard_delete", f"Invite code {code_id} permanently removed")
        flash("Invite code permanently removed.", "success")
        return redirect(url_for("admin_codes_expired"))

    # -------------------------------------------------------------------
    #  Admin – Site settings
    # -------------------------------------------------------------------

    @app.route("/admin/settings", methods=["GET", "POST"])
    @login_required
    @admin_required
    def admin_settings():
        """Admin site settings page: site name, colors, timezone, favicon, lockdown mode, and session limit."""
        if request.method == "POST":
            site_name = request.form.get("site_name", "").strip() or "BananaWiki"
            if len(site_name) > 100:
                flash("Site name must be 100 characters or fewer.", "error")
                return redirect(url_for("admin_settings"))
            color_fields = {
                "primary_color": request.form.get("primary_color", "#7c8dc6"),
                "secondary_color": request.form.get("secondary_color", "#151520"),
                "accent_color": request.form.get("accent_color", "#6e8aca"),
                "text_color": request.form.get("text_color", "#b8bcc8"),
                "sidebar_color": request.form.get("sidebar_color", "#111118"),
                "bg_color": request.form.get("bg_color", "#0d0d14"),
            }
            for name, val in color_fields.items():
                if not _is_valid_hex_color(val):
                    flash(f"Invalid color value for {name}.", "error")
                    return redirect(url_for("admin_settings"))
            tz_name = request.form.get("timezone", "UTC").strip() or "UTC"
            try:
                ZoneInfo(tz_name)
            except (ZoneInfoNotFoundError, KeyError):
                flash("Invalid time zone selected.", "error")
                return redirect(url_for("admin_settings"))

            # Favicon settings
            favicon_enabled = 1 if request.form.get("favicon_enabled") else 0
            favicon_type = request.form.get("favicon_type", "yellow").strip()
            if favicon_type not in _VALID_FAVICON_TYPES:
                favicon_type = "yellow"

            current_settings = db.get_site_settings()
            favicon_custom = current_settings["favicon_custom"] if current_settings["favicon_custom"] else ""

            if favicon_type == "custom":
                f = request.files.get("favicon_custom_file")
                if f and f.filename and _allowed_favicon_file(f.filename):
                    try:
                        img = Image.open(f.stream)
                        img.verify()
                        f.stream.seek(0)
                    except Exception:
                        flash("Custom favicon is not a valid image.", "error")
                        return redirect(url_for("admin_settings"))
                    # Remove old custom favicon if present
                    if favicon_custom:
                        old_path = os.path.join(FAVICON_UPLOAD_FOLDER, favicon_custom)
                        if os.path.isfile(old_path) and favicon_custom.startswith("custom_"):
                            try:
                                os.remove(old_path)
                                notify_file_deleted(favicon_custom)
                            except OSError:
                                pass
                    os.makedirs(FAVICON_UPLOAD_FOLDER, exist_ok=True)
                    ext = f.filename.rsplit(".", 1)[1].lower()
                    favicon_custom = f"custom_{uuid.uuid4().hex}.{ext}"
                    upload_root = os.path.abspath(FAVICON_UPLOAD_FOLDER)
                    filepath = os.path.abspath(os.path.join(upload_root, favicon_custom))
                    if os.path.commonpath([upload_root, filepath]) != upload_root:
                        flash("Invalid favicon upload path.", "error")
                        return redirect(url_for("admin_settings"))
                    f.save(filepath)
                    notify_file_upload(favicon_custom, filepath, display_name="Custom favicon")

            db.update_site_settings(
                site_name=site_name,
                timezone=tz_name,
                favicon_enabled=favicon_enabled,
                favicon_type=favicon_type,
                favicon_custom=favicon_custom,
                lockdown_mode=1 if request.form.get("lockdown_mode") else 0,
                lockdown_message=request.form.get("lockdown_message", "").strip()[:1000],
                session_limit_enabled=1 if request.form.get("session_limit_enabled") else 0,
                **color_fields,
            )
            user = get_current_user()
            log_action("update_settings", request, user=user, site_name=site_name)
            notify_change("settings_update", f"Site settings updated (name='{site_name}')")
            flash("Settings updated.", "success")
            return redirect(url_for("admin_settings"))

        settings = db.get_site_settings()
        categories, uncategorized = db.get_category_tree()
        return render_template("admin/settings.html", settings=settings,
                               timezones=sorted(available_timezones()),
                               favicon_types=sorted(_VALID_FAVICON_TYPES - {"custom"}),
                               categories=categories, uncategorized=uncategorized)

    # -------------------------------------------------------------------
    #  Admin – User audit
    # -------------------------------------------------------------------

    @app.route("/admin/users/<string:user_id>/audit")
    @login_required
    @admin_required
    def admin_user_audit(user_id):
        """Admin: view the activity audit log and username history for a specific user."""
        target = db.get_user_by_id(user_id)
        if not target:
            abort(404)
        log_entries = _read_user_audit_log(target["username"])
        username_history = db.get_username_history(user_id)
        categories, uncategorized = db.get_category_tree()
        return render_template("admin/audit.html", target=target,
                               log_entries=log_entries,
                               username_history=username_history,
                               categories=categories, uncategorized=uncategorized)

    # -------------------------------------------------------------------
    #  Admin – Export user data
    # -------------------------------------------------------------------

    @app.route("/admin/users/<string:user_id>/export")
    @login_required
    @admin_required
    def admin_export_user_data(user_id):
        """Allow an admin to download all data for any user as a ZIP file."""
        target = db.get_user_by_id(user_id)
        if not target:
            abort(404)
        buf = build_user_export_zip(target)
        current_user = get_current_user()
        log_action("admin_export_user_data", request, user=current_user,
                   target_user=target["username"])
        filename = f"userdata_{target['username']}.zip"
        return send_file(buf, mimetype="application/zip",
                         as_attachment=True, download_name=filename)

    # -------------------------------------------------------------------
    #  Admin – Site migration (export / import)
    # -------------------------------------------------------------------

    @app.route("/admin/migration")
    @login_required
    @admin_required
    def admin_migration():
        """Render the site migration page."""
        user = get_current_user()
        categories, uncategorized = db.get_category_tree()
        log_action("view_migration", request, user=user)
        return render_template("admin/migration.html",
                               categories=categories, uncategorized=uncategorized)

    @app.route("/admin/migration/export", methods=["POST"])
    @login_required
    @admin_required
    def admin_migration_export():
        """Export the entire site as a ZIP containing a single JSON file."""
        user = get_current_user()
        data = db.export_site_data()
        payload = json.dumps(data, indent=2).encode("utf-8")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("site_export.json", payload)
        buf.seek(0)

        log_action("export_site", request, user=user)
        notify_change("site_export", "Full site exported")
        filename = f"site_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.zip"
        return send_file(buf, mimetype="application/zip",
                         as_attachment=True, download_name=filename)

    @app.route("/admin/migration/import", methods=["POST"])
    @login_required
    @admin_required
    def admin_migration_import():
        """Import a previously exported site ZIP."""
        user = get_current_user()
        mode = request.form.get("import_mode", "")
        if mode not in ("delete_all", "override", "keep"):
            flash("Invalid import mode selected.", "error")
            return redirect(url_for("admin_migration"))

        f = request.files.get("import_file")
        if not f or not f.filename:
            flash("No file selected.", "error")
            return redirect(url_for("admin_migration"))

        if not f.filename.lower().endswith(".zip"):
            flash("Please upload a .zip file.", "error")
            return redirect(url_for("admin_migration"))

        try:
            raw = f.read()
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                names = zf.namelist()
                json_names = [n for n in names if n.endswith(".json")]
                if not json_names:
                    flash("The uploaded archive contains no JSON data file.", "error")
                    return redirect(url_for("admin_migration"))
                with zf.open(json_names[0]) as jf:
                    data = json.load(jf)
        except zipfile.BadZipFile:
            flash("The uploaded file is not a valid ZIP archive.", "error")
            return redirect(url_for("admin_migration"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            flash("The data file inside the archive is not valid JSON.", "error")
            return redirect(url_for("admin_migration"))
        except Exception as exc:
            get_logger().warning("site import – failed to read archive: %s", exc)
            flash("Failed to read the uploaded archive.", "error")
            return redirect(url_for("admin_migration"))

        try:
            db.import_site_data(data, mode)
        except ValueError as exc:
            flash(f"Import failed: {exc}", "error")
            return redirect(url_for("admin_migration"))
        except Exception as exc:
            get_logger().exception("site import – unexpected error (mode=%s): %s", mode, exc)
            flash("An unexpected error occurred during import. The operation was rolled back.", "error")
            return redirect(url_for("admin_migration"))

        mode_labels = {
            "delete_all": "all previous data deleted, file restored",
            "override": "previous data kept, conflicts overridden",
            "keep": "previous data kept, conflicts left as-is",
        }
        log_action("import_site", request, user=user, mode=mode)
        notify_change("site_import", f"Full site imported (mode={mode})")
        flash(f"Site data imported successfully ({mode_labels[mode]}).", "success")
        return redirect(url_for("admin_migration"))

    # -------------------------------------------------------------------
    #  Admin – Announcements
    # -------------------------------------------------------------------

    @app.route("/admin/announcements")
    @login_required
    @admin_required
    def admin_announcements():
        """Display the admin announcement management page."""
        announcements = db.list_announcements()
        categories, uncategorized = db.get_category_tree()
        return render_template("admin/announcements.html",
                               announcements=announcements,
                               categories=categories, uncategorized=uncategorized)

    @app.route("/admin/announcements/create", methods=["POST"])
    @login_required
    @admin_required
    def admin_create_announcement():
        """Create a new site-wide announcement banner."""
        content = request.form.get("content", "").strip()
        color = request.form.get("color", "orange")
        text_size = request.form.get("text_size", "normal")
        visibility = request.form.get("visibility", "both")
        expires_at = request.form.get("expires_at", "").strip() or None
        not_removable = 1 if request.form.get("not_removable") else 0
        show_countdown = 1 if request.form.get("show_countdown") else 0
        user = get_current_user()

        if not content:
            flash("Announcement content is required.", "error")
            return redirect(url_for("admin_announcements"))
        if len(content) > 2000:
            flash("Announcement content must be 2000 characters or fewer.", "error")
            return redirect(url_for("admin_announcements"))
        if color not in _VALID_ANN_COLORS:
            flash("Invalid color.", "error")
            return redirect(url_for("admin_announcements"))
        if text_size not in _VALID_ANN_SIZES:
            flash("Invalid text size.", "error")
            return redirect(url_for("admin_announcements"))
        if visibility not in _VALID_ANN_VISIBILITY:
            flash("Invalid visibility.", "error")
            return redirect(url_for("admin_announcements"))
        if expires_at:
            try:
                naive = datetime.fromisoformat(expires_at)
                site_tz = get_site_timezone()
                local_dt = naive.replace(tzinfo=site_tz)
                expires_at = local_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            except ValueError:
                flash("Invalid expiration date format.", "error")
                return redirect(url_for("admin_announcements"))

        db.create_announcement(content, color, text_size, visibility, expires_at, user["id"],
                               not_removable=not_removable, show_countdown=show_countdown)
        log_action("create_announcement", request, user=user)
        notify_change("announcement_create", "Announcement created")
        flash("Announcement created.", "success")
        return redirect(url_for("admin_announcements"))

    @app.route("/admin/announcements/<int:ann_id>/edit", methods=["POST"])
    @login_required
    @admin_required
    def admin_edit_announcement(ann_id):
        """Edit an existing announcement's content, color, size, visibility, and expiry."""
        ann = db.get_announcement(ann_id)
        if not ann:
            abort(404)
        content = request.form.get("content", "").strip()
        color = request.form.get("color", "orange")
        text_size = request.form.get("text_size", "normal")
        visibility = request.form.get("visibility", "both")
        expires_at = request.form.get("expires_at", "").strip() or None
        is_active = 1 if request.form.get("is_active") else 0
        not_removable = 1 if request.form.get("not_removable") else 0
        show_countdown = 1 if request.form.get("show_countdown") else 0
        user = get_current_user()

        if not content:
            flash("Announcement content is required.", "error")
            return redirect(url_for("admin_announcements"))
        if len(content) > 2000:
            flash("Announcement content must be 2000 characters or fewer.", "error")
            return redirect(url_for("admin_announcements"))
        if color not in _VALID_ANN_COLORS:
            flash("Invalid color.", "error")
            return redirect(url_for("admin_announcements"))
        if text_size not in _VALID_ANN_SIZES:
            flash("Invalid text size.", "error")
            return redirect(url_for("admin_announcements"))
        if visibility not in _VALID_ANN_VISIBILITY:
            flash("Invalid visibility.", "error")
            return redirect(url_for("admin_announcements"))
        if expires_at:
            try:
                naive = datetime.fromisoformat(expires_at)
                site_tz = get_site_timezone()
                local_dt = naive.replace(tzinfo=site_tz)
                expires_at = local_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
            except ValueError:
                flash("Invalid expiration date format.", "error")
                return redirect(url_for("admin_announcements"))

        db.update_announcement(ann_id, content=content, color=color, text_size=text_size,
                               visibility=visibility, expires_at=expires_at, is_active=is_active,
                               not_removable=not_removable, show_countdown=show_countdown)
        log_action("edit_announcement", request, user=user, ann_id=ann_id)
        notify_change("announcement_edit", f"Announcement {ann_id} updated")
        flash("Announcement updated.", "success")
        return redirect(url_for("admin_announcements"))

    @app.route("/admin/announcements/<int:ann_id>/delete", methods=["POST"])
    @login_required
    @admin_required
    def admin_delete_announcement(ann_id):
        """Permanently delete an announcement by ID."""
        ann = db.get_announcement(ann_id)
        if not ann:
            abort(404)
        user = get_current_user()
        db.delete_announcement(ann_id)
        log_action("delete_announcement", request, user=user, ann_id=ann_id)
        notify_change("announcement_delete", f"Announcement {ann_id} deleted")
        flash("Announcement deleted.", "success")
        return redirect(url_for("admin_announcements"))

    # -------------------------------------------------------------------
    #  Public – Announcement full view
    # -------------------------------------------------------------------

    @app.route("/announcements/<int:ann_id>")
    def view_announcement(ann_id):
        """Public route: display a single announcement's full content page."""
        ann = db.get_announcement(ann_id)
        if not ann:
            abort(404)
        # Check visibility
        user = get_current_user()
        is_logged_in = bool(user)
        if ann["visibility"] == "logged_in" and not is_logged_in:
            abort(404)
        if ann["visibility"] == "logged_out" and is_logged_in:
            abort(404)
        # Check if active and not expired
        if not ann["is_active"]:
            abort(404)
        if ann["expires_at"]:
            try:
                exp = datetime.fromisoformat(ann["expires_at"]).replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) > exp:
                    abort(404)
            except ValueError:
                pass
        content_html = render_markdown(ann["content"])
        categories, uncategorized = db.get_category_tree()
        return render_template("wiki/announcement.html", ann=ann,
                               content_html=content_html,
                               categories=categories, uncategorized=uncategorized)
