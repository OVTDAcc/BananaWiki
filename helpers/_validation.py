"""File validation, input validation, and URL safety helpers."""

import re
from urllib.parse import urlparse

from flask import request

import config
from ._constants import _USERNAME_RE


def allowed_file(filename):
    """Return True if *filename* has an extension permitted for image uploads."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in config.ALLOWED_EXTENSIONS


def allowed_attachment(filename):
    """Return True if *filename* has an extension permitted for page attachments."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in config.ATTACHMENT_ALLOWED_EXTENSIONS


def _is_valid_hex_color(value):
    """Return True if value is a valid 7-char hex color like #aabbcc."""
    return bool(re.fullmatch(r"#[0-9a-fA-F]{6}", value))


def _is_valid_username(value):
    """Return True if the username contains only safe characters.

    Allowed: letters, digits, underscores and hyphens.
    This prevents log-injection (newlines / control chars) and
    avoids confusing Unicode look-alikes.
    """
    return bool(_USERNAME_RE.fullmatch(value))


def _safe_referrer():
    """Return request.referrer only if it is same-origin; otherwise return None."""
    ref = request.referrer
    if not ref:
        return None
    parsed = urlparse(ref)
    if parsed.netloc and parsed.netloc != request.host:
        return None
    return ref
