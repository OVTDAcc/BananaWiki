# Configuration Reference

All configuration lives in `config.py` at the root of the project. Edit it directly — there are no environment-specific config files. Restart the server after making changes.

## Networking

| Setting | Default | Description |
|---|---|---|
| `PORT` | `5001` | Port the server listens on. Pick a free port for each app on your server. |
| `HOST` | `"127.0.0.1"` | Address Gunicorn binds to. The default (`127.0.0.1`) is correct when nginx or Cloudflare is the public-facing proxy. Set to `"0.0.0.0"` only if Gunicorn must be reachable directly from the internet (no proxy). |

## Reverse Proxy & Cloudflare

| Setting | Default | Description |
|---|---|---|
| `PROXY_MODE` | `True` | Set to `True` when running behind nginx, Caddy, or Cloudflare (the recommended setup). Enables `ProxyFix` middleware so Flask reads the real client IP and protocol from forwarded headers. Also marks session cookies as `Secure`. Set to `False` only for local development. |

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

## Chat Attachments

| Setting | Default | Description |
|---|---|---|
| `CHAT_ATTACHMENT_FOLDER` | `instance/chat_attachments` | Directory where direct-message and group-chat attachments are stored. Outside `static/` so downloads always go through authenticated routes. |
| `CHAT_ALLOWED_EXTENSIONS` | *(see config.py)* | Permitted chat attachment file types. The allowed list is intentionally narrower than page attachments. |

## Logging

| Setting | Default | Description |
|---|---|---|
| `LOGGING_LEVEL` | `"verbose"` | Control logging detail level. Options: `"off"` (no logs), `"minimal"` (critical only), `"medium"` (critical+important), `"verbose"` (all actions, default), `"debug"` (all+HTTP requests). |
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

## Page Reservations

| Setting | Default | Description |
|---|---|---|
| `PAGE_RESERVATION_DURATION_HOURS` | `48` | How long a page checkout remains active before it expires automatically. |
| `PAGE_RESERVATION_COOLDOWN_HOURS` | `72` | How long a user must wait after a reservation ends before reserving the same page again. |

## Settings Managed in the Admin UI

Not every adjustable setting lives in `config.py`. The following options are stored in the database and should be managed from **Admin → Settings** so they can be changed without editing files:

- chat attachment size limits and daily upload quotas
- chat cleanup schedule and retention settings
- site name, timezone, and color palette
- lockdown mode and the lockdown message
- one-session-per-user enforcement
- OAuth provider settings

## Telegram Sync / Backup

It is **strongly recommended** to enable sync so that your data is automatically backed up to Telegram whenever a significant change occurs.

| Setting | Default | Description |
|---|---|---|
| `SYNC` | `False` | Enable or disable Telegram backup sync. |
| `SYNC_TOKEN` | `""` | Telegram Bot API token. Create a bot with [@BotFather](https://t.me/BotFather) to get one. |
| `SYNC_USERID` | `""` | Telegram user or chat ID that will receive backups. |
| `SYNC_SPLIT_THRESHOLD` | `45 * 1024 * 1024` (45 MB) | Maximum backup size before splitting. Backups larger than this will be sent separately. |
| `SYNC_COMPRESS_LEVEL` | `9` | ZIP compression level (0-9). Higher values = better compression but slower. |
| `SYNC_INCLUDE_CHAT_ATTACHMENTS` | `True` | Include chat attachments in automatic backups. Set to `False` if attachments are too large. |

### How sync works

Changes are **debounced**: after a change occurs, the system waits 60 seconds for more changes before sending a backup. If changes keep coming in, the backup is forced after 10 minutes regardless. This prevents flooding Telegram with backups during periods of heavy editing.

Every backup zip contains the database, `config.py`, the secret key, log files, and a manifest listing the changes that triggered the backup. The system uses **smart backup logic**:

- **Unified backups**: If total size is under the split threshold (45 MB by default), everything is sent as a single ZIP file.
- **Separate backups**: If total size exceeds the threshold, data is split intelligently to stay within Telegram's 50 MB limit.
- **Smart compression**: Uses configurable compression level (default: 9) for maximum space savings.
- **Chat backup optimization**: Large chat backups (>1 MB) are sent as text files instead of chunked messages for better efficiency.

The only reason a file is excluded is if it would push the archive over the configured size limit.

> **Security note:** Because `config.py` (which contains `SYNC_TOKEN` and `SYNC_USERID`) and `instance/.secret_key` are bundled into every backup zip, the Telegram chat that receives backups will accumulate copies of these credentials. Anyone with access to that Telegram chat — including its chat history — can read the bot token and the Flask session secret key. Treat the receiving Telegram account and chat as a sensitive secret store. Rotate `SYNC_TOKEN` and regenerate `instance/.secret_key` if you believe the Telegram chat has been compromised.

Uploaded image files are sent as individual Telegram messages (not bundled in the zip archive) so they can be easily retrieved. Message IDs are tracked in `sync_upload_msgs.json` for deletion threading.

### Triggering events

A backup is triggered on: user signup, page create/edit/revert/delete, page and category reordering, category changes, site settings changes, user management actions, and file uploads.
