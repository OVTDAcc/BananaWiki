"""
Tests for the custom permission system.

Tests the new granular permission system for editors and users,
including permission checking, category access, and role changes.
"""
import os
import sys
import pytest
from werkzeug.security import generate_password_hash

# Ensure the project root is importable
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
    """Create a test client."""
    from app import app
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        yield c


@pytest.fixture
def admin_user():
    """Create an admin user and mark setup as done."""
    import db
    uid = db.create_user("admin", generate_password_hash("admin123"), role="admin")
    db.update_site_settings(setup_done=1)
    return uid


@pytest.fixture
def logged_in_admin(client, admin_user):
    """Return a client that is logged in as admin."""
    client.post("/login", data={"username": "admin", "password": "admin123"})
    return client


# ============================================================================
# PERMISSION SYSTEM TESTS
# ============================================================================

def test_permission_constants():
    """Test that permission constants are properly defined."""
    from helpers._permissions import (
        PERMISSIONS,
        get_all_permission_keys,
        get_default_permissions,
    )

    # Check that permissions are defined
    assert len(PERMISSIONS) > 0

    # Check that all permission keys are unique
    all_keys = get_all_permission_keys()
    assert len(all_keys) == len(set(all_keys))

    # Check defaults exist for both roles
    editor_defaults = get_default_permissions('editor')
    user_defaults = get_default_permissions('user')

    assert len(editor_defaults) > 0
    assert len(user_defaults) > 0
    assert len(editor_defaults) > len(user_defaults)  # Editors should have more permissions


def test_create_user_with_permissions():
    """Test creating a user with default permissions."""
    import db
    from helpers._permissions import get_default_permissions

    # Create an editor
    editor_id = db.create_user("editor1", generate_password_hash("pass123"), role="editor")

    # Set default permissions
    defaults = get_default_permissions('editor')
    db.set_user_permissions(editor_id, defaults)

    # Verify permissions were set
    perms = db.get_user_permissions(editor_id)
    assert len(perms['enabled_permissions']) == len(defaults)
    assert perms['enabled_permissions'] == defaults


def test_permission_checking():
    """Test has_permission function."""
    import db
    from helpers._permissions import get_default_permissions

    # Create editor with default permissions
    editor_id = db.create_user("editor1", generate_password_hash("pass123"), role="editor")
    defaults = get_default_permissions('editor')
    db.set_user_permissions(editor_id, defaults)

    editor = {"id": editor_id, "role": "editor"}

    # Check permission that should be enabled
    assert db.has_permission(editor, "page.create")

    # Check permission that shouldn't be enabled by default
    assert not db.has_permission(editor, "category.delete")

    # Admins should have all permissions
    admin_id = db.create_user("admin1", generate_password_hash("pass123"), role="admin")
    admin = {"id": admin_id, "role": "admin"}
    assert db.has_permission(admin, "page.create")
    assert db.has_permission(admin, "category.delete")


def test_category_read_access():
    """Test category read access restrictions."""
    import db
    from helpers._permissions import get_default_permissions

    # Create categories
    cat1 = db.create_category("Category 1")
    cat2 = db.create_category("Category 2")

    # Create user with restricted read access to cat1 only
    user_id = db.create_user("user1", generate_password_hash("pass123"), role="user")
    defaults = get_default_permissions('user')
    db.set_user_permissions(
        user_id, defaults,
        read_restricted=True,
        read_category_ids=[cat1],
    )

    user = {"id": user_id, "role": "user"}

    # Should have access to cat1
    assert db.has_category_read_access(user, cat1)

    # Should NOT have access to cat2
    assert not db.has_category_read_access(user, cat2)

    # Should NOT have access to uncategorized (None)
    assert not db.has_category_read_access(user, None)


def test_category_write_access():
    """Test category write access restrictions."""
    import db
    from helpers._permissions import get_default_permissions

    # Create categories
    cat1 = db.create_category("Category 1")
    cat2 = db.create_category("Category 2")

    # Create editor with restricted write access to cat1 only
    editor_id = db.create_user("editor1", generate_password_hash("pass123"), role="editor")
    defaults = get_default_permissions('editor')
    db.set_user_permissions(
        editor_id, defaults,
        write_restricted=True,
        write_category_ids=[cat1],
    )

    editor = {"id": editor_id, "role": "editor"}

    # Should have write access to cat1
    assert db.has_category_write_access(editor, cat1)

    # Should NOT have write access to cat2
    assert not db.has_category_write_access(editor, cat2)

    # Should NOT have write access to uncategorized (None)
    assert not db.has_category_write_access(editor, None)


def test_unrestricted_category_access():
    """Test unrestricted category access."""
    import db
    from helpers._permissions import get_default_permissions

    # Create categories
    cat1 = db.create_category("Category 1")
    cat2 = db.create_category("Category 2")

    # Create editor with unrestricted access
    editor_id = db.create_user("editor1", generate_password_hash("pass123"), role="editor")
    defaults = get_default_permissions('editor')
    db.set_user_permissions(
        editor_id, defaults,
        read_restricted=False,
        write_restricted=False,
    )

    editor = {"id": editor_id, "role": "editor"}

    # Should have access to all categories
    assert db.has_category_read_access(editor, cat1)
    assert db.has_category_read_access(editor, cat2)
    assert db.has_category_read_access(editor, None)
    assert db.has_category_write_access(editor, cat1)
    assert db.has_category_write_access(editor, cat2)
    assert db.has_category_write_access(editor, None)


def test_clear_user_permissions():
    """Test clearing user permissions."""
    import db
    from helpers._permissions import get_default_permissions

    # Create user with permissions
    user_id = db.create_user("user1", generate_password_hash("pass123"), role="user")
    defaults = get_default_permissions('user')
    db.set_user_permissions(user_id, defaults)

    # Verify permissions exist
    perms = db.get_user_permissions(user_id)
    assert len(perms['enabled_permissions']) > 0

    # Clear permissions
    db.clear_user_permissions(user_id)

    # Verify permissions are cleared
    perms = db.get_user_permissions(user_id)
    assert len(perms['enabled_permissions']) == 0


def test_admin_permission_page(logged_in_admin):
    """Test accessing the admin permissions page."""
    import db
    from helpers._permissions import get_default_permissions

    # Create a user
    user_id = db.create_user("testuser", generate_password_hash("pass123"), role="user")
    defaults = get_default_permissions('user')
    db.set_user_permissions(user_id, defaults)

    # Access permissions page
    resp = logged_in_admin.get(f"/admin/users/{user_id}/permissions")
    assert resp.status_code == 200
    assert b"Custom Permissions" in resp.data
    assert b"testuser" in resp.data


def test_update_permissions_via_admin(logged_in_admin):
    """Test updating permissions through admin interface."""
    import db
    from helpers._permissions import get_default_permissions

    # Create an editor
    editor_id = db.create_user("editor1", generate_password_hash("pass123"), role="editor")
    defaults = get_default_permissions('editor')
    db.set_user_permissions(editor_id, defaults)

    # Create a category
    cat_id = db.create_category("Test Category")

    # Update permissions through POST
    resp = logged_in_admin.post(
        f"/admin/users/{editor_id}/permissions",
        data={
            "permissions": ["page.view_all", "page.create"],
            "read_restricted": "1",
            "read_category_ids": [str(cat_id)],
            "write_restricted": "1",
            "write_category_ids": [str(cat_id)],
        }
    )
    assert resp.status_code == 302  # Redirect

    # Verify permissions were updated
    perms = db.get_user_permissions(editor_id)
    assert "page.view_all" in perms['enabled_permissions']
    assert "page.create" in perms['enabled_permissions']
    assert perms['category_access']['restricted']
    assert cat_id in perms['category_access']['allowed_category_ids']


def test_role_change_initializes_permissions(logged_in_admin):
    """Test that changing role initializes default permissions."""
    import db

    # Create a user
    user_id = db.create_user("testuser", generate_password_hash("pass123"), role="user")

    # Change role to editor
    resp = logged_in_admin.post(
        f"/admin/users/{user_id}/edit",
        data={
            "action": "change_role",
            "role": "editor",
        }
    )
    assert resp.status_code == 302

    # Verify permissions were initialized
    perms = db.get_user_permissions(user_id)
    assert len(perms['enabled_permissions']) > 0


def test_create_user_initializes_permissions(logged_in_admin):
    """Test that creating a user/editor initializes permissions."""
    import db

    # Create an editor through admin interface
    resp = logged_in_admin.post(
        "/admin/users/create",
        data={
            "username": "neweditor",
            "password": "pass123",
            "confirm_password": "pass123",
            "role": "editor",
        }
    )
    assert resp.status_code == 302

    # Get the created user
    user = db.get_user_by_username("neweditor")
    assert user is not None

    # Verify permissions were initialized
    perms = db.get_user_permissions(user["id"])
    assert len(perms['enabled_permissions']) > 0


def test_user_can_view_page_helper():
    """Test the user_can_view_page helper function."""
    import db
    from helpers._auth import user_can_view_page
    from helpers._permissions import get_default_permissions

    # Create a category and pages
    cat_id = db.create_category("Test Category")
    page_id = db.create_page("Test Page", "test-page", "Content", category_id=cat_id)
    deindexed_page_id = db.create_page("Hidden Page", "hidden", "Secret", category_id=cat_id)
    db.set_page_deindexed(deindexed_page_id, True)

    # Get page objects
    page = db.get_page_by_slug("test-page")
    deindexed_page = db.get_page_by_slug("hidden")

    # Create user with restricted read access (no access to this category)
    user_id = db.create_user("user1", generate_password_hash("pass123"), role="user")
    defaults = get_default_permissions('user')
    db.set_user_permissions(
        user_id, defaults,
        read_restricted=True,
        read_category_ids=[],  # No categories allowed
    )
    user = {"id": user_id, "role": "user"}

    # User should NOT be able to view the page
    assert not user_can_view_page(user, page)

    # User should NOT be able to view deindexed page
    assert not user_can_view_page(user, deindexed_page)

    # Create editor with view_deindexed permission and unrestricted access
    editor_id = db.create_user("editor1", generate_password_hash("pass123"), role="editor")
    editor_defaults = get_default_permissions('editor')
    db.set_user_permissions(
        editor_id, editor_defaults,
        read_restricted=False,
    )
    editor = {"id": editor_id, "role": "editor"}

    # Editor should be able to view regular page
    assert user_can_view_page(editor, page)

    # Editor should be able to view deindexed page (if has permission)
    if "page.view_deindexed" in editor_defaults:
        assert user_can_view_page(editor, deindexed_page)


def test_separate_read_write_restrictions():
    """Test that read and write restrictions are independent."""
    import db
    from helpers._permissions import get_default_permissions

    # Create categories
    cat1 = db.create_category("Category 1")
    cat2 = db.create_category("Category 2")
    cat3 = db.create_category("Category 3")

    # Create editor with:
    # - Read access to cat1 and cat2
    # - Write access to cat2 and cat3
    editor_id = db.create_user("editor1", generate_password_hash("pass123"), role="editor")
    defaults = get_default_permissions('editor')
    db.set_user_permissions(
        editor_id, defaults,
        read_restricted=True,
        read_category_ids=[cat1, cat2],
        write_restricted=True,
        write_category_ids=[cat2, cat3],
    )

    editor = {"id": editor_id, "role": "editor"}

    # cat1: read yes, write no
    assert db.has_category_read_access(editor, cat1)
    assert not db.has_category_write_access(editor, cat1)

    # cat2: read yes, write yes
    assert db.has_category_read_access(editor, cat2)
    assert db.has_category_write_access(editor, cat2)

    # cat3: read no, write yes
    assert not db.has_category_read_access(editor, cat3)
    assert db.has_category_write_access(editor, cat3)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
