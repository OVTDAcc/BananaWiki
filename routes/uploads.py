"""
BananaWiki – File upload/download and easter egg routes.
"""

from flask import (render_template, request, redirect, url_for, session, flash,
                   send_file, send_from_directory, jsonify, abort)
import os, io, uuid, zipfile
from werkzeug.utils import secure_filename
from PIL import Image
import db
import config
from helpers import (
    login_required, editor_required, admin_required, get_current_user,
    allowed_file, allowed_attachment, rate_limit, editor_has_category_access,
)
import wiki_logger
from sync import notify_change, notify_file_upload, notify_file_deleted


def cleanup_unused_uploads():
    """Delete uploaded image files that are not referenced in any page or history.

    Called after draft deletion, page commit, page creation, and page deletion
    so that images uploaded but never committed (or removed before committing)
    are automatically purged.  Images still present in the revision history are
    preserved because :func:`db.get_all_referenced_image_filenames` scans
    both ``pages.content`` and ``page_history.content``.
    """
    if not os.path.isdir(config.UPLOAD_FOLDER):
        return
    referenced = db.get_all_referenced_image_filenames()
    for fname in os.listdir(config.UPLOAD_FOLDER):
        if fname.startswith("."):
            continue
        if fname not in referenced:
            fpath = os.path.join(config.UPLOAD_FOLDER, fname)
            if os.path.isfile(fpath):
                try:
                    os.remove(fpath)
                    notify_file_deleted(fname)
                except OSError:
                    pass


def register_upload_routes(app):
    """Register file upload/download and easter egg routes on the Flask app."""

    @app.route("/api/upload", methods=["POST"])
    @login_required
    @editor_required
    @rate_limit(10, 60)
    def upload_image():
        """Upload an image file for use in wiki pages; returns the URL and filename as JSON."""
        if "file" not in request.files:
            return jsonify({"error": "No file provided"}), 400
        f = request.files["file"]
        if not f.filename or not allowed_file(f.filename):
            return jsonify({"error": "Invalid file type"}), 400
        # Validate that the file is a genuine image by reading it with Pillow
        try:
            img = Image.open(f.stream)
            img.verify()
            f.stream.seek(0)
        except Exception:
            return jsonify({"error": "File is not a valid image"}), 400
        os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
        ext = f.filename.rsplit(".", 1)[1].lower()
        filename = f"{uuid.uuid4().hex}.{ext}"
        upload_root = os.path.abspath(config.UPLOAD_FOLDER)
        filepath = os.path.abspath(os.path.normpath(os.path.join(upload_root, filename)))
        if os.path.commonpath([upload_root, filepath]) != upload_root:
            return jsonify({"error": "Invalid upload path"}), 400
        f.save(filepath)
        user = get_current_user()
        wiki_logger.log_action("upload_image", request, user=user, filename=filename)
        notify_file_upload(filename, filepath)
        url = url_for("static", filename=f"uploads/{filename}")
        return jsonify({"url": url, "filename": filename})

    @app.route("/api/upload/delete", methods=["POST"])
    @login_required
    @editor_required
    @rate_limit(10, 60)
    def delete_upload():
        """Delete a previously uploaded image file by filename."""
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "invalid request"}), 400
        filename = data.get("filename", "")
        safe_name = secure_filename(filename)
        if not safe_name:
            return jsonify({"error": "invalid filename"}), 400
        filepath = os.path.join(config.UPLOAD_FOLDER, safe_name)
        upload_root = os.path.abspath(config.UPLOAD_FOLDER)
        filepath = os.path.abspath(os.path.normpath(filepath))
        if os.path.commonpath([upload_root, filepath]) != upload_root:
            return jsonify({"error": "invalid filename"}), 400
        if os.path.isfile(filepath):
            try:
                os.remove(filepath)
            except FileNotFoundError:
                pass  # file was already removed (race condition)
            except OSError:
                return jsonify({"error": "failed to delete file"}), 500
            user = get_current_user()
            wiki_logger.log_action("delete_upload", request, user=user, filename=safe_name)
            notify_file_deleted(safe_name)
        return jsonify({"ok": True})

    # ---------------------------------------------------------------------------
    #  Page Attachments
    # ---------------------------------------------------------------------------

    @app.route("/api/page/<int:page_id>/attachments", methods=["POST"])
    @login_required
    @editor_required
    @rate_limit(20, 60)
    def upload_attachment(page_id):
        """Upload a file attachment to a wiki page (max 5 MB)."""
        page = db.get_page(page_id)
        if not page:
            return jsonify({"error": "Page not found"}), 404
        user = get_current_user()
        if not editor_has_category_access(user, page["category_id"]):
            return jsonify({"error": "Access denied"}), 403
        if "file" not in request.files:
            return jsonify({"error": "No file provided"}), 400
        f = request.files["file"]
        if not f.filename or not allowed_attachment(f.filename):
            return jsonify({"error": "File type not allowed"}), 400
        # Stream to a temp file while enforcing the size limit
        os.makedirs(config.ATTACHMENT_FOLDER, exist_ok=True)
        ext = f.filename.rsplit(".", 1)[1].lower()
        stored_name = f"{uuid.uuid4().hex}.{ext}"
        attach_root = os.path.abspath(config.ATTACHMENT_FOLDER)
        filepath = os.path.abspath(os.path.join(attach_root, stored_name))
        if os.path.commonpath([attach_root, filepath]) != attach_root:
            return jsonify({"error": "Invalid upload path"}), 400
        file_size = 0
        chunk_size = 64 * 1024  # 64 KB
        try:
            with open(filepath, "wb") as out:
                while True:
                    chunk = f.stream.read(chunk_size)
                    if not chunk:
                        break
                    file_size += len(chunk)
                    if file_size > config.MAX_ATTACHMENT_SIZE:
                        out.close()
                        os.remove(filepath)
                        return jsonify({"error": "File exceeds the 5 MB limit"}), 413
                    out.write(chunk)
        except OSError:
            if os.path.isfile(filepath):
                os.remove(filepath)
            return jsonify({"error": "Failed to save file"}), 500
        original_name = secure_filename(f.filename)
        attachment_id = db.add_page_attachment(page_id, stored_name, original_name, file_size, user["id"])
        wiki_logger.log_action("upload_attachment", request, user=user, page=page["slug"], filename=original_name)
        notify_change("attachment_upload", f"Attachment '{original_name}' uploaded to page '{page['slug']}'")
        notify_file_upload(stored_name, filepath, display_name=original_name)
        return jsonify({"id": attachment_id, "name": original_name, "size": file_size})

    @app.route("/api/attachments/<int:attachment_id>", methods=["DELETE"])
    @login_required
    @editor_required
    @rate_limit(20, 60)
    def delete_attachment(attachment_id):
        """Delete a page attachment."""
        attachment = db.get_page_attachment(attachment_id)
        if not attachment:
            return jsonify({"error": "Not found"}), 404
        page = db.get_page(attachment["page_id"])
        user = get_current_user()
        if page and not editor_has_category_access(user, page["category_id"]):
            return jsonify({"error": "Access denied"}), 403
        filepath = os.path.join(config.ATTACHMENT_FOLDER, attachment["filename"])
        attach_root = os.path.abspath(config.ATTACHMENT_FOLDER)
        filepath = os.path.abspath(filepath)
        if os.path.commonpath([attach_root, filepath]) == attach_root and os.path.isfile(filepath):
            os.remove(filepath)
        db.delete_page_attachment(attachment_id)
        wiki_logger.log_action("delete_attachment", request, user=user, filename=attachment["original_name"])
        notify_change("attachment_delete", f"Attachment '{attachment['original_name']}' deleted from page '{page['slug'] if page else 'unknown'}'")
        notify_file_deleted(attachment["filename"])
        return jsonify({"ok": True})

    @app.route("/page/<slug>/attachments/<int:attachment_id>/download")
    @login_required
    def download_attachment(slug, attachment_id):
        """Download a single attachment."""
        page = db.get_page_by_slug(slug)
        if not page:
            abort(404)
        attachment = db.get_page_attachment(attachment_id)
        if not attachment or attachment["page_id"] != page["id"]:
            abort(404)
        attach_root = os.path.abspath(config.ATTACHMENT_FOLDER)
        filepath = os.path.abspath(os.path.join(attach_root, attachment["filename"]))
        if os.path.commonpath([attach_root, filepath]) != attach_root:
            abort(404)
        if not os.path.isfile(filepath):
            abort(404)
        return send_file(filepath, as_attachment=True, download_name=attachment["original_name"])

    @app.route("/page/<slug>/attachments/download-all")
    @login_required
    def download_all_attachments(slug):
        """Download all attachments for a page as a ZIP file."""
        page = db.get_page_by_slug(slug)
        if not page:
            abort(404)
        attachments = db.get_page_attachments(page["id"])
        if not attachments:
            flash("No attachments to download.", "error")
            return redirect(url_for("view_page", slug=slug))
        attach_root = os.path.abspath(config.ATTACHMENT_FOLDER)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for att in attachments:
                filepath = os.path.abspath(os.path.join(attach_root, att["filename"]))
                if os.path.commonpath([attach_root, filepath]) == attach_root and os.path.isfile(filepath):
                    zf.write(filepath, att["original_name"])
        buf.seek(0)
        zip_name = f"{slug}-attachments.zip"
        return send_file(buf, mimetype="application/zip", as_attachment=True, download_name=zip_name)

    @app.route("/doom")
    @login_required
    def play_doom():
        """Play Doom in the browser."""
        categories, uncategorized = db.get_category_tree()
        return render_template(
            "wiki/doom.html",
            categories=categories,
            uncategorized=uncategorized,
        )

    @app.route("/easter-egg")
    @login_required
    def easter_egg():
        """Easter egg celebration page — shows whether the user has found the egg."""
        user = get_current_user()
        categories, uncategorized = db.get_category_tree()
        return render_template(
            "wiki/easter_egg.html",
            categories=categories,
            uncategorized=uncategorized,
        )

    @app.route("/api/easter-egg/trigger", methods=["POST"])
    @login_required
    @rate_limit(10, 60)
    def easter_egg_trigger():
        """Record that the logged-in user has found the easter egg (one-way flag)."""
        user = get_current_user()
        db.set_easter_egg_found(user["id"])
        wiki_logger.log_action("easter_egg_triggered", request, user=user)
        return jsonify({"ok": True})
