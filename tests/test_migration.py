"""
Tests for the site migration (export / import) feature.
"""

import io
import json
import os
import sys
import zipfile

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
    from werkzeug.security import generate_password_hash
    import db
    uid = db.create_user("admin", generate_password_hash("admin123"), role="admin")
    db.update_site_settings(setup_done=1)
    return uid


@pytest.fixture
def logged_in_admin(client, admin_user):
    client.post("/login", data={"username": "admin", "password": "admin123"})
    return client


# ---------------------------------------------------------------------------
# db.export_site_data
# ---------------------------------------------------------------------------

def test_export_site_data_structure(admin_user):
    """export_site_data() returns a dict with _meta and all expected tables."""
    import db
    data = db.export_site_data()
    assert "_meta" in data
    assert data["_meta"]["version"] == 1
    assert "exported_at" in data["_meta"]
    for table in ("users", "invite_codes", "categories", "pages",
                  "page_history", "drafts", "announcements",
                  "username_history", "site_settings"):
        assert table in data, f"Missing table: {table}"


def test_export_contains_user(admin_user):
    """Exported data includes the admin user."""
    import db
    data = db.export_site_data()
    usernames = [u["username"] for u in data["users"]]
    assert "admin" in usernames


def test_export_contains_home_page():
    """Exported data includes the home page that init_db() creates."""
    import db
    data = db.export_site_data()
    slugs = [p["slug"] for p in data["pages"]]
    assert "home" in slugs


def test_export_contains_about_page():
    """Exported data includes the about page that init_db() creates."""
    import db
    data = db.export_site_data()
    slugs = [p["slug"] for p in data["pages"]]
    assert "about" in slugs


def test_about_page_exists_after_init():
    """About page is created automatically during init_db()."""
    import db
    about = db.get_page_by_slug("about")
    assert about is not None
    assert about["title"] == "About"
    assert "BananaWiki" in about["content"]
    assert about["sort_order"] == 999999


# ---------------------------------------------------------------------------
# db.import_site_data – delete_all mode
# ---------------------------------------------------------------------------

def test_import_delete_all_replaces_users(admin_user):
    """delete_all import removes existing users and inserts exported ones."""
    import db
    from werkzeug.security import generate_password_hash

    # Export current state (has 'admin')
    data = db.export_site_data()

    # Add a new user that should be gone after the import
    db.create_user("ghost", generate_password_hash("pw"), role="user")

    db.import_site_data(data, "delete_all")

    usernames = [u["username"] for u in db.list_users()]
    assert "admin" in usernames
    assert "ghost" not in usernames


def test_import_delete_all_keeps_home_page():
    """After a delete_all import the home page from the export is present."""
    import db
    data = db.export_site_data()
    db.import_site_data(data, "delete_all")
    assert db.get_home_page() is not None


# ---------------------------------------------------------------------------
# db.import_site_data – override mode
# ---------------------------------------------------------------------------

def test_import_override_keeps_existing_user(admin_user):
    """override mode keeps users not present in the export."""
    import db
    from werkzeug.security import generate_password_hash

    data = db.export_site_data()
    db.create_user("extra", generate_password_hash("pw"), role="user")

    db.import_site_data(data, "override")

    usernames = [u["username"] for u in db.list_users()]
    assert "admin" in usernames
    assert "extra" in usernames


# ---------------------------------------------------------------------------
# db.import_site_data – keep mode
# ---------------------------------------------------------------------------

def test_import_keep_preserves_existing_data(admin_user):
    """keep mode leaves existing records untouched."""
    import db
    from werkzeug.security import generate_password_hash

    data = db.export_site_data()

    # Modify admin's role in export data; keep mode should ignore the conflict
    for u in data["users"]:
        if u["username"] == "admin":
            u["role"] = "user"

    db.import_site_data(data, "keep")

    admin = db.get_user_by_username("admin")
    assert admin["role"] == "admin"  # original value preserved


# ---------------------------------------------------------------------------
# db.import_site_data – validation errors
# ---------------------------------------------------------------------------

def test_import_invalid_mode_raises():
    import db
    data = db.export_site_data()
    with pytest.raises(ValueError, match="Unknown import mode"):
        db.import_site_data(data, "bad_mode")


def test_import_wrong_version_raises():
    import db
    data = db.export_site_data()
    data["_meta"]["version"] = 99
    with pytest.raises(ValueError, match="Incompatible export version"):
        db.import_site_data(data, "delete_all")


# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------

def test_migration_page_accessible_to_admin(logged_in_admin):
    resp = logged_in_admin.get("/admin/migration")
    assert resp.status_code == 200
    assert b"Site Migration" in resp.data


def test_migration_page_requires_admin(client, admin_user):
    from werkzeug.security import generate_password_hash
    import db
    db.create_user("regularuser", generate_password_hash("pw"), role="user")
    client.post("/login", data={"username": "regularuser", "password": "pw"})
    resp = client.get("/admin/migration", follow_redirects=True)
    assert b"Admin access required" in resp.data


def test_export_route_returns_zip(logged_in_admin):
    resp = logged_in_admin.post("/admin/migration/export")
    assert resp.status_code == 200
    assert resp.content_type == "application/zip"
    buf = io.BytesIO(resp.data)
    with zipfile.ZipFile(buf) as zf:
        names = zf.namelist()
    assert any(n.endswith(".json") for n in names)


def test_export_zip_contains_valid_json(logged_in_admin):
    resp = logged_in_admin.post("/admin/migration/export")
    buf = io.BytesIO(resp.data)
    with zipfile.ZipFile(buf) as zf:
        json_name = next(n for n in zf.namelist() if n.endswith(".json"))
        data = json.loads(zf.read(json_name))
    assert "_meta" in data
    assert "users" in data


def _make_zip_from_data(data):
    """Helper: wrap a dict as a ZIP containing site_export.json."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("site_export.json", json.dumps(data))
    buf.seek(0)
    return buf.read()


def test_import_route_delete_all(logged_in_admin, admin_user):
    import db
    data = db.export_site_data()
    zip_bytes = _make_zip_from_data(data)

    resp = logged_in_admin.post(
        "/admin/migration/import",
        data={
            "import_mode": "delete_all",
            "import_file": (io.BytesIO(zip_bytes), "backup.zip"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"imported successfully" in resp.data


def test_import_route_invalid_mode(logged_in_admin):
    import db
    data = db.export_site_data()
    zip_bytes = _make_zip_from_data(data)

    resp = logged_in_admin.post(
        "/admin/migration/import",
        data={
            "import_mode": "bad",
            "import_file": (io.BytesIO(zip_bytes), "backup.zip"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"Invalid import mode" in resp.data


def test_import_route_no_file(logged_in_admin):
    resp = logged_in_admin.post(
        "/admin/migration/import",
        data={"import_mode": "keep"},
        follow_redirects=True,
    )
    assert b"No file selected" in resp.data


def test_import_route_bad_zip(logged_in_admin):
    resp = logged_in_admin.post(
        "/admin/migration/import",
        data={
            "import_mode": "keep",
            "import_file": (io.BytesIO(b"not a zip"), "bad.zip"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"valid ZIP" in resp.data


def test_import_route_non_zip_extension(logged_in_admin):
    resp = logged_in_admin.post(
        "/admin/migration/import",
        data={
            "import_mode": "keep",
            "import_file": (io.BytesIO(b"{}"), "backup.json"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b".zip" in resp.data


def test_migration_link_on_settings_page(logged_in_admin):
    """The admin settings page should contain a link to the migration tools."""
    resp = logged_in_admin.get("/admin/settings")
    assert resp.status_code == 200
    assert b"migration" in resp.data.lower()
