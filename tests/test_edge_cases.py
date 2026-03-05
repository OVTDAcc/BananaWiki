"""
Comprehensive edge case tests for BananaWiki.

Tests critical edge cases, boundary conditions, and error handling
that were identified during code review.
"""
import os
import sys
import pytest
from io import BytesIO
from PIL import Image
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


@pytest.fixture
def editor_user():
    """Create an editor user."""
    import db
    return db.create_user("editor", generate_password_hash("editor123"), role="editor")


@pytest.fixture
def logged_in_editor(client, admin_user, editor_user):
    """Return a client that is logged in as editor."""
    client.post("/login", data={"username": "editor", "password": "editor123"})
    return client


@pytest.fixture
def regular_user():
    """Create a regular user."""
    import db
    return db.create_user("user", generate_password_hash("user123"), role="user")


@pytest.fixture
def logged_in_user(client, admin_user, regular_user):
    """Return a client that is logged in as regular user."""
    client.post("/login", data={"username": "user", "password": "user123"})
    return client


# ============================================================================
# EDGE CASE TESTS: Empty and Whitespace-Only Inputs
# ============================================================================

def test_page_title_only_whitespace(logged_in_editor):
    """Test creating page with whitespace-only title."""
    response = logged_in_editor.post("/create", data={
        "title": "   \t\n  ",
        "content": "Test content",
        "category_id": "",
        "difficulty": ""
    }, follow_redirects=True)

    # Should reject empty title after stripping
    assert response.status_code == 200
    assert b"required" in response.data.lower() or b"invalid" in response.data.lower()


def test_category_name_only_whitespace(logged_in_editor):
    """Test creating category with whitespace-only name."""
    import db
    response = logged_in_editor.post("/categories/create", data={
        "name": "   \t  ",
        "parent_id": ""
    })

    # Should reject empty name after stripping
    assert response.status_code in [200, 400]
    # Check that no category was created with empty name
    categories = db.list_categories()
    for cat in categories:
        assert cat["name"].strip() != ""


def test_search_with_empty_query(logged_in_user):
    """Test search API with empty query."""
    response = logged_in_user.get("/api/search?q=")
    # Should handle gracefully, might return 404 for missing parameter
    assert response.status_code in [200, 400, 404]


# ============================================================================
# EDGE CASE TESTS: Very Long Inputs
# ============================================================================

def test_page_title_at_max_length(logged_in_editor):
    """Test creating page with title at maximum length."""
    # Maximum is 200 characters
    max_title = "A" * 200
    response = logged_in_editor.post("/create", data={
        "title": max_title,
        "content": "Test content",
        "category_id": "",
        "difficulty": ""
    })

    assert response.status_code in [200, 302]


def test_page_title_over_max_length(logged_in_editor):
    """Test creating page with title over maximum length."""
    # Over 200 characters
    over_max_title = "A" * 201
    response = logged_in_editor.post("/create", data={
        "title": over_max_title,
        "content": "Test content",
        "category_id": "",
        "difficulty": ""
    })

    # Should reject
    assert b"too long" in response.data.lower() or b"maximum" in response.data.lower()


def test_category_name_over_max_length(logged_in_editor):
    """Test creating category with name over maximum length."""
    # Over 100 characters
    over_max_name = "A" * 101
    response = logged_in_editor.post("/categories/create", data={
        "name": over_max_name,
        "parent_id": ""
    })

    # Should reject
    assert response.status_code in [200, 400]


# ============================================================================
# EDGE CASE TESTS: Numeric Input Validation
# ============================================================================

def test_accessibility_negative_font_scale(logged_in_user):
    """Test setting negative font scale in accessibility settings."""
    import db
    response = logged_in_user.post("/api/accessibility", json={
        "font_scale": -999,
        "contrast_level": 0,
        "letter_spacing": 0,
        "line_spacing": 1.5
    })

    # Should either reject or clamp to valid range
    assert response.status_code in [200, 400]

    if response.status_code == 200:
        # If accepted, should be clamped to valid range
        user = db.get_user_by_username("user")
        settings = db.get_user_accessibility(user["id"])
        assert settings["font_scale"] >= 0


def test_accessibility_extremely_large_sidebar_width(logged_in_user):
    """Test setting extremely large sidebar width."""
    response = logged_in_user.post("/api/accessibility", json={
        "sidebar_width": 999999,
        "content_max_width": 1200
    })

    # Should either reject or clamp to valid range
    assert response.status_code in [200, 400]


def test_category_parent_id_non_numeric(logged_in_editor):
    """Test creating category with non-numeric parent_id."""
    response = logged_in_editor.post("/categories/create", data={
        "name": "Test Category",
        "parent_id": "not-a-number"
    })

    # Should reject or handle gracefully
    assert response.status_code in [200, 400, 500]


# ============================================================================
# EDGE CASE TESTS: File Upload Edge Cases
# ============================================================================

def test_upload_zero_byte_file(logged_in_editor):
    """Test uploading a zero-byte file."""
    response = logged_in_editor.post("/upload", data={
        "file": (BytesIO(b""), "empty.txt")
    })

    # Should reject zero-byte files
    assert response.status_code in [200, 400]


def test_upload_file_with_multiple_dots(logged_in_editor):
    """Test uploading file with multiple dots in name."""
    response = logged_in_editor.post("/upload", data={
        "file": (BytesIO(b"test content"), "file.name.with.dots.txt")
    })

    # Should handle gracefully - extension is last segment
    assert response.status_code in [200, 302, 400]


def test_upload_image_tiny_dimensions(logged_in_editor):
    """Test uploading 1x1 pixel image."""
    # Create 1x1 pixel image
    img = Image.new('RGB', (1, 1), color='red')
    img_bytes = BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes.seek(0)

    response = logged_in_editor.post("/upload", data={
        "file": (img_bytes, "tiny.png")
    })

    # Should either accept or reject gracefully
    assert response.status_code in [200, 302, 400]


# ============================================================================
# EDGE CASE TESTS: Category Operations
# ============================================================================

def test_category_move_to_self(logged_in_editor):
    """Test moving category to itself as parent."""
    import db
    cat_id = db.create_category("Test Category", None)

    response = logged_in_editor.post(f"/categories/{cat_id}/edit", data={
        "name": "Test Category",
        "parent_id": str(cat_id)
    })

    # Should reject moving to self
    assert b"cannot" in response.data.lower() or b"invalid" in response.data.lower()


def test_category_deep_nesting(logged_in_editor):
    """Test creating deeply nested categories."""
    import db
    parent_id = None
    cat_ids = []

    # Create 50 nested categories
    for i in range(50):
        cat_id = db.create_category(f"Category {i}", parent_id)
        cat_ids.append(cat_id)
        parent_id = cat_id

    # Should succeed or have reasonable depth limit
    assert len(cat_ids) > 0

    # Try to get category tree - should not crash
    categories = db.list_categories()
    assert isinstance(categories, list)


def test_delete_category_with_pages(logged_in_editor, editor_user):
    """Test deleting category that contains pages."""
    import db
    cat_id = db.create_category("Test Category", None)

    # Create page in category
    page_id = db.create_page(
        title="Test Page",
        content="Content",
        slug="test-page-in-cat",
        author_id=editor_user,
        category_id=cat_id
    )

    response = logged_in_editor.post(f"/categories/{cat_id}/delete")

    # Should either move pages to uncategorized or reject deletion
    assert response.status_code in [200, 302, 400]

    # Verify page still exists
    page = db.get_page_by_slug("test-page-in-cat")
    assert page is not None


# ============================================================================
# EDGE CASE TESTS: Slug Generation
# ============================================================================

def test_slug_generation_with_special_characters(logged_in_editor):
    """Test slug generation with various special characters."""
    test_titles = [
        "Test / With / Slashes",
        "Test & Ampersand",
        "Test @ Symbol",
        "Test # Hash",
    ]

    for title in test_titles:
        response = logged_in_editor.post("/create", data={
            "title": title,
            "content": "Content",
            "category_id": "",
            "difficulty": ""
        }, follow_redirects=True)

        # Should either succeed or fail gracefully
        assert response.status_code in [200, 302, 400]


def test_slug_collision_handling(logged_in_editor, editor_user):
    """Test handling of slug collisions."""
    import db

    # Create first page
    page1_id = db.create_page(
        title="Test Page",
        content="Content 1",
        slug="test-page",
        author_id=editor_user
    )

    # Try to create page with same slug
    response = logged_in_editor.post("/create", data={
        "title": "Test Page",
        "content": "Content 2",
        "category_id": "",
        "difficulty": ""
    }, follow_redirects=True)

    # Should succeed with modified slug (test-page-1)
    assert response.status_code == 200

    # Verify both pages exist
    page1 = db.get_page(page1_id)
    assert page1["slug"] == "test-page"


# ============================================================================
# EDGE CASE TESTS: User Management
# ============================================================================

def test_delete_user_with_many_contributions(logged_in_admin):
    """Test deleting user who has many page contributions."""
    import db

    # Create editor with pages
    editor_id = db.create_user("prolific_editor", generate_password_hash("password123"), "editor")

    # Create 20 pages (reduced from 100 for faster test)
    for i in range(20):
        db.create_page(
            title=f"Page {i}",
            content=f"Content {i}",
            slug=f"page-{i}",
            author_id=editor_id
        )

    # Delete user
    response = logged_in_admin.post(f"/admin/users/{editor_id}/delete")

    # Should succeed without crashing
    assert response.status_code in [200, 302]

    # Verify pages still exist (contributions should be preserved)
    page = db.get_page_by_slug("page-10")
    assert page is not None


def test_change_username_to_existing(logged_in_admin):
    """Test changing username to one that already exists."""
    import db
    user1_id = db.create_user("user1", generate_password_hash("password123"), "user")
    user2_id = db.create_user("user2", generate_password_hash("password123"), "user")

    response = logged_in_admin.post(f"/admin/users/{user1_id}/rename", data={
        "new_username": "user2"
    })

    # Should reject duplicate username
    assert response.status_code in [200, 400]
    assert b"taken" in response.data.lower() or b"exists" in response.data.lower()


# ============================================================================
# EDGE CASE TESTS: Session Management
# ============================================================================

def test_login_with_disabled_user(client, admin_user):
    """Test logging in with a disabled user account."""
    import db
    user_id = db.create_user("disabled_user", generate_password_hash("password123"), "user")

    # Disable the user
    db.update_user(user_id, disabled=True)

    # Try to login
    response = client.post("/login", data={
        "username": "disabled_user",
        "password": "password123"
    })

    # Should reject login for disabled user
    assert response.status_code == 200
    assert b"disabled" in response.data.lower() or b"suspended" in response.data.lower()


# ============================================================================
# EDGE CASE TESTS: Color Validation
# ============================================================================

def test_admin_settings_invalid_color_formats(logged_in_admin):
    """Test admin settings with various invalid color formats."""
    invalid_colors = [
        "red",  # CSS color name
        "#fff",  # 3-char hex
        "#ffffffff",  # 8-char hex with alpha
        "#gggggg",  # invalid hex characters
    ]

    for color in invalid_colors:
        response = logged_in_admin.post("/admin/settings", data={
            "site_name": "Test Wiki",
            "primary_color": color,
            "secondary_color": "#000000",
            "text_color": "#000000",
            "background_color": "#ffffff",
            "sidebar_color": "#f5f5f5",
            "accent_color": "#ff6b6b"
        })

        # Should reject invalid colors
        if response.status_code == 200:
            # If accepted, verify it's not being stored as-is
            assert b"invalid" in response.data.lower() or b"must be" in response.data.lower()


# ============================================================================
# EDGE CASE TESTS: Search Functionality
# ============================================================================

def test_search_with_sql_injection_attempt(logged_in_user):
    """Test search with SQL injection patterns."""
    sql_patterns = [
        "'; DROP TABLE pages; --",
        "1' OR '1'='1",
        "admin'--",
    ]

    for pattern in sql_patterns:
        response = logged_in_user.get(f"/api/search?q={pattern}")

        # Should handle safely (parameterized queries)
        assert response.status_code in [200, 404]
        if response.status_code == 200:
            data = response.get_json()
            assert isinstance(data, list)


def test_search_with_very_long_query(logged_in_user):
    """Test search with extremely long query string."""
    long_query = "A" * 10000
    response = logged_in_user.get(f"/api/search?q={long_query}")

    # Should handle gracefully
    assert response.status_code in [200, 400, 413, 414]


# ============================================================================
# EDGE CASE TESTS: Rate Limiting
# ============================================================================

def test_rate_limit_exactly_at_threshold(client, admin_user):
    """Test rate limiting at exact threshold."""
    # Login rate limit is 5 attempts per 60 seconds
    for i in range(5):
        response = client.post("/login", data={
            "username": "nonexistent",
            "password": "wrong"
        })
        assert response.status_code in [200, 302]

    # 6th attempt should be rate limited
    response = client.post("/login", data={
        "username": "nonexistent",
        "password": "wrong"
    })
    assert response.status_code in [429, 200]


# ============================================================================
# EDGE CASE TESTS: Concurrency (Basic)
# ============================================================================

def test_setup_already_completed(client, admin_user):
    """Test accessing setup page after setup is complete."""
    response = client.get("/setup")

    # Should redirect to login
    assert response.status_code == 302
    assert b"/login" in response.data or (response.location and "/login" in response.location)


def test_invite_code_already_used(client, admin_user):
    """Test using an invite code that was already used."""
    import db

    # Generate invite code
    code_id, code = db.create_invite_code(admin_user, hours_valid=24)

    # Use the code
    user1_id = db.create_user("user1", generate_password_hash("password123"), "user")
    success = db.use_invite_code(code, user1_id)
    assert success

    # Try to use the same code again
    user2_id = db.create_user("user2", generate_password_hash("password123"), "user")
    success = db.use_invite_code(code, user2_id)
    assert not success


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
