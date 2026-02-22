"""
BananaWiki Configuration File
Customize your instance settings here.
"""

import os
import secrets

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# =============================================================================
# Networking Configuration
# =============================================================================
# Port to listen on.  Each app on your server gets its own port
# (e.g. 5001 for BananaWiki, 5002 for another app, etc.).
PORT = 5001

# Bind to all network interfaces so the app is reachable from other machines.
# Set to False to restrict access to localhost only.
USE_PUBLIC_IP = True

# Host binding (derived from USE_PUBLIC_IP above):
#   0.0.0.0   – all interfaces (public + local)
#   127.0.0.1 – localhost only
HOST = "0.0.0.0" if USE_PUBLIC_IP else "127.0.0.1"

# Custom domain or subdomain for production deployments.
# Examples: "example.com", "wiki.example.com"
# Set to None when accessing via IP address only.
CUSTOM_DOMAIN = None

# =============================================================================
# Reverse Proxy / Cloudflare Support
# =============================================================================
# Enable this when running behind a reverse proxy (nginx, Caddy) or Cloudflare.
# The proxy must set the standard forwarding headers (X-Forwarded-For,
# X-Forwarded-Proto, etc.) so Flask sees the real client IP and scheme.
#
# Typical Cloudflare setup:
#   1. Run BananaWiki on HTTP (PORT = 5001)
#   2. Point your Cloudflare DNS A record to your server's public IP
#   3. Cloudflare handles HTTPS for visitors and connects to your server via HTTP
#   4. Set PROXY_MODE = True and CUSTOM_DOMAIN = "wiki.example.com"
PROXY_MODE = False

# =============================================================================
# SSL / HTTPS  (optional — not needed with Cloudflare)
# =============================================================================
# Provide paths to an SSL certificate and private key to serve HTTPS directly.
# When Cloudflare handles SSL, leave these as None.
# Example:
#   SSL_CERT = "/etc/letsencrypt/live/yourdomain.com/fullchain.pem"
#   SSL_KEY  = "/etc/letsencrypt/live/yourdomain.com/privkey.pem"
SSL_CERT = None
SSL_KEY = None

# =============================================================================
# Security
# =============================================================================
SECRET_KEY_FILE = os.path.join(BASE_DIR, "instance", ".secret_key")


def _load_secret_key():
    """Load or generate a persistent secret key."""
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key

    instance_dir = os.path.dirname(SECRET_KEY_FILE)
    os.makedirs(instance_dir, exist_ok=True)

    if os.path.exists(SECRET_KEY_FILE):
        with open(SECRET_KEY_FILE, "r", encoding="utf-8") as f:
            file_key = f.read().strip()
        if file_key:
            return file_key

    new_key = secrets.token_hex(32)
    with open(SECRET_KEY_FILE, "w", encoding="utf-8") as f:
        f.write(new_key)
    os.chmod(SECRET_KEY_FILE, 0o600)
    return new_key


SECRET_KEY = _load_secret_key()

# =============================================================================
# Database
# =============================================================================
DATABASE_PATH = os.path.join(BASE_DIR, "instance", "bananawiki.db")

# =============================================================================
# Uploads
# =============================================================================
UPLOAD_FOLDER = os.path.join(BASE_DIR, "app", "static", "uploads")
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB max upload size
# Note: SVG is intentionally disallowed due to potential embedded script/XSS risks.
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

# =============================================================================
# Logging
# =============================================================================
# Enable or disable logging (default: on)
LOGGING_ENABLED = True

# Log file path
LOG_FILE = os.path.join(BASE_DIR, "logs", "bananawiki.log")

# =============================================================================
# Page History
# =============================================================================
# Page history is always active. All page edits, title changes, and reverts are
# logged and can be viewed. Rolling back a page creates a new history entry;
# nothing is ever deleted from page history.
PAGE_HISTORY_ENABLED = True

# =============================================================================
# Invite Codes
# =============================================================================
# How long invite codes last before expiring (in hours)
INVITE_CODE_EXPIRY_HOURS = 48

# =============================================================================
# Telegram Sync / Backup
# =============================================================================
# It is STRONGLY RECOMMENDED to enable sync so that runtime data (database,
# uploads, config, logs) is automatically backed up to Telegram whenever a
# significant change occurs (user signup, page edit, settings change, etc.).
#
# SYNC         – Enable or disable the sync feature (default: off)
# SYNC_TOKEN   – Telegram Bot API token (from @BotFather)
# SYNC_USERID  – Telegram user/chat ID to receive backups
SYNC = False
SYNC_TOKEN = ""
SYNC_USERID = ""
