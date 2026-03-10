# Operations Guide

This guide covers running, deploying, updating, and recovering BananaWiki.

## Runtime modes

| Mode | Command | Best for |
| --- | --- | --- |
| Development | `make dev` or `./dev.sh` | local testing and feature work |
| Gunicorn only | `make start` or `./start.sh` | manual production-style runs |
| Automated install | `sudo ./install.sh` | fresh Debian/Ubuntu VPS deployment |
| Provisioning wizard | `sudo python setup.py` | guided server provisioning with web UI |

## Development mode

```bash
make dev
```

This is a convenience wrapper around `./dev.sh`. It bootstraps `./venv` and runs the Flask development server. It is not intended for public production traffic.

## Gunicorn mode

```bash
./start.sh
```

Useful overrides:

```bash
./start.sh --port 8080
./start.sh --host 0.0.0.0
./start.sh --bind 0.0.0.0:5001
./start.sh --workers 4
```

`start.sh` reads `HOST` and `PORT` from `config.py` when you do not override them.

## Automated production installation

```bash
sudo ./install.sh
```

The installer performs these high-level steps:

1. install system dependencies
2. prepare the application directory
3. create the Python virtual environment
4. install Python packages
5. create a systemd service
6. optionally configure nginx and TLS

Common flags:

```bash
sudo ./install.sh --non-interactive
sudo ./install.sh --app-dir /opt/BananaWiki
sudo ./install.sh --user www-data
sudo ./install.sh --port 5001 --workers 4
sudo ./install.sh --domain wiki.example.com --email admin@example.com --ssl
sudo ./install.sh --no-nginx
```

## Setup wizard (`setup.py`)

`setup.py` is a separate provisioning wizard, not the same as the in-app `/setup` route.

Run it like this:

```bash
sudo python setup.py
sudo python setup.py --host 0.0.0.0 --port 5050
```

It can help with:

- domain/IP detection
- deployment mode selection
- systemd service creation
- nginx configuration
- optional certificate setup

## Admin settings after deployment

After the service is reachable and the first admin account exists, visit **Admin → Site Settings**.

![Admin settings](images/admin-settings.png)

Important runtime controls live there, including:

- timezone and site name
- dark/light theme palettes
- favicon selection
- lockdown mode and message
- session-limit toggle
- page reservation toggle
- chat enablement, quotas, cleanup schedule, and retention rules

## Updating safely

Use the repository's updater instead of hand-editing a production deployment:

```bash
sudo ./update.sh
```

Helpful flags:

```bash
sudo ./update.sh --branch main
sudo ./update.sh --skip-backup
sudo ./update.sh --no-restart
sudo ./update.sh --app-dir /opt/BananaWiki --service-name bananawiki
```

What the updater does:

1. creates a compressed backup unless skipped
2. checks for uncommitted changes
3. fetches and pulls from git
4. refreshes Python dependencies
5. restarts the service unless disabled
6. verifies the deployment

Backups are stored under `backups/`, and the script keeps the newest five backup archives.

## Useful service commands

```bash
sudo systemctl status bananawiki
sudo systemctl restart bananawiki
sudo systemctl stop bananawiki
journalctl -u bananawiki -f
```

## Testing and verification

Before or after operational changes, run:

```bash
make test
```

If you already have the virtualenv active:

```bash
python -m pytest tests/ -v
```

## Backups and runtime data

BananaWiki stores important live data in these locations:

- `instance/bananawiki.db`
- `instance/.secret_key`
- `instance/attachments/`
- `instance/chat_attachments/`
- `logs/bananawiki.log`

If Telegram sync is enabled in `config.py`, the app can also ship runtime backups through `sync.py` after significant changes.

## Resetting a password

Use the built-in CLI tool:

```bash
python reset_password.py
```

## Troubleshooting

### Reverse proxy issues

If HTTPS redirects, cookie security, or client IPs behave incorrectly behind nginx/Cloudflare, verify `PROXY_MODE = True` in `config.py` and ensure the proxy sends the expected forwarded headers.

### Uploads fail unexpectedly

Check both the Flask-wide `MAX_CONTENT_LENGTH` and the relevant attachment-size setting. Wiki attachments and chat attachments have their own limits and allowed extensions.

### Users report forced logout

Check whether lockdown mode or session-limit enforcement is enabled in site settings.

### Chat cleanup ran at an unexpected time

The cleanup schedule is controlled in site settings and surfaced in the UI countdown helpers; it is not configured in `config.py` anymore.
