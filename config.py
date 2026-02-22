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
# Protocol mode: "http", "https", or "both"
#   "http"  – serve over plain HTTP only (default)
#   "https" – serve over HTTPS only (requires SSL_CERT and SSL_KEY)
#   "both"  – serve HTTPS and automatically redirect HTTP to HTTPS
#             (requires SSL_CERT and SSL_KEY)
PROTOCOL = "http"

# Port for single-protocol mode ("http" or "https")
PORT = 8080

# Separate ports for "both" mode:
#   HTTP_PORT  – port for the HTTP-to-HTTPS redirect listener
#   HTTPS_PORT – port for the main HTTPS application server
HTTP_PORT = 80
HTTPS_PORT = 443

# Whether to bind to the public IP (0.0.0.0) so it is accessible from other machines
USE_PUBLIC_IP = True

# Whether to also listen on localhost/127.0.0.1
USE_LOCAL_IP = True

# Custom domain or subdomain for production deployments.
# Examples: "example.com", "wiki.example.com", "platform1.example.com"
# Used for startup messages and as the HTTP-to-HTTPS redirect target.
# Set to None when accessing via IP address only.
CUSTOM_DOMAIN = None

# Flask SERVER_NAME for URL generation in multi-site setups.
# Format: "hostname" or "hostname:port" (omit port for 80/443).
# Leave as None for automatic configuration (recommended for most setups).
# Only set this when hosting multiple Flask sites on the same machine and
# you need Flask to generate correct external URLs.
# Example: "wiki.example.com" or "localhost:5001"
SERVER_NAME = None

# Host binding: 0.0.0.0 serves on all interfaces (public + local)
# 127.0.0.1 serves only on localhost
HOST = "0.0.0.0" if USE_PUBLIC_IP else "127.0.0.1"

# =============================================================================
# SSL / HTTPS
# =============================================================================
# To enable HTTPS, provide paths to your SSL certificate and private key.
# When both are set the app will serve over HTTPS instead of plain HTTP.
# Example:
#   SSL_CERT = "/etc/letsencrypt/live/yourdomain.com/fullchain.pem"
#   SSL_KEY  = "/etc/letsencrypt/live/yourdomain.com/privkey.pem"
SSL_CERT = None
SSL_KEY = None

# =============================================================================
# Reverse Proxy Support
# =============================================================================
# Enable this when running behind a reverse proxy (e.g. nginx, Apache, Caddy,
# Cloudflare, or a cloud load balancer on OCI / Google Cloud / AWS).  The proxy
# must set the standard forwarding headers (X-Forwarded-For, X-Forwarded-Proto,
# etc.).  This ensures Flask sees the real client IP and correct URL scheme.
#
# Multi-site hosting example (one machine, multiple Flask sites):
#   nginx routes platform1.example.com → localhost:5001
#                platform2.example.com → localhost:5002
#   Each site sets PORT to its unique port and PROXY_MODE = True.
#   See README.md for full reverse-proxy and Cloudflare configuration examples.
PROXY_MODE = False

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
