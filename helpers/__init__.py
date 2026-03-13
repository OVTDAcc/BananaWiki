"""
BananaWiki – Utility functions, constants, and shared helpers.

Extracted from app.py to keep route handlers separate from reusable logic.

This package re-exports every public and private name so that existing
``from helpers import X`` statements continue to work unchanged.
"""

from helpers._constants import (          # noqa: F401
    ALLOWED_TAGS,
    ALLOWED_ATTRS,
    _DUMMY_HASH,
    ROLE_LABELS,
    _USERNAME_RE,
)

from helpers._rate_limiting import (      # noqa: F401
    _RateLimitStore,
    _LOGIN_ATTEMPTS,
    _LOGIN_MAX_ATTEMPTS,
    _LOGIN_WINDOW,
    _check_login_rate_limit,
    _record_login_attempt,
    _clear_login_attempts,
    _RL_LOCK,
    _RL_STORE,
    _RL_GLOBAL_MAX,
    _RL_GLOBAL_WINDOW,
    _rl_check,
    rate_limit,
)

from helpers._markdown import (           # noqa: F401
    render_markdown,
    _make_video_iframe,
    _embed_videos_in_html,
)

from helpers._diff import (              # noqa: F401
    compute_char_diff,
    compute_diff_html,
    compute_formatted_diff_html,
)

from helpers._text import slugify        # noqa: F401

from helpers._validation import (        # noqa: F401
    allowed_file,
    allowed_attachment,
    _is_valid_hex_color,
    _is_valid_username,
    _safe_referrer,
)

from helpers._auth import (              # noqa: F401
    get_current_user,
    login_required,
    editor_required,
    admin_required,
    editor_has_category_access,
    user_can_view_page,
    user_can_view_category,
    filter_visible_navigation,
)

from helpers._time import (              # noqa: F401
    get_site_timezone,
    time_ago,
    format_datetime,
    format_datetime_local_input,
    get_effective_chat_cleanup_settings,
    get_time_since_last_chat_cleanup,
    get_time_until_next_chat_cleanup,
)
