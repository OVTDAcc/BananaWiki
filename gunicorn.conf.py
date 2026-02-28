"""
Gunicorn configuration file for BananaWiki.

Usage:
    gunicorn wsgi:app -c gunicorn.conf.py

All settings here can be overridden via command-line flags or environment
variables. See https://docs.gunicorn.org/en/stable/settings.html
"""

import multiprocessing

import config as _bw_config  # underscore prefix avoids Gunicorn setting clash

# ---------------------------------------------------------------------------
#  Bind address
# ---------------------------------------------------------------------------
# Uses HOST and PORT from config.py by default.
# Override: gunicorn wsgi:app --bind 0.0.0.0:5001
bind = f"{_bw_config.HOST}:{_bw_config.PORT}"

# ---------------------------------------------------------------------------
#  Workers
# ---------------------------------------------------------------------------
# A good default is 2-4x the number of CPU cores.
# For a small wiki, 2 workers is usually sufficient.
workers = min(multiprocessing.cpu_count() * 2 + 1, 4)

# Worker class – sync is simplest and works well for typical wiki workloads.
worker_class = "sync"

# ---------------------------------------------------------------------------
#  Forwarded headers (reverse proxy)
# ---------------------------------------------------------------------------
# When behind nginx, Gunicorn trusts the X-Forwarded-* headers.
# This is handled by ProxyFix in app.py when PROXY_MODE = True.
forwarded_allow_ips = "*" if _bw_config.PROXY_MODE else "127.0.0.1"

# ---------------------------------------------------------------------------
#  Logging
# ---------------------------------------------------------------------------
accesslog = "-"        # stdout
errorlog = "-"         # stderr
loglevel = "info"

# ---------------------------------------------------------------------------
#  Timeouts
# ---------------------------------------------------------------------------
timeout = 30           # worker timeout (seconds)
graceful_timeout = 30  # graceful shutdown timeout
keepalive = 2          # keep-alive connections (seconds)
