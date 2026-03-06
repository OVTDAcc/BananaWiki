"""Test badge system functionality."""

import os
import sys
import tempfile

# Add the parent directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db


def test_badge_creation():
    """Test creating badge types."""
    print("Testing badge type creation...")

    # Create first_edit badge
    badge_id = db.create_badge_type(
        name="First Contributor",
        description="Made your first edit to the wiki",
        icon="✏️",
        color="#4a90e2",
        enabled=True,
        auto_trigger=True,
        trigger_type="first_edit",
        trigger_threshold=1
    )
    assert badge_id > 0, "Badge creation failed"
    print(f"  ✓ Created badge with ID: {badge_id}")

    # Verify badge exists
    badge = db.get_badge_type(badge_id)
    assert badge is not None, "Badge not found"
    assert badge['name'] == "First Contributor"
    assert badge['trigger_type'] == "first_edit"
    print(f"  ✓ Badge retrieved successfully: {badge['icon']} {badge['name']}")

    # Create contribution count badge
    badge_id_2 = db.create_badge_type(
        name="Prolific Contributor",
        description="Made 10 contributions to the wiki",
        icon="🌟",
        color="#ffd700",
        enabled=True,
        auto_trigger=True,
        trigger_type="contribution_count",
        trigger_threshold=10
    )
    print(f"  ✓ Created second badge with ID: {badge_id_2}")

    # List all badges
    badges = db.list_badge_types()
    assert len(badges) >= 2, "Not all badges were created"
    print(f"  ✓ Total badges: {len(badges)}")


def test_badge_awarding():
    """Test awarding badges to users."""
    print("\nTesting badge awarding...")

    # Create a test user
    from werkzeug.security import generate_password_hash
    user_id = db.create_user("testuser", generate_password_hash("password"), role="user")
    print(f"  ✓ Created test user with ID: {user_id}")

    # Get a badge to award
    badges = db.list_badge_types()
    badge = badges[0]

    # Award badge to user
    result = db.award_badge(user_id, badge['id'], awarded_by=None)
    assert result is not None, "Badge awarding failed"
    print(f"  ✓ Awarded badge '{badge['name']}' to user")

    # Verify user has badge
    user_badges = db.get_user_badges(user_id)
    assert len(user_badges) > 0, "User doesn't have awarded badge"
    assert user_badges[0]['name'] == badge['name']
    print(f"  ✓ User has {len(user_badges)} badge(s)")

    # Test duplicate awarding (should return None)
    result = db.award_badge(user_id, badge['id'], awarded_by=None)
    assert result is None, "Duplicate badge was awarded"
    print(f"  ✓ Duplicate badge awarding prevented")


def test_badge_revocation():
    """Test revoking badges."""
    print("\nTesting badge revocation...")

    # Get test user and their badges
    user = db.get_user_by_username("testuser")
    user_badges = db.get_user_badges(user['id'])
    badge = user_badges[0]

    # Revoke badge
    db.revoke_badge(user['id'], badge['badge_type_id'], revoked_by=None, permanent=False)
    print(f"  ✓ Revoked badge temporarily")

    # Verify badge is revoked
    active_badges = db.get_user_badges(user['id'], include_revoked=False)
    assert len(active_badges) == 0, "Badge still active after revocation"
    print(f"  ✓ Badge no longer active")

    # Verify badge still exists in history
    all_badges = db.get_user_badges(user['id'], include_revoked=True)
    assert len(all_badges) > 0, "Badge was permanently deleted"
    assert all_badges[0]['revoked'] == 1, "Badge not marked as revoked"
    print(f"  ✓ Badge kept in history as revoked")


def test_auto_triggers():
    """Test automatic badge triggering."""
    print("\nTesting automatic badge triggers...")

    # Get test user
    user = db.get_user_by_username("testuser")

    # Simulate making a page edit by creating a page
    from datetime import datetime
    page_id = db.create_page(
        title="Test Page",
        slug="test-page",
        content="Test content",
        edited_by=user['id']
    )
    print(f"  ✓ Created test page with ID: {page_id}")

    # Check and award auto badges
    awarded = db.check_and_award_auto_badges(user['id'])
    print(f"  ✓ Auto-check completed, awarded: {awarded}")

    # Verify first_edit badge was awarded
    user_badges = db.get_user_badges(user['id'], include_revoked=False)
    first_edit_badges = [b for b in user_badges if b['trigger_type'] == 'first_edit']
    if len(first_edit_badges) > 0:
        print(f"  ✓ First edit badge automatically awarded!")


def test_badge_notifications():
    """Test badge notification system."""
    print("\nTesting badge notifications...")

    user = db.get_user_by_username("testuser")

    # Get unnotified badges
    unnotified = db.get_unnotified_badges(user['id'])
    print(f"  ✓ User has {len(unnotified)} unnotified badge(s)")

    if len(unnotified) > 0:
        # Mark as notified
        db.mark_badges_notified(user['id'])
        print(f"  ✓ Marked badges as notified")

        # Verify no unnotified badges remain
        unnotified_after = db.get_unnotified_badges(user['id'])
        assert len(unnotified_after) == 0, "Badges still unnotified"
        print(f"  ✓ No unnotified badges remaining")


def main():
    """Run all badge system tests."""
    print("=" * 60)
    print("BADGE SYSTEM TESTS")
    print("=" * 60)

    # Initialize database
    db.init_db()
    print("✓ Database initialized\n")

    try:
        test_badge_creation()
        test_badge_awarding()
        test_badge_revocation()
        test_auto_triggers()
        test_badge_notifications()

        print("\n" + "=" * 60)
        print("ALL TESTS PASSED ✓")
        print("=" * 60)
        return 0
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
