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
# Port to serve the application on
PORT = 8080

# Whether to bind to the public IP (0.0.0.0) so it is accessible from other machines
USE_PUBLIC_IP = True

# Whether to also listen on localhost/127.0.0.1
USE_LOCAL_IP = True

# Custom domain (set to None to disable)
CUSTOM_DOMAIN = None

# Host binding: 0.0.0.0 serves on all interfaces (public + local)
# 127.0.0.1 serves only on localhost
HOST = "0.0.0.0" if USE_PUBLIC_IP else "127.0.0.1"

# =============================================================================
# Security
# =============================================================================
SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))

# =============================================================================
# Database
# =============================================================================
DATABASE_PATH = os.path.join(BASE_DIR, "instance", "bananawiki.db")

# =============================================================================
# Uploads
# =============================================================================
UPLOAD_FOLDER = os.path.join(BASE_DIR, "app", "static", "uploads")
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB max upload size
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "svg"}

# =============================================================================
# Logging
# =============================================================================
# Enable or disable logging (default: on)
LOGGING_ENABLED = True

# Log file path
LOG_FILE = os.path.join(BASE_DIR, "logs", "bananawiki.log")

# =============================================================================
# Invite Codes
# =============================================================================
# How long invite codes last before expiring (in hours)
INVITE_CODE_EXPIRY_HOURS = 48
