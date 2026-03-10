"""
BananaWiki – Direct messaging (chat) routes.
"""

from flask import (render_template, request, redirect, url_for, session, flash, send_file, jsonify, abort,
                   send_from_directory)
import os, io, uuid, threading, zipfile, json, re
from datetime import datetime, timedelta, timezone
from werkzeug.utils import secure_filename
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import db
import config
from helpers import login_required, admin_required, get_current_user, rate_limit, get_site_timezone
from wiki_logger import log_action
from sync import backup_chats_before_cleanup, backup_group_chats_before_cleanup


def register_chat_routes(app):
    """Register direct messaging routes on the Flask app."""

    def _chat_allowed_file(filename):
        """Return True if the extension is in CHAT_ALLOWED_EXTENSIONS."""
        return "." in filename and filename.rsplit(".", 1)[1].lower() in config.CHAT_ALLOWED_EXTENSIONS

    def _chat_disabled_redirect(endpoint="home", **values):
        """Redirect users whose chat access has been disabled."""
        flash("Your chat privileges have been disabled by an administrator.", "error")
        return redirect(url_for(endpoint, **values))

    def _chat_message_state(chat):
        """Return rendered chat HTML and lightweight counters for live refresh."""
        messages = db.get_chat_messages(chat["id"])
        attachment_count = sum(len(msg.get("attachments") or []) for msg in messages)
        latest_message_id = messages[-1]["id"] if messages else 0
        html = render_template("chats/_messages.html", chat=chat, messages=messages)
        return messages, {
            "html": html,
            "message_count": len(messages),
            "attachment_count": attachment_count,
            "latest_message_id": latest_message_id,
        }

    def _remove_chat_files(filenames):
        """Delete chat attachment files from disk, ignoring missing files."""
        for fname in filenames:
            try:
                fpath = os.path.join(config.CHAT_ATTACHMENT_FOLDER, fname)
                if os.path.isfile(fpath):
                    os.remove(fpath)
            except OSError:
                pass

    @app.route("/chats")
    @login_required
    def chat_list():
        """List all direct message conversations for the current user."""
        user = get_current_user()
        settings = db.get_site_settings()
        if settings and not settings["chat_dm_enabled"] and user["role"] not in ("admin", "protected_admin"):
            flash("Direct messaging is currently disabled.", "error")
            return redirect(url_for("home"))
        if db.is_user_chat_disabled(user["id"]):
            return _chat_disabled_redirect()
        chats = db.get_user_chats(user["id"])
        total_unread_dm = db.get_total_unread_dm_count(user["id"])
        categories, uncategorized = db.get_category_tree()
        return render_template("chats/list.html", chats=chats,
                               total_unread_dm=total_unread_dm,
                               categories=categories, uncategorized=uncategorized)

    @app.route("/chats/new", methods=["GET", "POST"])
    @login_required
    @rate_limit(10, 60)
    def chat_new():
        """Start a new direct message conversation with another user."""
        user = get_current_user()
        settings = db.get_site_settings()
        if settings and not settings["chat_dm_enabled"] and user["role"] not in ("admin", "protected_admin"):
            flash("Direct messaging is currently disabled.", "error")
            return redirect(url_for("home"))
        if settings and not settings["chat_allow_dm_creation"] and user["role"] not in ("admin", "protected_admin"):
            flash("Creating new direct message conversations is currently disabled.", "error")
            return redirect(url_for("chat_list"))
        if db.is_user_chat_disabled(user["id"]):
            return _chat_disabled_redirect()
        if request.method == "POST":
            target_username = request.form.get("username", "").strip()
            if not target_username:
                flash("Please enter a username.", "error")
                return redirect(url_for("chat_new"))
            target = db.get_user_by_username(target_username)
            if not target:
                flash("User not found.", "error")
                return redirect(url_for("chat_new"))
            if target["id"] == user["id"]:
                flash("You cannot start a chat with yourself.", "error")
                return redirect(url_for("chat_new"))
            chat = db.get_or_create_chat(user["id"], target["id"])
            return redirect(url_for("chat_view", chat_id=chat["id"]))
        all_users = db.list_users()
        categories, uncategorized = db.get_category_tree()
        return render_template("chats/new.html", all_users=all_users,
                               categories=categories, uncategorized=uncategorized)

    @app.route("/chats/<int:chat_id>")
    @login_required
    def chat_view(chat_id):
        """View and load messages in a direct message conversation."""
        user = get_current_user()
        settings = db.get_site_settings()
        if settings and not settings["chat_dm_enabled"] and user["role"] not in ("admin", "protected_admin"):
            flash("Direct messaging is currently disabled.", "error")
            return redirect(url_for("home"))
        if db.is_user_chat_disabled(user["id"]):
            return _chat_disabled_redirect()
        if not db.is_chat_participant(chat_id, user["id"]):
            flash("Access denied.", "error")
            return redirect(url_for("chat_list"))
        chat = db.get_chat_by_id(chat_id)
        if not chat:
            abort(404)
        # Reset unread count when viewing the chat
        db.reset_unread_count(chat_id, user["id"])
        # Determine other user
        other_id = chat["user2_id"] if chat["user1_id"] == user["id"] else chat["user1_id"]
        other_user = db.get_user_by_id(other_id)
        messages, message_state = _chat_message_state(chat)
        categories, uncategorized = db.get_category_tree()
        return render_template("chats/chat.html", chat=chat, messages=messages,
                               other_user=other_user, message_state=message_state,
                               clear_attachment_count=message_state["attachment_count"],
                               categories=categories, uncategorized=uncategorized)

    @app.route("/chats/<int:chat_id>/messages")
    @login_required
    def chat_messages_partial(chat_id):
        """Return the latest direct-message HTML for live refresh."""
        user = get_current_user()
        settings = db.get_site_settings()
        if settings and not settings["chat_dm_enabled"] and user["role"] not in ("admin", "protected_admin"):
            return jsonify({"error": "Direct messaging is currently disabled."}), 403
        if db.is_user_chat_disabled(user["id"]):
            return jsonify({"error": "Chat access disabled."}), 403
        if not db.is_chat_participant(chat_id, user["id"]):
            return jsonify({"error": "Access denied."}), 403
        chat = db.get_chat_by_id(chat_id)
        if not chat:
            abort(404)
        db.reset_unread_count(chat_id, user["id"])
        _, message_state = _chat_message_state(chat)
        return jsonify(message_state)

    @app.route("/chats/<int:chat_id>/send", methods=["POST"])
    @login_required
    @rate_limit(30, 60)
    def chat_send(chat_id):
        """Send a message (and optional file attachment) in a direct message conversation."""
        user = get_current_user()
        settings = db.get_site_settings()
        if settings and not settings["chat_dm_enabled"] and user["role"] not in ("admin", "protected_admin"):
            flash("Direct messaging is currently disabled.", "error")
            return redirect(url_for("home"))
        if db.is_user_chat_disabled(user["id"]):
            return _chat_disabled_redirect()
        if not db.is_chat_participant(chat_id, user["id"]):
            flash("Access denied.", "error")
            return redirect(url_for("chat_list"))

        # Get chat object for finding the other participant
        chat = db.get_chat_by_id(chat_id)
        if not chat:
            flash("Chat not found.", "error")
            return redirect(url_for("chat_list"))

        content = request.form.get("content", "").strip()
        if not content:
            flash("Message cannot be empty.", "error")
            return redirect(url_for("chat_view", chat_id=chat_id))
        max_msg_len = settings["chat_max_message_length"] if settings and settings["chat_max_message_length"] else 5000
        if len(content) > max_msg_len:
            flash(f"Message cannot exceed {max_msg_len} characters.", "error")
            return redirect(url_for("chat_view", chat_id=chat_id))
        ip_address = request.remote_addr or "unknown"
        msg_id = db.send_chat_message(chat_id, user["id"], content, ip_address)

        # Increment unread count for the other participant
        other_id = chat["user2_id"] if chat["user1_id"] == user["id"] else chat["user1_id"]
        db.increment_unread_count(chat_id, other_id)

        # Handle file attachment if present
        if "attachment" in request.files:
            f = request.files["attachment"]
            if f.filename:
                # Check if attachments are enabled
                if settings and not settings["chat_attachments_enabled"] and user["role"] not in ("admin", "protected_admin"):
                    flash("File attachments are currently disabled.", "error")
                    return redirect(url_for("chat_view", chat_id=chat_id))
                # Check daily limit from site settings
                max_attachments = settings["chat_attachments_per_day_limit"] if settings and settings["chat_attachments_per_day_limit"] else 10
                att_count = db.get_user_chat_attachment_count_today(user["id"])
                if att_count >= max_attachments:
                    flash(f"Daily attachment limit of {max_attachments} files reached.", "error")
                    return redirect(url_for("chat_view", chat_id=chat_id))
                if not _chat_allowed_file(f.filename):
                    flash("File type not allowed.", "error")
                    return redirect(url_for("chat_view", chat_id=chat_id))
                original_name = secure_filename(f.filename) or "file"
                ext = original_name.rsplit(".", 1)[1].lower() if "." in original_name else "bin"
                stored_name = f"{uuid.uuid4().hex}.{ext}"
                os.makedirs(config.CHAT_ATTACHMENT_FOLDER, exist_ok=True)
                filepath = os.path.join(config.CHAT_ATTACHMENT_FOLDER, stored_name)
                # Chunked write with size enforcement (limit from site settings, in bytes)
                max_att_size_mb = settings["chat_max_attachment_size_mb"] if settings and settings["chat_max_attachment_size_mb"] else 5
                max_att_size = max_att_size_mb * 1024 * 1024
                file_size = 0
                chunk_size = 64 * 1024
                oversized = False
                with open(filepath, "wb") as out:
                    while True:
                        chunk = f.stream.read(chunk_size)
                        if not chunk:
                            break
                        file_size += len(chunk)
                        if file_size > max_att_size:
                            oversized = True
                            break
                        out.write(chunk)
                if oversized:
                    try:
                        os.remove(filepath)
                    except OSError:
                        pass
                    flash(f"File exceeds the {max_att_size_mb} MB limit.", "error")
                    return redirect(url_for("chat_view", chat_id=chat_id))
                db.add_chat_attachment(msg_id, stored_name, original_name, file_size)

        log_action("chat_send", request, user=user, chat_id=chat_id)
        return redirect(url_for("chat_view", chat_id=chat_id))

    @app.route("/chats/<int:chat_id>/delete_message", methods=["POST"])
    @login_required
    @rate_limit(30, 60)
    def chat_delete_message(chat_id):
        """Delete a specific direct message from a chat."""
        user = get_current_user()
        if db.is_user_chat_disabled(user["id"]):
            return _chat_disabled_redirect()
        chat = db.get_chat_by_id(chat_id)
        if not chat:
            abort(404)
        if not db.is_chat_participant(chat_id, user["id"]):
            flash("Access denied.", "error")
            return redirect(url_for("chat_list"))
        message_id = request.form.get("message_id", type=int)
        if not message_id:
            flash("The specified message is invalid.", "error")
            return redirect(url_for("chat_view", chat_id=chat_id))
        msg = db.get_chat_message_by_id(message_id)
        if not msg or msg["chat_id"] != chat_id:
            flash("The specified message was not found.", "error")
            return redirect(url_for("chat_view", chat_id=chat_id))
        if msg["sender_id"] != user["id"]:
            flash("You do not have the required permissions to delete this message.", "error")
            return redirect(url_for("chat_view", chat_id=chat_id))
        files = db.delete_chat_message(message_id)
        _remove_chat_files(files)
        flash(
            f"Message has been successfully deleted. Removed {len(files)} attachment"
            f"{'' if len(files) == 1 else 's'}.",
            "success",
        )
        log_action("chat_delete_message", request, user=user, chat_id=chat_id, message_id=message_id)
        return redirect(url_for("chat_view", chat_id=chat_id))

    @app.route("/chats/attachments/<int:attachment_id>/download")
    @login_required
    def chat_attachment_download(attachment_id):
        """Download a file attachment from a direct message conversation."""
        att = db.get_chat_attachment(attachment_id)
        if not att:
            abort(404)
        user = get_current_user()
        if db.is_user_chat_disabled(user["id"]):
            return _chat_disabled_redirect()
        is_admin = user["role"] in ("admin", "protected_admin")
        if not is_admin and not db.is_chat_participant(att["chat_id"], user["id"]):
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

    @app.route("/chats/<int:chat_id>/export", methods=["GET"])
    @login_required
    @rate_limit(10, 60)
    def chat_export(chat_id):
        """Export direct message chat messages and attachments as a downloadable file.

        Both participants can export their chat history.
        """
        user = get_current_user()
        if db.is_user_chat_disabled(user["id"]):
            return _chat_disabled_redirect()
        chat = db.get_chat_by_id(chat_id)
        if not chat:
            abort(404)

        # Check permissions: both participants can export
        if not db.is_chat_participant(chat_id, user["id"]):
            flash("Access denied.", "error")
            return redirect(url_for("chat_list"))

        # Get messages and chat info
        messages = db.get_chat_messages(chat_id)
        user1 = db.get_user_by_id(chat["user1_id"])
        user2 = db.get_user_by_id(chat["user2_id"])

        if not messages:
            flash("No messages to export.", "info")
            return redirect(url_for("chat_view", chat_id=chat_id))

        # Generate text content
        text_lines = [
            f"Direct Message Export",
            f"Participants: {user1['username']} & {user2['username']}",
            f"Export Date: {datetime.now(timezone.utc).isoformat()}",
            f"Total Messages: {len(messages)}",
            "=" * 80,
            "",
        ]

        attachment_files = []
        total_attachment_size = 0

        for msg in messages:
            sender = msg.get("sender_name", "Unknown")
            timestamp = msg["created_at"]
            content = msg["content"]
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
        text_size = len(text_content.encode("utf-8"))
        total_size = text_size + total_attachment_size

        # Create safe filename
        other_username = user2["username"] if user["id"] == user1["id"] else user1["username"]
        safe_name = re.sub(r'[^\w\s-]', '', other_username).strip().replace(' ', '_')
        timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        # Simple text file if no attachments and small size
        if not attachment_files and text_size < 10 * 1024 * 1024:
            filename = f"dm_{safe_name}_{timestamp_str}.txt"
            return send_file(
                io.BytesIO(text_content.encode("utf-8")),
                mimetype="text/plain",
                as_attachment=True,
                download_name=filename,
            )
        else:
            # ZIP with messages and attachments
            filename = f"dm_{safe_name}_{timestamp_str}.zip"
            zip_buffer = io.BytesIO()

            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
                # Add text content
                zipf.writestr(f"dm_{safe_name}_messages.txt", text_content)

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

    @app.route("/chats/<int:chat_id>/clear", methods=["POST"])
    @login_required
    @rate_limit(5, 60)
    def chat_clear(chat_id):
        """Clear all messages in a direct message chat. Both participants can clear the chat."""
        user = get_current_user()
        if db.is_user_chat_disabled(user["id"]):
            return _chat_disabled_redirect()
        chat = db.get_chat_by_id(chat_id)
        if not chat:
            abort(404)

        # Check permissions: both participants can clear
        if not db.is_chat_participant(chat_id, user["id"]):
            flash("Access denied.", "error")
            return redirect(url_for("chat_list"))

        messages = db.get_chat_messages(chat_id)
        message_count = len(messages)
        attachment_count = sum(len(msg.get("attachments") or []) for msg in messages)
        # Delete all messages and attachments
        files_to_delete = db.clear_chat_messages(chat_id)
        _remove_chat_files(files_to_delete)
        flash(
            f"Chat has been successfully cleared. Removed {message_count} message"
            f"{'' if message_count == 1 else 's'} and {attachment_count} attachment"
            f"{'' if attachment_count == 1 else 's'}.",
            "success",
        )
        log_action("chat_clear", request, user=user, chat_id=chat_id,
                   message_count=message_count, attachment_count=attachment_count)
        return redirect(url_for("chat_view", chat_id=chat_id))

    # -----------------------------------------------------------------------
    #  Admin – Chat monitoring
    # -----------------------------------------------------------------------
    @app.route("/admin/chats")
    @login_required
    @admin_required
    def admin_chats():
        """Admin: browse all direct message conversations, optionally filtered by user."""
        user_filter = request.args.get("user_id")
        if user_filter:
            chats = db.get_user_chats_admin(user_filter)
            filter_user = db.get_user_by_id(user_filter)
        else:
            chats = db.get_all_chats_admin()
            filter_user = None
        all_users = db.list_users()
        categories, uncategorized = db.get_category_tree()
        return render_template("admin/chats.html", chats=chats,
                               all_users=all_users, filter_user=filter_user,
                               categories=categories, uncategorized=uncategorized)

    @app.route("/admin/chats/<int:chat_id>")
    @login_required
    @admin_required
    def admin_chat_view(chat_id):
        """Admin: view all messages within a specific direct message conversation."""
        chat = db.get_chat_by_id(chat_id)
        if not chat:
            abort(404)
        messages = db.get_chat_messages(chat_id)
        user1 = db.get_user_by_id(chat["user1_id"])
        user2 = db.get_user_by_id(chat["user2_id"])
        categories, uncategorized = db.get_category_tree()
        return render_template("admin/chat_view.html", chat=chat, messages=messages,
                               user1=user1, user2=user2,
                               categories=categories, uncategorized=uncategorized)

    # -----------------------------------------------------------------------
    #  Chat cleanup scheduler (runs weekly at configured hour)
    # -----------------------------------------------------------------------
    _cleanup_timer_holder = [None]

    def _schedule_chat_cleanup():
        """Schedule the next chat cleanup based on configured frequency and hour."""
        try:
            site_tz = get_site_timezone()
            now = datetime.now(site_tz)
            settings = db.get_site_settings()

            # Get cleanup schedule from DB settings with sensible defaults
            cleanup_frequency = (settings["chat_cleanup_frequency_days"] if settings and settings["chat_cleanup_frequency_days"] else 7)
            cleanup_hour = (settings["chat_cleanup_hour"] if settings and settings["chat_cleanup_hour"] is not None else 3)

            # Get last cleanup time
            last_cleanup = None
            if settings:
                try:
                    last_cleanup_str = settings["last_chat_cleanup_at"]
                    if last_cleanup_str:
                        # Parse ISO format datetime
                        last_cleanup = datetime.fromisoformat(last_cleanup_str.replace('Z', '+00:00'))
                        # Convert to site timezone
                        last_cleanup = last_cleanup.astimezone(site_tz)
                except (KeyError, ValueError, AttributeError, TypeError):
                    pass

            # If no last cleanup recorded, schedule for next configured hour today/tomorrow
            if not last_cleanup:
                target = now.replace(hour=cleanup_hour, minute=0, second=0, microsecond=0)
                if target <= now:
                    target += timedelta(days=1)
            else:
                # Schedule for configured frequency after last cleanup
                target = last_cleanup.replace(hour=cleanup_hour, minute=0, second=0, microsecond=0)
                target += timedelta(days=cleanup_frequency)

                # If target is in the past, schedule for the next interval
                while target <= now:
                    target += timedelta(days=cleanup_frequency)

            delay = (target - now).total_seconds()
            _cleanup_timer_holder[0] = threading.Timer(delay, _run_chat_cleanup)
            _cleanup_timer_holder[0].daemon = True
            _cleanup_timer_holder[0].start()
        except Exception:
            pass

    def _run_chat_cleanup():
        """Execute the scheduled chat cleanup: backup to Telegram then delete."""
        # Check if cleanup is enabled in site settings
        settings = db.get_site_settings()
        if not settings or not settings["chat_cleanup_enabled"]:
            return

        try:
            backup_chats_before_cleanup()
        except Exception:
            pass
        try:
            backup_group_chats_before_cleanup()
        except Exception:
            pass

        # Get DM-specific cleanup settings (use is not None to distinguish 0 from unset)
        dm_auto_clear_messages = settings["chat_dm_auto_clear_messages"] if settings["chat_dm_auto_clear_messages"] is not None else 0
        dm_auto_clear_attachments = settings["chat_dm_auto_clear_attachments"] if settings["chat_dm_auto_clear_attachments"] is not None else 1
        dm_message_retention_days = settings["chat_dm_message_retention_days"] if settings["chat_dm_message_retention_days"] is not None else 30
        dm_attachment_retention_days = settings["chat_dm_attachment_retention_days"] if settings["chat_dm_attachment_retention_days"] is not None else 7

        # Get Group-specific cleanup settings
        group_auto_clear_messages = settings["chat_group_auto_clear_messages"] if settings["chat_group_auto_clear_messages"] is not None else 0
        group_auto_clear_attachments = settings["chat_group_auto_clear_attachments"] if settings["chat_group_auto_clear_attachments"] is not None else 1
        group_message_retention_days = settings["chat_group_message_retention_days"] if settings["chat_group_message_retention_days"] is not None else 30
        group_attachment_retention_days = settings["chat_group_attachment_retention_days"] if settings["chat_group_attachment_retention_days"] is not None else 7

        att_dir = config.CHAT_ATTACHMENT_FOLDER

        # Clean up direct messages using DM-specific settings
        try:
            if dm_auto_clear_messages and dm_message_retention_days > 0:
                # Clear old messages (this also clears their attachments via CASCADE)
                files_to_delete = db.cleanup_old_chat_messages(dm_message_retention_days)
                for fname in files_to_delete:
                    try:
                        fpath = os.path.join(att_dir, fname)
                        if os.path.isfile(fpath):
                            os.remove(fpath)
                    except OSError:
                        pass
            elif dm_auto_clear_attachments and dm_attachment_retention_days > 0:
                # Clear only old attachments (keep messages)
                files_to_delete = db.cleanup_old_chat_attachments(dm_attachment_retention_days)
                for fname in files_to_delete:
                    try:
                        fpath = os.path.join(att_dir, fname)
                        if os.path.isfile(fpath):
                            os.remove(fpath)
                    except OSError:
                        pass
        except Exception:
            pass

        # Clean up group messages using Group-specific settings
        try:
            if group_auto_clear_messages and group_message_retention_days > 0:
                # Clear old messages (this also clears their attachments via CASCADE)
                group_files = db.cleanup_old_group_messages(group_message_retention_days)
                for fname in group_files:
                    try:
                        fpath = os.path.join(att_dir, fname)
                        if os.path.isfile(fpath):
                            os.remove(fpath)
                    except OSError:
                        pass
            elif group_auto_clear_attachments and group_attachment_retention_days > 0:
                # Clear only old attachments (keep messages)
                group_files = db.cleanup_old_group_attachments(group_attachment_retention_days)
                for fname in group_files:
                    try:
                        fpath = os.path.join(att_dir, fname)
                        if os.path.isfile(fpath):
                            os.remove(fpath)
                    except OSError:
                        pass
        except Exception:
            pass

        # Record cleanup timestamp
        try:
            site_tz = get_site_timezone()
            now = datetime.now(site_tz)
            db.update_site_settings(last_chat_cleanup_at=now.isoformat())
        except Exception:
            pass

        # Reschedule for next interval
        _schedule_chat_cleanup()

    _schedule_chat_cleanup()
