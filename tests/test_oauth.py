"""
Tests for the OAuth2 authentication feature (GitHub and Google).

These tests exercise the database layer, admin settings, and route logic
for the OAuth feature without making real network calls.
"""

import pytest
import json


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


def _setup_oauth_settings(client, admin_headers, **kwargs):
    """POST to admin settings to configure OAuth."""
    defaults = {
        "site_name": "BananaWiki",
        "timezone": "UTC",
        "bg_color": "#16161f",
        "text_color": "#c8ccd8",
        "primary_color": "#8fa0d4",
        "secondary_color": "#1e1e2c",
        "accent_color": "#7e9ada",
        "sidebar_color": "#1a1a24",
        "chat_max_message_length": "5000",
        "chat_max_attachment_size_mb": "5",
        "chat_attachments_per_day_limit": "10",
        "chat_dm_message_retention_days": "30",
        "chat_dm_attachment_retention_days": "7",
        "chat_group_message_retention_days": "30",
        "chat_group_attachment_retention_days": "7",
        "chat_cleanup_frequency_days": "7",
        "chat_cleanup_hour": "3",
    }
    defaults.update(kwargs)
    return client.post("/admin/settings", data=defaults, headers=admin_headers,
                       follow_redirects=True)


# ---------------------------------------------------------------------------
#  DB-level OAuth tests
# ---------------------------------------------------------------------------


def test_create_oauth_user(isolated_db):
    """create_oauth_user stores the provider and id; password cannot be used to log in."""
    import db
    from werkzeug.security import check_password_hash

    uid = db.create_oauth_user("octocat", "github", "12345678")
    assert uid is not None

    user = db.get_user_by_id(uid)
    assert user is not None
    assert user["username"] == "octocat"
    assert user["oauth_provider"] == "github"
    assert user["oauth_id"] == "12345678"
    assert user["role"] == "user"

    # The stored password hash must NOT match any reasonable plain-text
    # (it was generated from a random 32-byte token)
    assert user["password"]  # password field must be populated (non-empty hash)
    assert not check_password_hash(user["password"], "password")
    assert not check_password_hash(user["password"], "")


def test_get_user_by_oauth(isolated_db):
    """get_user_by_oauth returns the correct user for provider+id."""
    import db

    uid = db.create_oauth_user("octocat2", "github", "99999")
    found = db.get_user_by_oauth("github", "99999")
    assert found is not None
    assert found["id"] == uid

    # Different provider should return None
    assert db.get_user_by_oauth("google", "99999") is None
    # Wrong id should return None
    assert db.get_user_by_oauth("github", "00000") is None


def test_list_oauth_users(isolated_db):
    """list_oauth_users returns all OAuth-registered users."""
    import db

    db.create_oauth_user("gh_user", "github", "111")
    db.create_oauth_user("g_user", "google", "222")
    # Regular user (no oauth)
    db.create_user("local_user", "somehash")

    oauth_users = db.list_oauth_users()
    usernames = [u["username"] for u in oauth_users]
    assert "gh_user" in usernames
    assert "g_user" in usernames
    assert "local_user" not in usernames


def test_update_user_oauth_columns(isolated_db):
    """update_user allows setting oauth_provider and oauth_id."""
    import db

    uid = db.create_user("alice", "hash123")
    db.update_user(uid, oauth_provider="github", oauth_id="abc123")

    user = db.get_user_by_id(uid)
    assert user["oauth_provider"] == "github"
    assert user["oauth_id"] == "abc123"

    # Can clear them too
    db.update_user(uid, oauth_provider=None, oauth_id=None)
    user = db.get_user_by_id(uid)
    assert user["oauth_provider"] is None
    assert user["oauth_id"] is None


def test_oauth_settings_defaults(isolated_db):
    """OAuth columns in site_settings default to disabled."""
    import db

    settings = db.get_site_settings()
    assert settings["github_oauth_enabled"] == 0
    assert settings["github_client_id"] == ""
    assert settings["github_client_secret"] == ""
    assert settings["google_oauth_enabled"] == 0
    assert settings["google_client_id"] == ""
    assert settings["google_client_secret"] == ""
    assert settings["oauth_signup_enabled"] == 1
    assert settings["oauth_default_role"] == "user"


def test_update_oauth_settings(isolated_db):
    """update_site_settings persists OAuth settings."""
    import db

    db.update_site_settings(
        github_oauth_enabled=1,
        github_client_id="my_client_id",
        github_client_secret="my_secret",
        google_oauth_enabled=0,
        oauth_signup_enabled=0,
        oauth_default_role="editor",
    )
    s = db.get_site_settings()
    assert s["github_oauth_enabled"] == 1
    assert s["github_client_id"] == "my_client_id"
    assert s["github_client_secret"] == "my_secret"
    assert s["google_oauth_enabled"] == 0
    assert s["oauth_signup_enabled"] == 0
    assert s["oauth_default_role"] == "editor"


# ---------------------------------------------------------------------------
#  Route-level OAuth tests
# ---------------------------------------------------------------------------


def test_github_oauth_begin_disabled(client, admin_user):
    """GitHub OAuth begin redirects to login when GitHub is disabled."""
    resp = client.get("/auth/github", follow_redirects=True)
    # Should get redirected to login with an error flash
    assert resp.status_code == 200
    assert b"not enabled" in resp.data or b"Login" in resp.data


def test_google_oauth_begin_disabled(client, admin_user):
    """Google OAuth begin redirects to login when Google is disabled."""
    resp = client.get("/auth/google", follow_redirects=True)
    assert resp.status_code == 200
    assert b"not enabled" in resp.data or b"Login" in resp.data


def test_github_callback_invalid_state(client, admin_user):
    """GitHub callback rejects mismatched state parameter."""
    import db
    db.update_site_settings(github_oauth_enabled=1, github_client_id="x", github_client_secret="y")

    # Set a state in session then call callback with a different state
    with client.session_transaction() as sess:
        sess["oauth_state"] = "correct_state"
        sess["oauth_provider"] = "github"

    resp = client.get("/auth/github/callback?code=abc&state=wrong_state",
                      follow_redirects=True)
    assert resp.status_code == 200
    assert b"mismatch" in resp.data or b"Login" in resp.data


def test_google_callback_invalid_state(client, admin_user):
    """Google callback rejects mismatched state parameter."""
    import db
    db.update_site_settings(google_oauth_enabled=1, google_client_id="x", google_client_secret="y")

    with client.session_transaction() as sess:
        sess["oauth_state"] = "correct_state"
        sess["oauth_provider"] = "google"

    resp = client.get("/auth/google/callback?code=abc&state=bad_state",
                      follow_redirects=True)
    assert resp.status_code == 200
    assert b"mismatch" in resp.data or b"Login" in resp.data


def test_github_callback_user_denied(client, admin_user):
    """GitHub callback handles user denying OAuth access gracefully."""
    import db
    db.update_site_settings(github_oauth_enabled=1, github_client_id="x", github_client_secret="y")

    with client.session_transaction() as sess:
        sess["oauth_state"] = "valid_state"

    resp = client.get("/auth/github/callback?error=access_denied&state=valid_state",
                      follow_redirects=True)
    assert resp.status_code == 200
    assert b"cancelled" in resp.data or b"Login" in resp.data


def test_oauth_signup_confirm_no_pending(client, admin_user):
    """oauth_signup_confirm redirects to login if no pending data in session."""
    resp = client.get("/auth/oauth-signup", follow_redirects=True)
    assert resp.status_code == 200
    assert b"No pending" in resp.data or b"Login" in resp.data


def test_oauth_signup_confirm_post(client, admin_user):
    """oauth_signup_confirm creates a new user when given valid username."""
    import db
    db.update_site_settings(oauth_signup_enabled=1, oauth_default_role="user")

    with client.session_transaction() as sess:
        sess["oauth_pending"] = {
            "provider": "github",
            "provider_id": "7654321",
            "provider_login": "testuser",
            "suggested_username": "testuser",
        }

    resp = client.post("/auth/oauth-signup",
                       data={"username": "testuser_oauth", "csrf_token": "x"},
                       follow_redirects=True)
    # Should have created the user and logged them in
    user = db.get_user_by_username("testuser_oauth")
    assert user is not None
    assert user["oauth_provider"] == "github"
    assert user["oauth_id"] == "7654321"
    assert user["role"] == "user"


def test_oauth_signup_confirm_duplicate_username(client, admin_user):
    """oauth_signup_confirm rejects a username that's already taken."""
    import db
    db.create_user("existing_user", "somehash")

    with client.session_transaction() as sess:
        sess["oauth_pending"] = {
            "provider": "github",
            "provider_id": "9999",
            "provider_login": "existing_user",
            "suggested_username": "existing_user",
        }

    resp = client.post("/auth/oauth-signup",
                       data={"username": "existing_user", "csrf_token": "x"},
                       follow_redirects=True)
    assert b"already taken" in resp.data


def test_oauth_signup_confirm_short_username(client, admin_user):
    """oauth_signup_confirm rejects usernames shorter than 3 characters."""
    with client.session_transaction() as sess:
        sess["oauth_pending"] = {
            "provider": "github",
            "provider_id": "8888",
            "provider_login": "ab",
            "suggested_username": "ab",
        }

    resp = client.post("/auth/oauth-signup",
                       data={"username": "ab", "csrf_token": "x"},
                       follow_redirects=True)
    assert b"3 characters" in resp.data


# ---------------------------------------------------------------------------
#  Admin OAuth management tests
# ---------------------------------------------------------------------------


def test_admin_settings_save_oauth(logged_in_admin):
    """Admin can save OAuth settings through the admin settings page."""
    import db

    resp = _setup_oauth_settings(
        logged_in_admin,
        {},
        github_oauth_enabled="1",
        github_client_id="my_gh_client",
        github_client_secret="my_gh_secret",
        oauth_signup_enabled="1",
        oauth_default_role="user",
    )
    assert resp.status_code == 200

    s = db.get_site_settings()
    assert s["github_oauth_enabled"] == 1
    assert s["github_client_id"] == "my_gh_client"
    assert s["github_client_secret"] == "my_gh_secret"


def test_admin_can_set_oauth_user_password(logged_in_admin):
    """Admin can set a password for an OAuth-only user."""
    import db

    uid = db.create_oauth_user("oauthonly", "github", "555")

    resp = logged_in_admin.post(f"/admin/users/{uid}/edit", data={
        "action": "change_password",
        "password": "newpassword123",
        "confirm_password": "newpassword123",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"updated" in resp.data

    from werkzeug.security import check_password_hash
    updated = db.get_user_by_id(uid)
    assert check_password_hash(updated["password"], "newpassword123")


def test_admin_can_unlink_oauth(logged_in_admin):
    """Admin can remove the OAuth link from a user's account."""
    import db

    uid = db.create_oauth_user("oauthlinked", "github", "777")

    resp = logged_in_admin.post(f"/admin/users/{uid}/edit", data={
        "action": "unlink_oauth",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"unlinked" in resp.data

    updated = db.get_user_by_id(uid)
    assert updated["oauth_provider"] is None
    assert updated["oauth_id"] is None


def test_admin_unlink_oauth_no_provider(logged_in_admin):
    """Admin unlink_oauth action gracefully handles users with no OAuth link."""
    import db

    uid = db.create_user("localonly", "hash_pw")

    resp = logged_in_admin.post(f"/admin/users/{uid}/edit", data={
        "action": "unlink_oauth",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"no linked" in resp.data.lower()


def test_admin_settings_page_shows_oauth_section(logged_in_admin):
    """The admin settings page renders the OAuth section correctly."""
    resp = logged_in_admin.get("/admin/settings")
    assert resp.status_code == 200
    assert b"GitHub OAuth" in resp.data
    assert b"Google OAuth" in resp.data
    assert b"github_client_id" in resp.data


def test_login_page_shows_oauth_buttons_when_enabled(client, admin_user):
    """Login page shows GitHub/Google buttons when providers are enabled."""
    import db

    db.update_site_settings(
        github_oauth_enabled=1,
        github_client_id="cid",
        github_client_secret="csec",
    )

    resp = client.get("/login")
    assert resp.status_code == 200
    assert b"oauth_github_begin" in resp.data or b"/auth/github" in resp.data


def test_login_page_hides_oauth_buttons_when_disabled(client, admin_user):
    """Login page does not show OAuth buttons when all providers are disabled."""
    import db
    db.update_site_settings(github_oauth_enabled=0, google_oauth_enabled=0)

    resp = client.get("/login")
    assert resp.status_code == 200
    assert b"btn-oauth" not in resp.data


def test_unique_username_generation(isolated_db):
    """_unique_username produces a unique username even if the base is taken."""
    from routes.oauth import _unique_username
    import db

    db.create_user("alice", "hash")
    name = _unique_username("alice")
    assert name != "alice"
    assert not db.get_user_by_username(name)


def test_sanitize_oauth_username():
    """_sanitize_oauth_username strips invalid characters."""
    from routes.oauth import _sanitize_oauth_username

    assert _sanitize_oauth_username("john doe") == "john_doe"
    assert _sanitize_oauth_username("user@example.com") == "user_example_com"
    assert _sanitize_oauth_username("") == "user"
    assert len(_sanitize_oauth_username("a" * 100)) <= 50


def test_oauth_default_role_validation(logged_in_admin):
    """oauth_default_role only accepts 'user' or 'editor'; others default to 'user'."""
    import db

    _setup_oauth_settings(logged_in_admin, {}, oauth_default_role="admin")
    s = db.get_site_settings()
    # Should have been coerced to 'user' since 'admin' is not allowed
    assert s["oauth_default_role"] == "user"


def test_account_settings_unlink_oauth(client, admin_user):
    """A logged-in OAuth user can unlink their provider from account settings."""
    import db

    uid = db.create_oauth_user("oauth_user_acc", "google", "google_456")

    # Log in the user
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    resp = client.post("/account", data={
        "action": "unlink_oauth",
    }, follow_redirects=True)
    assert resp.status_code == 200

    updated = db.get_user_by_id(uid)
    assert updated["oauth_provider"] is None
