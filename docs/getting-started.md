# Getting Started

This guide is for operators and evaluators who want a current, reliable path from clone to a working BananaWiki instance.

## 1. Clone the repository

```bash
git clone https://github.com/OVTDAcc/BananaWiki.git
cd BananaWiki
```

## 2. Pick how you want to run it

### Option A: fastest local start

```bash
make dev
```

What it does:

- verifies Python 3.9+
- creates `./venv` if missing
- installs runtime dependencies from `requirements.txt`
- creates `instance/` if needed
- runs the Flask development server on `127.0.0.1:5001`

Equivalent direct script usage:

```bash
./dev.sh
./dev.sh --host 0.0.0.0 --port 5001
```

### Option B: production-style Gunicorn start

```bash
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
./start.sh
```

Useful overrides:

```bash
./start.sh --port 8080
./start.sh --host 0.0.0.0
./start.sh --bind 0.0.0.0:5001
./start.sh --workers 4
```

### Option C: automated production install

```bash
sudo ./install.sh
```

The installer can:

- install system packages
- create the application directory and virtualenv
- install Python dependencies
- write a systemd service
- configure nginx
- optionally obtain a Let's Encrypt certificate

## 3. Complete the in-app setup

On the first visit, BananaWiki redirects every request to `/setup` until the initial admin exists.

![Setup wizard](images/setup-wizard.png)

Create the administrator account with:

- username: 3–50 characters, letters/digits/underscores/hyphens only
- password: minimum 6 characters

After submission, sign in through `/login`.

## 4. Confirm the default experience

After login you land on the built-in Home page and can immediately start exploring the wiki shell.

![Wiki home](images/wiki-home.png)

Out of the box you will see:

- the default Home and About pages
- the Explorer sidebar
- quick create actions for editors/admins
- links to direct messages and group chats
- the topbar customization drawer

## 5. Make the first content changes

Open the Home page editor to see the split-pane editing workflow.

![Editor](images/editor.png)

The editor supports:

- live Markdown preview
- formatting toolbar
- internal page links
- image upload with alignment/width options
- video embedding
- difficulty tags
- page attachments
- draft autosave and conflict awareness

## 6. Run tests before shipping

Full suite:

```bash
make test
```

Direct pytest form:

```bash
. venv/bin/activate
python -m pytest tests/ -v
```

The repository's current full suite passes in the project virtualenv.

## 7. Initial admin checklist

After first login, review these areas before inviting users:

1. **Admin → Site Settings**
   - site name and timezone
   - theme defaults and color palettes
   - favicon behavior
   - lockdown/session-limit settings
   - page reservations
   - chat quotas and cleanup schedule
2. **Admin → Users**
   - confirm the first account role
   - create invite codes if self-service signup will be used
3. **Home/About pages**
   - replace defaults with your own content
4. **Categories**
   - create the initial tree and enable sequential navigation where useful

## 8. Common local commands

```bash
make dev      # run the development server
make start    # run Gunicorn through start.sh
make test     # install test deps and run pytest
make clean    # remove venv and cache directories
```

## 9. Notes about configuration

Use `config.py` for static deployment values such as host/port, file paths, size limits, and Telegram sync configuration.

Use **Admin → Site Settings** for live operational settings stored in SQLite, especially:

- theme defaults
- favicon settings
- lockdown mode
- session limit
- chat toggles, quotas, and cleanup frequency
- page reservations

For the full feature inventory, continue to [`feature-reference.md`](feature-reference.md). For deployment and maintenance, see [`operations.md`](operations.md).
