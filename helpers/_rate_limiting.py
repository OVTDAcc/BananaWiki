"""Login and general rate limiting helpers."""

import functools
import threading
from datetime import datetime, timezone

from flask import request, flash, jsonify, abort

import db
from wiki_logger import log_action


# ---------------------------------------------------------------------------
#  Login rate limiting (per-IP, shared across workers via DB)
# ---------------------------------------------------------------------------
class _RateLimitStore(dict):
    """Compatibility shim for tests; backing data lives in DB."""

    def clear(self):
        """Clear both the in-memory dict and the DB login_attempts table."""
        super().clear()
        db.clear_all_login_attempts()


_LOGIN_ATTEMPTS = _RateLimitStore()
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW = 60  # seconds


def _check_login_rate_limit():
    """Return True if the request IP is allowed to attempt login."""
    ip = request.remote_addr or "unknown"
    recent = db.count_recent_login_attempts(ip, _LOGIN_WINDOW)
    return recent < _LOGIN_MAX_ATTEMPTS


def _record_login_attempt():
    """Record a failed login attempt for the current IP."""
    ip = request.remote_addr or "unknown"
    db.record_login_attempt(ip)


def _clear_login_attempts():
    """Clear failed login attempts for the current IP (on successful login)."""
    ip = request.remote_addr or "unknown"
    db.clear_login_attempts(ip)


# ---------------------------------------------------------------------------
#  General rate limiting (in-memory, per-worker, thread-safe)
# ---------------------------------------------------------------------------
_RL_LOCK = threading.Lock()
_RL_STORE: dict = {}            # (ip, bucket) → list of UTC timestamps
_RL_GLOBAL_MAX = 300            # max requests per window for all endpoints
_RL_GLOBAL_WINDOW = 60          # window size in seconds
_RL_SWEEP_COUNTER = 0           # counts _rl_check calls; triggers periodic sweep
_RL_SWEEP_INTERVAL = 1000       # sweep stale keys every N calls


def _rl_sweep(cutoff):
    """Remove keys whose timestamp lists are entirely outside the current window.

    Must be called with *_RL_LOCK* already held.
    """
    stale = [k for k, v in _RL_STORE.items() if not any(t > cutoff for t in v)]
    for k in stale:
        del _RL_STORE[k]


def _rl_check(ip, bucket, max_requests, window):
    """Return True if the request is within the rate limit, and record it."""
    global _RL_SWEEP_COUNTER
    key = (ip, bucket)
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - window
    with _RL_LOCK:
        _RL_SWEEP_COUNTER += 1
        if _RL_SWEEP_COUNTER >= _RL_SWEEP_INTERVAL:
            _RL_SWEEP_COUNTER = 0
            _rl_sweep(cutoff)
        pruned = [t for t in _RL_STORE.get(key, []) if t > cutoff]
        if len(pruned) >= max_requests:
            if pruned:
                _RL_STORE[key] = pruned
            else:
                _RL_STORE.pop(key, None)
            return False
        pruned.append(now)
        _RL_STORE[key] = pruned
        return True


def rate_limit(max_requests=60, window=60):
    """Route decorator that enforces a per-IP rate limit."""
    def decorator(f):
        """Wrap the route function with the rate-limit enforcement logic."""
        bucket = f.__name__
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            """Check the per-IP rate limit before calling the route handler."""
            ip = request.remote_addr or "unknown"
            if not _rl_check(ip, bucket, max_requests, window):
                log_action("rate_limited", request, endpoint=bucket)
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Too many requests. Please slow down."}), 429
                flash("Too many requests. Please slow down.", "error")
                abort(429)
            return f(*args, **kwargs)
        return wrapper
    return decorator
