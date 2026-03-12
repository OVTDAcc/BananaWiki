"""Tests for the experimental Obsidian sync helpers and CLI workflow."""

import json
from pathlib import Path

import pytest
from PIL import Image
from werkzeug.security import generate_password_hash

import config


@pytest.fixture
def obsidian_env(tmp_path, monkeypatch):
    """Enable Obsidian sync and point asset folders at the temp directory."""
    upload_root = tmp_path / "uploads"
    attachment_root = tmp_path / "attachments"
    upload_root.mkdir()
    attachment_root.mkdir()
    monkeypatch.setattr(config, "EXPERIMENTAL_OBSIDIAN_SYNC", True)
    monkeypatch.setattr(config, "UPLOAD_FOLDER", str(upload_root))
    monkeypatch.setattr(config, "ATTACHMENT_FOLDER", str(attachment_root))
    return {"uploads": upload_root, "attachments": attachment_root}


def _write_png(path):
    """Create a tiny valid PNG image at ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (2, 2), color=(255, 215, 0)).save(path, format="PNG")


def test_obsidian_sync_requires_feature_flag(admin_user):
    """The experimental sync helpers must stay disabled unless the flag is on."""
    from helpers._obsidian_sync import authenticate_obsidian_user

    with pytest.raises(RuntimeError, match="disabled"):
        authenticate_obsidian_user("admin", "admin123")


def test_obsidian_sync_restricts_users_to_editor_roles(obsidian_env, admin_user):
    """Regular users must be denied even with valid credentials."""
    import db
    from helpers._obsidian_sync import authenticate_obsidian_user

    db.create_user("reader", generate_password_hash("reader123"), role="user")

    admin = authenticate_obsidian_user("admin", "admin123")
    assert admin["role"] == "admin"

    with pytest.raises(PermissionError, match="required permissions"):
        authenticate_obsidian_user("reader", "reader123")


def test_export_obsidian_vault_writes_markdown_assets_and_manifest(obsidian_env, admin_user, tmp_path):
    """Pulling a page should create a vault file, copied assets, and a manifest."""
    import db
    from helpers._obsidian_sync import export_obsidian_vault

    category_id = db.create_category("Guides")
    page_id = db.create_page("Sync Guide", "sync-guide", "Initial body", category_id, admin_user)

    _write_png(obsidian_env["uploads"] / "existing.png")
    attachment_path = obsidian_env["attachments"] / "manual.txt"
    attachment_path.write_text("manual", encoding="utf-8")
    attachment_id = db.add_page_attachment(page_id, "manual.txt", "manual.txt", attachment_path.stat().st_size, admin_user)

    content = (
        "Here is an image ![](/static/uploads/existing.png)\n\n"
        f"[Manual](/page/sync-guide/attachments/{attachment_id}/download)"
    )
    db.update_page(page_id, "Sync Guide", content, admin_user, "Prepare export")

    admin = db.get_user_by_id(admin_user)
    vault_dir = tmp_path / "vault"
    result = export_obsidian_vault(admin, vault_dir, slugs=["sync-guide"], include_home=False)

    page_file = vault_dir / "Guides" / "sync-guide.md"
    assert page_file.is_file()
    page_text = page_file.read_text(encoding="utf-8")
    assert "/static/uploads/existing.png" not in page_text
    assert "../assets/images/existing.png" in page_text
    assert "../assets/attachments/sync-guide" in page_text

    manifest = json.loads((vault_dir / ".bananawiki-obsidian.json").read_text(encoding="utf-8"))
    assert manifest["pages"][0]["slug"] == "sync-guide"
    assert (vault_dir / "assets" / "images" / "existing.png").is_file()
    assert any(item["vault_path"].startswith("assets/attachments/sync-guide/") for item in manifest["pages"][0]["attachments"])
    assert result["pages_exported"] == 1


def test_export_obsidian_vault_supports_directory_filters(obsidian_env, admin_user, tmp_path):
    """Selective pull should support category-directory filters."""
    import db
    from helpers._obsidian_sync import export_obsidian_vault

    guides_id = db.create_category("Guides")
    notes_id = db.create_category("Notes")
    db.create_page("Guide Page", "guide-page", "Guide body", guides_id, admin_user)
    db.create_page("Notes Page", "notes-page", "Notes body", notes_id, admin_user)

    admin = db.get_user_by_id(admin_user)
    vault_dir = tmp_path / "vault"
    export_obsidian_vault(admin, vault_dir, category_paths=["Guides"], include_home=False)

    assert (vault_dir / "Guides" / "guide-page.md").is_file()
    assert not (vault_dir / "Notes" / "notes-page.md").exists()


def test_import_obsidian_vault_updates_history_and_uploads_assets(obsidian_env, admin_user, tmp_path):
    """Pushing changes back should rewrite local asset refs and record page history."""
    import db
    from helpers._obsidian_sync import export_obsidian_vault, import_obsidian_vault

    category_id = db.create_category("Guides")
    page_id = db.create_page("Sync Guide", "sync-guide", "Original body", category_id, admin_user)

    _write_png(obsidian_env["uploads"] / "existing.png")
    db.update_page(
        page_id,
        "Sync Guide",
        "Original body\n\n![](/static/uploads/existing.png)",
        admin_user,
        "Prepare sync",
    )

    admin = db.get_user_by_id(admin_user)
    vault_dir = tmp_path / "vault"
    export_obsidian_vault(admin, vault_dir, slugs=["sync-guide"], include_home=False)

    _write_png(vault_dir / "assets" / "images" / "fresh.png")
    attachment_dir = vault_dir / "assets" / "attachments" / "sync-guide"
    attachment_dir.mkdir(parents=True, exist_ok=True)
    (attachment_dir / "spec.txt").write_text("spec", encoding="utf-8")

    page_file = vault_dir / "Guides" / "sync-guide.md"
    page_file.write_text(
        "---\n"
        f"bananawiki_page_id: {page_id}\n"
        'bananawiki_slug: "sync-guide"\n'
        'bananawiki_category: "Guides"\n'
        "bananawiki_is_home: false\n"
        'title: "Sync Guide"\n'
        "---\n"
        "Updated body with local assets.\n\n"
        "![](../assets/images/fresh.png)\n\n"
        "[Spec](../assets/attachments/sync-guide/spec.txt)\n",
        encoding="utf-8",
    )

    result = import_obsidian_vault(admin, vault_dir, slugs=["sync-guide"])

    updated = db.get_page(page_id)
    assert "Updated body with local assets." in updated["content"]
    assert "/static/uploads/" in updated["content"]
    assert "/page/sync-guide/attachments/" in updated["content"]
    history = db.get_page_history(page_id)
    assert history[0]["edit_message"] == "Obsidian sync push"
    assert result["images_uploaded"] == 1
    assert result["attachments_uploaded"] >= 1


def test_import_obsidian_vault_can_create_new_pages_and_categories(obsidian_env, admin_user, tmp_path):
    """Admin pushes should be able to create missing category folders and new pages."""
    import db
    from helpers._obsidian_sync import import_obsidian_vault

    admin = db.get_user_by_id(admin_user)
    vault_dir = tmp_path / "vault"
    new_page = vault_dir / "Projects" / "release-plan.md"
    new_page.parent.mkdir(parents=True, exist_ok=True)
    new_page.write_text("# Release Plan\n\nShip it.\n", encoding="utf-8")

    result = import_obsidian_vault(admin, vault_dir, category_paths=["Projects"])

    created = db.get_page_by_slug("release-plan")
    assert created is not None
    category = db.get_category(created["category_id"])
    assert category["name"] == "Projects"
    assert result["pages_created"] == 1
