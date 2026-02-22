"""
Tests for BananaWiki networking configuration.
"""

import importlib
import importlib.util
import os
import sys

import pytest

# Ensure the project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config

_GUNICORN_CONF_PATH = os.path.join(
    os.path.dirname(__file__), "..", "gunicorn.conf.py"
)


def _load_gunicorn_conf():
    """Load gunicorn.conf.py as a module (dot in filename prevents normal import)."""
    spec = importlib.util.spec_from_file_location("gunicorn_conf", _GUNICORN_CONF_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Use a temporary database for every test."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(config, "DATABASE_PATH", db_path)
    monkeypatch.setattr(config, "LOGGING_ENABLED", False)
    import db as db_mod
    db_mod.init_db()
    yield db_path


@pytest.fixture
def client():
    from app import app
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        yield c


# -----------------------------------------------------------------------
# Config defaults
# -----------------------------------------------------------------------
def test_default_port():
    assert config.PORT == 5001


def test_default_host_public():
    """USE_PUBLIC_IP=True binds to all interfaces."""
    assert config.USE_PUBLIC_IP is True
    assert config.HOST == "0.0.0.0"


def test_default_proxy_mode_off():
    assert config.PROXY_MODE is False


def test_default_ssl_disabled():
    assert config.SSL_CERT is None
    assert config.SSL_KEY is None


def test_default_custom_domain_none():
    assert config.CUSTOM_DOMAIN is None


# -----------------------------------------------------------------------
# Gunicorn config reads from config.py
# -----------------------------------------------------------------------
def test_gunicorn_conf_bind():
    """gunicorn.conf.py bind address matches config."""
    mod = _load_gunicorn_conf()
    assert mod.bind == f"{config.HOST}:{config.PORT}"


def test_gunicorn_conf_no_ssl_by_default():
    """SSL is not configured in gunicorn.conf.py when config has no certs."""
    mod = _load_gunicorn_conf()
    assert not hasattr(mod, "certfile")
    assert not hasattr(mod, "keyfile")


def test_gunicorn_conf_proxy_forwarded(monkeypatch):
    """forwarded_allow_ips is '*' when PROXY_MODE is True."""
    monkeypatch.setattr(config, "PROXY_MODE", True)
    mod = _load_gunicorn_conf()
    assert mod.forwarded_allow_ips == "*"


# -----------------------------------------------------------------------
# ProxyFix applied only when PROXY_MODE is True
# -----------------------------------------------------------------------
def test_proxy_fix_applied_when_enabled(monkeypatch):
    """When PROXY_MODE=True, the WSGI app should be wrapped by ProxyFix."""
    from werkzeug.middleware.proxy_fix import ProxyFix
    import app as app_mod
    monkeypatch.setattr(config, "PROXY_MODE", True)
    importlib.reload(app_mod)
    try:
        assert isinstance(app_mod.app.wsgi_app, ProxyFix)
    finally:
        monkeypatch.setattr(config, "PROXY_MODE", False)
        importlib.reload(app_mod)


# -----------------------------------------------------------------------
# WSGI entry point
# -----------------------------------------------------------------------
def test_wsgi_exports_app():
    """wsgi.py exposes the Flask app."""
    import wsgi
    from flask import Flask
    assert isinstance(wsgi.app, Flask)


# -----------------------------------------------------------------------
# App responds on configured host/port
# -----------------------------------------------------------------------
def test_app_serves_http(client):
    """App responds to HTTP requests via the test client."""
    from werkzeug.security import generate_password_hash
    import db
    db.create_user("admin", generate_password_hash("admin123"), role="admin")
    db.update_site_settings(setup_done=1)
    client.post("/login", data={"username": "admin", "password": "admin123"})
    resp = client.get("/")
    assert resp.status_code == 200
