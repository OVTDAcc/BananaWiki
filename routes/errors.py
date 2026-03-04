"""
BananaWiki – Error handler routes.
"""

from flask import render_template, flash, redirect, url_for

import db
from helpers import _safe_referrer


def register_error_handlers(app):
    """Register HTTP error handlers on the Flask app."""

    @app.errorhandler(404)
    def not_found(e):
        categories, uncategorized = db.get_category_tree()
        return render_template("wiki/404.html", categories=categories,
                               uncategorized=uncategorized), 404

    @app.errorhandler(403)
    def forbidden(e):
        categories, uncategorized = db.get_category_tree()
        return render_template("wiki/403.html", categories=categories,
                               uncategorized=uncategorized), 403

    @app.errorhandler(413)
    def request_entity_too_large(e):
        flash("File too large. Maximum upload size is 16 MB.", "error")
        return redirect(_safe_referrer() or url_for("home"))

    @app.errorhandler(429)
    def too_many_requests(e):
        try:
            categories, uncategorized = db.get_category_tree()
        except Exception:
            categories, uncategorized = [], []
        return render_template("wiki/429.html", categories=categories,
                               uncategorized=uncategorized), 429

    @app.errorhandler(500)
    def internal_error(e):
        try:
            categories, uncategorized = db.get_category_tree()
        except Exception:
            categories, uncategorized = [], []
        return render_template("wiki/500.html", categories=categories,
                               uncategorized=uncategorized), 500
