# Experimental Obsidian Sync

BananaWiki includes an experimental local pull/push workflow for syncing wiki pages with an Obsidian Vault.

## 1. How the authentication and role checks work

BananaWiki stores users in SQLite and keeps passwords as Werkzeug password hashes in the `users` table.

The sync workflow reuses those same accounts:

- the script checks the supplied BananaWiki username and password against the stored hash
- the script then verifies that the authenticated user has one of these roles:
  - `editor`
  - `admin`
  - `protected_admin`

Regular `user` accounts are rejected.

## 2. Enable the feature flag

Edit `/home/runner/work/BananaWiki/BananaWiki/config.py` and turn on the experimental toggle:

```python
EXPERIMENTAL_OBSIDIAN_SYNC = True
```

If the flag is left off, the sync script exits immediately.

## 3. Prepare your environment

From the repository root:

```bash
cd /home/runner/work/BananaWiki/BananaWiki
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
```

## 4. Optional environment variables

You can pass credentials and the vault path on the command line, or set these environment variables:

```bash
export BANANAWIKI_OBSIDIAN_VAULT="/absolute/path/to/YourVault"
export BANANAWIKI_OBSIDIAN_USERNAME="editor-or-admin"
export BANANAWIKI_OBSIDIAN_PASSWORD="your-password"
```

## 5. Pull pages into the vault

Pull every accessible page, including the home page:

```bash
. venv/bin/activate
python scripts/obsidian_sync.py --vault "/absolute/path/to/YourVault" \
  --username "admin" \
  --password "admin123" \
  pull
```

Pull only one page by slug:

```bash
python scripts/obsidian_sync.py --vault "/absolute/path/to/YourVault" \
  --username "admin" \
  --password "admin123" \
  pull --page "sync-guide"
```

Pull only one category directory:

```bash
python scripts/obsidian_sync.py --vault "/absolute/path/to/YourVault" \
  --username "admin" \
  --password "admin123" \
  pull --directory "Guides"
```

### Pull output layout

The script creates:

- one Markdown file per page
- category folders that mirror BananaWiki categories
- `assets/images/` for image uploads referenced by page content
- `assets/attachments/<page-slug>/` for page attachments
- `.bananawiki-obsidian.json` for sync metadata

Each page file starts with lightweight YAML-style frontmatter containing:

- the BananaWiki page id
- the BananaWiki slug
- the category path
- whether the page is the home page
- the current title

## 6. Edit in Obsidian

After pulling:

- edit the Markdown body directly in Obsidian
- keep page files inside their category folders if you want category placement to stay the same
- add new images under `assets/images/`
- add new attachments under `assets/attachments/<page-slug>/`
- link to local assets with relative paths such as `../assets/images/example.png`

### Creating new pages

To create a new page, add a new `.md` file anywhere in the vault outside `assets/`.

- the file name becomes the default slug
- the first `# Heading` becomes the title if no `title` frontmatter is set
- the parent folders determine the BananaWiki category path

If a category folder does not already exist:

- admins can create the missing category path during push
- editors can only push into categories that already exist and that they are allowed to edit

## 7. Push changes back to BananaWiki

Push the entire vault:

```bash
. venv/bin/activate
python scripts/obsidian_sync.py --vault "/absolute/path/to/YourVault" \
  --username "admin" \
  --password "admin123" \
  push
```

Push only one page:

```bash
python scripts/obsidian_sync.py --vault "/absolute/path/to/YourVault" \
  --username "admin" \
  --password "admin123" \
  push --page "sync-guide"
```

Push only one directory:

```bash
python scripts/obsidian_sync.py --vault "/absolute/path/to/YourVault" \
  --username "admin" \
  --password "admin123" \
  push --directory "Guides"
```

## 8. What “versioning/commits” means here

BananaWiki already keeps immutable page revision history in the `page_history` table.

When an Obsidian push changes an existing page, the sync code calls the normal page update path and stores the change as a new history entry with the edit message:

```text
Obsidian sync push
```

That database-backed page history is the authoritative commit trail for this experimental integration.

## 9. Notes and limitations

- This workflow is local to the BananaWiki server checkout; it is not a network API client.
- Existing image references are rewritten to local vault paths on pull and back to BananaWiki upload URLs on push.
- Existing attachment download links are rewritten to local vault files on pull and back to authenticated download URLs on push.
- Deleting a local file does not delete the BananaWiki page or its existing server-side assets.
- If you edit a page asset locally and push it, BananaWiki uploads a new server copy and updates the page content to point at the new asset.
- The feature is experimental and should be enabled only for trusted editors/admins.
