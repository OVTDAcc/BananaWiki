"""
Tests for the page checkout (edit-lock) feature.

Covers:
  - DB layer: checkout_page, release_checkout, get_page_checkout, cleanup_expired_checkouts
  - Route: GET /page/<slug>/edit checks out the page
  - Route: POST /page/<slug>/edit releases the checkout on save
  - Route: POST /page/<slug>/checkout/release releases the checkout manually
  - checkout_page is idempotent (refresh by same user)
  - checkout by one user is visible to another
  - expired checkouts are treated as absent
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Use a fresh temporary database for every test."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(config, "DATABASE_PATH", db_path)
    monkeypatch.setattr(config, "LOGGING_ENABLED", False)
    monkeypatch.setattr(config, "CHECKOUT_TIMEOUT_MINUTES", 30)
    import db as db_mod
    db_mod.init_db()
    yield db_path


@pytest.fixture(autouse=True)
def clear_rl_store():
    """Clear the in-memory rate-limit store before and after each test."""
    import app as app_mod
    with app_mod._RL_LOCK:
        app_mod._RL_STORE.clear()
    yield
    with app_mod._RL_LOCK:
        app_mod._RL_STORE.clear()


@pytest.fixture
def client():
    """Flask test client with CSRF disabled."""
    from app import app
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        yield c


@pytest.fixture
def editor_user():
    """Create an editor user and mark setup as done."""
    from werkzeug.security import generate_password_hash
    import db
    uid = db.create_user("editor1", generate_password_hash("pass123"), role="editor")
    db.update_site_settings(setup_done=1)
    return uid


@pytest.fixture
def second_editor():
    """Create a second editor user."""
    from werkzeug.security import generate_password_hash
    import db
    uid = db.create_user("editor2", generate_password_hash("pass456"), role="editor")
    return uid


@pytest.fixture
def logged_in_editor(client, editor_user):
    """Return a test client logged in as editor1."""
    client.post("/login", data={"username": "editor1", "password": "pass123"})
    return client


@pytest.fixture
def wiki_page():
    """Return the home page (always exists after init_db)."""
    import db
    return db.get_home_page()


@pytest.fixture
def normal_page():
    """Create a non-home wiki page and return it."""
    import db
    db.create_page("Test Page", "test-page", "", category_id=None)
    return db.get_page_by_slug("test-page")


# ---------------------------------------------------------------------------
# DB layer tests
# ---------------------------------------------------------------------------

class TestCheckoutDBLayer:
    def test_checkout_creates_record(self, editor_user, wiki_page):
        import db
        assert db.get_page_checkout(wiki_page["id"]) is None
        db.checkout_page(wiki_page["id"], editor_user)
        row = db.get_page_checkout(wiki_page["id"])
        assert row is not None
        assert row["user_id"] == editor_user

    def test_checkout_is_idempotent_for_same_user(self, editor_user, wiki_page):
        """Re-checking-out by the same user updates expires_at but keeps the lock."""
        import db
        db.checkout_page(wiki_page["id"], editor_user)
        first = db.get_page_checkout(wiki_page["id"])
        db.checkout_page(wiki_page["id"], editor_user)
        second = db.get_page_checkout(wiki_page["id"])
        assert second is not None
        assert second["user_id"] == editor_user
        # expires_at should be >= first checkout's expires_at
        assert second["expires_at"] >= first["expires_at"]

    def test_checkout_by_second_user_replaces_first(
        self, editor_user, second_editor, wiki_page
    ):
        """A second checkout replaces the first (last writer wins)."""
        import db
        db.checkout_page(wiki_page["id"], editor_user)
        db.checkout_page(wiki_page["id"], second_editor)
        row = db.get_page_checkout(wiki_page["id"])
        assert row["user_id"] == second_editor

    def test_release_removes_record(self, editor_user, wiki_page):
        import db
        db.checkout_page(wiki_page["id"], editor_user)
        db.release_checkout(wiki_page["id"], editor_user)
        assert db.get_page_checkout(wiki_page["id"]) is None

    def test_release_by_non_owner_is_noop(self, editor_user, second_editor, wiki_page):
        import db
        db.checkout_page(wiki_page["id"], editor_user)
        db.release_checkout(wiki_page["id"], second_editor)  # wrong user
        assert db.get_page_checkout(wiki_page["id"]) is not None

    def test_expired_checkout_returns_none(self, editor_user, wiki_page, monkeypatch):
        """get_page_checkout returns None and deletes the row when expired."""
        import db
        from db import _checkouts

        # Insert an already-expired checkout by monkeypatching _now_utc
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        future = past + timedelta(minutes=1)  # expires_at in the past

        original_now = _checkouts._now_utc

        call_count = [0]

        def fake_now():
            """Return past time on first call (insert), real time thereafter."""
            call_count[0] += 1
            if call_count[0] == 1:
                return past
            return original_now()

        monkeypatch.setattr(_checkouts, "_now_utc", fake_now)
        # Also patch timedelta so expires_at = past + 1 min (already past)
        import db._checkouts as _co
        monkeypatch.setattr(_co, "_now_utc", fake_now)

        # Directly insert an expired row
        from db._connection import get_db
        conn = get_db()
        conn.execute(
            "INSERT INTO page_checkouts (page_id, user_id, checked_out_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (wiki_page["id"], editor_user, past.isoformat(),
             (past + timedelta(seconds=1)).isoformat()),
        )
        conn.commit()
        conn.close()

        # Now _now_utc returns real (future) time → checkout should be expired
        monkeypatch.undo()
        assert db.get_page_checkout(wiki_page["id"]) is None

    def test_cleanup_expired_checkouts(self, editor_user, wiki_page):
        """cleanup_expired_checkouts removes expired rows."""
        import db
        from datetime import timezone
        from db._connection import get_db
        past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        conn = get_db()
        conn.execute(
            "INSERT INTO page_checkouts (page_id, user_id, checked_out_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (wiki_page["id"], editor_user, past, past),
        )
        conn.commit()
        conn.close()
        removed = db.cleanup_expired_checkouts()
        assert removed == 1
        assert db.get_page_checkout(wiki_page["id"]) is None

    def test_get_page_checkout_includes_username(self, editor_user, wiki_page):
        import db
        db.checkout_page(wiki_page["id"], editor_user)
        row = db.get_page_checkout(wiki_page["id"])
        assert row["username"] == "editor1"


# ---------------------------------------------------------------------------
# Route tests
# ---------------------------------------------------------------------------

class TestCheckoutRoutes:
    def test_edit_page_get_creates_checkout(
        self, logged_in_editor, editor_user, normal_page
    ):
        """Loading the edit page auto-checks-out for the current user."""
        import db
        resp = logged_in_editor.get(f"/page/{normal_page['slug']}/edit")
        assert resp.status_code == 200
        row = db.get_page_checkout(normal_page["id"])
        assert row is not None
        assert row["user_id"] == editor_user

    def test_edit_page_post_releases_checkout(
        self, logged_in_editor, editor_user, normal_page
    ):
        """Saving a page releases the checkout."""
        import db
        # First open the editor (creates checkout)
        logged_in_editor.get(f"/page/{normal_page['slug']}/edit")
        assert db.get_page_checkout(normal_page["id"]) is not None

        # Submit the edit form
        resp = logged_in_editor.post(
            f"/page/{normal_page['slug']}/edit",
            data={
                "title": "Test Page",
                "content": "Updated content.",
                "edit_message": "",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert db.get_page_checkout(normal_page["id"]) is None

    def test_release_checkout_route(
        self, logged_in_editor, editor_user, normal_page
    ):
        """POST /page/<slug>/checkout/release releases the checkout."""
        import db
        db.checkout_page(normal_page["id"], editor_user)
        resp = logged_in_editor.post(
            f"/page/{normal_page['slug']}/checkout/release",
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert db.get_page_checkout(normal_page["id"]) is None

    def test_release_checkout_route_requires_login(self, client, normal_page):
        """Unauthenticated users cannot call the release route."""
        resp = client.post(
            f"/page/{normal_page['slug']}/checkout/release",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 403)

    def test_edit_page_shows_checkout_warning(
        self, client, editor_user, second_editor, normal_page
    ):
        """Editor 2 sees a warning when editor 1 already has the page checked out."""
        import db
        db.checkout_page(normal_page["id"], editor_user)

        # Log in as editor 2
        client.post("/login", data={"username": "editor2", "password": "pass456"})
        resp = client.get(f"/page/{normal_page['slug']}/edit")
        assert resp.status_code == 200
        assert b"editor1" in resp.data
        assert b"already editing" in resp.data

    def test_view_page_shows_checkout_indicator(
        self, logged_in_editor, editor_user, second_editor, normal_page
    ):
        """The page view shows a checkout banner when someone is editing."""
        import db
        db.checkout_page(normal_page["id"], second_editor)
        resp = logged_in_editor.get(f"/page/{normal_page['slug']}")
        assert resp.status_code == 200
        assert b"editor2" in resp.data
        assert b"currently editing" in resp.data

    def test_view_page_no_banner_for_own_checkout(
        self, logged_in_editor, editor_user, normal_page
    ):
        """The checkout banner is NOT shown when the viewing user holds the checkout."""
        import db
        db.checkout_page(normal_page["id"], editor_user)
        resp = logged_in_editor.get(f"/page/{normal_page['slug']}")
        assert resp.status_code == 200
        assert b"currently editing" not in resp.data
