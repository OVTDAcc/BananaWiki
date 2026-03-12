# Obsidian integration (experimental)

BananaWiki includes an experimental round-trip workflow for **editors and admins** at **Account Settings → Obsidian Sync (Experimental)**.

## What it does

- Exports either:
  - every page you can edit, or
  - only the specific pages you select
- Bundles each page as Markdown in `pages/`
- Bundles inline uploaded images in `uploads/`
- Bundles page attachments in `attachments/<slug>/`
- Adds a `manifest.json` file so BananaWiki can import the bundle back in

## Basic setup

1. Open **Account Settings**.
2. In **Obsidian Sync (Experimental)** either:
   - leave the page list empty to export all writable pages, or
   - select only the pages you want to work on.
3. Download the ZIP file.
4. Extract the ZIP into a folder that will become an Obsidian vault.
5. Open that folder as a vault in Obsidian.

## Editing notes

- Each exported page is stored as `pages/<slug>.md`.
- BananaWiki writes frontmatter keys such as:
  - `bananawiki_page_id`
  - `bananawiki_slug`
  - `bananawiki_title`
  - `bananawiki_category_id`
- You can edit the page body freely.
- You can also adjust the BananaWiki frontmatter if you intentionally want to change the page title, slug, or category.
- Keep `manifest.json` in the vault root. BananaWiki uses it during import.

## Uploads and attachments

- Inline uploaded images are exported into `uploads/`.
- Page attachments are exported into `attachments/<slug>/`.
- When you import a ZIP back into BananaWiki:
  - Markdown content is updated
  - included inline uploads are restored
  - page attachments for the included pages are replaced with the copies from the ZIP

## Importing back into BananaWiki

1. Re-zip the vault contents so that `manifest.json` stays at the ZIP root.
2. Return to **Account Settings → Obsidian Sync (Experimental)**.
3. Use **Import Obsidian ZIP**.

## Current limitations

- This workflow is **experimental** and is meant for careful, manual round-tripping.
- Only pages you are allowed to edit can be imported.
- The import only changes the pages included in the ZIP.
- If a category referenced by the ZIP no longer exists, BananaWiki keeps the existing category when possible.
