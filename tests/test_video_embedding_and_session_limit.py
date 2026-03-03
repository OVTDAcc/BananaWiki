"""
Tests for video embedding and session limit features.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Use a temporary database for every test."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(config, "DATABASE_PATH", db_path)
    monkeypatch.setattr(config, "LOGGING_ENABLED", False)
    import db as db_mod
    db_mod.init_db()
    yield db_path


@pytest.fixture(autouse=True)
def clear_rl_store():
    """Clear the in-memory rate limit store before and after each test."""
    import app as app_mod
    with app_mod._RL_LOCK:
        app_mod._RL_STORE.clear()
    yield
    with app_mod._RL_LOCK:
        app_mod._RL_STORE.clear()


@pytest.fixture
def client():
    from app import app
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        yield c


@pytest.fixture
def admin_user():
    """Create an admin user and mark setup as done."""
    from werkzeug.security import generate_password_hash
    import db
    uid = db.create_user("admin", generate_password_hash("admin123"), role="admin")
    db.update_site_settings(setup_done=1)
    return uid


@pytest.fixture
def regular_user():
    """Create a regular (non-admin) user."""
    from werkzeug.security import generate_password_hash
    import db
    uid = db.create_user("user1", generate_password_hash("userpass"), role="user")
    return uid


@pytest.fixture
def logged_in_admin(client, admin_user):
    """Return a client logged in as admin."""
    client.post("/login", data={"username": "admin", "password": "admin123"})
    return client


# ---------------------------------------------------------------------------
# Video embedding: _embed_videos_in_html helper
# ---------------------------------------------------------------------------

class TestEmbedVideosInHtml:
    def test_youtube_watch_url_is_embedded(self):
        from app import _embed_videos_in_html
        html = '<p><a href="https://www.youtube.com/watch?v=dQw4w9WgXcQ">https://www.youtube.com/watch?v=dQw4w9WgXcQ</a></p>'
        result = _embed_videos_in_html(html)
        assert "video-embed" in result
        assert "https://www.youtube.com/embed/dQw4w9WgXcQ" in result
        assert "<iframe" in result

    def test_youtube_short_url_is_embedded(self):
        from app import _embed_videos_in_html
        html = '<p><a href="https://youtu.be/dQw4w9WgXcQ">https://youtu.be/dQw4w9WgXcQ</a></p>'
        result = _embed_videos_in_html(html)
        assert "video-embed" in result
        assert "https://www.youtube.com/embed/dQw4w9WgXcQ" in result

    def test_vimeo_url_is_embedded(self):
        from app import _embed_videos_in_html
        html = '<p><a href="https://vimeo.com/123456789">https://vimeo.com/123456789</a></p>'
        result = _embed_videos_in_html(html)
        assert "video-embed" in result
        assert "https://player.vimeo.com/video/123456789" in result

    def test_non_video_link_not_affected(self):
        from app import _embed_videos_in_html
        html = '<p><a href="https://example.com">Example</a></p>'
        result = _embed_videos_in_html(html)
        assert "video-embed" not in result
        assert result == html

    def test_youtube_link_with_custom_text_not_embedded(self):
        """Links with custom text (href != text) should not be embedded."""
        from app import _embed_videos_in_html
        html = '<p><a href="https://www.youtube.com/watch?v=dQw4w9WgXcQ">Watch this video</a></p>'
        result = _embed_videos_in_html(html)
        assert "video-embed" not in result

    def test_render_markdown_embed_videos_false(self):
        from app import render_markdown
        md = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        result = render_markdown(md, embed_videos=False)
        assert "video-embed" not in result
        assert "<iframe" not in result

    def test_render_markdown_embed_videos_true_bare_url(self):
        from app import render_markdown
        # Bare URL on its own line → wrapped in <p> by markdown
        md = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        result = render_markdown(md, embed_videos=True)
        assert "video-embed" in result
        assert "https://www.youtube.com/embed/dQw4w9WgXcQ" in result

    def test_render_markdown_embed_videos_true_linked_url(self):
        from app import render_markdown
        # Angle-bracket syntax → markdown produces <a> tag
        md = "<https://www.youtube.com/watch?v=dQw4w9WgXcQ>"
        result = render_markdown(md, embed_videos=True)
        assert "video-embed" in result
        assert "https://www.youtube.com/embed/dQw4w9WgXcQ" in result


# ---------------------------------------------------------------------------
# Video embedding: admin settings toggle
# ---------------------------------------------------------------------------

class TestVideoEmbedSetting:
    def test_page_always_embeds_video(self, logged_in_admin, admin_user):
        import db
        home = db.get_home_page()
        db.update_page(
            home["id"],
            home["title"],
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            admin_user,
            "test",
        )
        resp = logged_in_admin.get("/")
        assert resp.status_code == 200
        assert b"video-embed" in resp.data
        assert b"youtube.com/embed/dQw4w9WgXcQ" in resp.data

    def test_settings_page_has_no_video_embed_checkbox(self, logged_in_admin):
        resp = logged_in_admin.get("/admin/settings")
        assert resp.status_code == 200
        assert b"video_embed_enabled" not in resp.data


# ---------------------------------------------------------------------------
# Session limit feature
# ---------------------------------------------------------------------------

class TestSessionLimitSetting:
    def test_session_limit_disabled_by_default(self):
        import db
        db.init_db()
        settings = db.get_site_settings()
        assert settings["session_limit_enabled"] == 0

    def test_admin_can_enable_session_limit(self, logged_in_admin):
        resp = logged_in_admin.post("/admin/settings", data={
            "site_name": "BananaWiki",
            "timezone": "UTC",
            "primary_color": "#7c8dc6",
            "secondary_color": "#151520",
            "accent_color": "#6e8aca",
            "text_color": "#b8bcc8",
            "sidebar_color": "#111118",
            "bg_color": "#0d0d14",
            "session_limit_enabled": "1",
        })
        assert resp.status_code in (200, 302)
        import db
        settings = db.get_site_settings()
        assert settings["session_limit_enabled"] == 1

    def test_settings_page_has_session_limit_checkbox(self, logged_in_admin):
        resp = logged_in_admin.get("/admin/settings")
        assert resp.status_code == 200
        assert b"session_limit_enabled" in resp.data

    def test_session_token_set_on_login_when_limit_enabled(self, client, admin_user):
        import db
        db.update_site_settings(session_limit_enabled=1)
        client.post("/login", data={"username": "admin", "password": "admin123"})
        user = db.get_user_by_id(admin_user)
        assert user["session_token"] is not None
        # uuid4().hex produces exactly 32 hex characters
        assert len(user["session_token"]) == 32

    def test_session_token_not_set_on_login_when_limit_disabled(self, client, admin_user):
        import db
        db.update_site_settings(session_limit_enabled=0)
        # Ensure no token from previous logins
        db.update_user(admin_user, session_token=None)
        client.post("/login", data={"username": "admin", "password": "admin123"})
        user = db.get_user_by_id(admin_user)
        assert user["session_token"] is None

    def test_second_login_invalidates_first_session(self, client, admin_user):
        """When session_limit is on, logging in from a second client ends the first session."""
        from app import app
        import db
        db.update_site_settings(session_limit_enabled=1)

        # First client logs in
        with app.test_client() as client1:
            client1.post("/login", data={"username": "admin", "password": "admin123"})
            # First client can access the home page
            resp1 = client1.get("/")
            assert resp1.status_code == 200

            # Second client logs in from a different "device"
            with app.test_client() as client2:
                client2.post("/login", data={"username": "admin", "password": "admin123"})

            # First client's next request should be redirected to login
            resp1_after = client1.get("/")
            assert resp1_after.status_code == 302
            assert "/login" in resp1_after.headers["Location"]

    def test_session_limit_disabled_allows_multiple_sessions(self, client, admin_user):
        """When session_limit is off, multiple sessions are not invalidated."""
        from app import app
        import db
        db.update_site_settings(session_limit_enabled=0)

        with app.test_client() as client1:
            client1.post("/login", data={"username": "admin", "password": "admin123"})

            with app.test_client() as client2:
                client2.post("/login", data={"username": "admin", "password": "admin123"})

            # First client's session should still be valid
            resp1 = client1.get("/")
            assert resp1.status_code == 200


# ---------------------------------------------------------------------------
# Embed Video button and modal present in editor
# ---------------------------------------------------------------------------

class TestEmbedVideoEditorUI:
    def test_embed_video_button_in_editor(self, logged_in_admin):
        import db
        home = db.get_home_page()
        resp = logged_in_admin.get(f"/page/{home['slug']}/edit")
        assert resp.status_code == 200
        assert b"embed-video-btn" in resp.data

    def test_embed_video_modal_in_editor(self, logged_in_admin):
        import db
        home = db.get_home_page()
        resp = logged_in_admin.get(f"/page/{home['slug']}/edit")
        assert resp.status_code == 200
        assert b"video-embed-modal" in resp.data
        assert b"video-url-input" in resp.data
        assert b"video-insert-btn" in resp.data

    def test_video_url_inserted_bare_renders_as_embed(self, logged_in_admin, admin_user):
        import db
        home = db.get_home_page()
        db.update_page(
            home["id"],
            home["title"],
            "https://www.youtube.com/watch?v=abc1234abcd",
            admin_user,
            "test",
        )
        resp = logged_in_admin.get("/")
        assert resp.status_code == 200
        assert b"video-embed" in resp.data
        assert b"youtube.com/embed/abc1234abcd" in resp.data


# ---------------------------------------------------------------------------
# Edit image modal in editor (click-to-edit pre-population)
# ---------------------------------------------------------------------------

class TestEditImageModalUI:
    def test_image_options_modal_in_editor(self, logged_in_admin):
        import db
        home = db.get_home_page()
        resp = logged_in_admin.get(f"/page/{home['slug']}/edit")
        assert resp.status_code == 200
        assert b"image-options-modal" in resp.data
        assert b"img-alt-input" in resp.data
        assert b"img-width-input" in resp.data

    def test_image_options_modal_has_alignment_buttons(self, logged_in_admin):
        import db
        home = db.get_home_page()
        resp = logged_in_admin.get(f"/page/{home['slug']}/edit")
        assert resp.status_code == 200
        assert b'data-align="left"' in resp.data
        assert b'data-align="right"' in resp.data
        assert b'data-align="center"' in resp.data

    def test_edit_image_js_function_exists(self, logged_in_admin):
        from app import app
        with app.test_client() as c:
            resp = c.get("/static/js/main.js")
            assert resp.status_code == 200
            assert b"openEditImageModal" in resp.data
            assert b"updateImageInEditor" in resp.data
