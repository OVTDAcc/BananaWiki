"""
BananaWiki – Error handler routes.
"""

from flask import render_template, flash, redirect, url_for

import config
import db
from helpers import _safe_referrer


def register_error_handlers(app):
    """Register HTTP error handlers on the Flask app."""

    @app.errorhandler(404)
    def not_found(e):
        """Render the 404 Not Found page."""
        categories, uncategorized = db.get_category_tree()
        return render_template("wiki/404.html", categories=categories,
                               uncategorized=uncategorized), 404

    @app.errorhandler(403)
    def forbidden(e):
        """Render the 403 Forbidden page."""
        categories, uncategorized = db.get_category_tree()
        return render_template("wiki/403.html", categories=categories,
                               uncategorized=uncategorized), 403

    @app.errorhandler(413)
    def request_entity_too_large(e):
        """Redirect back with a flash message when the upload exceeds the size limit."""
        max_mb = (config.MAX_CONTENT_LENGTH + (1024 * 1024) - 1) // (1024 * 1024)
        flash(f"This upload is too large. The maximum allowed size is {max_mb} MB.", "error")
        return redirect(_safe_referrer() or url_for("home"))

    @app.errorhandler(429)
    def too_many_requests(e):
        """Render the 429 Too Many Requests page."""
        try:
            categories, uncategorized = db.get_category_tree()
        except Exception:
            categories, uncategorized = [], []
        return render_template("wiki/429.html", categories=categories,
                               uncategorized=uncategorized), 429

    @app.errorhandler(500)
    def internal_error(e):
        """Render the 500 Internal Server Error page."""
        try:
            categories, uncategorized = db.get_category_tree()
        except Exception:
            categories, uncategorized = [], []
        return render_template("wiki/500.html", categories=categories,
                               uncategorized=uncategorized), 500
