"""
BananaWiki – Authentication routes (login, signup, logout, setup, lockdown).
"""

import sqlite3
import uuid
from datetime import datetime, timezone

from flask import (
    render_template, request, redirect, url_for, session, flash,
)
from werkzeug.security import generate_password_hash, check_password_hash

import db
from helpers import (
    _DUMMY_HASH, _check_login_rate_limit, _record_login_attempt,
    _clear_login_attempts, get_current_user,
    _is_valid_username, rate_limit,
)
from wiki_logger import log_action
from sync import notify_change


def register_auth_routes(app):
    """Register authentication-related routes on the Flask app."""

    @app.route("/setup", methods=["GET", "POST"])
    def setup():
        """Initial admin-account setup wizard (only accessible before setup is complete)."""
        settings = db.get_site_settings()
        if settings["setup_done"]:
            return redirect(url_for("home"))

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            confirm = request.form.get("confirm_password", "")

            if not username or not password:
                flash("Please provide both a username and password to continue.", "error")
                return render_template("auth/setup.html")
            if len(username) < 3:
                flash("Username must contain at least 3 characters.", "error")
                return render_template("auth/setup.html")
            if len(username) > 50:
                flash("Username cannot exceed 50 characters.", "error")
                return render_template("auth/setup.html")
            if not _is_valid_username(username):
                flash("Username can only contain letters, numbers, underscores, and hyphens.", "error")
                return render_template("auth/setup.html")
            if password != confirm:
                flash("Password confirmation does not match. Please try again.", "error")
                return render_template("auth/setup.html")
            if len(password) < 6:
                flash("Password must contain at least 6 characters for security.", "error")
                return render_template("auth/setup.html")

            hashed = generate_password_hash(password)
            # Re-check setup_done to prevent race condition
            settings = db.get_site_settings()
            if settings["setup_done"]:
                flash("Initial setup has already been completed.", "info")
                return redirect(url_for("login"))
            try:
                db.create_user(username, hashed, role="admin")
            except sqlite3.IntegrityError:
                flash("This username is already registered. Please choose a different one.", "error")
                return render_template("auth/setup.html")
            db.update_site_settings(setup_done=1)
            log_action("setup_complete", request, username=username)
            notify_change("setup_complete", f"Admin account '{username}' created")
            flash("Administrator account created successfully! You may now log in.", "success")
            return redirect(url_for("login"))

        return render_template("auth/setup.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        """Login page: authenticate the user and start a session."""
        settings = db.get_site_settings()
        if not settings["setup_done"]:
            return redirect(url_for("setup"))

        lockdown = bool(settings["lockdown_mode"])

        if request.method == "POST":
            if not _check_login_rate_limit():
                log_action("login_rate_limited", request)
                flash("Too many login attempts detected. Please wait one minute before trying again.", "error")
                return render_template("auth/login.html", lockdown=lockdown), 429

            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = db.get_user_by_username(username)

            if not user:
                # Constant-time: check against dummy hash to prevent timing enumeration
                check_password_hash(_DUMMY_HASH, password)
                _record_login_attempt()
                log_action("login_failed", request, username=username)
                flash("The username or password you entered is incorrect.", "error")
                return render_template("auth/login.html", lockdown=lockdown)

            if not check_password_hash(user["password"], password):
                _record_login_attempt()
                log_action("login_failed", request, username=username)
                flash("The username or password you entered is incorrect.", "error")
                return render_template("auth/login.html", lockdown=lockdown)

            if user["suspended"]:
                log_action("login_suspended", request, username=username)
                flash("Your account has been suspended. Please contact a site administrator for assistance.", "error")
                return render_template("auth/login.html", lockdown=lockdown)

            if lockdown and user["role"] not in ("admin", "protected_admin"):
                log_action("login_blocked_lockdown", request, username=username)
                flash("This wiki is currently in lockdown mode. Only administrators can access the site at this time.", "error")
                return render_template("auth/login.html", lockdown=lockdown)

            session.clear()
            session.permanent = True
            session["user_id"] = user["id"]
            if settings["session_limit_enabled"]:
                token = uuid.uuid4().hex
                session["session_token"] = token
                db.update_user(user["id"], session_token=token)
            _clear_login_attempts()
            db.update_user(user["id"], last_login_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))

            # Check and award auto-triggered badges
            db.check_and_award_auto_badges(user["id"])

            # Check for unnotified badges
            unnotified = db.get_unnotified_badges(user["id"])
            if unnotified:
                session["badge_notifications"] = len(unnotified)

            log_action("login_success", request, user=user)
            notify_change("user_login", f"User '{user['username']}' logged in")
            return redirect(url_for("home"))

        return render_template("auth/login.html", lockdown=lockdown)

    @app.route("/signup", methods=["GET", "POST"])
    @rate_limit(10, 60)
    def signup():
        """Signup page: register a new account using a valid invite code."""
        settings = db.get_site_settings()
        if not settings["setup_done"]:
            return redirect(url_for("setup"))
        if settings["lockdown_mode"]:
            return redirect(url_for("lockdown"))

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            confirm = request.form.get("confirm_password", "")
            invite = request.form.get("invite_code", "").strip().upper()

            if not username or not password or not invite:
                flash("Please complete all required fields to create your account.", "error")
                return render_template("auth/signup.html")
            if len(username) < 3:
                flash("Username must contain at least 3 characters.", "error")
                return render_template("auth/signup.html")
            if len(username) > 50:
                flash("Username cannot exceed 50 characters.", "error")
                return render_template("auth/signup.html")
            if not _is_valid_username(username):
                flash("Username can only contain letters, numbers, underscores, and hyphens.", "error")
                return render_template("auth/signup.html")
            if password != confirm:
                flash("Password confirmation does not match. Please try again.", "error")
                return render_template("auth/signup.html")
            if len(password) < 6:
                flash("Password must contain at least 6 characters for security.", "error")
                return render_template("auth/signup.html")

            code_row = db.validate_invite_code(invite)
            if not code_row:
                log_action("signup_invalid_code", request, code=invite, username=username)
                flash("The invite code you entered is invalid or has expired.", "error")
                return render_template("auth/signup.html")

            if db.get_user_by_username(username):
                flash("This username is already registered. Please choose a different one.", "error")
                return render_template("auth/signup.html")

            hashed = generate_password_hash(password)
            try:
                user_id = db.create_user(username, hashed, invite_code=invite)
            except sqlite3.IntegrityError:
                flash("This username is already registered. Please choose a different one.", "error")
                return render_template("auth/signup.html")
            if not db.use_invite_code(invite, user_id):
                # Race condition: code was used by another user concurrently
                db.delete_user(user_id)
                flash("This invite code was just used by another person. Please request a new code.", "error")
                return render_template("auth/signup.html")

            log_action("signup_success", request, username=username, invite_code=invite)
            notify_change("user_signup", f"New user '{username}' registered")
            flash("Your account has been created successfully! You may now log in.", "success")
            return redirect(url_for("login"))

        return render_template("auth/signup.html")

    @app.route("/logout", methods=["POST"])
    def logout():
        """Log out the current user by clearing the session."""
        user = get_current_user()
        if user:
            log_action("logout", request, user=user)
        session.clear()
        flash("You have been successfully logged out.", "info")
        return redirect(url_for("login"))

    @app.route("/session-conflict")
    def session_conflict():
        """Inform the user that their session is active elsewhere."""
        settings = db.get_site_settings()
        return render_template("auth/session_conflict.html", settings=settings)

    @app.route("/session-conflict/force", methods=["POST"])
    @rate_limit(10, 60)
    def session_conflict_force():
        """Log out all other sessions by clearing the stored session token."""
        settings = db.get_site_settings()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if not username or not password:
            flash("Please enter your username and password to re-authenticate.", "error")
            return redirect(url_for("session_conflict"))
        user = db.get_user_by_username(username)
        if not user or not check_password_hash(user["password"], password):
            flash("The username or password you entered is incorrect.", "error")
            return redirect(url_for("session_conflict"))
        if user["suspended"]:
            flash("Your account is currently suspended.", "error")
            return redirect(url_for("session_conflict"))
        # Issue a new session token so all other sessions are invalidated
        token = uuid.uuid4().hex
        db.update_user(user["id"], session_token=token)
        session.clear()
        session.permanent = True
        session["user_id"] = user["id"]
        session["session_token"] = token
        log_action("session_conflict_force", request, user=user)
        flash("All other sessions have been logged out. You are now signed in here.", "info")
        return redirect(url_for("home"))

    @app.route("/lockdown")
    def lockdown():
        """Display the lockdown page when the site is in lockdown mode."""
        settings = db.get_site_settings()
        if not settings["lockdown_mode"]:
            return redirect(url_for("login"))
        return render_template("auth/lockdown.html", settings=settings)
