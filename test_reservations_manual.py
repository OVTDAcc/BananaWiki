#!/usr/bin/env python3
"""
Manual test script for page reservation system.
Run this to verify basic functionality works.
"""
import sys
import os
from datetime import datetime, timedelta, timezone

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import db

# Use a test database
config.DATABASE_PATH = "/tmp/test_reservations.db"

def test_basic_reservation():
    """Test basic reservation functionality."""
    print("=== Testing Basic Reservation Functionality ===\n")

    # Initialize database
    print("1. Initializing database...")
    db.init_db()
    print("   ✓ Database initialized\n")

    # Create test users
    print("2. Creating test users...")
    from werkzeug.security import generate_password_hash
    user1 = db.create_user("editor1", generate_password_hash("pass"), role="editor")
    user2 = db.create_user("editor2", generate_password_hash("pass"), role="editor")
    print(f"   ✓ Created editor1 (ID: {user1})")
    print(f"   ✓ Created editor2 (ID: {user2})\n")

    # Create test page
    print("3. Creating test page...")
    page_id = db.create_page("Test Page", "test-page", "Test content")
    print(f"   ✓ Created page (ID: {page_id})\n")

    # Test 1: Reserve page
    print("4. Testing reservation...")
    reservation = db.reserve_page(page_id, user1)
    assert reservation is not None
    assert reservation["page_id"] == page_id
    assert reservation["user_id"] == user1
    print(f"   ✓ User1 reserved page successfully")
    print(f"   Reserved at: {reservation['reserved_at']}")
    print(f"   Expires at: {reservation['expires_at']}\n")

    # Test 2: Check status
    print("5. Testing reservation status...")
    status = db.get_page_reservation_status(page_id, user1)
    assert status["is_reserved"] is True
    assert status["reserved_by"] == user1
    print(f"   ✓ Status shows page is reserved")
    print(f"   Reserved by: {status['reserved_by']}")
    print(f"   Reserved by username: {status['reserved_by_username']}\n")

    # Test 3: Try to reserve again (should fail)
    print("6. Testing duplicate reservation prevention...")
    try:
        db.reserve_page(page_id, user2)
        print("   ✗ FAIL: Second reservation should have been blocked!")
        return False
    except ValueError as e:
        print(f"   ✓ Correctly blocked second reservation: {e}\n")

    # Test 4: Check edit permission
    print("7. Testing edit permissions...")
    can_edit1, reason1 = db.can_user_edit_page(page_id, user1)
    can_edit2, reason2 = db.can_user_edit_page(page_id, user2)
    assert can_edit1 is True
    assert can_edit2 is False
    print(f"   ✓ User1 can edit: {can_edit1}")
    print(f"   ✓ User2 cannot edit: {can_edit2} (reason: {reason2})\n")

    # Test 5: Release reservation
    print("8. Testing reservation release...")
    released = db.release_page_reservation(page_id, user1)
    assert released is True
    print(f"   ✓ Reservation released successfully\n")

    # Test 6: Check cooldown
    print("9. Testing cooldown period...")
    status = db.get_page_reservation_status(page_id, user1)
    assert status["is_reserved"] is False
    assert status["user_in_cooldown"] is True
    print(f"   ✓ Page is no longer reserved")
    print(f"   ✓ User1 is in cooldown")
    print(f"   Cooldown until: {status['cooldown_until']}\n")

    # Test 7: Try to reserve during cooldown
    print("10. Testing cooldown enforcement...")
    try:
        db.reserve_page(page_id, user1)
        print("   ✗ FAIL: Should not allow reservation during cooldown!")
        return False
    except ValueError as e:
        print(f"   ✓ Correctly blocked reservation during cooldown: {e}\n")

    # Test 8: Different user can reserve
    print("11. Testing that other users can reserve after release...")
    reservation2 = db.reserve_page(page_id, user2)
    assert reservation2 is not None
    assert reservation2["user_id"] == user2
    print(f"   ✓ User2 successfully reserved page\n")

    # Test 9: No cross-page cooldown
    print("12. Testing no cross-page cooldown...")
    page2_id = db.create_page("Page 2", "page2", "Content 2")
    can_reserve, reason = db.can_user_reserve_page(page2_id, user1)
    assert can_reserve is True
    print(f"   ✓ User1 can reserve different page despite cooldown on page 1\n")

    # Test 10: Cleanup function
    print("13. Testing cleanup function...")
    result = db.cleanup_expired_reservations()
    print(f"   ✓ Cleanup completed")
    print(f"   Reservations cleaned: {result['reservations_cleaned']}")
    print(f"   Cooldowns cleaned: {result['cooldowns_cleaned']}\n")

    print("=== ALL TESTS PASSED ===\n")
    return True


def test_expiry():
    """Test expiry logic by manually setting timestamps."""
    print("=== Testing Expiry Logic ===\n")

    from werkzeug.security import generate_password_hash

    # Create user and page
    user = db.create_user("editor3", generate_password_hash("pass"), role="editor")
    page = db.create_page("Expiry Test", "expiry-test", "Content")

    # Reserve the page
    db.reserve_page(page, user)
    print("1. Page reserved\n")

    # Manually expire the reservation
    conn = db.get_db()
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn.execute(
        "UPDATE page_reservations SET expires_at=? WHERE page_id=?",
        (past, page)
    )
    conn.commit()
    conn.close()
    print("2. Manually set reservation to expired\n")

    # Check status - should show as not reserved
    status = db.get_page_reservation_status(page, user)
    assert status["is_reserved"] is False
    print("3. ✓ Status correctly shows page as not reserved\n")

    # Another user should be able to reserve
    user2 = db.create_user("editor4", generate_password_hash("pass"), role="editor")
    reservation = db.reserve_page(page, user2)
    assert reservation is not None
    print("4. ✓ Another user successfully reserved the expired page\n")

    print("=== EXPIRY TEST PASSED ===\n")
    return True


if __name__ == "__main__":
    try:
        success = test_basic_reservation()
        if success:
            success = test_expiry()

        if success:
            print("\n" + "="*50)
            print("✓ ALL MANUAL TESTS PASSED SUCCESSFULLY")
            print("="*50)
            sys.exit(0)
        else:
            print("\n" + "="*50)
            print("✗ SOME TESTS FAILED")
            print("="*50)
            sys.exit(1)

    except Exception as e:
        print(f"\n✗ TEST FAILED WITH EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
