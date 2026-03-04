"""
BananaWiki – User account and profile routes.
"""

from flask import (render_template, request, redirect, url_for, session, flash, send_file, abort)
import io
import json
import os
import sqlite3
import uuid
import zipfile
from PIL import Image
from werkzeug.security import generate_password_hash, check_password_hash
import db
import config
from helpers import (
    login_required, admin_required, get_current_user,
    allowed_file, _is_valid_username, _is_valid_hex_color,
    rate_limit, _safe_referrer, ROLE_LABELS, render_markdown,
    format_datetime,
)
from wiki_logger import log_action
from sync import notify_change, notify_file_upload, notify_file_deleted


def register_user_routes(app):
    """Register user account and profile routes on the Flask app."""

    def _profile_next(fallback):
        """Return next_url from the current form post if it is a safe same-site path, else fallback."""
        url = request.form.get("next_url", "").strip()
        # Only accept simple same-site paths: must start with / but not // and contain no backslashes
        if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
            return url
        return fallback

    @app.route("/account", methods=["GET", "POST"])
    @login_required
    @rate_limit(10, 60)
    def account_settings():
        """Display and handle the user's account settings page (username, password, profile, avatar)."""
        user = get_current_user()
        action = request.form.get("action", "") if request.method == "POST" else ""

        if action == "change_username":
            if user["is_superuser"]:
                flash("This account is protected and cannot be modified.", "error")
                return redirect(url_for("account_settings"))
            new_username = request.form.get("new_username", "").strip()
            password = request.form.get("password", "")
            if not check_password_hash(user["password"], password):
                flash("Incorrect password.", "error")
            elif len(new_username) < 3:
                flash("Username must be at least 3 characters.", "error")
            elif len(new_username) > 50:
                flash("Username must be 50 characters or fewer.", "error")
            elif not _is_valid_username(new_username):
                flash("Username may only contain letters, digits, underscores and hyphens.", "error")
            elif db.get_user_by_username(new_username) and new_username.lower() != user["username"].lower():
                flash("Username already taken.", "error")
            else:
                try:
                    db.update_user(user["id"], username=new_username)
                except sqlite3.IntegrityError:
                    flash("Username already taken.", "error")
                    return redirect(url_for("account_settings"))
                else:
                    db.record_username_change(user["id"], user["username"], new_username)
                    log_action("change_username", request, user=user, new_username=new_username)
                    notify_change("user_change_username", f"User '{user['username']}' renamed to '{new_username}'")
                    flash("Username updated.", "success")
            return redirect(url_for("account_settings"))

        if action == "change_password":
            if user["is_superuser"]:
                flash("This account is protected and cannot be modified.", "error")
                return redirect(url_for("account_settings"))
            current_pw = request.form.get("current_password", "")
            new_pw = request.form.get("new_password", "")
            confirm_pw = request.form.get("confirm_password", "")
            if not check_password_hash(user["password"], current_pw):
                flash("Incorrect current password.", "error")
            elif new_pw != confirm_pw:
                flash("New passwords do not match.", "error")
            elif len(new_pw) < 6:
                flash("Password must be at least 6 characters.", "error")
            else:
                db.update_user(user["id"], password=generate_password_hash(new_pw))
                log_action("change_password", request, user=user)
                notify_change("user_change_password", f"User '{user['username']}' changed password")
                flash("Password updated.", "success")
            return redirect(url_for("account_settings"))

        if action == "delete_account":
            if user["is_superuser"]:
                flash("This account is protected and cannot be deleted.", "error")
                return redirect(url_for("account_settings"))
            password = request.form.get("password", "")
            if not check_password_hash(user["password"], password):
                flash("Incorrect password.", "error")
                return redirect(url_for("account_settings"))
            if user["role"] in ("admin", "protected_admin") and db.count_admins() <= 1:
                flash("Cannot delete the last admin account.", "error")
                return redirect(url_for("account_settings"))
            log_action("delete_account", request, user=user)
            notify_change("user_delete_account", f"User '{user['username']}' deleted their account")
            profile = db.get_user_profile(user["id"])
            db.delete_user(user["id"])
            if profile and profile["avatar_filename"]:
                old_path = os.path.join(config.UPLOAD_FOLDER, profile["avatar_filename"])
                if os.path.isfile(old_path):
                    os.remove(old_path)
                notify_file_deleted(profile["avatar_filename"])
            session.clear()
            flash("Your account has been deleted.", "info")
            return redirect(url_for("login"))

        if action == "toggle_protected_admin":
            if user["role"] not in ("admin", "protected_admin"):
                flash("Only admins can toggle protected admin status.", "error")
                return redirect(url_for("account_settings"))
            password = request.form.get("password", "")
            if not check_password_hash(user["password"], password):
                flash("Incorrect password.", "error")
                return redirect(url_for("account_settings"))
            if user["role"] == "admin":
                db.update_user(user["id"], role="protected_admin")
                db.record_role_change(user["id"], "admin", "protected_admin", changed_by=user["id"])
                log_action("enable_protected_admin", request, user=user)
                notify_change("user_enable_protected_admin", f"User '{user['username']}' enabled protected admin status")
                flash("Protected admin status enabled.", "success")
            else:
                db.update_user(user["id"], role="admin")
                db.record_role_change(user["id"], "protected_admin", "admin", changed_by=user["id"])
                log_action("disable_protected_admin", request, user=user)
                notify_change("user_disable_protected_admin", f"User '{user['username']}' disabled protected admin status")
                flash("Protected admin status disabled.", "success")
            return redirect(url_for("account_settings"))

        if action == "update_profile":
            real_name = request.form.get("real_name", "").strip()[:100]
            bio = request.form.get("bio", "").strip()[:500]
            avatar_file = request.files.get("avatar")
            profile = db.get_user_profile(user["id"])
            old_avatar = profile["avatar_filename"] if profile else ""
            new_avatar = old_avatar
            if avatar_file and avatar_file.filename:
                if not allowed_file(avatar_file.filename):
                    flash("Invalid avatar file type.", "error")
                    return redirect(url_for("account_settings"))
                # 1 MB limit for avatars
                avatar_file.stream.seek(0, 2)
                size = avatar_file.stream.tell()
                avatar_file.stream.seek(0)
                if size > 1 * 1024 * 1024:
                    flash("Avatar must be 1 MB or smaller.", "error")
                    return redirect(url_for("account_settings"))
                try:
                    img = Image.open(avatar_file.stream)
                    img.verify()
                    avatar_file.stream.seek(0)
                except Exception:
                    flash("Avatar is not a valid image.", "error")
                    return redirect(url_for("account_settings"))
                avatar_dir = os.path.join(config.UPLOAD_FOLDER, "avatars")
                os.makedirs(avatar_dir, exist_ok=True)
                ext = avatar_file.filename.rsplit(".", 1)[1].lower()
                new_avatar = f"avatars/{uuid.uuid4().hex}.{ext}"
                save_path = os.path.abspath(os.path.join(config.UPLOAD_FOLDER, new_avatar))
                if os.path.commonpath([os.path.abspath(config.UPLOAD_FOLDER), save_path]) != os.path.abspath(config.UPLOAD_FOLDER):
                    flash("Invalid upload path.", "error")
                    return redirect(url_for("account_settings"))
                avatar_file.save(save_path)
                notify_file_upload(new_avatar, save_path, display_name=f"Avatar for {user['username']}")
                # Remove old avatar file if different
                if old_avatar and old_avatar != new_avatar:
                    old_path = os.path.join(config.UPLOAD_FOLDER, old_avatar)
                    if os.path.isfile(old_path):
                        os.remove(old_path)
                    notify_file_deleted(old_avatar)
            db.upsert_user_profile(user["id"], real_name=real_name, bio=bio, avatar_filename=new_avatar)
            log_action("update_profile", request, user=user)
            flash("Profile updated.", "success")
            return redirect(_profile_next(url_for("account_settings")))

        if action == "remove_avatar":
            profile = db.get_user_profile(user["id"])
            if profile and profile["avatar_filename"]:
                old_path = os.path.join(config.UPLOAD_FOLDER, profile["avatar_filename"])
                if os.path.isfile(old_path):
                    os.remove(old_path)
                notify_file_deleted(profile["avatar_filename"])
                db.upsert_user_profile(user["id"], avatar_filename="")
            flash("Avatar removed.", "success")
            return redirect(_profile_next(url_for("account_settings")))

        if action == "publish_profile":
            profile = db.get_user_profile(user["id"])
            if profile and profile["page_disabled_by_admin"]:
                flash("Your profile page has been disabled by an admin.", "error")
                return redirect(url_for("account_settings"))
            db.upsert_user_profile(user["id"], page_published=True)
            log_action("publish_profile", request, user=user)
            flash("Your profile page is now public.", "success")
            return redirect(_profile_next(url_for("account_settings")))

        if action == "unpublish_profile":
            db.upsert_user_profile(user["id"], page_published=False)
            log_action("unpublish_profile", request, user=user)
            flash("Your profile page is now hidden.", "success")
            return redirect(_profile_next(url_for("account_settings")))

        if action == "delete_profile":
            profile = db.get_user_profile(user["id"])
            if profile and profile["avatar_filename"]:
                old_path = os.path.join(config.UPLOAD_FOLDER, profile["avatar_filename"])
                if os.path.isfile(old_path):
                    os.remove(old_path)
                notify_file_deleted(profile["avatar_filename"])
            db.delete_user_profile(user["id"])
            log_action("delete_profile", request, user=user)
            flash("Your profile page has been deleted.", "success")
            return redirect(_profile_next(url_for("account_settings")))

        categories, uncategorized = db.get_category_tree()
        profile = db.get_user_profile(user["id"])
        return render_template("account/settings.html", user=user,
                               categories=categories, uncategorized=uncategorized,
                               profile=profile)

    def _build_user_export_zip(user):
        """Build an in-memory ZIP file containing all exported data for a user.

        ``user`` must be a valid user row (as returned by ``db.get_user_by_id``).
        Returns a ``BytesIO`` object ready to be sent as a file download.
        """
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # Account info (exclude password hash)
            account_data = {
                "id": user["id"],
                "username": user["username"],
                "role": user["role"],
                "suspended": bool(user["suspended"]),
                "invite_code": user["invite_code"],
                "created_at": user["created_at"],
                "last_login_at": user["last_login_at"],
                "easter_egg_found": bool(user["easter_egg_found"]),
                "is_superuser": bool(user["is_superuser"]),
            }
            zf.writestr("account.json", json.dumps(account_data, indent=2))

            # Username history
            username_history = [dict(r) for r in db.get_username_history(user["id"])]
            zf.writestr("username_history.json", json.dumps(username_history, indent=2))

            # Contributions (page edits)
            contributions = [dict(r) for r in db.get_user_contributions(user["id"])]
            zf.writestr("contributions.json", json.dumps(contributions, indent=2))

            # Drafts
            drafts = [dict(r) for r in db.list_user_drafts(user["id"])]
            zf.writestr("drafts.json", json.dumps(drafts, indent=2))

            # Accessibility preferences
            accessibility = db.get_user_accessibility(user["id"])
            zf.writestr("accessibility.json", json.dumps(accessibility, indent=2))

        buf.seek(0)
        return buf

    @app.route("/account/export")
    @login_required
    def export_own_data():
        """Allow a logged-in user to download all their own data as a ZIP file."""
        user = get_current_user()
        buf = _build_user_export_zip(user)
        filename = f"userdata_{user['username']}.zip"
        log_action("export_own_data", request, user=user)
        return send_file(buf, mimetype="application/zip",
                         as_attachment=True, download_name=filename)

    # -----------------------------------------------------------------------
    #  Users – People list & profiles
    # -----------------------------------------------------------------------
    @app.route("/users")
    @login_required
    def users_list():
        """Render the People directory; admins see all users, others see published profiles."""
        query = request.args.get("q", "").strip().lower()
        current_user = get_current_user()
        if current_user["role"] in ("admin", "protected_admin"):
            users = db.list_all_users_with_profiles()
        else:
            users = db.list_published_profiles()
            # Normalise column names so template works for both result sets
            users = [dict(u) for u in users]
            for u in users:
                u.setdefault("role", "user")
                u.setdefault("suspended", 0)
                u.setdefault("page_published", 1)
                u.setdefault("page_disabled_by_admin", 0)
        if query:
            users = [u for u in users if query in u["username"].lower()
                     or query in u["real_name"].lower()]
        categories, uncategorized = db.get_category_tree()
        return render_template("users/list.html", users=users, query=query,
                               categories=categories, uncategorized=uncategorized)

    @app.route("/users/<string:username>")
    @login_required
    def user_profile(username):
        """Render a user's public profile page with contribution heatmap and role history."""
        target = db.get_user_by_username(username)
        if not target:
            abort(404)
        profile = db.get_user_profile(target["id"])
        current_user = get_current_user()
        is_admin = current_user["role"] in ("admin", "protected_admin")
        is_own = current_user["id"] == target["id"]
        # Only admins and the user themselves can view unpublished/disabled profiles
        if not (is_admin or is_own):
            if not profile or not profile["page_published"] or profile["page_disabled_by_admin"]:
                abort(404)
        contrib_year, contributions = db.get_contributions_by_day(target["id"])
        contribution_list = db.get_user_contributions(target["id"])
        role_history = db.get_role_history(target["id"])
        custom_tags = db.get_user_custom_tags(target["id"])
        categories, uncategorized = db.get_category_tree()
        all_users = db.list_users() if is_admin else []
        return render_template(
            "users/profile.html",
            target=target,
            profile=profile,
            contributions=contributions,
            contrib_year=contrib_year,
            contribution_list=contribution_list,
            is_own=is_own,
            is_admin=is_admin,
            role_labels=ROLE_LABELS,
            role_history=role_history,
            custom_tags=custom_tags,
            all_users=all_users,
            categories=categories,
            uncategorized=uncategorized,
        )
