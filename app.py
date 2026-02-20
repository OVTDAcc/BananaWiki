"""
BananaWiki – Main Flask application
"""

import os
import re
import uuid
import json
import functools
from datetime import datetime, timezone

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, send_from_directory, abort,
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import markdown
import bleach

import config
import db
from wiki_logger import log_request, log_action, get_logger

app = Flask(
    __name__,
    template_folder="app/templates",
    static_folder="app/static",
)
app.secret_key = config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH

ALLOWED_TAGS = list(bleach.ALLOWED_TAGS) + [
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "br", "hr", "pre", "code",
    "table", "thead", "tbody", "tr", "th", "td",
    "ul", "ol", "li", "dl", "dt", "dd",
    "img", "figure", "figcaption",
    "div", "span", "section",
    "del", "ins", "sup", "sub",
]
ALLOWED_ATTRS = {
    "*": ["class", "id", "style"],
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title", "width", "height"],
    "td": ["align"],
    "th": ["align"],
}


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------
def render_markdown(text):
    """Convert markdown to sanitised HTML."""
    html = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "codehilite", "toc", "nl2br"],
    )
    return bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS)


def slugify(text):
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text.strip("-")


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in config.ALLOWED_EXTENSIONS


def get_current_user():
    uid = session.get("user_id")
    if uid:
        return db.get_user_by_id(uid)
    return None


def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        user = db.get_user_by_id(session["user_id"])
        if not user:
            session.clear()
            flash("Account not found.", "error")
            return redirect(url_for("login"))
        if user["suspended"]:
            session.clear()
            flash("Your account has been suspended.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def editor_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user or user["role"] not in ("editor", "admin"):
            flash("You do not have permission to perform this action.", "error")
            return redirect(url_for("home"))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        user = get_current_user()
        if not user or user["role"] != "admin":
            flash("Admin access required.", "error")
            return redirect(url_for("home"))
        return f(*args, **kwargs)
    return wrapper


def time_ago(dt_str):
    """Return a human-readable 'X ago' string."""
    if not dt_str:
        return "never"
    try:
        dt = datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return "unknown"
    diff = datetime.now(timezone.utc) - dt
    secs = int(diff.total_seconds())
    if secs < 60:
        return "just now"
    elif secs < 3600:
        m = secs // 60
        return f"{m} minute{'s' if m != 1 else ''} ago"
    elif secs < 86400:
        h = secs // 3600
        return f"{h} hour{'s' if h != 1 else ''} ago"
    else:
        d = secs // 86400
        return f"{d} day{'s' if d != 1 else ''} ago"


# ---------------------------------------------------------------------------
#  Context processors
# ---------------------------------------------------------------------------
@app.context_processor
def inject_globals():
    settings = db.get_site_settings()
    user = get_current_user()
    return {
        "current_user": user,
        "settings": settings,
        "time_ago": time_ago,
    }


# ---------------------------------------------------------------------------
#  Request hooks
# ---------------------------------------------------------------------------
@app.before_request
def before_request_hook():
    settings = db.get_site_settings()
    if not settings["setup_done"] and request.endpoint not in ("setup", "static"):
        return redirect(url_for("setup"))

    user = get_current_user()
    log_request(request, user)


# ---------------------------------------------------------------------------
#  Setup (first boot)
# ---------------------------------------------------------------------------
@app.route("/setup", methods=["GET", "POST"])
def setup():
    settings = db.get_site_settings()
    if settings["setup_done"]:
        return redirect(url_for("home"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not username or not password:
            flash("Username and password are required.", "error")
            return render_template("auth/setup.html")
        if len(username) < 3:
            flash("Username must be at least 3 characters.", "error")
            return render_template("auth/setup.html")
        if password != confirm:
            flash("Passwords do not match.", "error")
            return render_template("auth/setup.html")
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("auth/setup.html")

        hashed = generate_password_hash(password)
        db.create_user(username, hashed, role="admin")
        db.update_site_settings(setup_done=1)
        log_action("setup_complete", request, username=username)
        flash("Admin account created! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("auth/setup.html")


# ---------------------------------------------------------------------------
#  Authentication
# ---------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    settings = db.get_site_settings()
    if not settings["setup_done"]:
        return redirect(url_for("setup"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = db.get_user_by_username(username)

        if not user or not check_password_hash(user["password"], password):
            log_action("login_failed", request, username=username)
            flash("Invalid username or password.", "error")
            return render_template("auth/login.html")

        if user["suspended"]:
            log_action("login_suspended", request, username=username)
            flash("Your account has been suspended. Contact an administrator.", "error")
            return render_template("auth/login.html")

        session["user_id"] = user["id"]
        log_action("login_success", request, user=user)
        return redirect(url_for("home"))

    return render_template("auth/login.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    settings = db.get_site_settings()
    if not settings["setup_done"]:
        return redirect(url_for("setup"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        invite = request.form.get("invite_code", "").strip().upper()

        if not username or not password or not invite:
            flash("All fields are required.", "error")
            return render_template("auth/signup.html")
        if len(username) < 3:
            flash("Username must be at least 3 characters.", "error")
            return render_template("auth/signup.html")
        if password != confirm:
            flash("Passwords do not match.", "error")
            return render_template("auth/signup.html")
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("auth/signup.html")

        code_row = db.validate_invite_code(invite)
        if not code_row:
            log_action("signup_invalid_code", request, code=invite, username=username)
            flash("Invalid or expired invite code.", "error")
            return render_template("auth/signup.html")

        if db.get_user_by_username(username):
            flash("Username already taken.", "error")
            return render_template("auth/signup.html")

        hashed = generate_password_hash(password)
        user_id = db.create_user(username, hashed, invite_code=invite)
        db.use_invite_code(invite, user_id)

        log_action("signup_success", request, username=username, invite_code=invite)
        flash("Account created! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("auth/signup.html")


@app.route("/logout")
def logout():
    user = get_current_user()
    if user:
        log_action("logout", request, user=user)
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
#  Account settings
# ---------------------------------------------------------------------------
@app.route("/account", methods=["GET", "POST"])
@login_required
def account_settings():
    user = get_current_user()
    action = request.form.get("action", "") if request.method == "POST" else ""

    if action == "change_username":
        new_username = request.form.get("new_username", "").strip()
        password = request.form.get("password", "")
        if not check_password_hash(user["password"], password):
            flash("Incorrect password.", "error")
        elif len(new_username) < 3:
            flash("Username must be at least 3 characters.", "error")
        elif db.get_user_by_username(new_username) and new_username.lower() != user["username"].lower():
            flash("Username already taken.", "error")
        else:
            db.update_user(user["id"], username=new_username)
            log_action("change_username", request, user=user, new_username=new_username)
            flash("Username updated.", "success")
        return redirect(url_for("account_settings"))

    if action == "change_password":
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
            flash("Password updated.", "success")
        return redirect(url_for("account_settings"))

    if action == "delete_account":
        password = request.form.get("password", "")
        if not check_password_hash(user["password"], password):
            flash("Incorrect password.", "error")
            return redirect(url_for("account_settings"))
        if user["role"] == "admin" and db.count_admins() <= 1:
            flash("Cannot delete the last admin account.", "error")
            return redirect(url_for("account_settings"))
        log_action("delete_account", request, user=user)
        db.delete_user(user["id"])
        session.clear()
        flash("Your account has been deleted.", "info")
        return redirect(url_for("login"))

    return render_template("account/settings.html", user=user)


# ---------------------------------------------------------------------------
#  Wiki – Home & pages
# ---------------------------------------------------------------------------
@app.route("/")
@login_required
def home():
    page = db.get_home_page()
    user = get_current_user()
    content_html = render_markdown(page["content"]) if page else ""
    categories, uncategorized = db.get_category_tree()
    log_action("view_page", request, user=user, page="home")
    return render_template(
        "wiki/page.html",
        page=page,
        content_html=content_html,
        categories=categories,
        uncategorized=uncategorized,
    )


@app.route("/page/<slug>")
@login_required
def view_page(slug):
    page = db.get_page_by_slug(slug)
    if not page:
        abort(404)
    user = get_current_user()
    content_html = render_markdown(page["content"])
    categories, uncategorized = db.get_category_tree()

    editor_info = None
    if page["last_edited_by"]:
        editor = db.get_user_by_id(page["last_edited_by"])
        if editor:
            editor_info = {
                "username": editor["username"],
                "time_ago": time_ago(page["last_edited_at"]),
            }

    log_action("view_page", request, user=user, page=slug)
    return render_template(
        "wiki/page.html",
        page=page,
        content_html=content_html,
        categories=categories,
        uncategorized=uncategorized,
        editor_info=editor_info,
    )


@app.route("/page/<slug>/history")
@login_required
def page_history(slug):
    page = db.get_page_by_slug(slug)
    if not page:
        abort(404)
    history = db.get_page_history(page["id"])
    categories, uncategorized = db.get_category_tree()
    return render_template(
        "wiki/history.html",
        page=page,
        history=history,
        categories=categories,
        uncategorized=uncategorized,
    )


@app.route("/page/<slug>/history/<int:entry_id>")
@login_required
def view_history_entry(slug, entry_id):
    page = db.get_page_by_slug(slug)
    if not page:
        abort(404)
    entry = db.get_history_entry(entry_id)
    if not entry or entry["page_id"] != page["id"]:
        abort(404)
    content_html = render_markdown(entry["content"])
    categories, uncategorized = db.get_category_tree()
    return render_template(
        "wiki/history_entry.html",
        page=page,
        entry=entry,
        content_html=content_html,
        categories=categories,
        uncategorized=uncategorized,
    )


@app.route("/page/<slug>/revert/<int:entry_id>", methods=["POST"])
@login_required
@editor_required
def revert_page(slug, entry_id):
    page = db.get_page_by_slug(slug)
    if not page:
        abort(404)
    entry = db.get_history_entry(entry_id)
    if not entry or entry["page_id"] != page["id"]:
        abort(404)
    user = get_current_user()
    db.update_page(page["id"], entry["title"], entry["content"], user["id"],
                   f"Reverted to version from {entry['created_at']}")
    log_action("revert_page", request, user=user, page=slug, entry_id=entry_id)
    flash("Page reverted.", "success")
    return redirect(url_for("view_page", slug=slug))


# ---------------------------------------------------------------------------
#  Page editing
# ---------------------------------------------------------------------------
@app.route("/page/<slug>/edit", methods=["GET", "POST"])
@login_required
@editor_required
def edit_page(slug):
    page = db.get_page_by_slug(slug)
    if not page:
        abort(404)
    user = get_current_user()
    categories, uncategorized = db.get_category_tree()

    # Check for existing drafts from other users
    other_drafts = [
        d for d in db.get_drafts_for_page(page["id"]) if d["user_id"] != user["id"]
    ]

    if request.method == "POST":
        title = request.form.get("title", page["title"]).strip()
        content = request.form.get("content", "")
        edit_message = request.form.get("edit_message", "").strip()
        if not title:
            title = page["title"]
        db.update_page(page["id"], title, content, user["id"], edit_message)
        db.delete_draft(page["id"], user["id"])
        log_action("edit_page", request, user=user, page=slug, message=edit_message)
        flash("Page updated.", "success")
        return redirect(url_for("view_page", slug=slug))

    # Load draft if exists
    draft = db.get_draft(page["id"], user["id"])
    return render_template(
        "wiki/edit.html",
        page=page,
        draft=draft,
        other_drafts=other_drafts,
        categories=categories,
        uncategorized=uncategorized,
        all_categories=db.list_categories(),
    )


@app.route("/page/<slug>/edit/title", methods=["POST"])
@login_required
@editor_required
def edit_page_title(slug):
    page = db.get_page_by_slug(slug)
    if not page:
        abort(404)
    user = get_current_user()
    new_title = request.form.get("title", "").strip()
    if new_title:
        db.update_page_title(page["id"], new_title, user["id"])
        log_action("edit_page_title", request, user=user, page=slug, new_title=new_title)
        flash("Title updated.", "success")
    return redirect(url_for("view_page", slug=slug))


# ---------------------------------------------------------------------------
#  Page/Category CRUD (editors/admins)
# ---------------------------------------------------------------------------
@app.route("/create-page", methods=["GET", "POST"])
@login_required
@editor_required
def create_page():
    user = get_current_user()
    categories, uncategorized = db.get_category_tree()
    all_cats = db.list_categories()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "")
        cat_id = request.form.get("category_id")
        cat_id = int(cat_id) if cat_id else None
        if not title:
            flash("Title is required.", "error")
            return render_template("wiki/create_page.html", categories=categories,
                                   uncategorized=uncategorized, all_categories=all_cats)
        slug = slugify(title)
        # ensure unique slug
        base_slug = slug
        counter = 1
        while db.get_page_by_slug(slug):
            slug = f"{base_slug}-{counter}"
            counter += 1
        db.create_page(title, slug, content, cat_id, user["id"])
        log_action("create_page", request, user=user, page=slug)
        flash("Page created.", "success")
        return redirect(url_for("view_page", slug=slug))

    return render_template("wiki/create_page.html", categories=categories,
                           uncategorized=uncategorized, all_categories=all_cats)


@app.route("/page/<slug>/delete", methods=["POST"])
@login_required
@editor_required
def delete_page_route(slug):
    page = db.get_page_by_slug(slug)
    if not page:
        abort(404)
    if page["is_home"]:
        flash("Cannot delete the home page.", "error")
        return redirect(url_for("view_page", slug=slug))
    user = get_current_user()
    db.delete_page(page["id"])
    log_action("delete_page", request, user=user, page=slug)
    flash("Page deleted.", "success")
    return redirect(url_for("home"))


@app.route("/page/<slug>/move", methods=["POST"])
@login_required
@editor_required
def move_page(slug):
    page = db.get_page_by_slug(slug)
    if not page:
        abort(404)
    cat_id = request.form.get("category_id")
    cat_id = int(cat_id) if cat_id else None
    db.update_page_category(page["id"], cat_id)
    flash("Page moved.", "success")
    return redirect(url_for("view_page", slug=slug))


@app.route("/category/create", methods=["POST"])
@login_required
@editor_required
def create_category():
    name = request.form.get("name", "").strip()
    parent_id = request.form.get("parent_id")
    parent_id = int(parent_id) if parent_id else None
    if name:
        db.create_category(name, parent_id)
        user = get_current_user()
        log_action("create_category", request, user=user, category=name)
        flash("Category created.", "success")
    return redirect(request.referrer or url_for("home"))


@app.route("/category/<int:cat_id>/edit", methods=["POST"])
@login_required
@editor_required
def edit_category(cat_id):
    name = request.form.get("name", "").strip()
    if name:
        db.update_category(cat_id, name)
        user = get_current_user()
        log_action("edit_category", request, user=user, category_id=cat_id, new_name=name)
        flash("Category updated.", "success")
    return redirect(request.referrer or url_for("home"))


@app.route("/category/<int:cat_id>/delete", methods=["POST"])
@login_required
@editor_required
def delete_category_route(cat_id):
    db.delete_category(cat_id)
    user = get_current_user()
    log_action("delete_category", request, user=user, category_id=cat_id)
    flash("Category deleted.", "success")
    return redirect(request.referrer or url_for("home"))


# ---------------------------------------------------------------------------
#  Live preview API
# ---------------------------------------------------------------------------
@app.route("/api/preview", methods=["POST"])
@login_required
def api_preview():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Invalid request: missing or malformed JSON"}), 400
    content = data.get("content", "")
    html = render_markdown(content)
    return jsonify({"html": html})


# ---------------------------------------------------------------------------
#  Drafts / autosave API
# ---------------------------------------------------------------------------
@app.route("/api/draft/save", methods=["POST"])
@login_required
@editor_required
def api_save_draft():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "invalid request"}), 400
    page_id = data.get("page_id")
    title = data.get("title", "")
    content = data.get("content", "")
    user = get_current_user()
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
    drafts = db.get_drafts_for_page(page_id)
    others = [{"username": d["username"], "user_id": d["user_id"],
               "updated_at": d["updated_at"]} for d in drafts if d["user_id"] != user["id"]]
    return jsonify(others)


@app.route("/api/draft/transfer", methods=["POST"])
@login_required
@editor_required
def api_transfer_draft():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "invalid request"}), 400
    page_id = data.get("page_id")
    from_user = data.get("from_user_id")
    user = get_current_user()
    db.transfer_draft(page_id, from_user, user["id"])
    log_action("transfer_draft", request, user=user, page_id=page_id, from_user=from_user)
    return jsonify({"ok": True})


@app.route("/api/draft/delete", methods=["POST"])
@login_required
@editor_required
def api_delete_draft():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "invalid request"}), 400
    page_id = data.get("page_id")
    user = get_current_user()
    db.delete_draft(page_id, user["id"])
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
#  Image upload
# ---------------------------------------------------------------------------
@app.route("/api/upload", methods=["POST"])
@login_required
@editor_required
def upload_image():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    if not f.filename or not allowed_file(f.filename):
        return jsonify({"error": "Invalid file type"}), 400
    os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
    ext = f.filename.rsplit(".", 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(config.UPLOAD_FOLDER, filename)
    f.save(filepath)
    user = get_current_user()
    log_action("upload_image", request, user=user, filename=filename)
    url = url_for("static", filename=f"uploads/{filename}")
    return jsonify({"url": url, "filename": filename})


@app.route("/api/upload/delete", methods=["POST"])
@login_required
@editor_required
def delete_upload():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "invalid request"}), 400
    filename = data.get("filename", "")
    filepath = os.path.join(config.UPLOAD_FOLDER, secure_filename(filename))
    if os.path.exists(filepath):
        os.remove(filepath)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
#  Admin – User management
# ---------------------------------------------------------------------------
@app.route("/admin/users")
@login_required
@admin_required
def admin_users():
    role_filter = request.args.get("role")
    status_filter = request.args.get("status")
    users = db.list_users(role_filter=role_filter, status_filter=status_filter)
    categories, uncategorized = db.get_category_tree()
    return render_template("admin/users.html", users=users,
                           role_filter=role_filter, status_filter=status_filter,
                           categories=categories, uncategorized=uncategorized)


@app.route("/admin/users/<int:user_id>/edit", methods=["POST"])
@login_required
@admin_required
def admin_edit_user(user_id):
    target = db.get_user_by_id(user_id)
    if not target:
        abort(404)
    action = request.form.get("action", "")
    current_user = get_current_user()

    if action == "change_username":
        new_name = request.form.get("username", "").strip()
        if new_name and len(new_name) >= 3:
            existing = db.get_user_by_username(new_name)
            if existing and existing["id"] != user_id:
                flash("Username already taken.", "error")
            else:
                db.update_user(user_id, username=new_name)
                log_action("admin_change_username", request, user=current_user,
                           target_user=target["username"], new_username=new_name)
                flash("Username updated.", "success")

    elif action == "change_password":
        new_pw = request.form.get("password", "")
        if len(new_pw) >= 6:
            db.update_user(user_id, password=generate_password_hash(new_pw))
            log_action("admin_change_password", request, user=current_user,
                       target_user=target["username"])
            flash("Password updated.", "success")
        else:
            flash("Password must be at least 6 characters.", "error")

    elif action == "change_role":
        new_role = request.form.get("role", "")
        if new_role in ("user", "editor", "admin"):
            if target["role"] == "admin" and new_role != "admin" and db.count_admins() <= 1:
                flash("Cannot demote the last admin.", "error")
            else:
                db.update_user(user_id, role=new_role)
                log_action("admin_change_role", request, user=current_user,
                           target_user=target["username"], new_role=new_role)
                flash("Role updated.", "success")

    elif action == "suspend":
        if target["role"] == "admin" and db.count_admins() <= 1:
            flash("Cannot suspend the last admin.", "error")
        else:
            db.update_user(user_id, suspended=1)
            log_action("admin_suspend", request, user=current_user,
                       target_user=target["username"])
            flash("User suspended.", "success")

    elif action == "unsuspend":
        db.update_user(user_id, suspended=0)
        log_action("admin_unsuspend", request, user=current_user,
                   target_user=target["username"])
        flash("User unsuspended.", "success")

    elif action == "delete":
        if target["role"] == "admin" and db.count_admins() <= 1:
            flash("Cannot delete the last admin.", "error")
        else:
            db.delete_user(user_id)
            log_action("admin_delete_user", request, user=current_user,
                       target_user=target["username"])
            flash("User deleted.", "success")

    return redirect(url_for("admin_users"))


@app.route("/admin/users/create", methods=["POST"])
@login_required
@admin_required
def admin_create_user():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    confirm = request.form.get("confirm_password", "")
    role = request.form.get("role", "user")

    if not username or not password:
        flash("Username and password are required.", "error")
    elif len(username) < 3:
        flash("Username must be at least 3 characters.", "error")
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
        db.create_user(username, hashed, role=role)
        current_user = get_current_user()
        log_action("admin_create_user", request, user=current_user,
                   new_username=username, role=role)
        flash(f"User '{username}' created.", "success")

    return redirect(url_for("admin_users"))


# ---------------------------------------------------------------------------
#  Admin – Invite codes
# ---------------------------------------------------------------------------
@app.route("/admin/codes")
@login_required
@editor_required
def admin_codes():
    codes = db.list_invite_codes(active_only=True)
    categories, uncategorized = db.get_category_tree()
    return render_template("admin/codes.html", codes=codes,
                           categories=categories, uncategorized=uncategorized)


@app.route("/admin/codes/expired")
@login_required
@editor_required
def admin_codes_expired():
    codes = db.list_expired_codes()
    categories, uncategorized = db.get_category_tree()
    return render_template("admin/codes_expired.html", codes=codes,
                           categories=categories, uncategorized=uncategorized)


@app.route("/admin/codes/generate", methods=["POST"])
@login_required
@admin_required
def admin_generate_code():
    user = get_current_user()
    code = db.generate_invite_code(user["id"])
    log_action("generate_invite_code", request, user=user, code=code)
    flash(f"Invite code generated: {code}", "success")
    return redirect(url_for("admin_codes"))


@app.route("/admin/codes/<int:code_id>/delete", methods=["POST"])
@login_required
@editor_required
def admin_delete_code(code_id):
    user = get_current_user()
    db.delete_invite_code(code_id)
    log_action("delete_invite_code", request, user=user, code_id=code_id)
    flash("Invite code deleted.", "success")
    return redirect(url_for("admin_codes"))


# ---------------------------------------------------------------------------
#  Admin – Site settings
# ---------------------------------------------------------------------------
@app.route("/admin/settings", methods=["GET", "POST"])
@login_required
@admin_required
def admin_settings():
    if request.method == "POST":
        site_name = request.form.get("site_name", "").strip() or "BananaWiki"
        primary_color = request.form.get("primary_color", "#f4c542")
        secondary_color = request.form.get("secondary_color", "#1e1e2e")
        accent_color = request.form.get("accent_color", "#89b4fa")
        text_color = request.form.get("text_color", "#cdd6f4")
        sidebar_color = request.form.get("sidebar_color", "#181825")
        bg_color = request.form.get("bg_color", "#11111b")
        db.update_site_settings(
            site_name=site_name,
            primary_color=primary_color,
            secondary_color=secondary_color,
            accent_color=accent_color,
            text_color=text_color,
            sidebar_color=sidebar_color,
            bg_color=bg_color,
        )
        user = get_current_user()
        log_action("update_settings", request, user=user, site_name=site_name)
        flash("Settings updated.", "success")
        return redirect(url_for("admin_settings"))

    settings = db.get_site_settings()
    categories, uncategorized = db.get_category_tree()
    return render_template("admin/settings.html", settings=settings,
                           categories=categories, uncategorized=uncategorized)


# ---------------------------------------------------------------------------
#  Error handlers
# ---------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(e):
    return render_template("wiki/404.html"), 404


@app.errorhandler(403)
def forbidden(e):
    return render_template("wiki/404.html"), 403


# ---------------------------------------------------------------------------
#  Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    db.init_db()
    get_logger()
    app.run(host=config.HOST, port=config.PORT, debug=False)
