"""
BananaWiki – Database layer (SQLite)

This package re-exports every public symbol from the internal sub-modules so
that ``import db`` and ``db.function_name()`` continue to work exactly as
before.
"""

from ._connection import get_db  # noqa: F401  (keep first – used by other sub-modules)

# Schema
from ._schema import init_db  # noqa: F401

# Users & editor access
from ._users import (  # noqa: F401
    _gen_user_id,
    generate_random_id,
    create_user,
    get_user_by_id,
    get_user_by_username,
    _ALLOWED_USER_COLUMNS,
    update_user,
    delete_user,
    record_username_change,
    get_username_history,
    set_easter_egg_found,
    _A11Y_DEFAULTS,
    get_user_accessibility,
    save_user_accessibility,
    record_login_attempt,
    count_recent_login_attempts,
    clear_login_attempts,
    clear_all_login_attempts,
    list_users,
    count_admins,
    get_editor_access,
    set_editor_access,
    set_user_chat_disabled,
    is_user_chat_disabled,
)

# Invite codes
from ._invites import (  # noqa: F401
    generate_invite_code,
    validate_invite_code,
    use_invite_code,
    delete_invite_code,
    hard_delete_invite_code,
    list_invite_codes,
    list_expired_codes,
)

# Categories
from ._categories import (  # noqa: F401
    create_category,
    get_category,
    update_category,
    is_descendant_of,
    update_category_parent,
    delete_category,
    count_pages_in_category,
    list_categories,
    get_category_tree,
    update_pages_sort_order,
    update_categories_sort_order,
    search_categories,
)

# Pages & attachments
from ._pages import (  # noqa: F401
    update_category_sequential_nav,
    get_adjacent_pages,
    update_page_slug,
    search_pages,
    search_pages_full,
    create_page,
    get_page,
    get_page_by_slug,
    get_home_page,
    update_page,
    update_page_title,
    update_page_category,
    VALID_DIFFICULTY_TAGS,
    update_page_tag,
    set_page_deindexed,
    delete_page,
    get_page_history,
    get_history_entry,
    transfer_history_attribution,
    bulk_transfer_history_attribution,
    delete_history_entry,
    clear_page_history,
    _UPLOAD_REF_RE,
    get_all_referenced_image_filenames,
    add_page_attachment,
    get_page_attachments,
    get_page_attachment,
    delete_page_attachment,
)

# Drafts
from ._drafts import (  # noqa: F401
    save_draft,
    get_draft,
    get_drafts_for_page,
    delete_draft,
    transfer_draft,
    get_user_draft_count,
    list_user_drafts,
)

# Site settings
from ._settings import (  # noqa: F401
    get_site_settings,
    _ALLOWED_SETTINGS_COLUMNS,
    update_site_settings,
)

# Announcements & contributions
from ._announcements import (  # noqa: F401
    create_announcement,
    get_announcement,
    list_announcements,
    _ALLOWED_ANN_COLUMNS,
    update_announcement,
    delete_announcement,
    get_user_contributions,
    get_active_announcements,
)

# Import/export
from ._migration import (  # noqa: F401
    _MIGRATION_VERSION,
    _EXPORT_TABLES,
    export_site_data,
    import_site_data,
)

# User profiles
from ._profiles import (  # noqa: F401
    get_user_profile,
    upsert_user_profile,
    delete_user_profile,
    list_published_profiles,
    list_all_users_with_profiles,
    get_contributions_by_day,
)

# Direct messages
from ._chats import (  # noqa: F401
    get_or_create_chat,
    get_chat_by_id,
    is_chat_participant,
    get_user_chats,
    get_chat_messages,
    get_chat_message_by_id,
    send_chat_message,
    add_chat_attachment,
    get_user_chat_attachment_count_today,
    get_chat_attachment,
    get_all_chats_admin,
    get_user_chats_admin,
    get_all_messages_for_backup,
    cleanup_old_chat_messages,
    cleanup_old_chat_attachments,
    clear_chat_messages,
    delete_chat_message,
    increment_unread_count,
    reset_unread_count,
    get_total_unread_dm_count,
)

# Audit / role history / custom tags / contribution management
from ._audit import (  # noqa: F401
    record_role_change,
    get_role_history,
    get_user_custom_tags,
    add_user_custom_tag,
    update_user_custom_tag,
    delete_user_custom_tag,
    reorder_user_custom_tags,
    get_user_custom_tag,
    deattribute_contribution,
    deattribute_all_user_contributions,
    delete_role_history_entry,
    delete_all_role_history,
    get_role_history_entry,
    mass_reattribute_contributions,
)

# Group chats
from ._groups import (  # noqa: F401
    generate_invite_code_for_group,
    create_group_chat,
    get_or_create_global_chat,
    get_group_chat,
    get_group_chat_by_invite,
    is_group_member,
    get_group_member,
    get_group_member_role,
    add_group_member,
    remove_group_member,
    get_group_members,
    set_group_member_role,
    set_group_member_timeout,
    is_group_member_timed_out,
    get_user_groups,
    send_group_message,
    send_group_system_message,
    get_group_messages,
    add_group_attachment,
    get_group_attachment,
    delete_group_message,
    get_group_message_by_id,
    get_all_group_chats_admin,
    get_all_group_messages_for_backup,
    get_group_messages_for_export,
    cleanup_old_group_messages,
    cleanup_old_group_attachments,
    get_user_group_attachment_count_today,
    transfer_group_ownership,
    ban_group_member,
    unban_group_member,
    is_group_member_banned,
    get_group_banned_members,
    regenerate_group_invite_code,
    set_group_chat_active,
    delete_group_chat,
    clear_group_messages,
    increment_group_unread_count,
    reset_group_unread_count,
    get_total_unread_group_count,
)

# Custom permissions
from ._permissions import (  # noqa: F401
    get_user_permissions,
    set_user_permissions,
    has_permission,
    has_category_read_access,
    has_category_write_access,
    clear_user_permissions,
)

# Badges
from ._badges import (  # noqa: F401
    VALID_TRIGGER_TYPES,
    create_badge_type,
    get_badge_type,
    get_badge_type_by_name,
    list_badge_types,
    update_badge_type,
    delete_badge_type,
    award_badge,
    revoke_badge,
    get_user_badges,
    has_badge,
    get_badge_holders,
    count_user_badges,
    get_unnotified_badges,
    mark_badges_notified,
    clear_badge_notifications,
    check_and_award_auto_badges,
    revoke_all_badges_for_type,
)

# Page reservations
from ._reservations import (  # noqa: F401
    reservations_enabled,
    reserve_page,
    release_page_reservation,
    get_page_reservation_status,
    cleanup_expired_reservations,
    can_user_reserve_page,
    can_user_edit_page,
    get_user_reservations,
    get_all_active_reservations,
    get_active_page_reservations_map,
    force_release_reservation,
)
