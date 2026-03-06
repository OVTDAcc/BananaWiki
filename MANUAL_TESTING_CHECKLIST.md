# Manual Testing Checklist for Page Reservation System

This document provides step-by-step instructions for manually testing the page reservation feature.

## Prerequisites

1. BananaWiki running locally or on a test server
2. At least 2 user accounts with editor or admin role
3. At least 1 wiki page to test with

## Test Scenarios

### 1. Basic Reservation Flow

**Steps:**
1. Log in as User A (editor/admin)
2. Navigate to any wiki page
3. Look for the "Reserve this page for exclusive editing" checkbox
4. Check the checkbox
5. Verify you see a success message
6. Verify the page shows "You have reserved this page for editing"
7. Note the expiry time shown ("Expires in X hours")

**Expected Result:**
- Checkbox changes to reservation status display
- Shows your username and expiry time
- "Release Reservation" button appears

---

### 2. Blocking Other Users

**Steps:**
1. While logged in as User A with page reserved
2. In another browser/incognito window, log in as User B
3. Navigate to the same page
4. Observe the reservation status

**Expected Result:**
- User B sees: "Reserved by User A"
- User B sees the expiry time
- User B cannot see the reserve checkbox
- If User B tries to edit (`/page/slug/edit`), they should be redirected with an error message

---

### 3. Manual Release

**Steps:**
1. As User A (holding the reservation)
2. Click "Release Reservation" button
3. Confirm the dialog: "Are you sure you want to release your reservation?"
4. Click OK/Confirm

**Expected Result:**
- Reservation is released
- Page now shows the reserve checkbox again (disabled)
- Message shows "⏱ Cooldown: available in X hours"
- User A cannot re-check the checkbox (disabled)

---

### 4. Cooldown Period

**Steps:**
1. After releasing the reservation in Test 3
2. Try to check the "Reserve this page" checkbox
3. Observe the behavior

**Expected Result:**
- Checkbox is disabled (grayed out)
- Cooldown message shows: "⏱ Cooldown: available in X hours/days"
- Hovering over the disabled checkbox should show it's not clickable
- The cooldown should be 72 hours from the release time

---

### 5. Other User Can Reserve After Release

**Steps:**
1. After User A releases their reservation
2. As User B, navigate to the same page
3. Check the "Reserve this page" checkbox

**Expected Result:**
- User B successfully reserves the page
- User B sees "You have reserved this page for editing"
- User B can edit the page
- User A still sees the cooldown message for this page

---

### 6. No Cross-Page Cooldown

**Steps:**
1. While User A is in cooldown for Page 1
2. As User A, navigate to a different Page 2
3. Try to reserve Page 2

**Expected Result:**
- User A can successfully reserve Page 2
- The checkbox is enabled and clickable
- No cooldown message appears on Page 2
- Reservation succeeds without errors

---

### 7. Editing with Reservation

**Steps:**
1. As User A, reserve a page
2. Click "Edit" button or navigate to `/page/slug/edit`
3. Make some changes
4. Save the page

**Expected Result:**
- Edit page loads successfully
- Shows green notice: "🔒 You have reserved this page. Your reservation expires..."
- Changes save successfully
- Reservation remains active after saving

---

### 8. Editing Blocked for Others

**Steps:**
1. User A has page reserved
2. As User B, try to navigate to `/page/slug/edit`

**Expected Result:**
- User B is redirected back to the page view
- Error message: "Cannot edit: Page is reserved by User A"
- Edit form is not shown

---

### 9. Expiry After 48 Hours

**Note:** This test requires either waiting 48 hours or manipulating the database.

**Database Manipulation Method:**
```sql
UPDATE page_reservations
SET expires_at = datetime('now', '-1 hour')
WHERE page_id = <your_page_id>;
```

**Steps:**
1. Reserve a page as User A
2. Set the expiry to the past using SQL above
3. Refresh the page or navigate away and back
4. As User B, try to reserve the page

**Expected Result:**
- Page shows as unreserved
- User B can successfully reserve it
- User A sees cooldown message (because release was automatic)

---

### 10. Cooldown Expiry After 72 Hours

**Note:** This test requires either waiting 72 hours after a reservation release or manipulating the database.

**Database Manipulation Method:**
```sql
UPDATE user_page_cooldowns
SET cooldown_until = datetime('now', '-1 hour')
WHERE page_id = <your_page_id> AND user_id = '<user_a_id>';
```

**Steps:**
1. After User A has released a reservation and is in cooldown
2. Set the cooldown to expired using SQL above
3. As User A, refresh the page
4. Try to reserve the page again

**Expected Result:**
- Cooldown message disappears
- Checkbox becomes enabled
- User A can successfully reserve the page again

---

### 11. Permission Check

**Steps:**
1. Create a restricted category
2. Assign a page to that category
3. Set User A to be restricted to specific categories (not including this one)
4. As User A, try to reserve that page

**Expected Result:**
- API returns 403 Forbidden
- User A cannot reserve the page
- Error message about lacking category permissions

---

### 12. API Endpoint Testing

Using curl or Postman:

**Get Status:**
```bash
curl -H "Cookie: session=<your_session>" \
  http://localhost:5001/api/pages/3/reservation/status
```

**Reserve:**
```bash
curl -X POST -H "Cookie: session=<your_session>" \
  http://localhost:5001/api/pages/3/reservation
```

**Release:**
```bash
curl -X DELETE -H "Cookie: session=<your_session>" \
  http://localhost:5001/api/pages/3/reservation
```

**Expected Results:**
- Status returns JSON with `is_reserved`, `reserved_by`, etc.
- Reserve returns 200 OK with reservation data, or 409 Conflict if already reserved
- Release returns 200 OK, or 404 if no active reservation

---

## Completion Checklist

Mark each scenario as you test it:

- [ ] 1. Basic Reservation Flow
- [ ] 2. Blocking Other Users
- [ ] 3. Manual Release
- [ ] 4. Cooldown Period
- [ ] 5. Other User Can Reserve After Release
- [ ] 6. No Cross-Page Cooldown
- [ ] 7. Editing with Reservation
- [ ] 8. Editing Blocked for Others
- [ ] 9. Expiry After 48 Hours
- [ ] 10. Cooldown Expiry After 72 Hours
- [ ] 11. Permission Check
- [ ] 12. API Endpoint Testing

---

## Known Limitations

1. **No Background Job:** Expiry is checked on-demand (when pages are accessed), not via a background cron job
2. **Manual Cleanup:** Use `db.cleanup_expired_reservations()` if needed to clean up old entries
3. **Session-Based:** Uses Flask sessions for authentication (existing BananaWiki pattern)

---

## Troubleshooting

### Issue: Checkbox doesn't appear
- Verify you're logged in as an editor or admin
- Check that JavaScript is enabled
- Look for errors in browser console

### Issue: Reservation fails with "already reserved"
- Another user may have reserved it first
- Check the database: `SELECT * FROM page_reservations WHERE page_id=X;`

### Issue: Can't release reservation
- Verify you're the one who reserved it
- Check network tab for API errors
- Verify CSRF token is present

### Issue: Cooldown not working
- Check `user_page_cooldowns` table in database
- Verify timestamps are in the future
- Check that cooldown is page-specific (other pages should work)
