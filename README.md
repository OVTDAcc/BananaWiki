# BananaWiki

A lightweight, self-hosted wiki built with Flask and SQLite. Clean, fast, and easy to run — just clone, install, and go.

## Contents

- [Screenshots](#screenshots)
- [Features](#features)
- [Quick Start](#quick-start)
- [Initial Setup](#initial-setup)
- [User Roles](#user-roles)
- [Project Structure](#project-structure)
- [Running Tests](#running-tests)
- [Documentation](#documentation)

## Screenshots

<table>
<tr>
<td><strong>Login page</strong><br><img src="https://github.com/user-attachments/assets/d9fad2c1-ced2-4320-9c1b-f03603df5d11" alt="Login page"></td>
<td><strong>Home — wiki view</strong><br><img src="https://github.com/user-attachments/assets/ab13800e-08c4-425e-809c-05b1d1ef3599" alt="Home page"></td>
</tr>
<tr>
<td><strong>Split-pane Markdown editor with live preview</strong><br><img src="https://github.com/user-attachments/assets/e02c2bad-b065-4131-a869-1c2b15cb3219" alt="Markdown editor"></td>
<td><strong>Page revision history</strong><br><img src="https://github.com/user-attachments/assets/b60f7a48-eb1a-4bd2-8cb7-8d220d364559" alt="Page history"></td>
</tr>
<tr>
<td><strong>Admin — manage users</strong><br><img src="https://github.com/user-attachments/assets/c2385adb-c6bb-46ee-86d0-ceb55f16a2c4" alt="Admin users"></td>
<td><strong>Admin — site settings &amp; theme colors</strong><br><img src="https://github.com/user-attachments/assets/9f2cdf61-c944-4f3b-91f0-b2cc006bead5" alt="Admin settings"></td>
</tr>
<tr>
<td><strong>Admin — announcement manager</strong><br><img src="https://github.com/user-attachments/assets/3438ed27-4b4e-4f2d-b76c-ece9e537419a" alt="Admin announcements"></td>
<td><strong>Account settings &amp; admin shortcuts</strong><br><img src="https://github.com/user-attachments/assets/05afee31-38cb-47b3-8c01-45f89052207e" alt="Account settings"></td>
</tr>
<tr>
<td colspan="2"><strong>Announcement banner — orange (1/2) and red (2/2) variants with navigation</strong><br><img src="https://github.com/user-attachments/assets/1be5bb61-7ae5-48aa-9bbd-47c513b581d0" alt="Announcement banner"></td>
</tr>
</table>

## Features

- **Markdown Editing** — Tables, fenced code blocks, table of contents, and newline-to-break support
- **Split-Pane Editor** — Live preview alongside the editor with a formatting toolbar and image drop zone
- **Category Organization** — Hierarchical categories with collapsible sidebar navigation
- **Page History** — Full revision history with edit summaries, diff viewing, and one-click revert
- **Draft Autosave** — Auto-saves every few seconds; detects conflicts when multiple users edit the same page
- **Image Uploads** — Drag-and-drop or file picker with automatic Markdown insertion
- **Role-Based Access** — Four roles (user, editor, admin, protected_admin) with clear permission boundaries
- **Invite Code System** — Time-limited codes control who can sign up
- **Announcement Banners** — Site-wide banners with color themes, text sizes, visibility controls, expiry dates, and Markdown support
- **Customizable Appearance** — Change site name and full color palette from the admin panel
- **Telegram Sync** — Automatic backups of the database, uploads, config, and logs to Telegram
- **Mobile Responsive** — Collapsible sidebar with drag-to-resize on desktop

## Quick Start

**Requirements:** Python 3.9+

```bash
git clone https://github.com/overdeckat/BananaWiki.git
cd BananaWiki
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
gunicorn wsgi:app -c gunicorn.conf.py
```

Open `http://localhost:5001` — you'll be taken to the setup page to create the first admin account.

For development, you can also run:
```bash
python app.py
```
> The Flask dev server is single-threaded. Use Gunicorn for anything beyond local testing.

## Initial Setup

On first run, BananaWiki shows a one-time setup wizard:

1. Choose a **username** (3–50 characters, letters/digits/underscores/hyphens)
2. Set a **password** (minimum 6 characters)
3. Confirm the password

This creates the first admin account and marks setup complete. All subsequent users are added via invite codes or the admin panel.

## User Roles

| Role | What they can do |
|---|---|
| **User** | View pages |
| **Editor** | View, create, and edit pages; manage categories; revert history |
| **Admin** | Everything editors can do, plus: manage users, generate invite codes, configure settings, post announcements, delete pages |
| **Protected Admin** | Same as admin, but the account is shielded from modifications by other admins |

New users signing up with an invite code receive the **user** role by default. Admins can change roles from **Admin Operations → Manage Users**. The **protected_admin** role can only be toggled by the account owner from their account settings.

## Project Structure

```
BananaWiki/
├── app.py              # Flask app: all routes, middleware, and request handling
├── db.py               # Database layer: schema, migrations, and all queries
├── config.py           # Configuration — edit this to customize your instance
├── sync.py             # Telegram backup/sync module
├── wiki_logger.py      # Request and action logging
├── wsgi.py             # WSGI entry point for Gunicorn
├── gunicorn.conf.py    # Gunicorn server configuration
├── bananawiki.service  # systemd service file for production
├── requirements.txt    # Python dependencies
├── app/
│   ├── static/
│   │   ├── css/        # Stylesheets
│   │   ├── js/         # Client-side JavaScript
│   │   └── uploads/    # User-uploaded images (runtime)
│   └── templates/
│       ├── base.html                  # Base layout with sidebar
│       ├── _announcements_bar.html    # Announcement banner partial
│       ├── auth/       # Login, signup, setup, and lockdown pages
│       ├── wiki/       # Page view, edit, create, history, and error pages
│       ├── account/    # Account settings
│       └── admin/      # Admin panel: users, settings, codes, announcements
├── docs/               # Detailed documentation
├── instance/           # Database and secret key — created at runtime (gitignored)
├── logs/               # Application logs — created at runtime (gitignored)
└── tests/              # Test suite
```

## Running Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

Tests use isolated temporary databases and cover routes, database logic, rate limiting, networking, and sync behavior.

## Documentation

Detailed docs live in the [`docs/`](docs/) directory:

- **[Features](docs/features.md)** — complete feature list from most visible to most undocumented
- **[Configuration](docs/configuration.md)** — every `config.py` setting explained
- **[Deployment](docs/deployment.md)** — systemd, Gunicorn, Cloudflare, nginx, and SSL setup
- **[Architecture](docs/architecture.md)** — how the codebase is structured and how everything works