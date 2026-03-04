"""Authentication and authorization decorators and helpers."""

import functools

from flask import session, redirect, url_for, flash

import db


def get_current_user():
    """Return the currently logged-in user row, or None if not authenticated."""
    uid = session.get("user_id")
    if uid:
        return db.get_user_by_id(uid)
    return None


def login_required(f):
    """Decorator: redirect to login if the request has no valid authenticated session."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        """Inner wrapper that enforces the login check."""
        if "user_id" not in session:
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
    """Decorator: allow only editors and admins; redirect others to home."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        """Inner wrapper that enforces the editor role check."""
        user = get_current_user()
        if not user or user["role"] not in ("editor", "admin", "protected_admin"):
            flash("You do not have permission to perform this action.", "error")
            return redirect(url_for("home"))
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    """Decorator: allow only admins; redirect others to home."""
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        """Inner wrapper that enforces the admin role check."""
        user = get_current_user()
        if not user or user["role"] not in ("admin", "protected_admin"):
            flash("Admin access required.", "error")
            return redirect(url_for("home"))
        return f(*args, **kwargs)
    return wrapper


def editor_has_category_access(user, category_id):
    """Return True if *user* may edit content in the given *category_id*.

    Admins always have access.  Editors with unrestricted access also always
    have access.  Restricted editors only have access to their explicitly
    allowed categories; uncategorised pages (category_id=None) are not
    accessible to restricted editors.
    """
    if user["role"] in ("admin", "protected_admin"):
        return True
    access = db.get_editor_access(user["id"])
    if not access["restricted"]:
        return True
    if category_id is None:
        return False
    return int(category_id) in access["allowed_category_ids"]
