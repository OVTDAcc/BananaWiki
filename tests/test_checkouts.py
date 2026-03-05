"""Tests for page checkout functionality."""

import os
import sys
import pytest
from datetime import datetime, timezone, timedelta

# Ensure the project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config
import db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Use a temporary database for every test."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(config, "DATABASE_PATH", db_path)
    db.init_db()
    yield


def test_acquire_checkout_new():
    """Test acquiring a checkout on a page with no existing checkout."""
    # Create a test user and page
    user_id = db.create_user("testuser", "password123")
    page_id = db.create_page("Test Page", "test-page", "content", None, user_id)

    # Acquire checkout
    checkout = db.acquire_checkout(page_id, user_id)

    assert checkout is not None
    assert checkout["page_id"] == page_id
    assert checkout["user_id"] == user_id
    assert checkout["username"] == "testuser"
    assert checkout["checked_out_at"] is not None


def test_acquire_checkout_already_owned():
    """Test acquiring a checkout when user already owns it (refresh)."""
    user_id = db.create_user("testuser", "password123")
    page_id = db.create_page("Test Page", "test-page", "content", None, user_id)

    # Acquire checkout twice
    checkout1 = db.acquire_checkout(page_id, user_id)
    checkout2 = db.acquire_checkout(page_id, user_id)

    assert checkout2 is not None
    assert checkout2["user_id"] == user_id
    # Second checkout should have newer timestamp
    assert checkout2["checked_out_at"] >= checkout1["checked_out_at"]


def test_acquire_checkout_by_different_user():
    """Test that a different user cannot acquire a checkout."""
    user1_id = db.create_user("user1", "password123")
    user2_id = db.create_user("user2", "password123")
    page_id = db.create_page("Test Page", "test-page", "content", None, user1_id)

    # User 1 acquires checkout
    checkout1 = db.acquire_checkout(page_id, user1_id)
    assert checkout1 is not None

    # User 2 tries to acquire checkout
    checkout2 = db.acquire_checkout(page_id, user2_id)
    assert checkout2 is None


def test_release_checkout():
    """Test releasing a checkout."""
    user_id = db.create_user("testuser", "password123")
    page_id = db.create_page("Test Page", "test-page", "content", None, user_id)

    # Acquire and release checkout
    checkout = db.acquire_checkout(page_id, user_id)
    assert checkout is not None

    db.release_checkout(page_id, user_id)

    # Should be able to get checkout now (it's released)
    checkout_after = db.get_checkout(page_id)
    assert checkout_after is None


def test_get_checkout():
    """Test getting current checkout status."""
    user_id = db.create_user("testuser", "password123")
    page_id = db.create_page("Test Page", "test-page", "content", None, user_id)

    # No checkout initially
    checkout = db.get_checkout(page_id)
    assert checkout is None

    # Acquire checkout
    db.acquire_checkout(page_id, user_id)

    # Should now have checkout
    checkout = db.get_checkout(page_id)
    assert checkout is not None
    assert checkout["user_id"] == user_id


def test_refresh_checkout():
    """Test refreshing a checkout timestamp."""
    user_id = db.create_user("testuser", "password123")
    page_id = db.create_page("Test Page", "test-page", "content", None, user_id)

    # Acquire checkout
    checkout1 = db.acquire_checkout(page_id, user_id)

    # Wait a tiny bit (in real use this would be longer)
    import time
    time.sleep(0.01)

    # Refresh checkout
    success = db.refresh_checkout(page_id, user_id)
    assert success is True

    # Get updated checkout
    checkout2 = db.get_checkout(page_id)
    assert checkout2["checked_out_at"] >= checkout1["checked_out_at"]


def test_list_all_checkouts():
    """Test listing all active checkouts."""
    user1_id = db.create_user("user1", "password123")
    user2_id = db.create_user("user2", "password123")
    page1_id = db.create_page("Page 1", "page-1", "content", None, user1_id)
    page2_id = db.create_page("Page 2", "page-2", "content", None, user2_id)

    # Acquire checkouts
    db.acquire_checkout(page1_id, user1_id)
    db.acquire_checkout(page2_id, user2_id)

    # List all checkouts
    checkouts = db.list_all_checkouts()
    assert len(checkouts) == 2
    assert any(co["page_id"] == page1_id and co["user_id"] == user1_id for co in checkouts)
    assert any(co["page_id"] == page2_id and co["user_id"] == user2_id for co in checkouts)


def test_get_user_checkouts():
    """Test getting checkouts for a specific user."""
    user1_id = db.create_user("user1", "password123")
    user2_id = db.create_user("user2", "password123")
    page1_id = db.create_page("Page 1", "page-1", "content", None, user1_id)
    page2_id = db.create_page("Page 2", "page-2", "content", None, user2_id)

    # User 1 acquires two checkouts
    db.acquire_checkout(page1_id, user1_id)
    db.acquire_checkout(page2_id, user2_id)

    # Get user 1's checkouts
    user1_checkouts = db.get_user_checkouts(user1_id)
    assert len(user1_checkouts) == 1
    assert user1_checkouts[0]["page_id"] == page1_id


def test_cleanup_user_checkouts():
    """Test cleaning up all checkouts for a user."""
    user_id = db.create_user("testuser", "password123")
    page1_id = db.create_page("Page 1", "page-1", "content", None, user_id)
    page2_id = db.create_page("Page 2", "page-2", "content", None, user_id)

    # Acquire multiple checkouts
    db.acquire_checkout(page1_id, user_id)
    db.acquire_checkout(page2_id, user_id)

    # Cleanup all user checkouts
    db.cleanup_user_checkouts(user_id)

    # Should have no checkouts
    checkouts = db.get_user_checkouts(user_id)
    assert len(checkouts) == 0


def test_checkout_timeout():
    """Test that expired checkouts are automatically cleaned up."""
    user1_id = db.create_user("user1", "password123")
    user2_id = db.create_user("user2", "password123")
    page_id = db.create_page("Test Page", "test-page", "content", None, user1_id)

    # Manually create an expired checkout by directly inserting into DB
    expired_time = (datetime.now(timezone.utc) - timedelta(minutes=db.CHECKOUT_TIMEOUT_MINUTES + 1)).isoformat()
    conn = db.get_db()
    conn.execute(
        "INSERT INTO page_checkouts (page_id, user_id, checked_out_at) VALUES (?, ?, ?)",
        (page_id, user1_id, expired_time)
    )
    conn.commit()
    conn.close()

    # Try to get the checkout - should be None (expired)
    checkout = db.get_checkout(page_id)
    assert checkout is None

    # User 2 should now be able to acquire checkout
    checkout2 = db.acquire_checkout(page_id, user2_id)
    assert checkout2 is not None
    assert checkout2["user_id"] == user2_id
