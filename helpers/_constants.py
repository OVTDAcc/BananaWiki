"""Constants shared across BananaWiki helpers."""

import re

from werkzeug.security import generate_password_hash
import bleach


ALLOWED_TAGS = list(bleach.ALLOWED_TAGS) + [
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "br", "hr", "pre", "code",
    "table", "thead", "tbody", "tr", "th", "td",
    "ul", "ol", "li", "dl", "dt", "dd",
    "img", "figure", "figcaption",
    "div", "span", "section",
    "del", "ins", "sup", "sub",
]
ALLOWED_ATTRS = {
    "*": ["class", "id"],
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title", "width", "height"],
    "td": ["align"],
    "th": ["align"],
}

# Pre-computed dummy hash for constant-time login checks
_DUMMY_HASH = generate_password_hash("dummy-constant-time-check")

# Human-readable display labels for user roles.
ROLE_LABELS = {
    "user": "Member",
    "editor": "Editor",
    "admin": "Administrator",
    "protected_admin": "Administrator",
}

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
