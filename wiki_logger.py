"""
BananaWiki – Logging module
Logs requests, actions and events in detail.
"""

import logging
import os
from datetime import datetime, timezone

import config

_logger = None


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


def log_request(request, user=None):
    """Log an incoming HTTP request."""
    if not config.LOGGING_ENABLED:
        return
    logger = get_logger()
    ip = request.remote_addr
    method = request.method
    path = request.path
    ua = request.headers.get("User-Agent", "")
    username = user["username"] if user else "anonymous"
    logger.info(
        f"REQUEST | ip={ip} method={method} path={path} user={username} ua={ua}"
    )


def log_action(action, request, user=None, **details):
    """Log a specific action with extra detail."""
    if not config.LOGGING_ENABLED:
        return
    logger = get_logger()
    ip = request.remote_addr
    now = datetime.now(timezone.utc).isoformat()
    username = user["username"] if user else "anonymous"
    detail_str = " ".join(f"{k}={v}" for k, v in details.items())
    logger.info(
        f"ACTION  | time={now} ip={ip} user={username} action={action} {detail_str}"
    )
