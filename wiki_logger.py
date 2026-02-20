"""
BananaWiki – Logging module
Logs requests, actions and events in detail.
"""

import logging
import os
import re
from datetime import datetime, timezone

import config


_logger = None

# Pattern to strip characters that could forge log entries
_LOG_UNSAFE_RE = re.compile(r"[\r\n\x00-\x1f\x7f]")


def get_logger():
    global _logger
    if _logger is not None:
        return _logger

    _logger = logging.getLogger("bananawiki")
    _logger.setLevel(logging.DEBUG if config.LOGGING_ENABLED else logging.WARNING)

    if config.LOGGING_ENABLED:
        os.makedirs(os.path.dirname(config.LOG_FILE), exist_ok=True)
        fh = logging.FileHandler(config.LOG_FILE, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fmt = logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s")
        fh.setFormatter(fmt)
        _logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)
    sh.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s"))
    _logger.addHandler(sh)

    return _logger


def _sanitize(value):
    """Strip control characters (newlines, etc.) to prevent log injection."""
    return _LOG_UNSAFE_RE.sub("", str(value))


def log_request(request, user=None):
    """Log an incoming HTTP request."""
    if not config.LOGGING_ENABLED:
        return
    logger = get_logger()
    ip = _sanitize(request.remote_addr or "")
    method = _sanitize(request.method)
    path = _sanitize(request.path)
    ua = _sanitize(request.headers.get("User-Agent", ""))
    username = _sanitize(user["username"]) if user else "anonymous"
    logger.info(
        f"REQUEST | ip={ip} method={method} path={path} user={username} ua={ua}"
    )


_SENSITIVE_FIELDS = {"password", "current_password", "new_password",
                     "confirm_password", "secret", "token", "session"}


def log_action(action, request, user=None, **details):
    """Log a specific action with extra detail (sensitive fields are redacted)."""
    if not config.LOGGING_ENABLED:
        return
    logger = get_logger()
    ip = _sanitize(request.remote_addr or "")
    now = datetime.now(timezone.utc).isoformat()
    username = _sanitize(user["username"]) if user else "anonymous"
    safe_action = _sanitize(action)
    safe_details = {k: ("***" if k in _SENSITIVE_FIELDS else _sanitize(v))
                    for k, v in details.items()}
    detail_str = " ".join(f"{k}={v}" for k, v in safe_details.items())
    logger.info(
        f"ACTION  | time={now} ip={ip} user={username} action={safe_action} {detail_str}"
    )
