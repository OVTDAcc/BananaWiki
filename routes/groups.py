"""
BananaWiki – Group chat routes.
"""

import os
import re
import uuid
import json
import zipfile
import io
from datetime import datetime, timezone, timedelta
from werkzeug.utils import secure_filename

from flask import (
    render_template, request, redirect, url_for, session, flash,
    send_file, send_from_directory, abort,
)

import db
import config
from helpers import login_required, admin_required, get_current_user, rate_limit
from wiki_logger import log_action
from sync import notify_change


def _chat_allowed_file(filename):
    """Return True if the extension is in CHAT_ALLOWED_EXTENSIONS."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in config.CHAT_ALLOWED_EXTENSIONS


def register_group_routes(app):
    """Register group chat routes on the Flask app."""

    @app.route("/groups")
    @login_required
    def group_list():
        """List all group chats the current user belongs to."""
        user = get_current_user()
        groups = db.get_user_groups(user["id"])
        total_unread_group = db.get_total_unread_group_count(user["id"])
        categories, uncategorized = db.get_category_tree()
        return render_template("groups/list.html", groups=groups,
                               total_unread_group=total_unread_group,
                               categories=categories, uncategorized=uncategorized)

    @app.route("/groups/new", methods=["GET", "POST"])
    @login_required
    def group_new():
        """Create a new group chat."""
        user = get_current_user()
        if db.is_user_chat_disabled(user["id"]):
            flash("Your chat privileges have been disabled by an administrator.", "error")
            return redirect(url_for("group_list"))
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            description = request.form.get("description", "").strip()
            if not name:
                flash("A group name is required to continue.", "error")
                return redirect(url_for("group_new"))
            if len(name) > 100:
                flash("Group name cannot exceed 100 characters.", "error")
                return redirect(url_for("group_new"))
            if len(description) > 500:
                flash("Group description cannot exceed 500 characters.", "error")
                return redirect(url_for("group_new"))
            group = db.create_group_chat(name, user["id"], description)
            db.send_group_system_message(group["id"], f"{user['username']} created the group")
            notify_change("group_create", f"Group '{name}' created by {user['username']}")
            flash("Group has been successfully created!", "success")
            return redirect(url_for("group_view", group_id=group["id"]))
        categories, uncategorized = db.get_category_tree()
        return render_template("groups/new.html",
                               categories=categories, uncategorized=uncategorized)

    @app.route("/groups/join", methods=["GET", "POST"])
    @login_required
    def group_join():
        """Join an existing group chat using an invite code."""
        user = get_current_user()
        if request.method == "POST":
            code = request.form.get("invite_code", "").strip()
            if not code:
                flash("Please enter a valid invite code.", "error")
                return redirect(url_for("group_join"))
            group = db.get_group_chat_by_invite(code)
            if not group:
                flash("The invite code you entered is invalid.", "error")
                return redirect(url_for("group_join"))
            if db.is_group_member_banned(group["id"], user["id"]):
                flash("You are currently banned from this group.", "error")
                return redirect(url_for("group_join"))
            if db.is_group_member(group["id"], user["id"]):
                flash("You are already a member of this group.", "info")
                return redirect(url_for("group_view", group_id=group["id"]))
            db.add_group_member(group["id"], user["id"])
            db.send_group_system_message(group["id"], f"{user['username']} joined the group")
            notify_change("group_join", f"{user['username']} joined group '{group['name']}'")
            flash(f"You joined {group['name']}!", "success")
            return redirect(url_for("group_view", group_id=group["id"]))
        categories, uncategorized = db.get_category_tree()
        return render_template("groups/join.html",
                               categories=categories, uncategorized=uncategorized)

    @app.route("/groups/global")
    @login_required
    def group_global():
        """Join the global chat (auto-join) and redirect to it."""
        user = get_current_user()
        group = db.get_or_create_global_chat()
        if not db.is_group_member(group["id"], user["id"]):
            db.add_group_member(group["id"], user["id"])
            db.send_group_system_message(group["id"], f"{user['username']} joined the group")
        return redirect(url_for("group_view", group_id=group["id"]))

    @app.route("/groups/<int:group_id>")
    @login_required
    def group_view(group_id):
        """View messages and member list for a group chat."""
        user = get_current_user()
        group = db.get_group_chat(group_id)
        if not group:
            abort(404)
        if not db.is_group_member(group_id, user["id"]):
            flash("You are not currently a member of this group.", "error")
            return redirect(url_for("group_list"))
        # Reset unread count when viewing the group
        db.reset_group_unread_count(group_id, user["id"])
        messages = db.get_group_messages(group_id)
        members = db.get_group_members(group_id)
        banned_members = db.get_group_banned_members(group_id)
        my_membership = db.get_group_member(group_id, user["id"])
        all_users = db.list_users()
        categories, uncategorized = db.get_category_tree()
        return render_template("groups/chat.html", group=group, messages=messages,
                               members=members, banned_members=banned_members,
                               my_membership=my_membership, all_users=all_users,
                               categories=categories, uncategorized=uncategorized)

    @app.route("/groups/<int:group_id>/send", methods=["POST"])
    @login_required
    @rate_limit(30, 60)
    def group_send(group_id):
        """Send a message (and optional file attachment) to a group chat."""
        user = get_current_user()
        if db.is_user_chat_disabled(user["id"]):
            flash("Your chat privileges have been disabled by an administrator.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        group = db.get_group_chat(group_id)
        if not group:
            abort(404)
        if group["is_global"] and not group["is_active"]:
            flash("The global chat is currently deactivated.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        if not db.is_group_member(group_id, user["id"]):
            flash("Access denied.", "error")
            return redirect(url_for("group_list"))
        if db.is_group_member_banned(group_id, user["id"]):
            flash("You are currently banned from this group.", "error")
            return redirect(url_for("group_list"))
        if db.is_group_member_timed_out(group_id, user["id"]):
            flash("You are timed out and cannot send messages.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        content = request.form.get("content", "").strip()
        if not content:
            flash("Message cannot be empty.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        if len(content) > 5000:
            flash("Message cannot exceed 5,000 characters.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        ip_address = request.remote_addr or "unknown"
        msg_id = db.send_group_message(group_id, user["id"], content, ip_address)

        # Increment unread count for all other members
        members = db.get_group_members(group_id)
        for member in members:
            if member["user_id"] != user["id"]:
                db.increment_group_unread_count(group_id, member["user_id"])

        # Handle file attachment if present
        if "attachment" in request.files:
            f = request.files["attachment"]
            if f.filename:
                # Check daily limit (use site settings if available, fall back to config)
                settings = db.get_site_settings()
                max_attachments = settings.get("chat_attachments_per_day_limit", config.MAX_CHAT_ATTACHMENTS_PER_DAY) if settings else config.MAX_CHAT_ATTACHMENTS_PER_DAY
                att_count = db.get_user_group_attachment_count_today(user["id"])
                if att_count >= max_attachments:
                    flash(f"Daily attachment limit of {max_attachments} files reached.", "error")
                    return redirect(url_for("group_view", group_id=group_id))
                if not _chat_allowed_file(f.filename):
                    flash("File type not allowed.", "error")
                    return redirect(url_for("group_view", group_id=group_id))
                original_name = secure_filename(f.filename) or "file"
                ext = original_name.rsplit(".", 1)[1].lower() if "." in original_name else "bin"
                stored_name = f"{uuid.uuid4().hex}.{ext}"
                os.makedirs(config.CHAT_ATTACHMENT_FOLDER, exist_ok=True)
                filepath = os.path.join(config.CHAT_ATTACHMENT_FOLDER, stored_name)
                file_size = 0
                chunk_size = 64 * 1024
                oversized = False
                with open(filepath, "wb") as out:
                    while True:
                        chunk = f.stream.read(chunk_size)
                        if not chunk:
                            break
                        file_size += len(chunk)
                        if file_size > config.MAX_CHAT_ATTACHMENT_SIZE:
                            oversized = True
                            break
                        out.write(chunk)
                if oversized:
                    try:
                        os.remove(filepath)
                    except OSError:
                        pass
                    flash("File exceeds the 5 MB limit.", "error")
                    return redirect(url_for("group_view", group_id=group_id))
                db.add_group_attachment(msg_id, stored_name, original_name, file_size)

        log_action("group_chat_send", request, user=user, group_id=group_id)
        return redirect(url_for("group_view", group_id=group_id))

    @app.route("/groups/attachments/<int:attachment_id>/download")
    @login_required
    def group_attachment_download(attachment_id):
        """Download a file attachment from a group chat message."""
        att = db.get_group_attachment(attachment_id)
        if not att:
            abort(404)
        user = get_current_user()
        is_admin = user["role"] in ("admin", "protected_admin")
        if not is_admin and not db.is_group_member(att["group_id"], user["id"]):
            abort(403)
        att_dir = os.path.abspath(config.CHAT_ATTACHMENT_FOLDER)
        filepath = os.path.abspath(os.path.join(att_dir, att["filename"]))
        if os.path.commonpath([att_dir, filepath]) != att_dir:
            abort(400)
        if not os.path.isfile(filepath):
            abort(404)
        return send_from_directory(att_dir, att["filename"],
                                   as_attachment=True,
                                   download_name=att["original_name"])

    # ---------------------------------------------------------------------------
    #  Group Chat – Moderation
    # ---------------------------------------------------------------------------

    @app.route("/groups/<int:group_id>/members/add", methods=["POST"])
    @login_required
    def group_add_member(group_id):
        """Add a user to a group chat (owner or moderator only)."""
        user = get_current_user()
        group = db.get_group_chat(group_id)
        if not group:
            abort(404)
        my_role = db.get_group_member_role(group_id, user["id"])
        if my_role not in ("owner", "moderator"):
            flash("You do not have permission to add members.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        username = request.form.get("username", "").strip()
        if not username:
            flash("Please enter a username.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        target = db.get_user_by_username(username)
        if not target:
            flash("The specified user was not found.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        if db.is_group_member_banned(group_id, target["id"]):
            flash("User is banned from this group. Revoke the ban first.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        if db.is_group_member(group_id, target["id"]):
            flash("User is already a member.", "info")
            return redirect(url_for("group_view", group_id=group_id))
        db.add_group_member(group_id, target["id"])
        db.send_group_system_message(group_id, f"{target['username']} was added by {user['username']}")
        notify_change("group_add_member", f"{target['username']} added to group '{group['name']}' by {user['username']}")
        flash(f"{target['username']} has been added to the group.", "success")
        return redirect(url_for("group_view", group_id=group_id))

    @app.route("/groups/<int:group_id>/leave", methods=["POST"])
    @login_required
    def group_leave(group_id):
        """Leave a group chat (owners must transfer ownership first)."""
        user = get_current_user()
        group = db.get_group_chat(group_id)
        if not group:
            abort(404)
        my_role = db.get_group_member_role(group_id, user["id"])
        if not my_role:
            flash("You are not currently a member of this group.", "error")
            return redirect(url_for("group_list"))
        if my_role == "owner" and not group["is_global"]:
            flash("You must transfer ownership before leaving.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        db.remove_group_member(group_id, user["id"])
        db.send_group_system_message(group_id, f"{user['username']} left the group")
        notify_change("group_leave", f"{user['username']} left group '{group['name']}'")
        flash("You left the group.", "success")
        return redirect(url_for("group_list"))

    @app.route("/groups/<int:group_id>/kick", methods=["POST"])
    @login_required
    def group_kick(group_id):
        """Kick (remove) a member from a group chat (owner/moderator or site admin only)."""
        user = get_current_user()
        group = db.get_group_chat(group_id)
        if not group:
            abort(404)
        my_role = db.get_group_member_role(group_id, user["id"])
        is_site_admin = user["role"] in ("admin", "protected_admin")
        if group["is_global"]:
            if not is_site_admin:
                flash("Permission denied.", "error")
                return redirect(url_for("group_view", group_id=group_id))
        else:
            if my_role not in ("owner", "moderator"):
                flash("Permission denied.", "error")
                return redirect(url_for("group_view", group_id=group_id))
        target_id = request.form.get("user_id", "")
        target_membership = db.get_group_member(group_id, target_id)
        if not target_membership:
            flash("This user is not a member of the group.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        # Moderators cannot kick other moderators or the owner
        if not is_site_admin and my_role == "moderator" and target_membership["role"] in ("owner", "moderator"):
            flash("You cannot remove a moderator or owner.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        target_user = db.get_user_by_id(target_id)
        target_name = target_user["username"] if target_user else "Unknown"
        permanent = request.form.get("permanent", "") == "1"
        if permanent:
            db.ban_group_member(group_id, target_id)
            db.send_group_system_message(group_id, f"{target_name} was banned by {user['username']}")
            notify_change("group_ban", f"{target_name} banned from group '{group['name']}' by {user['username']}")
            flash(f"{target_name} has been banned.", "success")
        else:
            db.remove_group_member(group_id, target_id)
            db.send_group_system_message(group_id, f"{target_name} was removed by {user['username']}")
            notify_change("group_kick", f"{target_name} removed from group '{group['name']}' by {user['username']}")
            flash(f"{target_name} has been removed.", "success")
        return redirect(url_for("group_view", group_id=group_id))

    @app.route("/groups/<int:group_id>/promote", methods=["POST"])
    @login_required
    def group_promote(group_id):
        """Promote a group member to moderator (owner only)."""
        user = get_current_user()
        group = db.get_group_chat(group_id)
        if not group:
            abort(404)
        my_role = db.get_group_member_role(group_id, user["id"])
        if my_role != "owner":
            flash("Only the group owner can promote members.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        target_id = request.form.get("user_id", "")
        target_membership = db.get_group_member(group_id, target_id)
        if not target_membership:
            flash("This user is not a member of the group.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        if target_membership["role"] != "member":
            flash("User is already a moderator or owner.", "info")
            return redirect(url_for("group_view", group_id=group_id))
        target_user = db.get_user_by_id(target_id)
        target_name = target_user["username"] if target_user else "Unknown"
        db.set_group_member_role(group_id, target_id, "moderator")
        db.send_group_system_message(group_id, f"{target_name} was promoted to moderator by {user['username']}")
        notify_change("group_promote", f"{target_name} promoted to moderator in '{group['name']}' by {user['username']}")
        flash(f"{target_name} is now a moderator.", "success")
        return redirect(url_for("group_view", group_id=group_id))

    @app.route("/groups/<int:group_id>/demote", methods=["POST"])
    @login_required
    def group_demote(group_id):
        """Demote a group moderator back to regular member (owner only)."""
        user = get_current_user()
        group = db.get_group_chat(group_id)
        if not group:
            abort(404)
        my_role = db.get_group_member_role(group_id, user["id"])
        if my_role != "owner":
            flash("Only the group owner can demote moderators.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        target_id = request.form.get("user_id", "")
        target_membership = db.get_group_member(group_id, target_id)
        if not target_membership or target_membership["role"] != "moderator":
            flash("User is not a moderator.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        target_user = db.get_user_by_id(target_id)
        target_name = target_user["username"] if target_user else "Unknown"
        db.set_group_member_role(group_id, target_id, "member")
        db.send_group_system_message(group_id, f"{target_name} was demoted to member by {user['username']}")
        notify_change("group_demote", f"{target_name} demoted in '{group['name']}' by {user['username']}")
        flash(f"{target_name} is no longer a moderator.", "success")
        return redirect(url_for("group_view", group_id=group_id))

    @app.route("/groups/<int:group_id>/self-downgrade", methods=["POST"])
    @login_required
    @rate_limit(10, 60)
    def group_self_downgrade(group_id):
        """Allow a moderator to voluntarily downgrade themselves to member."""
        user = get_current_user()
        group = db.get_group_chat(group_id)
        if not group:
            abort(404)
        my_role = db.get_group_member_role(group_id, user["id"])

        # Check if user is a member of the group
        if my_role is None:
            flash("You are not currently a member of this group.", "error")
            return redirect(url_for("group_view", group_id=group_id))

        # Check if user is a moderator (only moderators can self-downgrade)
        if my_role != "moderator":
            if my_role == "owner":
                flash("Owners cannot self-downgrade. Transfer ownership first.", "error")
            else:
                flash("You are already a member.", "info")
            return redirect(url_for("group_view", group_id=group_id))

        # Perform the downgrade
        db.set_group_member_role(group_id, user["id"], "member")
        db.send_group_system_message(group_id, f"{user['username']} downgraded to member")
        notify_change("group_self_downgrade", f"{user['username']} self-downgraded in '{group['name']}'")
        log_action("group_self_downgrade", request, user, group=group['name'])
        flash("You are now a regular member.", "success")
        return redirect(url_for("group_view", group_id=group_id))

    @app.route("/groups/<int:group_id>/transfer", methods=["POST"])
    @login_required
    def group_transfer(group_id):
        """Transfer group ownership to another member (current owner only)."""
        user = get_current_user()
        group = db.get_group_chat(group_id)
        if not group:
            abort(404)
        if group["is_global"]:
            flash("Cannot transfer ownership of the global chat.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        my_role = db.get_group_member_role(group_id, user["id"])
        if my_role != "owner":
            flash("Only the group owner can transfer ownership.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        target_id = request.form.get("user_id", "")
        if target_id == user["id"]:
            flash("You already own this group.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        target_membership = db.get_group_member(group_id, target_id)
        if not target_membership:
            flash("This user is not a member of the group.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        target_user = db.get_user_by_id(target_id)
        target_name = target_user["username"] if target_user else "Unknown"
        db.transfer_group_ownership(group_id, user["id"], target_id)
        db.send_group_system_message(group_id, f"{user['username']} transferred ownership to {target_name}")
        notify_change("group_transfer", f"Ownership of '{group['name']}' transferred to {target_name} by {user['username']}")
        flash(f"Ownership transferred to {target_name}. You are now a moderator.", "success")
        return redirect(url_for("group_view", group_id=group_id))

    @app.route("/groups/<int:group_id>/timeout", methods=["POST"])
    @login_required
    def group_timeout(group_id):
        """Temporarily mute a group member for a specified number of minutes."""
        user = get_current_user()
        group = db.get_group_chat(group_id)
        if not group:
            abort(404)
        my_role = db.get_group_member_role(group_id, user["id"])
        is_site_admin = user["role"] in ("admin", "protected_admin")
        # For global chat, site admins can moderate; for regular groups, owner/mod
        if group["is_global"]:
            if not is_site_admin:
                flash("Only site admins can moderate the global chat.", "error")
                return redirect(url_for("group_view", group_id=group_id))
        else:
            if my_role not in ("owner", "moderator"):
                flash("Permission denied.", "error")
                return redirect(url_for("group_view", group_id=group_id))
        target_id = request.form.get("user_id", "")
        target_membership = db.get_group_member(group_id, target_id)
        if not target_membership:
            flash("This user is not a member of the group.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        # Don't allow timing out owner or same/higher rank
        if not group["is_global"] and my_role == "moderator" and target_membership["role"] in ("owner", "moderator"):
            flash("You cannot timeout a moderator or owner.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        duration = request.form.get("duration", "").strip()
        target_user = db.get_user_by_id(target_id)
        target_name = target_user["username"] if target_user else "Unknown"
        if duration == "indefinite":
            # Far future date for indefinite timeout
            until = "9999-12-31T23:59:59+00:00"
            db.set_group_member_timeout(group_id, target_id, until)
            db.send_group_system_message(group_id, f"{target_name} was timed out indefinitely by {user['username']}")
        elif duration:
            try:
                minutes = int(duration)
                if minutes < 1:
                    raise ValueError
            except (ValueError, TypeError):
                flash("The specified duration is invalid.", "error")
                return redirect(url_for("group_view", group_id=group_id))
            until = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
            db.set_group_member_timeout(group_id, target_id, until)
            db.send_group_system_message(group_id, f"{target_name} was timed out for {minutes} minute(s) by {user['username']}")
        else:
            flash("Please specify a duration.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        notify_change("group_timeout", f"{target_name} timed out in '{group['name']}' by {user['username']}")
        flash(f"{target_name} has been timed out.", "success")
        return redirect(url_for("group_view", group_id=group_id))

    @app.route("/groups/<int:group_id>/untimeout", methods=["POST"])
    @login_required
    def group_untimeout(group_id):
        """Remove a timeout from a group member, restoring their ability to send messages."""
        user = get_current_user()
        group = db.get_group_chat(group_id)
        if not group:
            abort(404)
        my_role = db.get_group_member_role(group_id, user["id"])
        is_site_admin = user["role"] in ("admin", "protected_admin")
        if group["is_global"]:
            if not is_site_admin:
                flash("Only site admins can moderate the global chat.", "error")
                return redirect(url_for("group_view", group_id=group_id))
        else:
            if my_role not in ("owner", "moderator"):
                flash("Permission denied.", "error")
                return redirect(url_for("group_view", group_id=group_id))
        target_id = request.form.get("user_id", "")
        target_membership = db.get_group_member(group_id, target_id)
        if not target_membership:
            flash("This user is not a member of the group.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        target_user = db.get_user_by_id(target_id)
        target_name = target_user["username"] if target_user else "Unknown"
        db.set_group_member_timeout(group_id, target_id, None)
        db.send_group_system_message(group_id, f"{target_name}'s timeout was removed by {user['username']}")
        flash(f"{target_name}'s timeout has been removed.", "success")
        return redirect(url_for("group_view", group_id=group_id))

    @app.route("/groups/<int:group_id>/delete_message", methods=["POST"])
    @login_required
    def group_delete_message(group_id):
        """Delete a specific message from a group chat (moderator/owner or site admin only)."""
        user = get_current_user()
        group = db.get_group_chat(group_id)
        if not group:
            abort(404)
        my_role = db.get_group_member_role(group_id, user["id"])
        is_site_admin = user["role"] in ("admin", "protected_admin")
        if group["is_global"]:
            if not is_site_admin:
                flash("Only site admins can delete messages in the global chat.", "error")
                return redirect(url_for("group_view", group_id=group_id))
        else:
            if my_role not in ("owner", "moderator"):
                flash("Permission denied.", "error")
                return redirect(url_for("group_view", group_id=group_id))
        message_id = request.form.get("message_id", type=int)
        if not message_id:
            flash("The specified message is invalid.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        msg = db.get_group_message_by_id(message_id)
        if not msg or msg["group_id"] != group_id:
            flash("The specified Message was not found.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        files = db.delete_group_message(message_id)
        for fname in files:
            try:
                fpath = os.path.join(config.CHAT_ATTACHMENT_FOLDER, fname)
                if os.path.isfile(fpath):
                    os.remove(fpath)
            except OSError:
                pass
        db.send_group_system_message(group_id, f"A message was deleted by {user['username']}")
        flash("Message has been successfully deleted.", "success")
        return redirect(url_for("group_view", group_id=group_id))

    # ---------------------------------------------------------------------------
    #  Admin – Group Chat monitoring
    # ---------------------------------------------------------------------------

    @app.route("/admin/groups")
    @login_required
    @admin_required
    def admin_groups():
        """Admin: list all group chats for monitoring."""
        groups = db.get_all_group_chats_admin()
        categories, uncategorized = db.get_category_tree()
        return render_template("admin/groups.html", groups=groups,
                               categories=categories, uncategorized=uncategorized)

    @app.route("/admin/groups/<int:group_id>")
    @login_required
    @admin_required
    def admin_group_view(group_id):
        """Admin: view messages and members of a specific group chat."""
        group = db.get_group_chat(group_id)
        if not group:
            abort(404)
        messages = db.get_group_messages(group_id)
        members = db.get_group_members(group_id)
        categories, uncategorized = db.get_category_tree()
        return render_template("admin/group_view.html", group=group,
                               messages=messages, members=members,
                               categories=categories, uncategorized=uncategorized)

    # ---------------------------------------------------------------------------
    #  Unban, Regenerate Code, Admin Takeover, Chat Disable
    # ---------------------------------------------------------------------------

    @app.route("/groups/<int:group_id>/unban", methods=["POST"])
    @login_required
    def group_unban(group_id):
        """Revoke a ban and allow a previously banned user to rejoin a group."""
        user = get_current_user()
        group = db.get_group_chat(group_id)
        if not group:
            abort(404)
        my_role = db.get_group_member_role(group_id, user["id"])
        is_site_admin = user["role"] in ("admin", "protected_admin")
        if group["is_global"]:
            if not is_site_admin:
                flash("Only site admins can moderate the global chat.", "error")
                return redirect(url_for("group_view", group_id=group_id))
        else:
            if my_role not in ("owner", "moderator"):
                flash("Permission denied.", "error")
                return redirect(url_for("group_view", group_id=group_id))
        target_id = request.form.get("user_id", "")
        if not db.is_group_member_banned(group_id, target_id):
            flash("This user is not currently banned from the group.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        target_user = db.get_user_by_id(target_id)
        target_name = target_user["username"] if target_user else "Unknown"
        db.unban_group_member(group_id, target_id)
        db.send_group_system_message(group_id, f"{target_name}'s ban was revoked by {user['username']}")
        flash(f"{target_name}'s ban has been revoked.", "success")
        return redirect(url_for("group_view", group_id=group_id))

    @app.route("/groups/<int:group_id>/regenerate_code", methods=["POST"])
    @login_required
    def group_regenerate_code(group_id):
        """Generate a new invite code for a group chat (owner only).

        Accepts an optional ``custom_code`` form field.  If supplied it must be
        1–32 characters, alphanumeric (letters and digits only), and unique
        across all groups.
        """
        user = get_current_user()
        group = db.get_group_chat(group_id)
        if not group:
            abort(404)
        my_role = db.get_group_member_role(group_id, user["id"])
        if my_role != "owner":
            flash("Only the group owner can regenerate the invite code.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        custom_code = request.form.get("custom_code", "").strip()
        if custom_code:
            if not re.match(r'^[A-Za-z0-9]{1,32}$', custom_code):
                flash("Custom invite code must be between 1 and 32 alphanumeric characters.", "error")
                return redirect(url_for("group_view", group_id=group_id))
            # Check uniqueness
            existing = db.get_group_chat_by_invite(custom_code)
            if existing and existing["id"] != group_id:
                flash("That invite code is already in use by another group.", "error")
                return redirect(url_for("group_view", group_id=group_id))
            new_code = db.regenerate_group_invite_code(group_id, custom_code)
        else:
            new_code = db.regenerate_group_invite_code(group_id)
        db.send_group_system_message(group_id, f"Invite code was regenerated by {user['username']}")
        flash(f"Invite code regenerated: {new_code}", "success")
        return redirect(url_for("group_view", group_id=group_id))

    @app.route("/groups/<int:group_id>/export", methods=["GET"])
    @login_required
    @rate_limit(10, 60)
    def group_export(group_id):
        """Export group chat messages and attachments as a downloadable file.

        Creates either a text file (if no attachments or small total size) or
        a ZIP archive (if attachments exist or total size is large).
        """
        user = get_current_user()
        group = db.get_group_chat(group_id)
        if not group:
            abort(404)

        # Check permissions: owner, moderator, or site admin only
        my_role = db.get_group_member_role(group_id, user["id"])
        is_site_admin = user["role"] in ("admin", "protected_admin")

        # Only owners, moderators, and site admins can export
        if not is_site_admin and my_role not in ("owner", "moderator"):
            flash("Only group owners and moderators can export chat data.", "error")
            return redirect(url_for("group_view", group_id=group_id))

        # Get messages and group info
        messages, group_info = db.get_group_messages_for_export(group_id)

        if not messages:
            flash("No messages to export.", "info")
            return redirect(url_for("group_view", group_id=group_id))

        # Generate text content
        text_lines = [
            f"Group Chat Export: {group_info['name']}",
            f"Export Date: {datetime.now(timezone.utc).isoformat()}",
            f"Total Messages: {len(messages)}",
            "=" * 80,
            "",
        ]

        attachment_files = []
        total_attachment_size = 0

        for msg in messages:
            sender = msg.get("sender_name") or "System"
            timestamp = msg["created_at"]
            content = msg["content"]
            is_system = msg.get("is_system", False)

            if is_system:
                text_lines.append(f"[{timestamp}] [SYSTEM] {content}")
            else:
                ip = msg.get("ip_address", "N/A")
                text_lines.append(f"[{timestamp}] {sender} (IP: {ip})")
                text_lines.append(f"  {content}")

            # Handle attachments
            if msg.get("attachments"):
                text_lines.append("  Attachments:")
                for att in msg["attachments"]:
                    att_name = att["original_name"]
                    att_size = att["file_size"]
                    att_filename = att["filename"]
                    text_lines.append(f"    - {att_name} ({att_size / 1024:.1f} KB)")

                    # Collect attachment file paths
                    att_path = os.path.join(config.CHAT_ATTACHMENT_FOLDER, att_filename)
                    if os.path.isfile(att_path):
                        attachment_files.append((att_filename, att_name, att_path, att_size))
                        total_attachment_size += att_size

            text_lines.append("")

        text_content = "\n".join(text_lines)

        # Decide whether to send as text file or ZIP
        # Use ZIP if:
        # - There are attachments, OR
        # - Total size (text + attachments) would exceed 10 MB
        text_size = len(text_content.encode("utf-8"))
        total_size = text_size + total_attachment_size

        # Threshold for unified vs separate: 50 MB (Telegram limit)
        UNIFIED_THRESHOLD = 50 * 1024 * 1024

        safe_group_name = re.sub(r'[^\w\s-]', '', group_info['name']).strip().replace(' ', '_')
        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        if not attachment_files and text_size < 10 * 1024 * 1024:
            # Simple text file export
            filename = f"group_chat_{safe_group_name}_{timestamp_str}.txt"
            return send_file(
                io.BytesIO(text_content.encode("utf-8")),
                mimetype="text/plain",
                as_attachment=True,
                download_name=filename,
            )
        elif total_size < UNIFIED_THRESHOLD:
            # Unified ZIP export (everything in one file)
            filename = f"group_chat_{safe_group_name}_{timestamp_str}.zip"
            zip_buffer = io.BytesIO()

            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
                # Add text content
                zipf.writestr(f"{safe_group_name}_messages.txt", text_content)

                # Add attachments in a subdirectory
                for att_filename, att_original_name, att_path, att_size in attachment_files:
                    zipf.write(att_path, f"attachments/{att_original_name}")

            zip_buffer.seek(0)
            return send_file(
                zip_buffer,
                mimetype="application/zip",
                as_attachment=True,
                download_name=filename,
            )
        else:
            # Separate exports - too large for single file
            # Create a manifest and split into multiple ZIPs
            filename = f"group_chat_{safe_group_name}_{timestamp_str}_part1.zip"
            zip_buffer = io.BytesIO()

            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
                # Add text content
                zipf.writestr(f"{safe_group_name}_messages.txt", text_content)

                # Add a manifest explaining the split
                manifest = {
                    "group_name": group_info['name'],
                    "export_date": datetime.now(timezone.utc).isoformat(),
                    "total_messages": len(messages),
                    "total_attachments": len(attachment_files),
                    "total_size_bytes": total_size,
                    "note": "Attachments are too large to include in a single file. Download them separately from the group chat.",
                }
                zipf.writestr("README.json", json.dumps(manifest, indent=2))

            zip_buffer.seek(0)
            flash(
                f"Export prepared. Attachments are too large ({total_attachment_size / (1024*1024):.1f} MB) "
                "to include in a single file. Download them separately from the chat.",
                "info"
            )
            return send_file(
                zip_buffer,
                mimetype="application/zip",
                as_attachment=True,
                download_name=filename,
            )

    @app.route("/groups/<int:group_id>/clear", methods=["POST"])
    @login_required
    @rate_limit(5, 60)
    def group_clear(group_id):
        """Clear all messages in a group chat. Only owners can clear."""
        user = get_current_user()
        group = db.get_group_chat(group_id)
        if not group:
            abort(404)

        # Check permissions: owner or site admin only
        my_role = db.get_group_member_role(group_id, user["id"])
        is_site_admin = user["role"] in ("admin", "protected_admin")

        if my_role != "owner" and not is_site_admin:
            flash("Only the group owner can clear the chat.", "error")
            return redirect(url_for("group_view", group_id=group_id))

        # Delete all messages and attachments
        files_to_delete = db.clear_group_messages(group_id)
        att_dir = config.CHAT_ATTACHMENT_FOLDER
        for fname in files_to_delete:
            try:
                fpath = os.path.join(att_dir, fname)
                if os.path.isfile(fpath):
                    os.remove(fpath)
            except OSError:
                pass

        # Send system message
        db.send_group_system_message(group_id, f"Chat cleared by {user['username']}")
        notify_change("group_clear", f"Group '{group['name']}' chat cleared by {user['username']}")
        flash("Group chat has been cleared successfully.", "success")
        log_action("group_clear", request, user=user, group_id=group_id)
        return redirect(url_for("group_view", group_id=group_id))

    @app.route("/groups/<int:group_id>/delete", methods=["POST"])
    @login_required
    def group_delete(group_id):
        """Permanently delete a non-global group chat (owner or site admin only)."""
        user = get_current_user()
        group = db.get_group_chat(group_id)
        if not group:
            abort(404)
        if group["is_global"]:
            flash("The global chat cannot be deleted.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        my_role = db.get_group_member_role(group_id, user["id"])
        is_site_admin = user["role"] in ("admin", "protected_admin")
        if my_role != "owner" and not is_site_admin:
            flash("Only the group owner can delete this group.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        group_name = group["name"]
        files = db.delete_group_chat(group_id)
        for fname in files:
            try:
                fpath = os.path.join(config.CHAT_ATTACHMENT_FOLDER, fname)
                if os.path.isfile(fpath):
                    os.remove(fpath)
            except OSError:
                pass
        notify_change("group_delete", f"Group '{group_name}' deleted by {user['username']}")
        log_action("group_delete", request, user=user, group_id=group_id)
        flash(f"Group '{group_name}' has been deleted.", "success")
        return redirect(url_for("group_list"))

    @app.route("/groups/<int:group_id>/toggle_active", methods=["POST"])
    @login_required
    @admin_required
    def group_toggle_active(group_id):
        """Deactivate or reactivate the global group chat (site admins only).

        When deactivated, members can still read history but cannot send new
        messages.  Messages continue to expire and be cleaned up as normal.
        """
        group = db.get_group_chat(group_id)
        if not group:
            abort(404)
        if not group["is_global"]:
            flash("Only the global chat can be deactivated this way.", "error")
            return redirect(url_for("group_view", group_id=group_id))
        user = get_current_user()
        new_state = not bool(group["is_active"])
        db.set_group_chat_active(group_id, new_state)
        action = "reactivated" if new_state else "deactivated"
        db.send_group_system_message(group_id, f"Global chat was {action} by {user['username']}")
        notify_change("group_toggle_active", f"Global chat {action} by {user['username']}")
        flash(f"Global chat has been {action}.", "success")
        return redirect(url_for("group_view", group_id=group_id))

    @app.route("/admin/groups/<int:group_id>/delete", methods=["POST"])
    @login_required
    @admin_required
    def admin_group_delete(group_id):
        """Admin: permanently delete any non-global group chat."""
        group = db.get_group_chat(group_id)
        if not group:
            abort(404)
        if group["is_global"]:
            flash("The global chat cannot be deleted.", "error")
            return redirect(url_for("admin_groups"))
        group_name = group["name"]
        user = get_current_user()
        files = db.delete_group_chat(group_id)
        for fname in files:
            try:
                fpath = os.path.join(config.CHAT_ATTACHMENT_FOLDER, fname)
                if os.path.isfile(fpath):
                    os.remove(fpath)
            except OSError:
                pass
        notify_change("admin_group_delete", f"Group '{group_name}' deleted by admin {user['username']}")
        log_action("admin_group_delete", request, user=user, group_id=group_id)
        flash(f"Group '{group_name}' has been deleted.", "success")
        return redirect(url_for("admin_groups"))

    @app.route("/groups/<int:group_id>/admin_takeover", methods=["POST"])
    @login_required
    @admin_required
    def group_admin_takeover(group_id):
        """Allow a site admin to take ownership of any group."""
        user = get_current_user()
        group = db.get_group_chat(group_id)
        if not group:
            abort(404)
        # Join the group if not already a member
        if not db.is_group_member(group_id, user["id"]):
            db.add_group_member(group_id, user["id"])
        # Demote current owner if there is one
        current_members = db.get_group_members(group_id)
        for m in current_members:
            if m["role"] == "owner" and m["user_id"] != user["id"]:
                db.set_group_member_role(group_id, m["user_id"], "moderator")
        # Set admin as owner
        db.set_group_member_role(group_id, user["id"], "owner")
        db.send_group_system_message(group_id, f"{user['username']} (admin) took ownership of the group")
        notify_change("group_admin_takeover", f"{user['username']} took ownership of group '{group['name']}'")
        flash("You are now the owner of this group.", "success")
        return redirect(url_for("group_view", group_id=group_id))

    @app.route("/admin/users/<user_id>/toggle_chat", methods=["POST"])
    @login_required
    @admin_required
    def admin_toggle_chat(user_id):
        """Toggle the chat disabled flag for a user."""
        target = db.get_user_by_id(user_id)
        if not target:
            abort(404)
        currently_disabled = db.is_user_chat_disabled(user_id)
        db.set_user_chat_disabled(user_id, not currently_disabled)
        status = "disabled" if not currently_disabled else "enabled"
        flash(f"Chat {status} for {target['username']}.", "success")
        return redirect(request.referrer or url_for("admin_chats"))
