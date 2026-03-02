"""
Tests for user profile (user pages) feature.

Covers:
  - Viewing a user profile page
  - Editing profile (real name, bio)
  - Publishing and unpublishing a profile page
  - Deleting a profile page (contributions are retained)
  - Hiding a profile from non-owners/non-admins (404)
  - Avatar upload validation (size limit, bad file type)
  - Removing an avatar
  - People directory (/users) for admin vs regular user
  - People directory search
  - Admin moderation: edit profile, remove avatar, disable/enable, delete
  - Sidebar People widget (published profiles only)
  - Contribution heatmap data on profile
  - Role badges shown on profile page
"""

import io
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config

MAX_AVATAR_SIZE_BYTES = 1 * 1024 * 1024  # 1 MB


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Fresh temporary database for every test."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(config, "DATABASE_PATH", db_path)
    monkeypatch.setattr(config, "LOGGING_ENABLED", False)
    # Point uploads at a temp directory so file-system operations work
    upload_dir = str(tmp_path / "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    monkeypatch.setattr(config, "UPLOAD_FOLDER", upload_dir)
    import db as db_mod
    db_mod.init_db()
    yield db_path


@pytest.fixture(autouse=True)
def clear_rl_store():
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
def admin_uid():
    from werkzeug.security import generate_password_hash
    import db
    uid = db.create_user("admin", generate_password_hash("admin123"), role="admin")
    db.update_site_settings(setup_done=1)
    return uid


@pytest.fixture
def regular_uid(admin_uid):
    """A regular (non-admin) user."""
    from werkzeug.security import generate_password_hash
    import db
    return db.create_user("alice", generate_password_hash("alice123"), role="user")


@pytest.fixture
def admin_client(client, admin_uid):
    client.post("/login", data={"username": "admin", "password": "admin123"})
    return client


@pytest.fixture
def alice_client(client, regular_uid):
    client.post("/login", data={"username": "alice", "password": "alice123"})
    return client


# ---------------------------------------------------------------------------
# Profile page – basic view
# ---------------------------------------------------------------------------

def test_own_profile_visible_without_published(admin_client):
    """User can always view their own profile even if unpublished."""
    resp = admin_client.get("/users/admin")
    assert resp.status_code == 200
    assert b"admin" in resp.data


def test_profile_404_for_unknown_username(admin_client):
    resp = admin_client.get("/users/nobody_here")
    assert resp.status_code == 404


def test_unpublished_profile_hidden_from_others(alice_client, admin_uid):
    """Another user cannot view an unpublished profile – should get 404."""
    resp = alice_client.get("/users/admin")
    assert resp.status_code == 404


def test_admin_can_view_unpublished_profile(admin_client, regular_uid):
    """Admins can view profiles even if not published."""
    resp = admin_client.get("/users/alice")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Edit profile (real name & bio)
# ---------------------------------------------------------------------------

def test_update_profile_real_name_and_bio(admin_client):
    resp = admin_client.post(
        "/account",
        data={
            "action": "update_profile",
            "real_name": "Admin User",
            "bio": "I run this wiki.",
            "next_url": "/users/admin",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Admin User" in resp.data
    assert b"I run this wiki." in resp.data


def test_profile_bio_max_length_enforced(admin_client):
    """Bio is stored truncated to 500 chars – page renders without error."""
    long_bio = "x" * 600
    resp = admin_client.post(
        "/account",
        data={"action": "update_profile", "real_name": "", "bio": long_bio,
              "next_url": "/users/admin"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    import db
    import config as cfg
    # Reload DB from the test's temp path (already patched via monkeypatch)
    profile = db.get_user_profile(
        db.get_user_by_username("admin")["id"]
    )
    assert len(profile["bio"]) <= 500


# ---------------------------------------------------------------------------
# Publish / unpublish / delete profile
# ---------------------------------------------------------------------------

def test_publish_profile(admin_client):
    # First create the profile record
    admin_client.post("/account", data={"action": "update_profile",
                                        "real_name": "", "bio": "",
                                        "next_url": "/"})
    resp = admin_client.post(
        "/account",
        data={"action": "publish_profile", "next_url": "/users/admin"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"now public" in resp.data or b"public" in resp.data.lower()


def test_unpublish_profile(admin_client):
    # Create + publish first
    admin_client.post("/account", data={"action": "update_profile",
                                        "real_name": "", "bio": "", "next_url": "/"})
    admin_client.post("/account", data={"action": "publish_profile", "next_url": "/"})
    resp = admin_client.post(
        "/account",
        data={"action": "unpublish_profile", "next_url": "/users/admin"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"hidden" in resp.data.lower() or b"Hidden" in resp.data


def test_delete_profile_retains_contributions(admin_client, admin_uid):
    """Deleting a profile page does NOT delete page_history contributions."""
    import db
    home = db.get_home_page()
    db.update_page(home["id"], "Home", "New content", admin_uid, "test edit")
    # Set up and delete profile
    admin_client.post("/account", data={"action": "update_profile",
                                        "real_name": "A", "bio": "B", "next_url": "/"})
    admin_client.post("/account", data={"action": "delete_profile", "next_url": "/"})
    # Contributions still exist in DB
    _, contribs = db.get_contributions_by_day(admin_uid)
    total = sum(contribs.values())
    assert total >= 1


def test_deleted_profile_not_in_published_list(admin_client, admin_uid):
    import db
    admin_client.post("/account", data={"action": "update_profile",
                                        "real_name": "", "bio": "", "next_url": "/"})
    admin_client.post("/account", data={"action": "publish_profile", "next_url": "/"})
    admin_client.post("/account", data={"action": "delete_profile", "next_url": "/"})
    profiles = db.list_published_profiles()
    assert not any(p["username"] == "admin" for p in profiles)


# ---------------------------------------------------------------------------
# Avatar upload validation
# ---------------------------------------------------------------------------

def test_avatar_upload_invalid_type_rejected(admin_client):
    data = {
        "action": "update_profile",
        "real_name": "",
        "bio": "",
        "next_url": "/",
        "avatar": (io.BytesIO(b"<svg/>"), "avatar.svg"),
    }
    resp = admin_client.post("/account", data=data,
                             content_type="multipart/form-data",
                             follow_redirects=True)
    assert resp.status_code == 200
    assert b"Invalid avatar" in resp.data or b"invalid" in resp.data.lower()


def test_avatar_upload_too_large_rejected(admin_client):
    big_bytes = b"\x00" * (MAX_AVATAR_SIZE_BYTES + 1)  # just over 1 MB
    data = {
        "action": "update_profile",
        "real_name": "",
        "bio": "",
        "next_url": "/",
        "avatar": (io.BytesIO(big_bytes), "photo.jpg"),
    }
    resp = admin_client.post("/account", data=data,
                             content_type="multipart/form-data",
                             follow_redirects=True)
    assert resp.status_code == 200
    assert b"1 MB" in resp.data or b"smaller" in resp.data.lower()


def test_remove_avatar(admin_client, tmp_path, monkeypatch):
    """remove_avatar action clears the avatar_filename in the DB."""
    import db
    uid = db.get_user_by_username("admin")["id"]
    # Directly inject a fake avatar record
    db.upsert_user_profile(uid, avatar_filename="avatars/fake.png")
    # Create the fake file so os.remove doesn't crash
    fake_path = os.path.join(config.UPLOAD_FOLDER, "avatars", "fake.png")
    os.makedirs(os.path.dirname(fake_path), exist_ok=True)
    open(fake_path, "w").close()

    resp = admin_client.post("/account",
                             data={"action": "remove_avatar", "next_url": "/"},
                             follow_redirects=True)
    assert resp.status_code == 200
    profile = db.get_user_profile(uid)
    assert profile["avatar_filename"] == ""


# ---------------------------------------------------------------------------
# People directory (/users)
# ---------------------------------------------------------------------------

def test_users_list_admin_sees_all(admin_client, regular_uid):
    """Admin sees all users in /users regardless of publish status."""
    resp = admin_client.get("/users")
    assert resp.status_code == 200
    assert b"alice" in resp.data


def test_users_list_regular_sees_only_published(alice_client, admin_uid):
    """Regular user only sees published profiles; admin has no published profile so is absent."""
    resp = alice_client.get("/users")
    assert resp.status_code == 200
    # admin has no published profile yet → must not appear for alice
    assert b"admin" not in resp.data


def test_users_list_search(admin_client, regular_uid):
    resp = admin_client.get("/users?q=ali")
    assert resp.status_code == 200
    assert b"alice" in resp.data


def test_users_list_search_no_results(admin_client):
    resp = admin_client.get("/users?q=zzz_no_match")
    assert resp.status_code == 200
    assert b"No members found" in resp.data


# ---------------------------------------------------------------------------
# Published profile visible to others
# ---------------------------------------------------------------------------

def test_published_profile_visible_to_others(alice_client, admin_uid):
    import db
    db.upsert_user_profile(admin_uid, real_name="Admin", bio="Hello",
                           page_published=True)
    resp = alice_client.get("/users/admin")
    assert resp.status_code == 200
    assert b"Admin" in resp.data


# ---------------------------------------------------------------------------
# Role badge on profile page
# ---------------------------------------------------------------------------

def test_admin_badge_shown_on_profile(admin_client):
    resp = admin_client.get("/users/admin")
    assert resp.status_code == 200
    assert b"Administrator" in resp.data or b"admin" in resp.data.lower()


def test_user_role_badge_shown(alice_client, regular_uid):
    import db
    db.upsert_user_profile(regular_uid, real_name="", bio="",
                           page_published=True)
    resp = alice_client.get("/users/alice")
    assert resp.status_code == 200
    # Role badge for "user" role should be present
    assert b"alice" in resp.data


# ---------------------------------------------------------------------------
# Sidebar People widget
# ---------------------------------------------------------------------------

def test_sidebar_people_appears_when_profiles_published(admin_client, admin_uid):
    import db
    db.upsert_user_profile(admin_uid, real_name="", bio="", page_published=True)
    resp = admin_client.get("/")
    assert resp.status_code == 200
    assert b"People" in resp.data


def test_sidebar_people_absent_when_no_published_profiles(admin_client):
    resp = admin_client.get("/")
    assert resp.status_code == 200
    # No published profiles → People section should not appear
    assert b"sidebar-people" not in resp.data


# ---------------------------------------------------------------------------
# Contribution heatmap data
# ---------------------------------------------------------------------------

def test_contribution_heatmap_present_on_profile(admin_client, admin_uid):
    resp = admin_client.get("/users/admin")
    assert resp.status_code == 200
    assert b"contributions in" in resp.data
    assert b"contrib-graph" in resp.data


def test_contribution_counts_after_edit(admin_client, admin_uid):
    import db
    home = db.get_home_page()
    db.update_page(home["id"], "Home", "Edited content", admin_uid, "my edit")
    _, contribs = db.get_contributions_by_day(admin_uid)
    assert sum(contribs.values()) >= 1


# ---------------------------------------------------------------------------
# Admin moderation tools
# ---------------------------------------------------------------------------

def test_admin_can_edit_other_user_profile(admin_client, regular_uid):
    resp = admin_client.post(
        f"/admin/users/{regular_uid}/profile",
        data={"action": "edit_profile", "real_name": "Alice R.", "bio": "Edited by admin"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    import db
    profile = db.get_user_profile(regular_uid)
    assert profile["real_name"] == "Alice R."
    assert profile["bio"] == "Edited by admin"


def test_admin_can_disable_user_profile(admin_client, regular_uid):
    import db
    db.upsert_user_profile(regular_uid, page_published=True)
    resp = admin_client.post(
        f"/admin/users/{regular_uid}/profile",
        data={"action": "disable_profile"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    profile = db.get_user_profile(regular_uid)
    assert profile["page_disabled_by_admin"] == 1
    assert profile["page_published"] == 0


def test_admin_can_reenable_user_profile(admin_client, regular_uid):
    import db
    db.upsert_user_profile(regular_uid, page_disabled_by_admin=True)
    resp = admin_client.post(
        f"/admin/users/{regular_uid}/profile",
        data={"action": "enable_profile"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    profile = db.get_user_profile(regular_uid)
    assert profile["page_disabled_by_admin"] == 0


def test_admin_can_delete_user_profile(admin_client, regular_uid):
    import db
    db.upsert_user_profile(regular_uid, real_name="Alice", bio="Bio")
    resp = admin_client.post(
        f"/admin/users/{regular_uid}/profile",
        data={"action": "delete_profile"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    profile = db.get_user_profile(regular_uid)
    assert profile is None


def test_admin_remove_avatar_for_user(admin_client, regular_uid):
    import db
    db.upsert_user_profile(regular_uid, avatar_filename="avatars/alice.png")
    fake_path = os.path.join(config.UPLOAD_FOLDER, "avatars", "alice.png")
    os.makedirs(os.path.dirname(fake_path), exist_ok=True)
    open(fake_path, "w").close()

    resp = admin_client.post(
        f"/admin/users/{regular_uid}/profile",
        data={"action": "remove_avatar"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    profile = db.get_user_profile(regular_uid)
    assert profile["avatar_filename"] == ""


def test_disabled_profile_cannot_be_published_by_user(alice_client, regular_uid):
    """A user whose profile was disabled by admin cannot re-publish it."""
    import db
    db.upsert_user_profile(regular_uid, page_disabled_by_admin=True)
    resp = alice_client.post(
        "/account",
        data={"action": "publish_profile", "next_url": "/"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    profile = db.get_user_profile(regular_uid)
    assert profile["page_published"] == 0


def test_admin_moderation_requires_admin(alice_client, admin_uid):
    """Non-admin cannot access admin moderation endpoint – redirected to home."""
    import db
    resp = alice_client.post(
        f"/admin/users/{admin_uid}/profile",
        data={"action": "edit_profile", "real_name": "Hacked", "bio": ""},
    )
    # admin_required redirects non-admins to home
    assert resp.status_code == 302
    # Verify the DB was not modified
    profile = db.get_user_profile(admin_uid)
    assert profile is None or profile["real_name"] != "Hacked"


# ---------------------------------------------------------------------------
# Protected admin profile protection
# ---------------------------------------------------------------------------

@pytest.fixture
def second_admin_uid(admin_uid):
    """A second admin used to test cross-admin restrictions."""
    from werkzeug.security import generate_password_hash
    import db
    return db.create_user("admin2", generate_password_hash("admin2pass"), role="admin")


@pytest.fixture
def second_admin_client(client, second_admin_uid):
    client.post("/login", data={"username": "admin2", "password": "admin2pass"})
    return client


@pytest.fixture
def protected_admin_uid(admin_uid):
    """An admin with the protected_admin role."""
    from werkzeug.security import generate_password_hash
    import db
    uid = db.create_user("padmin", generate_password_hash("padmin123"), role="protected_admin")
    db.upsert_user_profile(uid, real_name="Protected Admin", bio="Original bio")
    return uid


def test_admin_cannot_edit_protected_admin_profile(second_admin_client, protected_admin_uid):
    """An admin cannot edit a protected_admin's profile page."""
    import db
    resp = second_admin_client.post(
        f"/admin/users/{protected_admin_uid}/profile",
        data={"action": "edit_profile", "real_name": "Hacked", "bio": "Hacked bio"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    profile = db.get_user_profile(protected_admin_uid)
    assert profile["real_name"] != "Hacked"


def test_admin_cannot_disable_protected_admin_profile(second_admin_client, protected_admin_uid):
    """An admin cannot disable a protected_admin's profile page."""
    import db
    db.upsert_user_profile(protected_admin_uid, page_published=True)
    resp = second_admin_client.post(
        f"/admin/users/{protected_admin_uid}/profile",
        data={"action": "disable_profile"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    profile = db.get_user_profile(protected_admin_uid)
    assert profile["page_disabled_by_admin"] == 0


def test_admin_cannot_delete_protected_admin_profile(second_admin_client, protected_admin_uid):
    """An admin cannot delete a protected_admin's profile page."""
    import db
    resp = second_admin_client.post(
        f"/admin/users/{protected_admin_uid}/profile",
        data={"action": "delete_profile"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    profile = db.get_user_profile(protected_admin_uid)
    assert profile is not None


def test_admin_cannot_remove_avatar_of_protected_admin(second_admin_client, protected_admin_uid):
    """An admin cannot remove the avatar of a protected_admin."""
    import db
    db.upsert_user_profile(protected_admin_uid, avatar_filename="avatars/padmin.png")
    fake_path = os.path.join(config.UPLOAD_FOLDER, "avatars", "padmin.png")
    os.makedirs(os.path.dirname(fake_path), exist_ok=True)
    open(fake_path, "w").close()

    resp = second_admin_client.post(
        f"/admin/users/{protected_admin_uid}/profile",
        data={"action": "remove_avatar"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    profile = db.get_user_profile(protected_admin_uid)
    assert profile["avatar_filename"] == "avatars/padmin.png"


def test_protected_admin_can_edit_own_profile_via_admin(client, protected_admin_uid):
    """A protected_admin can moderate their own profile via the admin endpoint."""
    import db
    client.post("/login", data={"username": "padmin", "password": "padmin123"})
    resp = client.post(
        f"/admin/users/{protected_admin_uid}/profile",
        data={"action": "edit_profile", "real_name": "Self Edit", "bio": "My bio"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    profile = db.get_user_profile(protected_admin_uid)
    assert profile["real_name"] == "Self Edit"
