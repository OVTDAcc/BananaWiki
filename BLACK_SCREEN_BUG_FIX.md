# Black Screen Bug Fix

## Problem Description

Users were experiencing a bug where pages would randomly become black and unreadable after reloading a page, even if they had never customized their accessibility settings. The only workaround was to reset the customization settings.

## Root Cause

The bug was located in `/app/static/js/main.js` in the `syncColorInputs()` function (lines 1399-1420).

### Technical Details

When a user who had never customized their account loaded a page:

1. The server sent accessibility preferences with empty strings for all custom colors (the defaults)
2. JavaScript `initAccessibility()` was called with these empty-string preferences
3. The `syncColorInputs()` function tried to read CSS variables to populate color input fields
4. If a CSS variable couldn't be resolved (returned an invalid value), the `_rgbToHex()` helper function returned `null`
5. **The bug**: When `hex` was `null`, the code skipped setting `entry.input.value`, leaving it at the browser's default value (typically `#000000` - black)
6. When the user triggered any accessibility setting save (e.g., by resizing the sidebar), the color input's stale black value would be saved
7. On the next page load, custom colors would be applied, turning the entire site black

## The Fix

Modified the `syncColorInputs()` function to always initialize color input fields with safe, appropriate default colors when the CSS variable cannot be resolved. This prevents the browser's default `#000000` value from being accidentally saved.

### Code Changes

File: `/app/static/js/main.js`

The function now:
1. First checks if the user has explicitly saved a color preference and uses it if available
2. Otherwise, tries to read the current computed color from CSS
3. If neither works (returns `null`), uses safe default colors appropriate for each color type:
   - Background: white (#ffffff)
   - Text: dark gray (#2d3748)
   - Primary: blue (#4299e1)
   - Secondary: gray (#4a5568)
   - Accent: orange (#ed8936)
   - Sidebar: light gray (#f7fafc)

## Manual Testing Instructions

### Test 1: Fresh User Without Customization

1. Create a new user account or use an account that has never customized accessibility settings
2. Log in and navigate to any wiki page
3. **Without opening the accessibility panel**, resize the sidebar by dragging the resize handle
4. Reload the page
5. **Expected**: Page should remain readable with normal colors
6. **Previously**: Page would sometimes turn completely black

### Test 2: CSS Variable Resolution Failure Simulation

1. Open browser DevTools → Console
2. Run the following to simulate unresolvable CSS variables:
   ```javascript
   document.documentElement.style.setProperty('--bg', 'var(--nonexistent)');
   document.documentElement.style.setProperty('--text', 'var(--nonexistent)');
   ```
3. Open the accessibility panel (customize button in topbar)
4. Check the color inputs - they should show safe default colors, NOT black (#000000)
5. Close the panel without saving
6. Reload the page
7. **Expected**: Page should remain readable
8. **Previously**: Color inputs might have black values that could be accidentally saved

### Test 3: Normal Customization Still Works

1. Open the accessibility panel
2. Change the background color to a light blue (#e3f2fd)
3. Change the text color to dark blue (#1565c0)
4. Close the panel (changes auto-save)
5. Reload the page
6. **Expected**: Your custom colors should be preserved and displayed correctly
7. Reset customizations using the "Reset All" button
8. **Expected**: Page returns to default colors

### Test 4: Color Reset Behavior

1. Customize one or more colors
2. Click the ✕ button next to a color to clear it
3. Reload the page
4. **Expected**: Cleared color reverts to site default, page remains readable
5. **Previously**: In some cases, cleared colors could revert to black on reload

## Related Files

- `/app/static/js/main.js` - Contains the fix (syncColorInputs function)
- `/app/templates/base.html` - Server-side color CSS injection
- `/routes/api.py` - Accessibility settings API endpoints
- `/db/_users.py` - Accessibility preferences storage and retrieval

## Testing Recommendations

Run the manual tests above, particularly Test 1 and Test 2, as these directly replicate the conditions that caused the black screen bug. Test 3 ensures that normal functionality isn't broken by the fix.
