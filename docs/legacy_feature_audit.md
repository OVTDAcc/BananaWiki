# Legacy Feature Audit

This audit reviews a small set of older BananaWiki code paths against the current architecture, with a focus on auth, permissions, data access, and user-facing behavior.

## Reviewed features

| Feature | Files reviewed | Status |
| --- | --- | --- |
| Deindexed page direct view | `routes/wiki.py`, `helpers/_auth.py`, `tests/test_deindex.py` | Fixed |
| Deindexed page search visibility | `routes/api.py`, `db/_pages.py`, `tests/test_deindex.py` | Fixed |
| Legacy editor-category compatibility | `db/_permissions.py`, `db/_users.py`, `tests/test_feature_drift_fixes.py` | OK |
| Reservation-aware edit flows | `routes/wiki.py`, `tests/test_page_reservations.py`, `tests/test_feature_drift_fixes.py` | OK |

## Findings and changes

### 1. Deindexed page direct view
- **Issue found:** The older `/page/<slug>` route only checked category read access.
- **Why it drifted:** The route predates the current `user_can_view_page()` helper, which now represents the canonical page-visibility policy.
- **Changes made:** `routes/wiki.py` now delegates visibility checks to `user_can_view_page()`, and `helpers/_auth.py` now requires category access before the deindexed-page permission can grant access.
- **Remaining risk / edge case:** None identified beyond future permission-model changes; any new page-view route should reuse `user_can_view_page()`.

### 2. Deindexed page search visibility
- **Issue found:** Legacy search endpoints used role checks to decide whether deindexed pages should be queryable, which let editors see deindexed results even if that permission was removed and prevented regular users with the permission from finding them.
- **Why it drifted:** Search behavior was keyed to historic role assumptions instead of the current permission system.
- **Changes made:** `routes/api.py` now uses `db.has_permission(user, "page.view_deindexed")` to decide whether deindexed pages should be included in search candidates, and filters final results through `user_can_view_page()`.
- **Remaining risk / edge case:** Any future search endpoint should follow the same two-step pattern: fetch with permission-aware inclusion, then filter with `user_can_view_page()`.

### 3. Legacy editor-category compatibility
- **Issue found:** The older editor-category access helpers still exist alongside the newer unified permission system.
- **Why it did not break:** The current compatibility layer in `db/_permissions.py` continues to route write-access checks through shared helpers, and the existing regression tests still pass.
- **Changes made:** No code changes were necessary in this audit.
- **Remaining risk / edge case:** This area still deserves future cleanup if the project ever removes the legacy storage path entirely.

### 4. Reservation-aware edit flows
- **Issue found:** Reservation checks were reviewed because they were added later than many wiki routes and are a common source of drift.
- **Why it did not break:** Existing route helpers and regression tests still cover the current reservation flows.
- **Changes made:** No code changes were necessary in this audit.
- **Remaining risk / edge case:** Future mutating page routes should continue to reuse the existing reservation guards.
