# Page Reservation System

## Overview

The Page Reservation System allows users with edit permissions to temporarily lock a wiki page for exclusive editing. When a page is reserved, no other user can modify it until the reservation expires (48 hours) or is manually released.

## Key Features

- **48-hour reservations**: Lock a page for up to 48 hours
- **72-hour cooldown**: After releasing a reservation, users must wait 72 hours before re-reserving the same page
- **Per-page cooldown**: Cooldown only applies to the specific page, not all pages
- **Automatic expiry**: Reservations automatically expire after 48 hours
- **Permission-based**: Respects existing category-based edit permissions
- **Real-time status**: Shows who has reserved a page and when it expires
- **Conflict prevention**: Prevents race conditions when multiple users try to reserve simultaneously

## User Interface

### On Page View

For unreserved pages:
```
□ Reserve this page for exclusive editing
```

If the current user has reserved the page:
```
🔒 You have reserved this page for editing
    Expires in 22h 15m
    [Release Reservation]
```

If another user has reserved the page:
```
🔒 Reserved by username
    Expires in 22h 15m
```

During cooldown period:
```
□ Reserve this page for exclusive editing (disabled)
⏱ Cooldown: available in 3 days
```

### On Edit Page

When editing a reserved page you own:
```
🔒 You have reserved this page. Your reservation expires in 22h 15m.
```

## Configuration

Edit `config.py` to customize durations:

```python
# How long a page reservation lasts before expiring (in hours)
PAGE_RESERVATION_DURATION_HOURS = 48

# Cooldown period after a reservation ends before user can re-reserve (in hours)
PAGE_RESERVATION_COOLDOWN_HOURS = 72
```

## API Endpoints

### Get Reservation Status
```
GET /api/pages/<page_id>/reservation/status
```

Returns:
```json
{
  "is_reserved": true,
  "reserved_by": "user_id",
  "reserved_by_username": "username",
  "reserved_at": "2026-03-06T10:00:00+00:00",
  "expires_at": "2026-03-08T10:00:00+00:00",
  "time_remaining_text": "46h 15m",
  "user_in_cooldown": false,
  "cooldown_until": null,
  "cooldown_remaining_text": null
}
```

### Reserve a Page
```
POST /api/pages/<page_id>/reservation
```

Success response (200):
```json
{
  "ok": true,
  "reservation": {
    "page_id": 123,
    "reserved_at": "2026-03-06T10:00:00+00:00",
    "expires_at": "2026-03-08T10:00:00+00:00"
  }
}
```

Error responses:
- 409 Conflict: Page already reserved or user in cooldown
- 403 Forbidden: User lacks permission to edit the page
- 404 Not Found: Page doesn't exist

### Release Reservation
```
DELETE /api/pages/<page_id>/reservation
```

Success response (200):
```json
{
  "ok": true
}
```

Error responses:
- 404 Not Found: No active reservation by this user
- 403 Forbidden: User lacks permission

## Database Schema

### page_reservations Table
```sql
CREATE TABLE page_reservations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id         INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    user_id         TEXT    NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reserved_at     TEXT    NOT NULL,
    expires_at      TEXT    NOT NULL,
    released_at     TEXT,
    UNIQUE(page_id)
);
```

### user_page_cooldowns Table
```sql
CREATE TABLE user_page_cooldowns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id         INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    user_id         TEXT    NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    cooldown_until  TEXT    NOT NULL,
    UNIQUE(page_id, user_id)
);
```

## Python API

```python
import db

# Reserve a page
reservation = db.reserve_page(page_id, user_id)

# Get reservation status
status = db.get_page_reservation_status(page_id, user_id)

# Check if user can reserve
can_reserve, reason = db.can_user_reserve_page(page_id, user_id)

# Check if user can edit
can_edit, reason = db.can_user_edit_page(page_id, user_id)

# Release a reservation
released = db.release_page_reservation(page_id, user_id)

# Force release (admin action, no cooldown)
released = db.force_release_reservation(page_id)

# Get all user's active reservations
reservations = db.get_user_reservations(user_id)

# Cleanup expired reservations
result = db.cleanup_expired_reservations()
```

## Edge Cases

### User Deleted
When a user is deleted, all their reservations are automatically released (CASCADE delete).

### Page Deleted
When a page is deleted, its reservations and cooldowns are automatically removed (CASCADE delete).

### Loss of Edit Permission
If a user loses edit permission to a category while holding a reservation, they can still keep the reservation until expiry, but cannot renew it. Admins can force-release using `db.force_release_reservation()`.

### Race Conditions
The system uses database UNIQUE constraints to prevent two users from reserving the same page simultaneously. Only one INSERT will succeed; the other will receive a conflict error.

### Expiry Check
Reservation expiry is evaluated lazily (on request) rather than via background job. The `cleanup_expired_reservations()` function can be called periodically if needed, but is not required for correctness.

## Logging

All reservation actions are logged:
- `reserve_page`: When a page is reserved
- `release_page_reservation`: When a reservation is manually released

Check logs at `logs/bananawiki.log` (if logging is enabled).

## Testing

Run the manual test suite:
```bash
python test_reservations_manual.py
```

Or run full pytest suite (if pytest is installed):
```bash
pytest tests/test_page_reservations.py -v
```

## Troubleshooting

### Reservation stuck/orphaned
If a reservation appears stuck, you can manually clean it up:
```python
import db
db.force_release_reservation(page_id)
```

### Cooldown too long
To manually clear a cooldown:
```sql
DELETE FROM user_page_cooldowns
WHERE page_id = <page_id> AND user_id = '<user_id>';
```

Or via Python:
```python
from db import get_db
conn = get_db()
conn.execute("DELETE FROM user_page_cooldowns WHERE page_id=? AND user_id=?", (page_id, user_id))
conn.commit()
conn.close()
```

### Multiple active reservations
This shouldn't happen due to UNIQUE constraint, but if it does:
```sql
-- See all active reservations
SELECT pr.*, u.username
FROM page_reservations pr
JOIN users u ON pr.user_id = u.id
WHERE pr.released_at IS NULL AND pr.expires_at > datetime('now');
```

## Future Enhancements

Possible improvements for future versions:
- Background job for automatic cleanup
- Email notifications when reservation is about to expire
- Configurable reservation durations per category
- Transfer reservation to another user
- Extend reservation before expiry
- Dashboard showing all active reservations
- Reservation history/audit log
