# 🍌 BananaWiki

> A self-hosted wiki built with Flask and SQLite — clean, fast, and ready to run in minutes.

![Python](https://img.shields.io/badge/python-3.9%2B-blue?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/flask-3.1-lightgrey?logo=flask&logoColor=white)
![SQLite](https://img.shields.io/badge/database-SQLite-003B57?logo=sqlite&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)

BananaWiki is a lightweight, private wiki you can host on your own server. No cloud services, no external databases — just a Python app, a single SQLite file, and full control over your knowledge base.

---

## 📸 Screenshots

<table>
<tr>
<td align="center">
  <strong>Home — wiki view</strong><br>
  <img src="https://github.com/user-attachments/assets/ab13800e-08c4-425e-809c-05b1d1ef3599" alt="Home page" width="420">
</td>
<td align="center">
  <strong>Split-pane Markdown editor</strong><br>
  <img src="https://github.com/user-attachments/assets/e02c2bad-b065-4131-a869-1c2b15cb3219" alt="Markdown editor" width="420">
</td>
</tr>
<tr>
<td align="center">
  <strong>Page revision history</strong><br>
  <img src="https://github.com/user-attachments/assets/b60f7a48-eb1a-4bd2-8cb7-8d220d364559" alt="Page history" width="420">
</td>
<td align="center">
  <strong>User profile with contribution heatmap</strong><br>
  <img src="https://github.com/user-attachments/assets/e6e11b2e-dc9b-4a36-ba80-1014c7838bcf" alt="User profile" width="420">
</td>
</tr>
<tr>
<td align="center">
  <strong>People sidebar &amp; member directory</strong><br>
  <img src="https://github.com/user-attachments/assets/377a09a3-0515-4dbb-8d8a-9632940ce45b" alt="People sidebar" width="420">
</td>
<td align="center">
  <strong>Account settings &amp; admin shortcuts</strong><br>
  <img src="https://github.com/user-attachments/assets/05afee31-38cb-47b3-8c01-45f89052207e" alt="Account settings" width="420">
</td>
</tr>
<tr>
<td align="center">
  <strong>Admin — manage users</strong><br>
  <img src="https://github.com/user-attachments/assets/c2385adb-c6bb-46ee-86d0-ceb55f16a2c4" alt="Admin users" width="420">
</td>
<td align="center">
  <strong>Admin — site settings &amp; theme colors</strong><br>
  <img src="https://github.com/user-attachments/assets/9f2cdf61-c944-4f3b-91f0-b2cc006bead5" alt="Admin settings" width="420">
</td>
</tr>
<tr>
<td align="center">
  <strong>Admin — announcement manager</strong><br>
  <img src="https://github.com/user-attachments/assets/3438ed27-4b4e-4f2d-b76c-ece9e537419a" alt="Admin announcements" width="420">
</td>
<td align="center">
  <strong>Login page</strong><br>
  <img src="https://github.com/user-attachments/assets/d9fad2c1-ced2-4320-9c1b-f03603df5d11" alt="Login page" width="420">
</td>
</tr>
<tr>
<td colspan="2" align="center">
  <strong>Announcement banner — color variants with navigation</strong><br>
  <img src="https://github.com/user-attachments/assets/1be5bb61-7ae5-48aa-9bbd-47c513b581d0" alt="Announcement banner" width="860">
</td>
</tr>
</table>

---

## ✨ Features

### 📝 Writing & Editing
| Feature | Details |
|---|---|
| **Markdown editor** | Full Markdown support: tables, fenced code blocks, `[TOC]` table of contents, newline-to-`<br>` rendering |
| **Split-pane live preview** | Editor and rendered output side by side; drag the divider to resize; formatting toolbar for quick shortcuts |
| **Draft autosave** | Browser autosaves every few seconds; restores on re-open; conflict warning when two editors are on the same page at once |
| **Image uploads** | Drag-and-drop or file picker; modal to set alt text, position (inline / float left / float right / center), and optional pixel width |
| **Page attachments** | Attach PDFs, archives, and other files to any page; served through an authenticated route — not public static files |
| **Internal link picker** | Link dialog includes a Wiki Page tab with autocomplete so editors can link without knowing the exact URL |
| **URL slug rename** | Rename a page's slug after creation; all internal links across every page and open draft are rewritten atomically |
| **Difficulty tags** | Tag pages as `Beginner`, `Easy`, `Intermediate`, `Expert`, `Extra`, or a custom label with a custom color |

### 🗂️ Organisation
| Feature | Details |
|---|---|
| **Hierarchical categories** | Unlimited nesting depth; collapsible tree in the sidebar; drag-to-reorder pages and categories |
| **Sequential navigation** | Per-category Prev/Next buttons let readers walk through a category in order, like chapters in a book |
| **Page deindexing** | Editors can hide any page from the sidebar and search (while keeping it accessible via its URL) with a single toggle; admins and editors can still see and navigate to deindexed pages |
| **Page history** | Every save is a versioned snapshot; view any past state, read edit summaries, and revert with one click — nothing is ever deleted from history |

### 👥 People
| Feature | Details |
|---|---|
| **User profiles** | Public profile with real name, bio, and avatar (max 1 MB); publish, hide, or delete from the profile page directly |
| **Contribution heatmap** | GitHub-style yearly heatmap of wiki edits on every profile |
| **People directory** | Searchable member list at `/users`; sidebar widget shows the most active members |
| **Contributor attribution** | "Last edit by" links on every page and in every history row go directly to that user's profile |
| **Admin profile moderation** | Admins can edit any user's profile data, remove avatars, and disable or delete profile pages |

### 🔐 Accounts & Access
| Feature | Details |
|---|---|
| **Four-tier roles** | `user` (read-only) → `editor` → `admin` → `protected_admin` |
| **Invite code signup** | Time-limited single-use codes generated by admins; race-condition-safe consumption |
| **Protected admin mode** | Self-toggleable hardening: other admins cannot rename, demote, suspend, or delete a protected admin |
| **User data export** | Download all personal data (account info, contributions, drafts, history) as a ZIP from Account Settings |

### ♿ Accessibility
| Feature | Details |
|---|---|
| **Per-user preferences** | Text size (6 steps), high-contrast mode (6 levels), line/letter spacing, reduce-motion, six color overrides, sidebar width |
| **Accessibility panel** | One-click ♿ button in the topbar opens a drawer with all controls — available on every page including the editor |

### 🛠️ Admin & Operations
| Feature | Details |
|---|---|
| **Announcement banners** | Site-wide banners with five color themes, three text sizes, per-audience visibility, expiry dates, and Markdown support |
| **Customizable appearance** | Site name, six CSS color palette fields, favicon (eight preset colors or custom upload) |
| **Lockdown mode** | Instantly blocks all non-admin access with a configurable message |
| **Video embedding** | Bare YouTube and Vimeo URLs pasted on their own line are automatically rendered as responsive embedded players |
| **Session limit** | Enforce one active session per user — signing in on a new device invalidates the previous session (opt-in per-site setting) |
| **Site migration** | Full export/import as a ZIP; three conflict modes: delete all, override, or keep existing data |
| **Telegram backup** | Debounced automatic backups of the DB, config, logs, and uploads to a Telegram chat; exponential-backoff retries |

### 🔒 Security
- CSRF protection on every form and AJAX call (Flask-WTF)
- HTML sanitization with Bleach after every Markdown render
- Login rate limiting shared across all Gunicorn workers (SQLite-backed, 5 attempts / 60 s)
- Per-route rate limiting on all mutation endpoints
- Security headers on every response (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Content-Security-Policy`)
- Constant-time login checks to prevent username enumeration

---

## 🚀 Quick Start

**Requirements:** Python 3.9+

### For Local Development / Testing

**Option 1: Using Make (simplest)**
```bash
git clone https://github.com/ovtdadt/BananaWiki.git
cd BananaWiki
make dev
```

**Option 2: Using the dev script directly**
```bash
git clone https://github.com/ovtdadt/BananaWiki.git
cd BananaWiki
./dev.sh
```

Both methods automatically set up the virtual environment, install dependencies, and start the Flask development server. Open **http://localhost:5001** to access BananaWiki.

### For Production Deployment

**Option 1: Automated Installation (Recommended)**

```bash
git clone https://github.com/ovtdadt/BananaWiki.git
cd BananaWiki
sudo make install
# or: sudo ./install.sh
```

The installation script will guide you through an interactive setup that:
- Installs system dependencies
- Sets up the application with proper permissions
- Configures systemd service for automatic startup
- Optionally sets up nginx reverse proxy
- Optionally obtains SSL certificate with Let's Encrypt

**Option 2: Manual Setup**

```bash
git clone https://github.com/ovtdadt/BananaWiki.git
cd BananaWiki
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
make start                       # or: ./start.sh or: gunicorn wsgi:app -c gunicorn.conf.py
```

**On first visit**, you'll be redirected to the setup wizard to create the first admin account.

---

## ⚙️ Initial Setup

On first run, BananaWiki shows a one-time setup wizard:

1. Choose a **username** (3–50 characters, letters/digits/underscores/hyphens only)
2. Set a **password** (minimum 6 characters)
3. Confirm the password

This creates the first admin account and marks setup as complete. All subsequent users are added via **invite codes** or directly from the **Admin → Manage Users** panel.

---

## 👤 User Roles

| Role | Permissions |
|---|---|
| `user` | Read pages |
| `editor` | Read, create, edit, and delete pages; manage categories; revert history; upload images and attachments |
| `admin` | Everything editors can do, plus: manage users, generate invite codes, configure settings, post announcements, moderate profiles |
| `protected_admin` | Same as admin, but shielded from modification by other admins |

New users who sign up with an invite code receive the **user** role by default. Admins can change roles from **Admin → Manage Users**. The `protected_admin` role can only be toggled by the account owner from their own Account Settings page.

---

## 🗄️ Project Structure

```
BananaWiki/
├── app.py              # Flask app: all routes, middleware, and request handling
├── db.py               # Database layer: schema, migrations, and all queries
├── config.py           # Configuration — edit this to customize your instance
├── sync.py             # Telegram backup/sync module
├── wiki_logger.py      # Request and action logging
├── wsgi.py             # WSGI entry point for Gunicorn
├── gunicorn.conf.py    # Gunicorn server configuration
├── Makefile            # Convenient shortcuts: make dev, make start, make install
├── dev.sh              # Quick start script for local development
├── start.sh            # Production start script with Gunicorn
├── install.sh          # Automated production installation script
├── bananawiki.service  # systemd service file for production
├── setup.py            # Advanced server provisioning wizard (systemd + nginx + certbot)
├── reset_password.py   # CLI tool for resetting a user password outside the web UI
├── requirements.txt    # Python dependencies
├── app/
│   ├── static/
│   │   ├── css/        # Stylesheets
│   │   ├── js/         # Client-side JavaScript (editor, sidebar, drafts, easter egg)
│   │   ├── favicons/   # Preset and custom favicon images
│   │   └── uploads/    # User-uploaded images and avatars (runtime, gitignored)
│   └── templates/
│       ├── base.html                  # Base layout with sidebar and announcement bar
│       ├── _announcements_bar.html    # Announcement banner partial
│       ├── auth/       # login.html, signup.html, setup.html, lockdown.html
│       ├── wiki/       # page.html, edit.html, create_page.html, history.html,
│       │               # history_entry.html, announcement.html, easter_egg.html,
│       │               # _category.html (recursive sidebar partial),
│       │               # 403.html, 404.html, 429.html, 500.html
│       ├── account/    # settings.html
│       ├── users/      # list.html, profile.html
│       └── admin/      # users.html, codes.html, codes_expired.html,
│                       # settings.html, announcements.html, audit.html,
│                       # editor_access.html, migration.html
├── docs/               # Detailed documentation
├── instance/           # Database, attachments, secret key — created at runtime (gitignored)
├── logs/               # Application logs — created at runtime (gitignored)
└── tests/              # Test suite (606 tests across 9 files)
```

---

## 🧪 Running Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

Tests use isolated temporary databases and cover routes, database logic, rate limiting, networking/proxy configuration, and Telegram sync behavior.

---

## 📚 Documentation

Full documentation lives in the [`docs/`](docs/) directory:

| Doc | What's in it |
|---|---|
| [Features](docs/features.md) | Complete feature catalogue with code references |
| [Configuration](docs/configuration.md) | Every `config.py` setting with defaults and usage notes |
| [Deployment](docs/deployment.md) | systemd, manual Gunicorn, Cloudflare, nginx, Caddy, and direct SSL/TLS setups |
| [Architecture](docs/architecture.md) | Codebase structure, request lifecycle, security model, and database schema |
