"""
BananaWiki – Logging module
Logs requests, actions and events in detail with configurable verbosity levels.

Logging Levels:
  - off:      No logging
  - minimal:  Only critical errors and warnings
  - medium:   Errors, warnings, and important actions (auth, admin)
  - verbose:  Medium + all user actions (default)
  - debug:    All of the above + HTTP requests and debug info
"""

import logging
import os
import re
from datetime import datetime, timezone

import config


_logger = None
_log_level = None

# Pattern to strip characters that could forge log entries
_LOG_UNSAFE_RE = re.compile(r"[\r\n\x00-\x1f\x7f]")

# Logging level constants
LOG_OFF = "off"
LOG_MINIMAL = "minimal"
LOG_MEDIUM = "medium"
LOG_VERBOSE = "verbose"
LOG_DEBUG = "debug"

# Action categories for level filtering
CRITICAL_ACTIONS = {
    "admin_delete_user", "admin_change_role", "admin_deattribute_all",
    "admin_bulk_delete", "admin_force_release_checkout", "setup_complete"
}
IMPORTANT_ACTIONS = {
    "login_success", "login_failed", "signup_success", "logout",
    "change_password", "change_username", "delete_account",
    "admin_edit_profile", "admin_create_invite", "admin_delete_invite"
}
USER_ACTIONS = {
    "edit_page", "create_page", "delete_page", "revert_page", "move_page",
    "upload_image", "delete_image", "view_page", "profile_update",
    "reserve_page", "release_reservation", "send_message", "delete_message",
    "create_group", "join_group", "leave_group", "kick_member"
}


def _get_log_level():
    """Get the configured logging level."""
    global _log_level
    if _log_level is not None:
        return _log_level

    # Check new LOGGING_LEVEL config first
    level = getattr(config, "LOGGING_LEVEL", "verbose").lower()
    if level not in {LOG_OFF, LOG_MINIMAL, LOG_MEDIUM, LOG_VERBOSE, LOG_DEBUG}:
        level = LOG_VERBOSE  # Default to verbose if invalid

    # Fall back to old LOGGING_ENABLED for backwards compatibility
    if not getattr(config, "LOGGING_ENABLED", True):
        level = LOG_OFF

    _log_level = level
    return _log_level


def get_logger():
    global _logger
    if _logger is not None:
        return _logger

    _logger = logging.getLogger("bananawiki")
    level = _get_log_level()

    # Set logger level based on configured level
    if level == LOG_OFF:
        _logger.setLevel(logging.CRITICAL + 1)  # Disable all logging
    elif level == LOG_MINIMAL:
        _logger.setLevel(logging.WARNING)
    else:
        _logger.setLevel(logging.DEBUG)

    if level != LOG_OFF:
        os.makedirs(os.path.dirname(config.LOG_FILE), exist_ok=True)
        fh = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        # Enhanced format with more context
        fmt = logging.Formatter(
            "[%(asctime)s] [%(levelname)-8s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        fh.setFormatter(fmt)
        _logger.addHandler(fh)

    # Console handler for INFO and above
    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO if level != LOG_OFF else logging.CRITICAL + 1)
    sh.setFormatter(logging.Formatter(
        "[%(asctime)s] [%(levelname)-8s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    _logger.addHandler(sh)

    return _logger


def _sanitize(value):
    """Strip control characters (newlines, etc.) to prevent log injection."""
    return _LOG_UNSAFE_RE.sub("", str(value))


def log_request(request, user=None):
    """Log an incoming HTTP request (only at debug level)."""
    level = _get_log_level()
    if level != LOG_DEBUG:
        return

    logger = get_logger()
    ip = _sanitize(request.remote_addr or "unknown")
    method = _sanitize(request.method)
    path = _sanitize(request.path)
    ua = _sanitize(request.headers.get("User-Agent", ""))
    username = _sanitize(user["username"]) if user else "anonymous"

    # Enhanced request logging with more context
    logger.debug(
        f"HTTP {method:6s} | {path:40s} | user={username:20s} | ip={ip:15s} | ua={ua[:60]}"
    )


_SENSITIVE_FIELDS = {"password", "current_password", "new_password",
                     "confirm_password", "secret", "token", "session"}


def _should_log_action(action):
    """Determine if an action should be logged at the current level."""
    level = _get_log_level()

    if level == LOG_OFF:
        return False
    if level == LOG_DEBUG or level == LOG_VERBOSE:
        return True  # Log everything
    if level == LOG_MEDIUM:
        # Log critical and important actions only
        return action in CRITICAL_ACTIONS or action in IMPORTANT_ACTIONS
    if level == LOG_MINIMAL:
        # Log only critical actions
        return action in CRITICAL_ACTIONS

    return True  # Default to logging


def log_action(action, request, user=None, **details):
    """Log a specific action with extra detail (sensitive fields are redacted).

    Actions are categorized and filtered based on the logging level:
      - minimal: Only critical admin actions
      - medium:  Critical + important actions (auth, admin operations)
      - verbose: All actions including user actions (default)
      - debug:   All actions with maximum detail
    """
    if not _should_log_action(action):
        return

    logger = get_logger()
    ip = _sanitize(request.remote_addr or "unknown")
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    username = _sanitize(user["username"]) if user else "anonymous"
    safe_action = _sanitize(action)

    # Redact sensitive fields
    safe_details = {k: ("***" if k in _SENSITIVE_FIELDS else _sanitize(v))
                    for k, v in details.items()}

    # Enhanced formatting with categorization
    category = "CRITICAL" if action in CRITICAL_ACTIONS else \
               "IMPORTANT" if action in IMPORTANT_ACTIONS else \
               "USER" if action in USER_ACTIONS else "OTHER"

    # Build detail string with better formatting
    detail_parts = []
    for k, v in safe_details.items():
        # Truncate very long values for readability
        str_v = str(v)
        if len(str_v) > 100:
            str_v = str_v[:97] + "..."
        detail_parts.append(f"{k}={str_v}")
    detail_str = " ".join(detail_parts)

    # Log with structured format
    log_msg = f"[{category:8s}] {safe_action:30s} | user={username:20s} | ip={ip:15s}"
    if detail_str:
        log_msg += f" | {detail_str}"

    logger.info(log_msg)
