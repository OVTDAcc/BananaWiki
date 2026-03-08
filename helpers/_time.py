"""Timezone-aware time formatting helpers."""

from datetime import datetime, timedelta, timezone

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import db


def get_site_timezone():
    """Return the zoneinfo timezone configured in site settings (defaults to UTC)."""
    settings = db.get_site_settings()
    tz_name = (settings["timezone"] if settings and settings["timezone"] else "UTC")
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        return ZoneInfo("UTC")


def time_ago(dt_str):
    """Return a human-readable 'X ago' or 'in X' string."""
    if not dt_str:
        return "never"
    try:
        dt = datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return "unknown"
    diff = datetime.now(timezone.utc) - dt
    secs = int(diff.total_seconds())
    if secs < 0:
        # Future date
        secs = abs(secs)
        if secs < 60:
            return "in a moment"
        elif secs < 3600:
            m = secs // 60
            return f"in {m} minute{'s' if m != 1 else ''}"
        elif secs < 86400:
            h = secs // 3600
            return f"in {h} hour{'s' if h != 1 else ''}"
        else:
            d = secs // 86400
            return f"in {d} day{'s' if d != 1 else ''}"
    if secs < 60:
        return "just now"
    elif secs < 3600:
        m = secs // 60
        return f"{m} minute{'s' if m != 1 else ''} ago"
    elif secs < 86400:
        h = secs // 3600
        return f"{h} hour{'s' if h != 1 else ''} ago"
    else:
        d = secs // 86400
        return f"{d} day{'s' if d != 1 else ''} ago"


def format_datetime(dt_str):
    """Return a human-readable date/time string in the configured site timezone."""
    if not dt_str:
        return ""
    try:
        dt = datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return ""
    site_tz = get_site_timezone()
    dt_local = dt.astimezone(site_tz)
    tz_label = dt_local.strftime("%Z")
    return dt_local.strftime(f"%Y-%m-%d %H:%M {tz_label}")


def format_datetime_local_input(dt_str):
    """Convert a UTC ISO datetime to site-timezone value for datetime-local inputs."""
    if not dt_str:
        return ""
    try:
        dt = datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return ""
    site_tz = get_site_timezone()
    dt_local = dt.astimezone(site_tz)
    return dt_local.strftime("%Y-%m-%dT%H:%M")


def get_next_chat_cleanup_time():
    """Calculate and return the next scheduled chat cleanup time as an ISO datetime string."""
    try:
        site_tz = get_site_timezone()
        now = datetime.now(site_tz)
        settings = db.get_site_settings()

        # Get cleanup schedule from DB settings with sensible defaults
        cleanup_frequency = (settings["chat_cleanup_frequency_days"] if settings and settings["chat_cleanup_frequency_days"] else 7)
        cleanup_hour = (settings["chat_cleanup_hour"] if settings and settings["chat_cleanup_hour"] is not None else 3)

        # Get last cleanup time
        last_cleanup = None
        if settings:
            try:
                last_cleanup_str = settings["last_chat_cleanup_at"]
                if last_cleanup_str:
                    # Parse ISO format datetime
                    last_cleanup = datetime.fromisoformat(last_cleanup_str.replace('Z', '+00:00'))
                    # Convert to site timezone
                    last_cleanup = last_cleanup.astimezone(site_tz)
            except (KeyError, ValueError, AttributeError, TypeError):
                pass

        # If no last cleanup recorded, next cleanup is at configured hour today/tomorrow
        if not last_cleanup:
            target = now.replace(hour=cleanup_hour, minute=0, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
        else:
            # Schedule for configured frequency after last cleanup
            target = last_cleanup.replace(hour=cleanup_hour, minute=0, second=0, microsecond=0)
            target += timedelta(days=cleanup_frequency)

            # If target is in the past, schedule for the next interval
            while target <= now:
                target += timedelta(days=cleanup_frequency)

        # Convert to UTC for storage
        return target.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def get_time_since_last_chat_cleanup():
    """Return a human-readable string for time elapsed since last chat cleanup."""
    try:
        settings = db.get_site_settings()
        if not settings:
            return "Messages have not been cleaned up yet"

        try:
            last_cleanup_str = settings["last_chat_cleanup_at"]
            if not last_cleanup_str:
                return "Messages have not been cleaned up yet"
            return time_ago(last_cleanup_str)
        except (KeyError, TypeError):
            return "Messages have not been cleaned up yet"
    except Exception:
        return "Unknown"


def get_time_until_next_chat_cleanup():
    """Return a human-readable string for time remaining until next chat cleanup."""
    try:
        next_cleanup_str = get_next_chat_cleanup_time()
        if not next_cleanup_str:
            return "Unknown"

        next_cleanup = datetime.fromisoformat(next_cleanup_str).replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = next_cleanup - now
        secs = int(diff.total_seconds())

        if secs <= 0:
            return "Soon"

        if secs < 60:
            return "in a moment"
        elif secs < 3600:
            m = secs // 60
            return f"in {m} minute{'s' if m != 1 else ''}"
        elif secs < 86400:
            h = secs // 3600
            return f"in {h} hour{'s' if h != 1 else ''}"
        else:
            d = secs // 86400
            return f"in {d} day{'s' if d != 1 else ''}"
    except Exception:
        return "Unknown"

