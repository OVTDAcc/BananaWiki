# Random ID Migration Guide

## Overview

This document describes the approach for migrating from sequential INTEGER AUTOINCREMENT IDs to random TEXT IDs for entities in BananaWiki.

## Current State

**Already Using Random IDs:**
- ✅ **Users**: Use random 8-character alphanumeric TEXT IDs (e.g., `abc12345`)
- ✅ **File Uploads**: Use UUID-based filenames for attachments and avatars

**Still Using Sequential INTEGER IDs:**
- ❌ **Groups** (`group_chats.id`)
- ❌ **Pages** (`pages.id`)
- ❌ **Categories** (`categories.id`)
- ❌ **Messages** (`group_messages.id`, `chat_messages.id`)
- ❌ **Attachments** (`group_attachments.id`, `chat_attachments.id`)
- ❌ **Page History** (`page_history.id`)
- ❌ **Drafts** (`drafts.id`)
- ❌ **Announcements** (`announcements.id`)
- ❌ **Invite Codes** (`invite_codes.id`)

## Why Random IDs?

**Benefits:**
1. **Privacy**: Can't enumerate all entities by incrementing IDs
2. **Security**: Harder to guess entity counts or creation patterns
3. **Better UX**: More professional-looking URLs (`/groups/xj3k9m2p` vs `/groups/1`)

**Current Issues with Sequential IDs:**
- Users can guess total number of groups/pages by looking at ID
- Can try incrementing URLs to discover content
- Reveals information about creation order and timing

## Implementation Strategy

### Phase 1: Foundation (✅ COMPLETED)

1. Create `generate_random_id(length=12)` function in `db/_users.py`
2. Export function from `db/__init__.py` for use throughout codebase
3. Document the function with comprehensive notes

**Code Location:**
- `db/_users.py:20-49` - `generate_random_id()` function
- `db/__init__.py:17` - Export for use in other modules

### Phase 2: New Entity Types (Future Work)

Migrate entity types one at a time to minimize risk. Suggested order:

1. **Groups** (`group_chats`) - Medium complexity
   - Change `id` from INTEGER to TEXT PRIMARY KEY
   - Update all foreign keys: `group_members.group_id`, `group_messages.group_id`, `group_attachments.message_id`
   - Change route parameters: `<int:group_id>` → `<string:group_id>`
   - Update all SQL queries to handle TEXT IDs
   - Add collision detection (retry on duplicate)

2. **Announcements** (`announcements`) - Low complexity
   - Least foreign key dependencies
   - Good test case for migration process

3. **Categories** (`categories`) - Medium complexity
   - Self-referential foreign key: `parent_id`
   - Used in pages: `pages.category_id`

4. **Pages** (`pages`) - High complexity
   - Many foreign keys: `page_history.page_id`, `drafts.page_id`, etc.
   - Core functionality - requires extensive testing

5. **Messages & Attachments** - Low priority
   - High volume, less security sensitive
   - Consider keeping sequential for performance

### Phase 3: Migration for Existing Installations (Future Work)

Create a migration script that:
1. Backs up the database
2. Creates new tables with TEXT PRIMARY KEYs
3. Generates random IDs for existing entities
4. Migrates data preserving relationships
5. Updates foreign keys
6. Validates data integrity
7. Swaps tables

**Example migration for groups:**

```python
def migrate_groups_to_random_ids():
    """Migrate group_chats from INTEGER to TEXT IDs."""
    import db

    # 1. Create new table with TEXT id
    # 2. Generate random ID for each existing group
    # 3. Create mapping: old_id -> new_id
    # 4. Migrate group_chats data
    # 5. Update group_members.group_id using mapping
    # 6. Update group_messages.group_id using mapping
    # 7. Drop old tables
    # 8. Rename new tables
    # 9. Verify integrity
```

## Technical Considerations

### Database Schema Changes

**Before (Sequential):**
```sql
CREATE TABLE group_chats (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    ...
);
```

**After (Random):**
```sql
CREATE TABLE group_chats (
    id          TEXT    PRIMARY KEY,
    name        TEXT    NOT NULL,
    ...
);
```

### Route Parameter Changes

**Before:**
```python
@app.route("/groups/<int:group_id>/view")
def group_view(group_id):
    # group_id is an integer
```

**After:**
```python
@app.route("/groups/<string:group_id>/view")
def group_view(group_id):
    # group_id is a string, validate format
```

### Collision Detection

When generating random IDs, always check for collisions:

```python
def create_group_with_random_id(name, creator_id):
    conn = get_db()
    # Generate unique ID
    group_id = generate_random_id(12)
    while conn.execute("SELECT 1 FROM group_chats WHERE id=?", (group_id,)).fetchone():
        group_id = generate_random_id(12)

    # Insert with generated ID
    conn.execute(
        "INSERT INTO group_chats (id, name, creator_id) VALUES (?, ?, ?)",
        (group_id, name, creator_id)
    )
```

### Testing Requirements

For each entity type migrated:
1. ✅ Unit tests for ID generation and collision detection
2. ✅ Integration tests for CRUD operations
3. ✅ Foreign key relationship tests
4. ✅ Route parameter validation tests
5. ✅ Migration script tests (idempotency, rollback)
6. ✅ Performance tests (TEXT vs INTEGER lookup)

## Rollout Plan

1. **Development**: Implement on feature branch
2. **Testing**: Extensive testing on test installations
3. **Beta**: Deploy to willing beta testers
4. **Migration Script**: Test on copies of production databases
5. **Documentation**: Update all docs referencing IDs
6. **Release**: Include in major version (breaking change)

## Breaking Changes

⚠️ **This is a breaking change** that affects:
- Database schema
- API contracts
- URL structure
- Backup/restore procedures
- Any external integrations

Requires **major version bump** (e.g., 2.0.0 → 3.0.0).

## Performance Considerations

**INTEGER vs TEXT Primary Keys:**
- INTEGER: Faster comparisons, smaller storage, better indexing
- TEXT: Slightly slower, larger storage, still performant with proper indexing

**Mitigation:**
- Keep TEXT IDs short (12 characters)
- Add database indexes on foreign key columns
- Use SQLite's built-in TEXT indexing

**Benchmarks needed:**
- Compare SELECT performance: INTEGER vs TEXT
- Compare JOIN performance with TEXT foreign keys
- Test with realistic data volumes (1000+ entities)

## Current Status

- ✅ **Phase 1 Complete**: Foundation laid with `generate_random_id()` function
- ⏳ **Phase 2 Pending**: Entity-by-entity migration (future work)
- ⏳ **Phase 3 Pending**: Migration script for existing installations

## Next Steps

1. Get community feedback on migration approach
2. Prioritize which entities to migrate first
3. Create detailed migration plan for each entity type
4. Implement comprehensive test suite
5. Create migration script with rollback capability
6. Schedule for major version release

## References

- `db/_users.py:20-49` - `generate_random_id()` implementation
- `db/_schema.py:408-527` - Example of previous ID type migration (users INT→TEXT)
- `db/__init__.py:17` - Exported function for use throughout codebase

## Contact

For questions or discussion about this migration, please open an issue on GitHub.
