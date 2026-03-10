# Custom Permission System

## Overview

BananaWiki now includes a comprehensive custom permission system that allows administrators to grant granular permissions to editors and users. This replaces the old simple role-based system with a flexible, permission-based approach.

## Key Features

- **38 individual permissions** across 10 categories (pages, categories, history, drafts, attachments, tags, profiles, chat, search, invites)
- **Separate read and write category restrictions** - read access remains distinct, while editor write access automatically includes read access to the same categories
- **Default permission sets** - reasonable defaults for editors and users that can be customized
- **Permission-based deindexed page visibility** - control who can see hidden pages
- **Admin interface** - easy-to-use UI for configuring permissions
- **Backward compatible** - integrates with existing editor category access system

## Roles

### Admin & Protected Admin
- Have **all permissions** automatically
- Cannot have custom permissions configured
- Can manage permissions for other users

### Editor
- **Default permissions**: 22 enabled (page creation, editing, viewing deindexed pages, draft management, file uploads, etc.)
- Can have **custom permissions** configured by admin
- Can have **write access** restricted to specific categories
- Can have **read access** restricted to specific categories, but any category with write access is always readable too

### User
- **Default permissions**: 11 enabled (viewing pages, viewing profiles, chat, search, etc.)
- Can have **custom permissions** configured by admin
- Can have **read access** restricted to specific categories
- Cannot receive editor/admin capabilities from custom permissions; change the role to editor/admin instead

## Permission Categories

### Page Permissions
- `page.view_all` - View all pages including deindexed ones
- `page.view_deindexed` - View pages marked as deindexed
- `page.create` - Create new wiki pages
- `page.edit_all` - Edit any page in allowed categories
- `page.delete` - Delete wiki pages
- `page.edit_metadata` - Change page title, slug, category
- `page.deindex` - Mark pages as deindexed/hidden

### Category Permissions
- `category.view_all` - View all category pages
- `category.create` - Create new categories
- `category.edit` - Rename and modify categories
- `category.delete` - Delete categories
- `category.reorder` - Change category sort order
- `category.manage_sequential` - Enable/disable sequential navigation

### Page History
- `history.view` - View page edit history
- `history.revert` - Revert pages to previous versions
- `history.delete` - Delete individual history entries
- `history.transfer` - Transfer page attribution to another user

### Draft Management
- `draft.create` - Save page drafts
- `draft.view_own` - View your own drafts
- `draft.delete_own` - Delete your own drafts
- `draft.transfer` - Transfer drafts to other users

### File Attachments
- `attachment.upload` - Upload images and attachments
- `attachment.view` - View and download attachments
- `attachment.delete_own` - Delete attachments you uploaded
- `attachment.delete_any` - Delete any user's attachments

### Page Tags
- `tag.edit_difficulty` - Set difficulty tags on pages
- `tag.edit_custom` - Set custom tags on pages

### User Profiles
- `profile.view` - View public user profiles
- `profile.edit_own` - Edit your own profile page

### Chat & Messaging
- `chat.dm` - Send and receive direct messages
- `chat.group` - Join and participate in group chats
- `chat.create_group` - Create new group chats
- `chat.upload` - Upload files in chats

### Search & Navigation
- `search.pages` - Search wiki content
- `search.users` - Search for users

### Invite Codes
- `invite.generate` - Create invite codes for new users
- `invite.view` - View list of invite codes
- `invite.delete` - Delete unused invite codes

## Category Access Control

### Read Access
- Controls which categories a user can **view** pages in
- **Unrestricted**: User can view pages in all categories
- **Restricted**: User can only view pages in specifically allowed categories
- Uncategorized pages are not accessible when restricted

### Write Access (Editors only)
- Controls which categories an editor can **create/edit** pages in
- **Unrestricted**: Editor can edit pages in all categories
- **Restricted**: Editor can only edit pages in specifically allowed categories
- Any category an editor can write to is also automatically readable

## Admin Interface

### Accessing Permission Settings

1. Navigate to **Admin → Users** (`/admin/users`)
2. Find the user (editor or regular user) you want to configure
3. Click the **✏️ Permissions** button next to their name
4. Configure permissions and save

### Permission Configuration Page

The permission configuration page shows:

1. **Permission Categories** - All available permissions grouped by function
    - Check/uncheck individual permissions
    - Permissions auto-enable dependencies (e.g., enabling "View Deindexed Pages" auto-enables "View All Pages")
    - Regular users only see permissions that do not grant editor/admin capabilities

2. **Category Access - Read** - Configure which categories the user can view
   - **All categories**: Unrestricted read access
   - **Specific categories only**: Select allowed categories

3. **Category Access - Write** (Editors only) - Configure which categories the editor can edit
   - **All categories**: Unrestricted write access
   - **Specific categories only**: Select allowed categories

### Role Changes

When changing a user's role:

- **To Editor**: Default editor permissions (22 permissions) are automatically assigned
- **To User**: Default user permissions (11 permissions) are automatically assigned
- **To Admin**: All custom permissions are cleared (admins have all permissions)

The admin can then customize these defaults by clicking the **✏️ Permissions** button.

## Implementation Details

### Database Schema

Three new tables store permission data:

```sql
-- Individual permission grants
CREATE TABLE user_permissions (
    user_id         TEXT NOT NULL,
    permission_key  TEXT NOT NULL,
    UNIQUE(user_id, permission_key)
);

-- Category access restrictions (read/write)
CREATE TABLE user_category_access (
    user_id     TEXT NOT NULL,
    access_type TEXT NOT NULL CHECK(access_type IN ('read','write')),
    restricted  INTEGER NOT NULL DEFAULT 0,
    UNIQUE(user_id, access_type)
);

-- Allowed categories for restricted users
CREATE TABLE user_allowed_categories (
    user_id     TEXT NOT NULL,
    category_id INTEGER NOT NULL,
    access_type TEXT NOT NULL CHECK(access_type IN ('read','write')),
    UNIQUE(user_id, category_id, access_type)
);
```

### API Functions

**Permission Checking:**
```python
# Check if user has a specific permission
db.has_permission(user, "page.create")

# Check category read access
db.has_category_read_access(user, category_id)

# Check category write access
db.has_category_write_access(user, category_id)
```

**Permission Management:**
```python
# Get user's current permissions
perms = db.get_user_permissions(user_id)
# Returns: {
#   'enabled_permissions': set of keys,
#   'category_access': {'restricted': bool, 'allowed_category_ids': [...]},
#   'category_write_access': {'restricted': bool, 'allowed_category_ids': [...]}
# }

# Set user permissions
db.set_user_permissions(
    user_id,
    permission_keys=['page.view_all', 'page.create', ...],
    read_restricted=False,
    read_category_ids=[],
    write_restricted=True,
    write_category_ids=[1, 2, 3]
)

# Clear all permissions
db.clear_user_permissions(user_id)
```

**Default Permissions:**
```python
from helpers._permissions import get_default_permissions

# Get defaults for a role
editor_defaults = get_default_permissions('editor')  # Returns set of 22 permission keys
user_defaults = get_default_permissions('user')      # Returns set of 11 permission keys
```

### Helper Functions

```python
from helpers._auth import user_can_view_page, user_can_view_category

# Check if user can view a specific page (considers deindexed status and category access)
if user_can_view_page(user, page):
    # Show page

# Check if user can view pages in a category
if user_can_view_category(user, category_id):
    # Show category pages
```

## Backward Compatibility

The new permission system maintains compatibility with the old `editor_category_access` system:

- The old `editor_has_category_access()` function now uses the new permission system
- Existing editor category restrictions should be migrated to the new system
- The old editor access page (`/admin/users/<id>/editor-access`) is still available but deprecated

## Testing

Comprehensive tests are available in `tests/test_permissions.py`:

```bash
python -m pytest tests/test_permissions.py -v
```

Tests cover:
- Permission checking
- Category access restrictions (read/write)
- Role changes initializing permissions
- Admin UI functionality
- Page visibility based on permissions
- Independent read/write restrictions

## Migration Notes

For existing installations:

1. The new tables are created automatically on first run
2. Existing users have no custom permissions set initially
3. When an admin changes a user's role to editor/user, default permissions are automatically assigned
4. Old editor category restrictions still work but should be migrated to the new system
5. To migrate: Visit each editor's permission page and configure their access using the new UI

## Future Enhancements

Potential future improvements:

- Permission templates/presets for common user types
- Bulk permission updates for multiple users
- Permission inheritance or user groups
- Audit log for permission changes
- API endpoints for programmatic permission management
