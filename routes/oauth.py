"""
BananaWiki – OAuth2 authentication routes (GitHub and Google).

Both providers use the Authorization Code flow:
  1. Redirect user to provider with a signed ``state`` parameter.
  2. Provider redirects back to /auth/<provider>/callback with ``code``.
  3. Exchange ``code`` for an access token (server-to-server POST).
  4. Fetch the user's profile from the provider API.
  5. Look up or create a local user, then start a session.

Security notes
--------------
* The ``state`` parameter is a cryptographically random token stored in the
  session to prevent CSRF / open-redirect attacks on the callback.
* Client secrets are read from the database each request so that admin changes
  take effect immediately.
* All provider HTTP calls are wrapped in try/except so network failures give a
  user-friendly error rather than a 500.
* Rate limiting is applied to the initiation endpoints (same limits as login).
"""

import secrets
import sqlite3
import uuid
import urllib.request
import urllib.parse
import json
import re
import logging
from datetime import datetime, timezone

from flask import (
    render_template, request, redirect, url_for, session, flash, abort,
)
from werkzeug.security import generate_password_hash

import db
from helpers import (
    get_current_user, rate_limit, _is_valid_username,
)
from wiki_logger import log_action
from sync import notify_change


# ---------------------------------------------------------------------------
#  Internal helpers
# ---------------------------------------------------------------------------

_USERNAME_CLEANUP_RE = re.compile(r"[^a-zA-Z0-9_-]")


def _sanitize_oauth_username(raw: str) -> str:
    """Turn a provider display name into a valid BananaWiki username."""
    cleaned = _USERNAME_CLEANUP_RE.sub("_", raw or "")
    cleaned = cleaned.strip("_")
    return (cleaned[:50] or "user")


def _unique_username(base: str) -> str:
    """Return *base* (or *base_N*) that is not already taken in the DB."""
    base = _sanitize_oauth_username(base)
    if len(base) < 3:
        base = (base + "___")[:3]
    candidate = base[:50]
    counter = 1
    while db.get_user_by_username(candidate):
        candidate = f"{base}_{counter}"[:50]
        counter += 1
        if counter > 9999:
            # Extreme fallback – generate random suffix and verify uniqueness
            for _ in range(10):
                candidate = f"{base[:20]}_{secrets.token_hex(4)}"[:50]
                if not db.get_user_by_username(candidate):
                    break
            break
    return candidate


def _http_post_json(url: str, data: dict, headers: dict = None) -> dict:
    """POST *data* (form-encoded) to *url* and return the parsed JSON body.

    Raises ``RuntimeError`` on HTTP errors or JSON parse failures.
    """
    encoded = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=encoded, headers=headers or {})
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} from {url}") from exc
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Non-JSON response from {url}: {body[:200]}") from exc


def _http_get_json(url: str, token: str) -> dict:
    """GET *url* with a Bearer token and return the parsed JSON body."""
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "BananaWiki/1.0")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} from {url}") from exc
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Non-JSON response from {url}: {body[:200]}") from exc


def _complete_oauth_login(user, settings, request_obj):
    """Finalise a session for *user* after a successful OAuth authentication.

    This mirrors the logic in the password login route.
    """
    if user["suspended"]:
        flash("Your account has been suspended. Please contact a site administrator for assistance.", "error")
        return redirect(url_for("login"))

    lockdown = bool(settings["lockdown_mode"])
    if lockdown and user["role"] not in ("admin", "protected_admin"):
        flash("This wiki is currently in lockdown mode. Only administrators can access the site at this time.", "error")
        return redirect(url_for("lockdown"))

    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    if settings["session_limit_enabled"]:
        token = uuid.uuid4().hex
        session["session_token"] = token
        db.update_user(user["id"], session_token=token)

    db.update_user(user["id"], last_login_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
    db.check_and_award_auto_badges(user["id"])
    unnotified = db.get_unnotified_badges(user["id"])
    if unnotified:
        session["badge_notifications"] = len(unnotified)

    log_action("oauth_login_success", request_obj, user=user,
               provider=user["oauth_provider"] or "linked")
    notify_change("user_login", f"User '{user['username']}' logged in via OAuth")
    return redirect(url_for("home"))


# ---------------------------------------------------------------------------
#  Route registration
# ---------------------------------------------------------------------------

def register_oauth_routes(app):
    """Register OAuth2 routes on the Flask app."""

    # -----------------------------------------------------------------------
    #  GitHub OAuth
    # -----------------------------------------------------------------------

    @app.route("/auth/github")
    @rate_limit(20, 60)
    def oauth_github_begin():
        """Redirect the user to GitHub's OAuth authorisation page."""
        settings = db.get_site_settings()
        if not settings["setup_done"]:
            return redirect(url_for("setup"))
        if not settings["github_oauth_enabled"]:
            flash("GitHub login is not enabled on this site.", "error")
            return redirect(url_for("login"))

        state = secrets.token_urlsafe(32)
        session["oauth_state"] = state
        session["oauth_provider"] = "github"

        params = urllib.parse.urlencode({
            "client_id": settings["github_client_id"],
            "redirect_uri": url_for("oauth_github_callback", _external=True),
            "scope": "user:email",
            "state": state,
        })
        return redirect(f"https://github.com/login/oauth/authorize?{params}")

    @app.route("/auth/github/callback")
    @rate_limit(20, 60)
    def oauth_github_callback():
        """Handle GitHub's redirect back after user authorisation."""
        settings = db.get_site_settings()
        if not settings["setup_done"]:
            return redirect(url_for("setup"))
        if not settings["github_oauth_enabled"]:
            flash("GitHub login is not enabled on this site.", "error")
            return redirect(url_for("login"))

        # --- CSRF state check ---
        expected_state = session.pop("oauth_state", None)
        got_state = request.args.get("state", "")
        if not expected_state or not secrets.compare_digest(expected_state, got_state):
            flash("OAuth state mismatch. Please try again.", "error")
            return redirect(url_for("login"))

        # User denied access
        if request.args.get("error"):
            flash("GitHub authorisation was cancelled.", "info")
            return redirect(url_for("login"))

        code = request.args.get("code", "")
        if not code:
            flash("No authorisation code received from GitHub. Please try again.", "error")
            return redirect(url_for("login"))

        # --- Exchange code for access token ---
        try:
            token_resp = _http_post_json(
                "https://github.com/login/oauth/access_token",
                {
                    "client_id": settings["github_client_id"],
                    "client_secret": settings["github_client_secret"],
                    "code": code,
                    "redirect_uri": url_for("oauth_github_callback", _external=True),
                },
            )
        except RuntimeError as exc:
            log_action("oauth_github_token_error", request, error=str(exc))
            flash("Could not contact GitHub to complete login. Please try again later.", "error")
            return redirect(url_for("login"))

        access_token = token_resp.get("access_token", "")
        if not access_token:
            flash("GitHub did not return an access token. Please try again.", "error")
            return redirect(url_for("login"))

        # --- Fetch GitHub user profile ---
        try:
            gh_user = _http_get_json("https://api.github.com/user", access_token)
        except RuntimeError as exc:
            log_action("oauth_github_profile_error", request, error=str(exc))
            flash("Could not retrieve your GitHub profile. Please try again later.", "error")
            return redirect(url_for("login"))

        github_id = str(gh_user.get("id", ""))
        github_login = gh_user.get("login", "")
        github_name = gh_user.get("name", "") or github_login

        if not github_id:
            flash("GitHub did not return a valid user identifier. Please try again.", "error")
            return redirect(url_for("login"))

        # --- Fetch primary verified email (login may have no public email) ---
        github_email = gh_user.get("email", "") or ""
        if not github_email:
            try:
                emails = _http_get_json("https://api.github.com/user/emails", access_token)
                primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
                if primary:
                    github_email = primary.get("email", "")
            except RuntimeError as exc:
                logging.getLogger(__name__).debug(
                    "GitHub email fetch failed (non-fatal): %s", exc
                )

        return _handle_oauth_callback(
            provider="github",
            provider_id=github_id,
            provider_login=github_login or github_name,
            provider_email=github_email,
            settings=settings,
        )

    # -----------------------------------------------------------------------
    #  Google OAuth
    # -----------------------------------------------------------------------

    @app.route("/auth/google")
    @rate_limit(20, 60)
    def oauth_google_begin():
        """Redirect the user to Google's OAuth authorisation page."""
        settings = db.get_site_settings()
        if not settings["setup_done"]:
            return redirect(url_for("setup"))
        if not settings["google_oauth_enabled"]:
            flash("Google login is not enabled on this site.", "error")
            return redirect(url_for("login"))

        state = secrets.token_urlsafe(32)
        session["oauth_state"] = state
        session["oauth_provider"] = "google"

        params = urllib.parse.urlencode({
            "client_id": settings["google_client_id"],
            "redirect_uri": url_for("oauth_google_callback", _external=True),
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "online",
        })
        return redirect(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")

    @app.route("/auth/google/callback")
    @rate_limit(20, 60)
    def oauth_google_callback():
        """Handle Google's redirect back after user authorisation."""
        settings = db.get_site_settings()
        if not settings["setup_done"]:
            return redirect(url_for("setup"))
        if not settings["google_oauth_enabled"]:
            flash("Google login is not enabled on this site.", "error")
            return redirect(url_for("login"))

        # --- CSRF state check ---
        expected_state = session.pop("oauth_state", None)
        got_state = request.args.get("state", "")
        if not expected_state or not secrets.compare_digest(expected_state, got_state):
            flash("OAuth state mismatch. Please try again.", "error")
            return redirect(url_for("login"))

        if request.args.get("error"):
            flash("Google authorisation was cancelled.", "info")
            return redirect(url_for("login"))

        code = request.args.get("code", "")
        if not code:
            flash("No authorisation code received from Google. Please try again.", "error")
            return redirect(url_for("login"))

        # --- Exchange code for access token ---
        try:
            token_resp = _http_post_json(
                "https://oauth2.googleapis.com/token",
                {
                    "client_id": settings["google_client_id"],
                    "client_secret": settings["google_client_secret"],
                    "code": code,
                    "redirect_uri": url_for("oauth_google_callback", _external=True),
                    "grant_type": "authorization_code",
                },
            )
        except RuntimeError as exc:
            log_action("oauth_google_token_error", request, error=str(exc))
            flash("Could not contact Google to complete login. Please try again later.", "error")
            return redirect(url_for("login"))

        access_token = token_resp.get("access_token", "")
        if not access_token:
            error_desc = token_resp.get("error_description", token_resp.get("error", "unknown"))
            flash(f"Google did not return an access token: {error_desc}. Please try again.", "error")
            return redirect(url_for("login"))

        # --- Fetch Google user info ---
        try:
            g_user = _http_get_json(
                "https://www.googleapis.com/oauth2/v2/userinfo", access_token
            )
        except RuntimeError as exc:
            log_action("oauth_google_profile_error", request, error=str(exc))
            flash("Could not retrieve your Google profile. Please try again later.", "error")
            return redirect(url_for("login"))

        google_id = str(g_user.get("id", ""))
        google_name = g_user.get("name", "") or g_user.get("given_name", "")
        google_email = g_user.get("email", "")

        if not google_id:
            flash("Google did not return a valid user identifier. Please try again.", "error")
            return redirect(url_for("login"))

        return _handle_oauth_callback(
            provider="google",
            provider_id=google_id,
            provider_login=google_name or google_email.split("@")[0],
            provider_email=google_email,
            settings=settings,
        )

    # -----------------------------------------------------------------------
    #  OAuth signup confirmation (shown when new user needs to pick username)
    # -----------------------------------------------------------------------

    @app.route("/auth/oauth-signup", methods=["GET", "POST"])
    @rate_limit(10, 60)
    def oauth_signup_confirm():
        """Ask the new OAuth user to confirm / adjust their username."""
        # Pending data lives in the session set by _handle_oauth_callback
        pending = session.get("oauth_pending")
        if not pending:
            flash("No pending OAuth signup found. Please try signing in again.", "error")
            return redirect(url_for("login"))

        settings = db.get_site_settings()

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            if not username:
                flash("A username is required to continue.", "error")
                return render_template("auth/oauth_signup.html",
                                       pending=pending, settings=settings)
            if len(username) < 3:
                flash("Username must be at least 3 characters long.", "error")
                return render_template("auth/oauth_signup.html",
                                       pending=pending, settings=settings)
            if len(username) > 50:
                flash("Username cannot exceed 50 characters.", "error")
                return render_template("auth/oauth_signup.html",
                                       pending=pending, settings=settings)
            if not _is_valid_username(username):
                flash("Username can only contain letters, digits, underscores and hyphens.", "error")
                return render_template("auth/oauth_signup.html",
                                       pending=pending, settings=settings)
            if db.get_user_by_username(username):
                flash("Username already taken. Please choose another.", "error")
                return render_template("auth/oauth_signup.html",
                                       pending=pending, settings=settings)

            provider = pending["provider"]
            provider_id = pending["provider_id"]
            role = settings["oauth_default_role"] or "user"
            if role not in ("user", "editor"):
                role = "user"

            try:
                user_id = db.create_oauth_user(username, provider, provider_id, role=role)
            except sqlite3.IntegrityError:
                flash("Username already taken. Please choose another.", "error")
                return render_template("auth/oauth_signup.html",
                                       pending=pending, settings=settings)
            except Exception as exc:
                logging.getLogger(__name__).error("OAuth signup failed: %s", exc)
                flash("Could not create account. Please try again.", "error")
                return render_template("auth/oauth_signup.html",
                                       pending=pending, settings=settings)

            session.pop("oauth_pending", None)
            user = db.get_user_by_id(user_id)
            log_action("oauth_signup", request, user=user, provider=provider)
            notify_change("user_signup", f"New user '{username}' registered via {provider}")
            return _complete_oauth_login(user, settings, request)

        return render_template("auth/oauth_signup.html", pending=pending, settings=settings)

    # -----------------------------------------------------------------------
    #  Shared callback handler
    # -----------------------------------------------------------------------

    def _handle_oauth_callback(provider, provider_id, provider_login, provider_email, settings):
        """Core logic shared by GitHub and Google callback routes."""
        # Look up existing user linked to this provider account
        existing = db.get_user_by_oauth(provider, provider_id)
        if existing:
            return _complete_oauth_login(existing, settings, request)

        # --- New provider ID – could be an existing user linking their account ---
        current_user = get_current_user()
        if current_user:
            # Logged-in user: link this provider to their account
            db.update_user(current_user["id"], oauth_provider=provider, oauth_id=str(provider_id))
            log_action("oauth_link", request, user=current_user, provider=provider)
            flash(f"Your {provider.capitalize()} account has been successfully linked.", "success")
            return redirect(url_for("account_settings"))

        # --- No existing user: check if new OAuth signups are allowed ---
        if not settings["oauth_signup_enabled"]:
            flash("New account registration via OAuth is not enabled on this site.", "error")
            return redirect(url_for("login"))

        # Check lockdown
        if settings["lockdown_mode"]:
            return redirect(url_for("lockdown"))

        # Build a suggested username and store pending data in session
        suggested = _unique_username(provider_login)
        session["oauth_pending"] = {
            "provider": provider,
            "provider_id": provider_id,
            "provider_login": provider_login,
            "suggested_username": suggested,
        }
        return redirect(url_for("oauth_signup_confirm"))
