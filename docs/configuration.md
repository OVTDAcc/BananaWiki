# Configuration Reference

All configuration lives in `config.py` at the root of the project. Edit it directly — there are no environment-specific config files. Restart the server after making changes.

## Networking

| Setting | Default | Description |
|---|---|---|
| `PORT` | `5001` | Port the server listens on. Pick a free port for each app on your server. |
| `USE_PUBLIC_IP` | `False` | `True` binds to `0.0.0.0` (all interfaces). `False` binds to `127.0.0.1` (localhost only — use this behind a reverse proxy). |
| `HOST` | *(derived)* | Set automatically from `USE_PUBLIC_IP`. Do not edit directly. |
| `CUSTOM_DOMAIN` | `None` | Domain or subdomain for the site (e.g. `wiki.example.com`). Used in log messages and links. Set to `None` for IP-only access. |

## Reverse Proxy & Cloudflare

| Setting | Default | Description |
|---|---|---|
| `PROXY_MODE` | `False` | Set to `True` when running behind nginx, Caddy, or Cloudflare. Enables `ProxyFix` middleware so Flask reads the real client IP and protocol from forwarded headers. Also marks session cookies as `Secure`. |

## SSL / HTTPS

| Setting | Default | Description |
|---|---|---|
| `SSL_CERT` | `None` | Path to an SSL certificate (e.g. `/etc/letsencrypt/live/example.com/fullchain.pem`). Leave `None` if using Cloudflare or a reverse proxy for TLS. |
| `SSL_KEY` | `None` | Path to the matching SSL private key. |

## Security

| Setting | Default | Description |
|---|---|---|
| `SECRET_KEY` | *(auto-generated)* | Flask session secret. Auto-generated on first run and stored in `instance/.secret_key`. You can also set it via the `SECRET_KEY` environment variable. |

## Database

| Setting | Default | Description |
|---|---|---|
| `DATABASE_PATH` | `instance/bananawiki.db` | Path to the SQLite database file. The `instance/` directory is created automatically on startup. |

## File Uploads

| Setting | Default | Description |
|---|---|---|
| `UPLOAD_FOLDER` | `app/static/uploads` | Directory where uploaded images are stored. |
| `MAX_CONTENT_LENGTH` | `16 * 1024 * 1024` | Maximum request body size (16 MB). Applies to image uploads. |
| `ALLOWED_EXTENSIONS` | `{"png", "jpg", "jpeg", "gif", "webp"}` | Permitted image file types. SVG is intentionally excluded due to XSS risk. |

## Page Attachments

| Setting | Default | Description |
|---|---|---|
| `ATTACHMENT_FOLDER` | `instance/attachments` | Directory where page file attachments are stored. Outside `static/` so files cannot be accessed directly by URL. |
| `MAX_ATTACHMENT_SIZE` | `5 * 1024 * 1024` | Maximum size per attachment (5 MB). |
| `ATTACHMENT_ALLOWED_EXTENSIONS` | *(see config.py)* | Permitted attachment file types: documents, archives, images, audio/video, and source code files. |

## Logging

| Setting | Default | Description |
|---|---|---|
| `LOGGING_ENABLED` | `True` | Write logs to disk. Disable to suppress all file logging. |
| `LOG_FILE` | `logs/bananawiki.log` | Path to the log file. The `logs/` directory is created automatically. |

Logs record every request (IP, method, path, user) and every significant action (logins, page edits, admin operations). Sensitive fields (passwords, tokens) are redacted automatically.

## Page History

| Setting | Default | Description |
|---|---|---|
| `PAGE_HISTORY_ENABLED` | `True` | Enables the page history viewer. Every edit, title change, and revert is recorded. Reverting creates a new history entry — nothing is ever deleted. |

## Invite Codes

| Setting | Default | Description |
|---|---|---|
| `INVITE_CODE_EXPIRY_HOURS` | `48` | How long a generated invite code is valid before it expires. |

## Telegram Sync / Backup

It is **strongly recommended** to enable sync so that your data is automatically backed up to Telegram whenever a significant change occurs.

| Setting | Default | Description |
|---|---|---|
| `SYNC` | `False` | Enable or disable Telegram backup sync. |
| `SYNC_TOKEN` | `""` | Telegram Bot API token. Create a bot with [@BotFather](https://t.me/BotFather) to get one. |
| `SYNC_USERID` | `""` | Telegram user or chat ID that will receive backups. |
| `SYNC_INCLUDE_SENSITIVE` | `False` | Include the database, secret key, config, and logs in backup archives. Disabled by default for safety. Enable only if your Telegram account/chat is trusted. |

### How sync works

Changes are **debounced**: after a change occurs, the system waits 60 seconds for more changes before sending a backup. If changes keep coming in, the backup is forced after 10 minutes regardless. This prevents flooding Telegram with backups during periods of heavy editing.

Uploaded image files are sent as individual Telegram messages (not bundled in the zip archive) so they can be easily retrieved. Message IDs are tracked in `sync_upload_msgs.json` for deletion threading.

### Triggering events

A backup is triggered on: user signup, page create/edit/revert/delete, page and category reordering, category changes, site settings changes, user management actions, and file uploads.
