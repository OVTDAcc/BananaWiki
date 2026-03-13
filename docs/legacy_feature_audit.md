# Legacy Feature Audit

This audit reviews a small set of older BananaWiki code paths against the current architecture, with a focus on auth, permissions, data access, and user-facing behavior.

## Reviewed features

| Feature | Files reviewed | Status |
| --- | --- | --- |
| Attachment download authorization | `routes/uploads.py`, `helpers/_auth.py`, `tests/test_missing_coverage.py` | Fixed |
| Session-limit logout cleanup | `routes/auth.py`, `app.py`, `tests/test_video_embedding_and_session_limit.py` | Fixed |
| Deindexed page direct view | `routes/wiki.py`, `helpers/_auth.py`, `tests/test_deindex.py` | Fixed |
| Deindexed page search visibility | `routes/api.py`, `db/_pages.py`, `tests/test_deindex.py` | Fixed |
| Draft deletion category access | `routes/api.py`, `tests/test_production.py` | Fixed |
| Legacy editor-category compatibility | `db/_permissions.py`, `db/_users.py`, `tests/test_feature_drift_fixes.py` | OK |
| Reservation-aware edit flows | `routes/wiki.py`, `tests/test_page_reservations.py`, `tests/test_feature_drift_fixes.py` | OK |
| Legacy chat cleanup fallback | `helpers/_time.py`, `routes/chat.py`, `routes/groups.py`, `tests/test_feature_drift_fixes.py`, `tests/test_chats.py`, `tests/test_group_chats.py` | Fixed |
| My drafts category filtering | `db/_drafts.py`, `routes/api.py`, `tests/test_production.py` | Fixed |
| Page history access controls | `routes/wiki.py`, `helpers/_auth.py`, `tests/test_feature_drift_fixes.py` | Fixed |
| Invite validation after admin suspension | `db/_invites.py`, `routes/auth.py`, `tests/test_production.py` | Fixed |

## Findings and changes

### 1. Attachment download authorization
- **Issue found:** Older attachment download routes only checked that the page and file existed.
- **Why it drifted:** These routes predated the shared `user_can_view_page()` helper and never adopted the newer visibility rules for restricted categories and deindexed pages.
- **Changes made:** `routes/uploads.py` now checks `user_can_view_page()` before serving single-file or bulk attachment downloads, and `tests/test_missing_coverage.py` now covers both restricted-category and deindexed-page regressions.
- **Remaining risk / edge case:** Any future attachment-serving route should reuse the same page-visibility guard instead of open-coding access checks.

### 2. Session-limit logout cleanup
- **Issue found:** The legacy logout flow cleared the browser session but left `users.session_token` populated in the database.
- **Why it drifted:** Logout was implemented before the single-session enforcement logic became the canonical session state model.
- **Changes made:** `routes/auth.py` now clears the stored token during logout, and `tests/test_video_embedding_and_session_limit.py` now verifies that the database token is removed when session limits are enabled.
- **Remaining risk / edge case:** Other admin-driven account state changes should continue to be reviewed whenever session-limit behavior evolves.

### 3. Deindexed page direct view
- **Issue found:** The older `/page/<slug>` route only checked category read access.
- **Why it drifted:** The route predates the current `user_can_view_page()` helper, which now represents the canonical page-visibility policy.
- **Changes made:** `routes/wiki.py` now delegates visibility checks to `user_can_view_page()`, and `helpers/_auth.py` now requires category access before the deindexed-page permission can grant access.
- **Remaining risk / edge case:** None identified beyond future permission-model changes; any new page-view route should reuse `user_can_view_page()`.

### 4. Deindexed page search visibility
- **Issue found:** Legacy search endpoints used role checks to decide whether deindexed pages should be queryable, which let editors see deindexed results even if that permission was removed and prevented regular users with the permission from finding them.
- **Why it drifted:** Search behavior was keyed to historic role assumptions instead of the current permission system.
- **Changes made:** `routes/api.py` now uses `db.has_permission(user, "page.view_deindexed")` to decide whether deindexed pages should be included in search candidates, and filters final results through `user_can_view_page()`.
- **Remaining risk / edge case:** Any future search endpoint should follow the same two-step pattern: fetch with permission-aware inclusion, then filter with `user_can_view_page()`.

### 5. Legacy editor-category compatibility
- **Issue found:** The older editor-category access helpers still exist alongside the newer unified permission system.
- **Why it did not break:** The current compatibility layer in `db/_permissions.py` continues to route write-access checks through shared helpers, and the existing regression tests still pass.
- **Changes made:** No code changes were necessary in this audit.
- **Remaining risk / edge case:** This area still deserves future cleanup if the project ever removes the legacy storage path entirely.

### 6. Draft deletion category access
- **Issue found:** The older `/api/draft/delete` endpoint deleted drafts after only validating `page_id`.
- **Why it drifted:** The route predated the shared `_get_editable_page_or_response()` compatibility helper, so it never adopted the newer category write-access checks that the other draft APIs already enforce.
- **Changes made:** `routes/api.py` now routes draft deletion through the same editable-page guard as save/load/other-drafts/transfer, and `tests/test_production.py` now verifies that restricted editors cannot delete drafts for pages in disallowed categories.
- **Remaining risk / edge case:** Future draft-related endpoints should continue to reuse `_get_editable_page_or_response()` so background AJAX flows cannot bypass edit restrictions.

### 7. Reservation-aware edit flows
- **Issue found:** Reservation checks were reviewed because they were added later than many wiki routes and are a common source of drift.
- **Why it did not break:** Existing route helpers and regression tests still cover the current reservation flows.
- **Changes made:** No code changes were necessary in this audit.
- **Remaining risk / edge case:** Future mutating page routes should continue to reuse the existing reservation guards.

### 8. Legacy chat cleanup fallback
- **Issue found:** The weekly chat cleanup scheduler and cleanup banners were reading only the newer DM/group cleanup columns, even though older installations may still rely on the original shared `chat_auto_clear_*` and retention settings.
- **Why it drifted:** Chat cleanup started as a single global configuration and was later split into DM-specific and group-specific settings. The runtime cleanup path was updated to use the new columns, but it stopped applying the documented compatibility fallback for historical databases whose newer columns still held migration defaults.
- **Changes made:** `helpers/_time.py` now resolves effective cleanup settings by preferring legacy values until the newer split settings have been explicitly saved, `routes/admin.py` marks the split cleanup settings as configured when admins save the modern controls, `routes/chat.py` and `routes/groups.py` now use those effective settings for scheduled cleanup and banner visibility, and regression coverage was added in `tests/test_feature_drift_fixes.py`, `tests/test_chats.py`, and `tests/test_group_chats.py`.
- **Remaining risk / edge case:** A future schema migration could make this even more explicit by copying legacy values into the split columns on upgrade and eventually retiring the fallback path once all historical installations have been migrated.

### 9. My drafts category filtering
- **Issue found:** The older `/api/draft/mine` listing endpoint returned every saved draft for an editor, even after newer category write restrictions removed access to some pages.
- **Why it drifted:** The endpoint predates the current category write-access model. The sibling draft save/load/delete/transfer routes were modernized to reuse shared edit guards, but the legacy listing route still serialized raw `list_user_drafts()` results.
- **Changes made:** `db/_drafts.py` now exposes each draft's page category in the joined metadata, `routes/api.py` filters `/api/draft/mine` through `editor_has_category_access()`, and `tests/test_production.py` now verifies that restricted editors only see drafts for categories they may still edit.
- **Remaining risk / edge case:** If the project ever needs to surface inaccessible drafts for recovery or admin review, that should happen through a dedicated admin-facing workflow instead of the user-facing editor draft list.

### 10. Page history access controls
- **Issue found:** The older page-history list/detail/revert routes only checked login or editor role and did not reuse the current page-visibility and category write-access guards.
- **Why it drifted:** Page history predates the shared `user_can_view_page()` and `editor_has_category_access()` helpers, so it kept legacy assumptions about who could inspect or revert a page's history.
- **Changes made:** `routes/wiki.py` now blocks history list/detail/revert access when the current user cannot view the page under the modern visibility rules, and `revert_page()` now reuses the same category write-access guard as the main edit route. `tests/test_feature_drift_fixes.py` adds regressions for restricted-category history access, deindexed history access, and permission-aware reverts.
- **Remaining risk / edge case:** Other page-mutation routes that predate deindexing should continue to be reviewed whenever visibility rules evolve so all direct slug-based workflows keep honoring the same shared helpers.

### 11. Invite validation after admin suspension
- **Issue found:** Legacy invite validation continued to accept an unused invite code even after the admin account that created it had been suspended or deleted.
- **Why it drifted:** Invite-code validation predates the newer admin suspension workflow, so the unauthenticated signup path kept treating invite codes as self-contained tokens instead of re-checking the creator's current account state.
- **Changes made:** `db/_invites.py` now joins the creator record during `validate_invite_code()` and rejects codes whose creator account is suspended or missing, while `tests/test_production.py` adds both direct validation regressions and signup-path regressions.
- **Remaining risk / edge case:** If the project ever wants suspension to revoke other pending artifacts (for example, active sessions or pre-generated exports), those flows should likewise re-check the actor's current account status instead of relying only on legacy token state.
