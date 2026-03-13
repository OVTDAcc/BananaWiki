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

    This function now uses the new custom permission system for category write access.
    For backward compatibility, it falls back to the old editor_category_access system
    if no custom permissions are set.
    """
    if not user:
        return False

    if user["role"] in ("admin", "protected_admin"):
        return True

    # Custom permissions never elevate a regular user into editor-level write access.
    if user["role"] != "editor":
        return False

    # Use new permission system
    return db.has_category_write_access(user, category_id)


def user_can_view_category(user, category_id):
    """Return True if *user* can view pages in the given *category_id*.

    Admins always have access. Regular users and editors check their
    custom permissions for read access. Editors may always view any category
    they are allowed to write to.
    """
    if not user:
        return False

    if user["role"] in ("admin", "protected_admin"):
        return True

    # Use new permission system
    return db.has_category_read_access(user, category_id)


def user_can_view_page(user, page):
    """Return True if *user* can view the given *page*.

    Takes into account:
    - Deindexed pages (only editors/admins can see them by default)
    - Category read access restrictions
    - Custom permissions
    """
    if not user:
        return False

    # Admins can view all pages
    if user["role"] in ("admin", "protected_admin"):
        return True

    # Check category read access first so deindexed permission does not bypass
    # category restrictions introduced by the current permission system.
    category_id = page["category_id"] if "category_id" in page.keys() else None
    if not user_can_view_category(user, category_id):
        return False

    # Check if page is deindexed (handle both dict and sqlite3.Row)
    is_deindexed = page["is_deindexed"] if "is_deindexed" in page.keys() else False
    if is_deindexed:
        # Only users with page.view_deindexed permission can see them
        return db.has_permission(user, "page.view_deindexed")

    return True


def filter_visible_navigation(categories, uncategorized, user):
    """Return sidebar categories/pages filtered through the current visibility policy."""
    if not user:
        return {"categories": [], "uncategorized": []}

    def visit(nodes):
        """Recursively keep only visible categories and pages."""
        visible_nodes = []
        for node in nodes:
            filtered_children = visit(node.get("children", []))
            filtered_pages = [page for page in node.get("pages", []) if user_can_view_page(user, page)]
            if user_can_view_category(user, node["id"]):
                visible_node = dict(node)
                visible_node["children"] = filtered_children
                visible_node["pages"] = filtered_pages
                visible_nodes.append(visible_node)
            else:
                # Keep accessible descendants navigable without leaking the
                # blocked parent category's name in the sidebar.
                visible_nodes.extend(filtered_children)
        return visible_nodes

    return {
        "categories": visit(categories or []),
        "uncategorized": [page for page in (uncategorized or []) if user_can_view_page(user, page)],
    }
