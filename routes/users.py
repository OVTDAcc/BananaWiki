"""
BananaWiki – User account and profile routes.
"""

from flask import (render_template, request, redirect, url_for, session, flash, send_file, abort)
import io
import json
import os
import re
import sqlite3
import uuid
import zipfile
from PIL import Image
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import db
import config
from helpers import (
    login_required, admin_required, editor_required, get_current_user,
    allowed_file, allowed_attachment, _is_valid_username, _is_valid_hex_color,
    rate_limit, _safe_referrer, ROLE_LABELS, render_markdown,
    format_datetime, slugify, editor_has_category_access,
)
from routes.uploads import cleanup_unused_uploads
from wiki_logger import log_action
from sync import notify_change, notify_file_upload, notify_file_deleted


_OBSIDIAN_UPLOAD_REF_RE = re.compile(r'/static/uploads/([^\s)"\']+)')


def build_user_export_zip(user):
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


def _collect_obsidian_sync_pages(user):
    """Return writable pages for the Obsidian sync UI."""
    categories, uncategorized = db.get_category_tree()
    pages = []

    def visit(nodes, parent_label=""):
        for node in nodes:
            category_label = f"{parent_label} / {node['name']}" if parent_label else node["name"]
            for page in node["pages"]:
                if editor_has_category_access(user, page["category_id"]):
                    pages.append({
                        "id": page["id"],
                        "slug": page["slug"],
                        "title": page["title"],
                        "category_id": page["category_id"],
                        "category_label": category_label,
                    })
            visit(node["children"], category_label)

    visit(categories)
    for page in uncategorized:
        if editor_has_category_access(user, page["category_id"]):
            pages.append({
                "id": page["id"],
                "slug": page["slug"],
                "title": page["title"],
                "category_id": page["category_id"],
                "category_label": "Uncategorized",
            })
    return pages


def _build_obsidian_frontmatter(page, page_info):
    """Return frontmatter metadata for a syncable page."""
    category_id = page["category_id"]
    category_value = "null" if category_id is None else str(int(category_id))
    lines = [
        "---",
        f"bananawiki_page_id: {int(page['id'])}",
        f"bananawiki_slug: {json.dumps(page['slug'])}",
        f"bananawiki_title: {json.dumps(page['title'])}",
        f"bananawiki_category_id: {category_value}",
        f"bananawiki_category: {json.dumps(page_info['category_label'])}",
        "---",
        "",
    ]
    return "\n".join(lines)


def _parse_obsidian_markdown(text):
    """Split optional BananaWiki frontmatter from Obsidian markdown content."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    for idx in range(1, len(lines)):
        if lines[idx].strip() != "---":
            continue
        metadata = {}
        found = False
        for line in lines[1:idx]:
            if ":" not in line:
                continue
            key, raw_value = line.split(":", 1)
            key = key.strip()
            if not key.startswith("bananawiki_"):
                continue
            raw_value = raw_value.strip()
            try:
                value = json.loads(raw_value)
            except Exception:
                value = raw_value
            metadata[key] = value
            found = True
        if not found:
            return {}, text
        body_lines = lines[idx + 1:]
        if body_lines and body_lines[0] == "":
            body_lines = body_lines[1:]
        return metadata, "\n".join(body_lines)

    return {}, text


def _build_obsidian_export_zip(user, selected_slugs=None):
    """Build an Obsidian-friendly ZIP archive for writable pages."""
    available_pages = _collect_obsidian_sync_pages(user)
    available_by_slug = {page["slug"]: page for page in available_pages}
    requested_slugs = [slug.strip() for slug in (selected_slugs or []) if slug.strip()]
    if requested_slugs:
        missing = sorted({slug for slug in requested_slugs if slug not in available_by_slug})
        if missing:
            raise ValueError("One or more selected pages are not available for Obsidian export.")
        pages = [available_by_slug[slug] for slug in requested_slugs]
    else:
        pages = available_pages
    if not pages:
        raise ValueError("At least one writable page is required to continue.")

    upload_root = os.path.abspath(config.UPLOAD_FOLDER)
    attachment_root = os.path.abspath(config.ATTACHMENT_FOLDER)
    manifest = {"format": 1, "pages": []}
    archived_uploads = set()
    buf = io.BytesIO()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for page_info in pages:
            page = db.get_page(page_info["id"])
            if not page:
                continue

            markdown_path = f"pages/{page['slug']}.md"
            content = (page["content"] or "")
            zf.writestr(markdown_path, _build_obsidian_frontmatter(page, page_info) + content)

            page_entry = {
                "page_id": page["id"],
                "slug": page["slug"],
                "title": page["title"],
                "category_id": page["category_id"],
                "category_label": page_info["category_label"],
                "markdown_path": markdown_path,
                "uploads": [],
                "attachments": [],
            }

            for upload_name in sorted(set(_OBSIDIAN_UPLOAD_REF_RE.findall(content))):
                upload_path = os.path.abspath(os.path.join(upload_root, upload_name))
                if os.path.commonpath([upload_root, upload_path]) != upload_root:
                    continue
                if not os.path.isfile(upload_path):
                    continue
                archive_path = f"uploads/{upload_name}"
                if archive_path not in archived_uploads:
                    zf.write(upload_path, archive_path)
                    archived_uploads.add(archive_path)
                page_entry["uploads"].append({
                    "filename": upload_name,
                    "archive_path": archive_path,
                })

            for idx, attachment in enumerate(db.get_page_attachments(page["id"]), start=1):
                stored_name = attachment["filename"]
                attachment_path = os.path.abspath(os.path.join(attachment_root, stored_name))
                if os.path.commonpath([attachment_root, attachment_path]) != attachment_root:
                    continue
                if not os.path.isfile(attachment_path):
                    continue
                safe_original = secure_filename(attachment["original_name"]) or f"attachment-{attachment['id']}"
                archive_path = f"attachments/{page['slug']}/{idx:02d}-{safe_original}"
                zf.write(attachment_path, archive_path)
                page_entry["attachments"].append({
                    "original_name": attachment["original_name"],
                    "archive_path": archive_path,
                })

            manifest["pages"].append(page_entry)

        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr(
            "README.md",
            "# BananaWiki Obsidian Sync (Experimental)\n\n"
            "See docs/obsidian_integration.md in the repository for setup and round-trip notes.\n",
        )

    buf.seek(0)
    return buf, len(manifest["pages"])


def _save_obsidian_upload(filename, data):
    """Validate and store an imported inline upload."""
    safe_name = secure_filename(os.path.basename(filename))
    if not safe_name or not allowed_file(safe_name):
        raise ValueError(f"Upload '{filename}' is not an allowed image file.")
    if len(data) > config.MAX_CONTENT_LENGTH:
        raise ValueError(f"Upload '{safe_name}' exceeds the configured image size limit.")
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
    except Exception as exc:
        raise ValueError(f"Upload '{safe_name}' is not a valid image.") from exc

    upload_root = os.path.abspath(config.UPLOAD_FOLDER)
    os.makedirs(upload_root, exist_ok=True)
    filepath = os.path.abspath(os.path.join(upload_root, safe_name))
    if os.path.commonpath([upload_root, filepath]) != upload_root:
        raise ValueError(f"Upload '{safe_name}' has an invalid storage path.")
    with open(filepath, "wb") as f:
        f.write(data)
    return safe_name, filepath


def _replace_page_attachments(page_id, attachments, zf, user):
    """Replace all page attachments using the provided archive entries."""
    attachment_root = os.path.abspath(config.ATTACHMENT_FOLDER)
    os.makedirs(attachment_root, exist_ok=True)

    existing = db.get_page_attachments(page_id)
    for attachment in existing:
        old_path = os.path.abspath(os.path.join(attachment_root, attachment["filename"]))
        if os.path.commonpath([attachment_root, old_path]) == attachment_root and os.path.isfile(old_path):
            os.remove(old_path)
            notify_file_deleted(attachment["filename"])
        db.delete_page_attachment(attachment["id"])

    imported = 0
    for attachment in attachments:
        archive_path = attachment.get("archive_path", "")
        original_name = secure_filename(attachment.get("original_name", ""))
        if not archive_path:
            raise ValueError("An imported attachment is missing its archive path.")
        if not original_name or not allowed_attachment(original_name):
            raise ValueError(f"Attachment '{original_name or archive_path}' is not allowed.")
        try:
            data = zf.read(archive_path)
        except KeyError as exc:
            raise ValueError(f"Attachment '{archive_path}' is missing from the archive.") from exc
        if len(data) > config.MAX_ATTACHMENT_SIZE:
            raise ValueError(f"Attachment '{original_name}' exceeds the configured size limit.")
        ext = original_name.rsplit(".", 1)[1].lower()
        stored_name = f"{uuid.uuid4().hex}.{ext}"
        filepath = os.path.abspath(os.path.join(attachment_root, stored_name))
        if os.path.commonpath([attachment_root, filepath]) != attachment_root:
            raise ValueError(f"Attachment '{original_name}' has an invalid storage path.")
        with open(filepath, "wb") as f:
            f.write(data)
        db.add_page_attachment(page_id, stored_name, original_name, len(data), user["id"])
        notify_file_upload(stored_name, filepath, display_name=original_name)
        imported += 1
    return imported


def _import_obsidian_zip(user, archive_file):
    """Import an experimental Obsidian archive into BananaWiki."""
    if not archive_file or not archive_file.filename:
        raise ValueError("An Obsidian ZIP export is required to continue.")
    if not archive_file.filename.lower().endswith(".zip"):
        raise ValueError("The uploaded Obsidian file must be a ZIP archive.")

    try:
        zf = zipfile.ZipFile(archive_file.stream)
    except zipfile.BadZipFile as exc:
        raise ValueError("Failed to read the uploaded Obsidian archive.") from exc

    try:
        manifest = json.loads(zf.read("manifest.json"))
    except KeyError as exc:
        raise ValueError("The uploaded archive is missing manifest.json.") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("The uploaded archive contains an invalid manifest.json.") from exc

    pages = manifest.get("pages") or []
    if not pages:
        raise ValueError("The uploaded Obsidian archive does not contain any pages.")

    restored_uploads = 0
    restored_upload_names = set()
    imported_attachments = 0
    created_pages = 0
    updated_pages = 0

    for page_entry in pages:
        markdown_path = page_entry.get("markdown_path", "")
        if not markdown_path:
            raise ValueError("A page entry in manifest.json is missing markdown_path.")
        try:
            raw_markdown = zf.read(markdown_path).decode("utf-8")
        except KeyError as exc:
            raise ValueError(f"Page markdown '{markdown_path}' is missing from the archive.") from exc
        except UnicodeDecodeError as exc:
            raise ValueError(f"Page markdown '{markdown_path}' must be UTF-8 encoded.") from exc

        metadata, content = _parse_obsidian_markdown(raw_markdown)
        page_id = metadata.get("bananawiki_page_id", page_entry.get("page_id"))
        slug = slugify(str(metadata.get("bananawiki_slug", page_entry.get("slug", ""))).strip())
        title = str(metadata.get("bananawiki_title", page_entry.get("title", ""))).strip()
        category_id = metadata.get("bananawiki_category_id", page_entry.get("category_id"))

        if category_id in ("", "null", None):
            category_id = None
        elif isinstance(category_id, str):
            if not category_id.isdigit():
                raise ValueError(f"Page '{slug or markdown_path}' has an invalid category id.")
            category_id = int(category_id)

        if not slug:
            slug = slugify(title)
        if not slug:
            raise ValueError(f"Page '{markdown_path}' does not define a valid slug.")
        if not title:
            title = slug.replace("-", " ").title()

        page = None
        if isinstance(page_id, int) or (isinstance(page_id, str) and str(page_id).isdigit()):
            page = db.get_page(int(page_id))
        if not page:
            page = db.get_page_by_slug(slug)

        if category_id is not None and not db.get_category(category_id):
            category_id = page["category_id"] if page else None

        if page:
            if not editor_has_category_access(user, page["category_id"]):
                raise ValueError(f"You do not have permission to import changes for page '{page['slug']}'.")
            target_category_id = page["category_id"]
            if category_id != page["category_id"] and editor_has_category_access(user, category_id):
                db.update_page_category(page["id"], category_id)
                target_category_id = category_id
            existing_slug = db.get_page_by_slug(slug)
            if existing_slug and existing_slug["id"] != page["id"]:
                raise ValueError(f"Slug '{slug}' is already in use by another page.")
            db.update_page(page["id"], title, content, user["id"], "Imported from Obsidian vault")
            if slug != page["slug"]:
                db.update_page_slug(page["id"], slug)
            page = db.get_page(page["id"])
            if target_category_id != page["category_id"]:
                db.update_page_category(page["id"], target_category_id)
            updated_pages += 1
        else:
            if not editor_has_category_access(user, category_id):
                raise ValueError(f"You do not have permission to create page '{slug}' in the requested category.")
            if db.get_page_by_slug(slug):
                raise ValueError(f"Slug '{slug}' is already in use by another page.")
            page_id = db.create_page(title, slug, content, category_id, user["id"])
            page = db.get_page(page_id)
            created_pages += 1

        for upload in page_entry.get("uploads", []):
            archive_path = upload.get("archive_path", "")
            filename = upload.get("filename", "")
            if not archive_path or not filename:
                raise ValueError(f"Page '{slug}' contains an invalid upload entry.")
            safe_name = secure_filename(os.path.basename(filename))
            if safe_name in restored_upload_names:
                continue
            try:
                data = zf.read(archive_path)
            except KeyError as exc:
                raise ValueError(f"Upload '{archive_path}' is missing from the archive.") from exc
            saved_name, filepath = _save_obsidian_upload(safe_name, data)
            notify_file_upload(saved_name, filepath)
            restored_upload_names.add(saved_name)
            restored_uploads += 1

        imported_attachments += _replace_page_attachments(page["id"], page_entry.get("attachments", []), zf, user)

    cleanup_unused_uploads()
    return {
        "created_pages": created_pages,
        "updated_pages": updated_pages,
        "restored_uploads": restored_uploads,
        "imported_attachments": imported_attachments,
    }


def register_user_routes(app):
    """Register user account and profile routes on the Flask app."""

    def _profile_next(fallback):
        """Return next_url from the current form post if it is a safe same-site path, else fallback."""
        url = request.form.get("next_url", "").strip()
        # Only accept simple same-site paths: must start with / but not // and contain no backslashes
        if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
            return url
        return fallback

    @app.route("/badges/notifications")
    @login_required
    def badge_notifications():
        """View and dismiss badge notifications."""
        user = get_current_user()
        unnotified = db.get_unnotified_badges(user["id"])
        categories, uncategorized = db.get_category_tree()
        return render_template(
            "users/badge_notifications.html",
            unnotified=unnotified,
            categories=categories,
            uncategorized=uncategorized,
        )

    @app.route("/badges/notifications/dismiss", methods=["POST"])
    @login_required
    @rate_limit(10, 60)
    def dismiss_badge_notifications():
        """Dismiss all badge notifications for the current user."""
        user = get_current_user()
        db.mark_badges_notified(user["id"])
        if "badge_notifications" in session:
            del session["badge_notifications"]
        flash("Badge notifications dismissed.", "info")
        return redirect(request.referrer or url_for("home"))

    @app.route("/account", methods=["GET", "POST"])
    @login_required
    @rate_limit(10, 60)
    def account_settings():
        """Display and handle the user's account settings page (username, password, profile, avatar)."""
        user = get_current_user()
        action = request.form.get("action", "") if request.method == "POST" else ""

        if action == "change_username":
            if user["is_superuser"]:
                flash("This account is protected and cannot be modified by administrators.", "error")
                return redirect(url_for("account_settings"))
            new_username = request.form.get("new_username", "").strip()
            password = request.form.get("password", "")
            if not check_password_hash(user["password"], password):
                flash("Incorrect password.", "error")
            elif len(new_username) < 3:
                flash("Username must be at least 3 characters long.", "error")
            elif len(new_username) > 50:
                flash("Username cannot exceed 50 characters.", "error")
            elif not _is_valid_username(new_username):
                flash("Username can only contain letters, digits, underscores and hyphens.", "error")
            elif db.get_user_by_username(new_username) and new_username.lower() != user["username"].lower():
                flash("Username already taken. Please choose another.", "error")
            else:
                try:
                    db.update_user(user["id"], username=new_username)
                except sqlite3.IntegrityError:
                    flash("Username already taken. Please choose another.", "error")
                    return redirect(url_for("account_settings"))
                else:
                    db.record_username_change(user["id"], user["username"], new_username)
                    log_action("change_username", request, user=user, new_username=new_username)
                    notify_change("user_change_username", f"User '{user['username']}' renamed to '{new_username}'")
                    flash("Username updated.", "success")
            return redirect(url_for("account_settings"))

        if action == "change_password":
            if user["is_superuser"]:
                flash("This account is protected and cannot be modified by administrators.", "error")
                return redirect(url_for("account_settings"))
            current_pw = request.form.get("current_password", "")
            new_pw = request.form.get("new_password", "")
            confirm_pw = request.form.get("confirm_password", "")
            if not check_password_hash(user["password"], current_pw):
                flash("Incorrect current password.", "error")
            elif new_pw != confirm_pw:
                flash("New passwords do not match.", "error")
            elif len(new_pw) < 6:
                flash("Password must contain at least 6 characters for security.", "error")
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
                    flash("Avatar file size cannot exceed 1 MB.", "error")
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
            flash("Profile has been successfully updated.", "success")
            return redirect(_profile_next(url_for("account_settings")))

        if action == "remove_avatar":
            profile = db.get_user_profile(user["id"])
            if profile and profile["avatar_filename"]:
                old_path = os.path.join(config.UPLOAD_FOLDER, profile["avatar_filename"])
                if os.path.isfile(old_path):
                    os.remove(old_path)
                notify_file_deleted(profile["avatar_filename"])
                db.upsert_user_profile(user["id"], avatar_filename="")
            flash("Avatar has been successfully removed.", "success")
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
        obsidian_pages = _collect_obsidian_sync_pages(user) if user["role"] in ("editor", "admin", "protected_admin") else []
        return render_template("account/settings.html", user=user,
                                categories=categories, uncategorized=uncategorized,
                                profile=profile, obsidian_pages=obsidian_pages)

    @app.route("/account/export")
    @login_required
    def export_own_data():
        """Allow a logged-in user to download all their own data as a ZIP file."""
        user = get_current_user()
        buf = build_user_export_zip(user)
        filename = f"userdata_{user['username']}.zip"
        log_action("export_own_data", request, user=user)
        return send_file(buf, mimetype="application/zip",
                         as_attachment=True, download_name=filename)

    @app.route("/account/obsidian/export", methods=["POST"])
    @login_required
    @editor_required
    @rate_limit(5, 60)
    def export_obsidian_vault():
        """Export writable pages, uploads, and attachments for the experimental Obsidian workflow."""
        user = get_current_user()
        try:
            buf, page_count = _build_obsidian_export_zip(user, request.form.getlist("page_slugs"))
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("account_settings"))
        filename = f"obsidian_vault_{user['username']}.zip"
        log_action("export_obsidian_vault", request, user=user, page_count=page_count)
        return send_file(buf, mimetype="application/zip",
                         as_attachment=True, download_name=filename)

    @app.route("/account/obsidian/import", methods=["POST"])
    @login_required
    @editor_required
    @rate_limit(5, 60)
    def import_obsidian_vault():
        """Import an experimental Obsidian ZIP export back into BananaWiki."""
        user = get_current_user()
        try:
            summary = _import_obsidian_zip(user, request.files.get("vault_zip"))
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("account_settings"))
        notify_change(
            "obsidian_import",
            f"Obsidian import completed by '{user['username']}' "
            f"({summary['updated_pages']} updated, {summary['created_pages']} created)",
        )
        log_action(
            "import_obsidian_vault",
            request,
            user=user,
            updated_pages=summary["updated_pages"],
            created_pages=summary["created_pages"],
            restored_uploads=summary["restored_uploads"],
            imported_attachments=summary["imported_attachments"],
        )
        flash(
            "Obsidian vault has been successfully imported. "
            f"{summary['updated_pages']} pages updated, {summary['created_pages']} created, "
            f"{summary['restored_uploads']} uploads restored, and "
            f"{summary['imported_attachments']} attachments synced.",
            "success",
        )
        return redirect(url_for("account_settings"))

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
        user_badges = db.get_user_badges(target["id"], include_revoked=False)
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
            user_badges=user_badges,
            all_users=all_users,
            categories=categories,
            uncategorized=uncategorized,
        )
