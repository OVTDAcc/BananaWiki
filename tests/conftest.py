"""
Shared pytest fixtures for all test modules.

Provides isolated database, rate limit clearing, and authenticated client fixtures.
"""

import os
import sys

import pytest

# Add parent directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Use a fresh temporary database for every test."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(config, "DATABASE_PATH", db_path)
    monkeypatch.setattr(config, "LOGGING_LEVEL", "off")
    import db as db_mod
    db_mod.init_db()
    yield db_path


@pytest.fixture(autouse=True)
def clear_rl_store():
    """Clear the in-memory rate limit store before and after each test."""
    # Import app module to access rate limit store
    try:
        import app as app_mod
        with app_mod._RL_LOCK:
            app_mod._RL_STORE.clear()
    except (ImportError, AttributeError):
        # If app module or rate limit store doesn't exist, skip
        pass

    yield

    try:
        import app as app_mod
        with app_mod._RL_LOCK:
            app_mod._RL_STORE.clear()
    except (ImportError, AttributeError):
        pass


@pytest.fixture
def client():
    """Flask test client with CSRF disabled for testing."""
    # Try routes-based app first, then fall back to monolithic app
    try:
        from app import app
    except ImportError:
        import app as app_mod
        app = app_mod.app

    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        yield c


@pytest.fixture
def admin_user():
    """Create an admin user and mark setup as complete."""
    from werkzeug.security import generate_password_hash
    import db
    uid = db.create_user("admin", generate_password_hash("admin123"), role="admin")
    db.update_site_settings(setup_done=1)
    return uid


@pytest.fixture
def editor_user():
    """Create an editor user."""
    from werkzeug.security import generate_password_hash
    import db
    uid = db.create_user("editor", generate_password_hash("editor123"), role="editor")
    return uid


@pytest.fixture
def regular_user():
    """Create a regular (non-editor, non-admin) user."""
    from werkzeug.security import generate_password_hash
    import db
    uid = db.create_user("user", generate_password_hash("user123"), role="user")
    return uid


@pytest.fixture
def logged_in_admin(client, admin_user):
    """Flask client logged in as admin."""
    client.post("/login", data={"username": "admin", "password": "admin123"})
    return client


@pytest.fixture
def logged_in_editor(client, editor_user):
    """Flask client logged in as editor."""
    client.post("/login", data={"username": "editor", "password": "editor123"})
    return client


@pytest.fixture
def logged_in_user(client, regular_user):
    """Flask client logged in as regular user."""
    client.post("/login", data={"username": "user", "password": "user123"})
    return client
