# Update Guide

This guide covers how to safely update BananaWiki to the latest version.

## Table of Contents

- [Quick Update](#quick-update)
- [Update Process Overview](#update-process-overview)
- [Update Script Options](#update-script-options)
- [Manual Update Process](#manual-update-process)
- [Rollback Instructions](#rollback-instructions)
- [Database Migrations](#database-migrations)
- [Troubleshooting](#troubleshooting)
- [Best Practices](#best-practices)

---

## Quick Update

The easiest way to update BananaWiki is with the `update.sh` script:

```bash
cd /opt/BananaWiki  # or your installation directory
sudo ./update.sh
```

The script will:
1. ✅ Create a backup of your current installation
2. ✅ Pull the latest code from git
3. ✅ Update Python dependencies
4. ✅ Run database migrations automatically
5. ✅ Restart the service
6. ✅ Verify the update was successful

**The entire process typically takes 1-2 minutes with minimal downtime.**

---

## Update Process Overview

### What Happens During an Update

1. **Backup Creation**
   - A complete backup is created in the `backups/` directory
   - Includes: database, config, logs, and uploaded files
   - Excludes: virtual environment, git data, and old backups
   - Last 5 backups are kept automatically

2. **Code Update**
   - Fetches latest changes from git
   - Checks for local modifications (offers to stash them)
   - Pulls the latest code from the specified branch

3. **Dependency Update**
   - Updates Python packages from `requirements.txt`
   - Ensures all dependencies are at correct versions

4. **Database Migration**
   - Migrations run automatically when the service starts
   - All schema changes are non-destructive
   - Uses `ALTER TABLE ADD COLUMN` with defaults for backward compatibility

5. **Service Restart**
   - Gracefully restarts the systemd service
   - Verifies service started successfully
   - Auto-rollback if the service fails to start

6. **Verification**
   - Confirms git commit and branch
   - Checks service status
   - Reports any issues

### Update Safety Features

- **Automatic backups** before every update
- **Change detection** warns about uncommitted local modifications
- **Dependency verification** ensures all packages are installed
- **Service health checks** verify successful startup
- **Automatic rollback** if service fails after update
- **Backup retention** keeps last 5 backups automatically

---

## Update Script Options

### Basic Usage

```bash
# Standard update to latest version of current branch
sudo ./update.sh

# Update to a specific branch
sudo ./update.sh --branch main

# Update without restarting the service
sudo ./update.sh --no-restart

# Update without creating backup (NOT RECOMMENDED)
sudo ./update.sh --skip-backup
```

### Available Options

| Option | Description |
|--------|-------------|
| `--branch BRANCH` | Update to specific git branch (default: current branch) |
| `--skip-backup` | Skip creating backup before update (not recommended) |
| `--no-restart` | Don't restart the service after update |
| `--app-dir DIR` | Application directory (default: script directory) |
| `--service-name NAME` | Systemd service name (default: bananawiki) |
| `-h, --help` | Show help message |

### Examples

**Update to specific branch:**
```bash
sudo ./update.sh --branch develop
```

**Update without service restart (for manual restart later):**
```bash
sudo ./update.sh --no-restart
# Then restart manually when ready:
sudo systemctl restart bananawiki
```

**Update with custom service name:**
```bash
sudo ./update.sh --service-name my-wiki
```

---

## Manual Update Process

If you need to update manually without the script:

### 1. Create Backup

```bash
cd /opt/BananaWiki
mkdir -p backups
tar -czf backups/backup_$(date +%Y%m%d_%H%M%S).tar.gz \
    --exclude='venv' --exclude='.git' --exclude='backups' .
```

### 2. Stop the Service

```bash
sudo systemctl stop bananawiki
```

### 3. Pull Latest Changes

```bash
git fetch --all
git pull origin main  # or your branch
```

### 4. Update Dependencies

```bash
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 5. Start the Service

```bash
sudo systemctl start bananawiki
```

Database migrations run automatically on startup.

### 6. Verify

```bash
sudo systemctl status bananawiki
journalctl -u bananawiki -n 50
```

---

## Rollback Instructions

If an update causes issues, you can rollback to the previous version.

### Using Backup (Recommended)

```bash
# 1. Stop the service
sudo systemctl stop bananawiki

# 2. Extract backup (replace with your backup filename)
cd /opt/BananaWiki
sudo tar -xzf backups/bananawiki_backup_YYYYMMDD_HHMMSS.tar.gz

# 3. Start the service
sudo systemctl start bananawiki

# 4. Verify
sudo systemctl status bananawiki
```

### Using Git

```bash
# 1. Stop the service
sudo systemctl stop bananawiki

# 2. Revert to previous commit
cd /opt/BananaWiki
git log --oneline -10  # Find the commit to revert to
git reset --hard <commit-hash>

# 3. Update dependencies (in case requirements changed)
source venv/bin/activate
pip install -r requirements.txt

# 4. Start the service
sudo systemctl start bananawiki
```

### Verify Rollback

```bash
# Check git status
git log --oneline -5

# Check service
sudo systemctl status bananawiki

# View logs
sudo journalctl -u bananawiki -f
```

---

## Database Migrations

BananaWiki uses an automatic migration system that runs on app startup.

### How Migrations Work

- **Automatic execution**: Migrations run when the app starts
- **Non-destructive**: Only adds columns, never removes data
- **Backward compatible**: New columns have sensible defaults
- **Safe for existing data**: Uses `ALTER TABLE ... ADD COLUMN ... DEFAULT`

### Migration Process

1. On app startup, `db.init_db()` is called
2. Schema tables are created if they don't exist
3. Missing columns are added via `ALTER TABLE`
4. Data migrations run (e.g., user ID TEXT migration)
5. App starts normally

### Checking Migration Status

Migrations run automatically and log to the application logs:

```bash
# View migration logs
sudo journalctl -u bananawiki -n 100 | grep -i migration

# Or check app logs
tail -f logs/bananawiki.log
```

### Manual Migration Trigger

Migrations run automatically, but you can trigger them manually:

```bash
cd /opt/BananaWiki
source venv/bin/activate
python3 -c "from db import init_db; init_db(); print('Migrations complete')"
```

---

## Troubleshooting

### Update Script Issues

**Problem: Permission denied**
```bash
# Solution: Run with sudo
sudo ./update.sh
```

**Problem: Not a git repository**
```bash
# Solution: Ensure you're in the correct directory and installed via git
cd /opt/BananaWiki
git status
```

**Problem: Uncommitted changes**
```bash
# The script will detect this and offer to stash changes
# Or manually stash before updating:
git stash save "My local changes"
sudo ./update.sh
git stash pop  # Restore changes after update
```

### Service Issues After Update

**Problem: Service won't start**

```bash
# Check service status
sudo systemctl status bananawiki

# View detailed logs
sudo journalctl -u bananawiki -n 50 --no-pager

# Check for Python errors
sudo journalctl -u bananawiki -f
```

**Problem: Import errors or missing modules**

```bash
# Reinstall dependencies
cd /opt/BananaWiki
source venv/bin/activate
pip install --force-reinstall -r requirements.txt
sudo systemctl restart bananawiki
```

**Problem: Database errors**

```bash
# Check database file permissions
ls -la bananawiki.db
sudo chown www-data:www-data bananawiki.db

# Check database integrity
sqlite3 bananawiki.db "PRAGMA integrity_check;"
```

### Common Error Messages

**"Database is locked"**
- The database is being accessed by another process
- Stop the service and try again: `sudo systemctl stop bananawiki`

**"No module named 'flask'"**
- Virtual environment not activated or dependencies not installed
- Run: `source venv/bin/activate && pip install -r requirements.txt`

**"Permission denied" when accessing database**
- Database file permissions incorrect
- Run: `sudo chown www-data:www-data bananawiki.db instance/`

---

## Best Practices

### Before Updating

1. ✅ **Read the changelog** or release notes for breaking changes
2. ✅ **Check disk space** - ensure at least 500MB free
3. ✅ **Notify users** if running a shared wiki
4. ✅ **Choose low-traffic time** for updates

### During Updates

1. ✅ **Use the update script** - it handles all steps correctly
2. ✅ **Don't skip backups** unless you have external backups
3. ✅ **Monitor logs** during and after update
4. ✅ **Test critical features** after update

### After Updates

1. ✅ **Verify service status** - check `systemctl status`
2. ✅ **Test key features** - login, page creation, editing
3. ✅ **Check logs** for errors or warnings
4. ✅ **Review changelog** for new features or changes
5. ✅ **Update documentation** if you have custom docs

### Update Schedule Recommendations

**Production environments:**
- Update to stable releases only
- Test updates in development/staging first
- Schedule updates during maintenance windows
- Keep at least 3 backups

**Development environments:**
- Can update to development branches
- Update more frequently to test new features
- Less critical backup requirements

### Backup Strategy

The update script keeps the last 5 backups automatically. For production:

1. **External backups**: Use Telegram sync or external backup system
2. **Retention**: Keep daily backups for 7 days, weekly for 30 days
3. **Test restores**: Periodically test backup restoration
4. **Off-site storage**: Store critical backups off-server

### Update Frequency

**Recommended update frequency:**
- **Security updates**: Immediately
- **Bug fixes**: Within 1 week
- **New features**: Monthly or as needed
- **Major versions**: Plan and test thoroughly

---

## Additional Resources

- [Deployment Guide](deployment.md) - Initial installation instructions
- [Configuration Guide](configuration.md) - Configuration options
- [Architecture Guide](architecture.md) - System architecture details
- [Telegram Backup](configuration.md#telegram-sync--backup) - Automated backup setup

---

## Support

If you encounter issues during updates:

1. Check the [Troubleshooting](#troubleshooting) section above
2. Review service logs: `sudo journalctl -u bananawiki -f`
3. Restore from backup if needed
4. Report issues on GitHub: https://github.com/ovtdadt/BananaWiki/issues

Remember: **Always keep backups**, and test updates in a development environment first when possible.
