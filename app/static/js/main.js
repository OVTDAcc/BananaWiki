/* BananaWiki – Main JS */

// CSRF token helper
function getCsrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
}

// In-site confirmation dialog
var _bwConfirmCallback = null;

function bwConfirm(message, callback) {
    var modal = document.getElementById('bw-confirm-modal');
    var msgEl = document.getElementById('bw-confirm-message');
    if (!modal || !msgEl) {
        if (callback && window.confirm(message)) callback();
        return;
    }
    msgEl.textContent = message;
    _bwConfirmCallback = callback || null;
    modal.style.display = 'flex';
    var okBtn = document.getElementById('bw-confirm-ok');
    if (okBtn) okBtn.focus();
}

function initConfirmModal() {
    var modal = document.getElementById('bw-confirm-modal');
    if (!modal) return;
    document.getElementById('bw-confirm-ok').addEventListener('click', function() {
        modal.style.display = 'none';
        var cb = _bwConfirmCallback;
        _bwConfirmCallback = null;
        if (cb) cb();
    });
    document.getElementById('bw-confirm-cancel').addEventListener('click', function() {
        modal.style.display = 'none';
        _bwConfirmCallback = null;
    });
    modal.addEventListener('click', function(e) {
        if (e.target === modal) {
            modal.style.display = 'none';
            _bwConfirmCallback = null;
        }
    });
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && modal.style.display !== 'none') {
            modal.style.display = 'none';
            _bwConfirmCallback = null;
        }
    });
    // Intercept submits on forms with data-confirm attribute
    document.addEventListener('submit', function(e) {
        var form = e.target;
        var msg = form.getAttribute('data-confirm');
        if (!msg) return;
        e.preventDefault();
        bwConfirm(msg, function() {
            form.removeAttribute('data-confirm');
            form.submit();
        });
    }, true);
}

// Flash message close buttons (no auto-dismiss)
function initFlashMessages() {
    document.querySelectorAll('.flash').forEach(function(el) {
        var closeBtn = el.querySelector('.flash-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', function() {
                el.remove();
            });
        }
    });
}

// Page title scroll animation – shows page title in topbar when scrolling
function initPageTitleScroll() {
    var contentEl = document.querySelector('.content');
    var pageH1 = document.querySelector('.page-header h1');
    var topbarTitle = document.getElementById('topbar-page-title');
    if (!contentEl || !pageH1 || !topbarTitle) return;
    topbarTitle.textContent = pageH1.textContent;
    var topbarThreshold = 50; // approx topbar height in px
    var ticking = false;
    contentEl.addEventListener('scroll', function() {
        if (!ticking) {
            requestAnimationFrame(function() {
                var rect = pageH1.getBoundingClientRect();
                if (rect.bottom < topbarThreshold) {
                    topbarTitle.classList.add('visible');
                } else {
                    topbarTitle.classList.remove('visible');
                }
                ticking = false;
            });
            ticking = true;
        }
    });
}

document.addEventListener('DOMContentLoaded', function() {
    initFlashMessages();
    initPageTitleScroll();
    initConfirmModal();

    // Sidebar toggle for mobile
    var toggleBtn = document.getElementById('sidebar-toggle');
    var sidebar = document.getElementById('sidebar');
    var overlay = document.getElementById('sidebar-overlay');

    // Helper to get the first focusable element inside a container
    function getFirstFocusableElement(container) {
        if (!container) return null;
        return container.querySelector(
            'a[href], button:not([disabled]), textarea:not([disabled]), ' +
            'input:not([disabled]), select:not([disabled]), ' +
            '[tabindex]:not([tabindex="-1"])'
        );
    }

    var lastFocusedElementBeforeSidebar = null;

    if (toggleBtn && sidebar) {
        toggleBtn.addEventListener('click', function() {
            // Remember what was focused before toggling
            if (!sidebar.classList.contains('open')) {
                lastFocusedElementBeforeSidebar = document.activeElement;
            }

            sidebar.classList.toggle('open');
            var isOpen = sidebar.classList.contains('open');

            if (overlay) {
                overlay.classList.toggle('active', isOpen);
            }

            if (isOpen) {
                // Move focus into the sidebar
                var focusTarget = getFirstFocusableElement(sidebar) || sidebar;
                if (focusTarget === sidebar && !focusTarget.hasAttribute('tabindex')) {
                    focusTarget.setAttribute('tabindex', '-1');
                }
                if (typeof focusTarget.focus === 'function') {
                    focusTarget.focus();
                }
            } else {
                // Restore focus to the element that opened the sidebar
                var toFocus = lastFocusedElementBeforeSidebar || toggleBtn;
                if (toFocus && typeof toFocus.focus === 'function') {
                    toFocus.focus();
                }
            }
        });
        if (overlay) {
            overlay.addEventListener('click', function() {
                // Close sidebar and overlay
                sidebar.classList.remove('open');
                overlay.classList.remove('active');
                // Return focus to the toggle button
                if (toggleBtn && typeof toggleBtn.focus === 'function') {
                    toggleBtn.focus();
                }
            });
        }
    }

    // Sidebar resize handle
    var resizeHandle = document.getElementById('sidebar-resize-handle');
    if (resizeHandle && sidebar) {
        var isResizing = false;
        resizeHandle.addEventListener('mousedown', function(e) {
            isResizing = true;
            resizeHandle.classList.add('resizing');
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
            e.preventDefault();
        });
        document.addEventListener('mousemove', function(e) {
            if (!isResizing) return;
            var newWidth = e.clientX;
            if (newWidth >= 180 && newWidth <= 500) {
                sidebar.style.width = newWidth + 'px';
                sidebar.style.minWidth = newWidth + 'px';
            }
        });
        document.addEventListener('mouseup', function() {
            if (isResizing) {
                isResizing = false;
                resizeHandle.classList.remove('resizing');
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
                // Save the new sidebar width as an accessibility preference
                var w = parseInt(sidebar.style.width, 10);
                if (w >= 180 && w <= 500) {
                    saveA11ySetting('sidebar_width', w);
                }
            }
        });
    }
});

// Autosave for editor
function initAutosave(pageId) {
    var titleEl = document.getElementById('edit-title');
    var contentEl = document.getElementById('edit-content');
    if (!titleEl || !contentEl) return;

    var saveTimer = null;
    var saving = false;
    var disabled = false;

    function setIndicator(state) {
        var indicator = document.getElementById('save-indicator');
        if (!indicator) return;
        indicator.className = 'save-indicator save-indicator-' + state;
        if (state === 'syncing') {
            indicator.textContent = 'Syncing\u2026';
        } else if (state === 'saved') {
            indicator.textContent = 'All changes saved';
        } else if (state === 'error') {
            indicator.textContent = 'Error saving';
        } else {
            indicator.textContent = '';
        }
    }

    var pendingCallback = null;

    function doSave(callback) {
        if (disabled) return;
        if (saving) {
            // If a save is already in progress, queue callback for when it finishes
            if (callback) pendingCallback = callback;
            return;
        }
        saving = true;
        setIndicator('syncing');
        fetch('/api/draft/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify({
                page_id: pageId,
                title: titleEl.value,
                content: contentEl.value
            })
        }).then(function(r) {
            if (!r.ok) throw new Error('Save failed');
            return r.json();
        }).then(function(d) {
            saving = false;
            if (!disabled) setIndicator('saved');
            if (callback) callback(true);
            if (pendingCallback) { var cb = pendingCallback; pendingCallback = null; doSave(cb); }
        }).catch(function(err) {
            saving = false;
            if (!disabled) setIndicator('error');
            if (callback) callback(false);
            if (pendingCallback) { var cb = pendingCallback; pendingCallback = null; cb(false); }
        });
    }

    function scheduleSave() {
        if (disabled) return;
        if (saveTimer) clearTimeout(saveTimer);
        saveTimer = setTimeout(doSave, 1500);
    }

    function stopAutosave() {
        disabled = true;
        if (saveTimer) { clearTimeout(saveTimer); saveTimer = null; }
        setIndicator('');
    }

    // Save Draft & Close button
    var saveDraftCloseBtn = document.getElementById('save-draft-close');
    if (saveDraftCloseBtn) {
        saveDraftCloseBtn.addEventListener('click', function() {
            if (saveTimer) clearTimeout(saveTimer);
            doSave(function(ok) {
                if (ok) {
                    var redirectUrl = saveDraftCloseBtn.dataset.redirect || '/';
                    window.location.href = redirectUrl;
                } else {
                    alert('Failed to save draft. Please try again.');
                }
            });
        });
    }

    titleEl.addEventListener('input', scheduleSave);
    contentEl.addEventListener('input', scheduleSave);

    // Expose stop function for draft deletion
    window._bwStopAutosave = stopAutosave;

    // Check for other drafts and page staleness periodically
    var pageLoadedAt = new Date().toISOString();
    setInterval(function() {
        fetch('/api/draft/others/' + pageId)
            .then(function(r) {
                if (!r.ok) throw new Error('Failed to check drafts');
                return r.json();
            })
            .then(function(resp) {
                var drafts = resp.drafts || [];
                var notice = document.getElementById('other-drafts-notice');
                if (notice && drafts.length > 0) {
                    notice.innerHTML = '';
                    notice.appendChild(document.createTextNode('Warning: Other users editing this page: '));
                    drafts.forEach(function(d, idx) {
                        if (idx > 0) notice.appendChild(document.createTextNode(', '));
                        notice.appendChild(document.createTextNode(d.username));
                    });
                    drafts.forEach(function(d) {
                        notice.appendChild(document.createTextNode(' '));
                        var btn = document.createElement('button');
                        btn.className = 'btn btn-sm';
                        btn.textContent = "Transfer " + d.username + "'s draft";
                        btn.addEventListener('click', function() {
                            transferDraft(pageId, d.user_id);
                        });
                        notice.appendChild(btn);
                    });
                    notice.style.display = 'block';
                }
                // Stale draft detection: page was updated after we opened the editor
                var staleNotice = document.getElementById('stale-draft-notice');
                if (staleNotice && resp.page_last_edited_at) {
                    if (!staleNotice.dataset.shown && resp.page_last_edited_at > pageLoadedAt) {
                        staleNotice.style.display = 'block';
                        staleNotice.dataset.shown = '1';
                    }
                }
            })
            .catch(function() { /* silently ignore polling errors */ });
    }, 10000);
}

function transferDraft(pageId, fromUserId) {
    bwConfirm('Transfer this draft to your account? Your current draft will be replaced.', function() {
    fetch('/api/draft/transfer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        body: JSON.stringify({ page_id: pageId, from_user_id: fromUserId })
    }).then(function(r) {
        if (!r.ok) throw new Error('Transfer failed');
        return r.json();
    }).then(function() {
        location.reload();
    }).catch(function() {
        alert('Failed to transfer draft.');
    });
    });
}

function deleteDraft(pageId) {
    // Stop autosave to prevent re-saving the draft
    if (window._bwStopAutosave) window._bwStopAutosave();
    fetch('/api/draft/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        body: JSON.stringify({ page_id: pageId })
    }).then(function(r) {
        if (!r.ok) throw new Error('Delete failed');
        return r.json();
    }).then(function() {
        location.reload();
    }).catch(function() {
        alert('Failed to delete draft.');
    });
}

function discardDraftAndClose(pageId, redirectUrl) {
    bwConfirm('Discard this draft? All unsaved changes will be lost.', function() {
    if (window._bwStopAutosave) window._bwStopAutosave();
    fetch('/api/draft/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        body: JSON.stringify({ page_id: pageId })
    }).then(function(r) {
        if (!r.ok) throw new Error('Delete failed');
        return r.json();
    }).then(function() {
        window.location.href = redirectUrl;
    }).catch(function() {
        alert('Failed to discard draft.');
    });
    });
}

function initDraftManager() {
    var container = document.getElementById('draft-manager-list');
    if (!container) return;
    fetch('/api/draft/mine')
        .then(function(r) { return r.json(); })
        .then(function(drafts) {
            if (!drafts.length) {
                container.innerHTML = '<p style="opacity:.7;font-size:.9rem">No pending drafts.</p>';
                return;
            }
            var html = '<table class="draft-manager-table"><thead><tr><th>Page</th><th>Last saved</th><th>Actions</th></tr></thead><tbody>';
            drafts.forEach(function(d) {
                var editUrl = '/page/' + d.page_slug + '/edit';
                html += '<tr data-page-id="' + d.page_id + '">'
                    + '<td>' + escapeHtml(d.page_title) + '</td>'
                    + '<td style="white-space:nowrap;font-size:.85rem;opacity:.7">' + escapeHtml(d.updated_at_formatted || d.updated_at) + '</td>'
                    + '<td style="white-space:nowrap">'
                    + '<a href="' + editUrl + '" class="btn btn-sm" style="margin-right:.4rem">Continue editing</a>'
                    + '<button class="btn btn-sm btn-outline btn-danger-outline" onclick="discardDraftFromSettings(' + d.page_id + ', this)">Discard</button>'
                    + '</td>'
                    + '</tr>';
            });
            html += '</tbody></table>';
            container.innerHTML = html;
        })
        .catch(function() {
            container.innerHTML = '<p style="opacity:.7;font-size:.9rem">Could not load drafts.</p>';
        });
}

function discardDraftFromSettings(pageId, btn) {
    bwConfirm('Discard this draft? This cannot be undone.', function() {
    btn.disabled = true;
    fetch('/api/draft/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        body: JSON.stringify({ page_id: pageId })
    }).then(function(r) {
        if (!r.ok) throw new Error('Delete failed');
        return r.json();
    }).then(function() {
        var row = btn.closest('tr');
        if (row) row.remove();
        var tbody = document.querySelector('#draft-manager-list tbody');
        if (tbody && tbody.querySelectorAll('tr').length === 0) {
            document.getElementById('draft-manager-list').innerHTML =
                '<p style="opacity:.7;font-size:.9rem">No pending drafts.</p>';
        }
    }).catch(function() {
        btn.disabled = false;
        alert('Failed to discard draft.');
    });
    });
}

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

// Image upload via drag & drop or file input
function initImageUpload(contentEl) {
    if (!contentEl) return;

    var dropZone = document.getElementById('drop-zone');

    function uploadFile(file) {
        var fd = new FormData();
        fd.append('file', file);
        fd.append('csrf_token', getCsrfToken());
        return fetch('/api/upload', { method: 'POST', body: fd })
            .then(function(r) { return r.json().then(function(data) { return { ok: r.ok, data: data }; }); })
            .then(function(result) {
                if (!result.ok || result.data.error) {
                    alert('Upload failed: ' + (result.data.error || 'Unknown error'));
                    return result.data;
                }
                if (result.data.url) {
                    var pos = contentEl.selectionStart || contentEl.value.length;
                    var md = '\n![' + file.name + '](' + result.data.url + ')\n';
                    contentEl.value = contentEl.value.substring(0, pos) + md + contentEl.value.substring(pos);
                    contentEl.dispatchEvent(new Event('input'));
                }
                return result.data;
            })
            .catch(function(err) {
                console.error('Upload error:', err);
                alert('Upload failed: could not reach server.');
            });
    }

    // Drop zone
    if (dropZone) {
        dropZone.addEventListener('dragover', function(e) {
            e.preventDefault();
            dropZone.classList.add('drag-over');
        });
        dropZone.addEventListener('dragleave', function() {
            dropZone.classList.remove('drag-over');
        });
        dropZone.addEventListener('drop', function(e) {
            e.preventDefault();
            dropZone.classList.remove('drag-over');
            Array.from(e.dataTransfer.files).forEach(uploadFile);
        });
    }

    // Also handle drop on textarea
    contentEl.addEventListener('dragover', function(e) { e.preventDefault(); });
    contentEl.addEventListener('drop', function(e) {
        e.preventDefault();
        Array.from(e.dataTransfer.files).forEach(uploadFile);
    });

    // Attach button
    var attachBtn = document.getElementById('attach-btn');
    var fileInput = document.getElementById('file-input');
    if (attachBtn && fileInput) {
        attachBtn.addEventListener('click', function() { fileInput.click(); });
        fileInput.addEventListener('change', function() {
            Array.from(fileInput.files).forEach(uploadFile);
            fileInput.value = '';
        });
    }
}

// Open category manage modal by moving it to body (escapes sidebar overflow)
function openCatModal(id) {
    var modal = document.getElementById(id);
    if (!modal) return;
    if (!modal._bwOrigParent) modal._bwOrigParent = modal.parentNode;
    document.body.appendChild(modal);
    modal.style.display = 'flex';
}

// Close category manage modal and return it to its original location
function closeCatModal(btn) {
    var modal = btn.closest('.modal');
    if (!modal) return;
    modal.style.display = 'none';
    if (modal._bwOrigParent) modal._bwOrigParent.appendChild(modal);
}

// Category delete confirmation
function confirmCatDelete(form, pageCount, catName) {
    var action = form.querySelector('.cat-page-action').value;
    var msg = 'Delete category "' + catName + '"?';
    if (pageCount > 0) {
        if (action === 'delete') {
            msg += '\n\nThis will PERMANENTLY DELETE ' + pageCount + ' page(s) in this category!';
        } else if (action === 'move') {
            var sel = form.querySelector('.cat-move-target');
            var targetName = sel && sel.value ? sel.options[sel.selectedIndex].text : '';
            if (!sel || !sel.value) {
                alert('Please select a target category to move pages to.');
                return false;
            }
            msg += '\n\n' + pageCount + ' page(s) will be moved to "' + targetName + '".';
        } else {
            msg += '\n\n' + pageCount + ' page(s) will become uncategorized.';
        }
    }
    bwConfirm(msg, function() { form.submit(); });
    return false;
}


// ---------------------------------------------------------------------------
//  Announcements bar
// ---------------------------------------------------------------------------
function initAnnouncements() {
    var bar = document.getElementById('announcements-bar');
    if (!bar) return;

    var allSlides = Array.from(bar.querySelectorAll('.announcement-slide'));
    if (!allSlides.length) return;

    // Filter out session-dismissed announcements
    var dismissed = [];
    try {
        dismissed = JSON.parse(sessionStorage.getItem('dismissed_announcements') || '[]');
    } catch (e) { dismissed = []; }

    var slides = allSlides.filter(function(s) {
        return dismissed.indexOf(parseInt(s.dataset.annId, 10)) === -1;
    });

    if (!slides.length) return;

    bar.style.display = 'block';
    var current = 0;

    function showSlide(idx) {
        slides.forEach(function(s) { s.style.display = 'none'; });
        if (!slides.length) { bar.style.display = 'none'; return; }
        slides[idx].style.display = 'block';
        // Update nav visibility and counter in the active slide
        var slide = slides[idx];
        var prev = slide.querySelector('.ann-prev');
        var next = slide.querySelector('.ann-next');
        var counter = slide.querySelector('.ann-counter');
        var cur = slide.querySelector('.ann-current');
        var hasMany = slides.length > 1;
        if (prev) prev.style.display = hasMany ? '' : 'none';
        if (next) next.style.display = hasMany ? '' : 'none';
        if (counter) counter.style.display = hasMany ? '' : 'none';
        if (cur) cur.textContent = (idx + 1) + ' / ' + slides.length;
    }

    showSlide(0);

    bar.addEventListener('click', function(e) {
        var target = e.target;
        if (target.classList.contains('ann-prev')) {
            current = (current - 1 + slides.length) % slides.length;
            showSlide(current);
        } else if (target.classList.contains('ann-next')) {
            current = (current + 1) % slides.length;
            showSlide(current);
        } else if (target.classList.contains('ann-close')) {
            var id = parseInt(target.dataset.annId, 10);
            dismissed.push(id);
            try { sessionStorage.setItem('dismissed_announcements', JSON.stringify(dismissed)); } catch (e) {}
            slides = slides.filter(function(s) {
                return parseInt(s.dataset.annId, 10) !== id;
            });
            if (!slides.length) { bar.style.display = 'none'; return; }
            if (current >= slides.length) current = slides.length - 1;
            showSlide(current);
        }
    });
}

// ---------------------------------------------------------------------------
//  Easter egg – Konami code → falling bananas
// ---------------------------------------------------------------------------
(function () {
    var KONAMI = [38, 38, 40, 40, 37, 39, 37, 39, 66, 65]; // ↑↑↓↓←→←→BA
    var pos = 0;

    function launchBananas() {
        var count = 30;
        for (var i = 0; i < count; i++) {
            (function (delay) {
                setTimeout(function () {
                    var el = document.createElement('div');
                    el.className = 'banana-drop';
                    el.textContent = '🍌';
                    el.style.left = (Math.random() * 98) + 'vw';
                    el.style.animationDuration = (1.5 + Math.random() * 2) + 's';
                    el.style.fontSize = (1.2 + Math.random() * 1.5) + 'rem';
                    document.body.appendChild(el);
                    el.addEventListener('animationend', function () {
                        el.parentNode && el.parentNode.removeChild(el);
                    });
                }, delay);
            })(i * 80);
        }

        // Notify the backend (fire-and-forget, best effort), then navigate to easter egg page
        var csrfMeta = document.querySelector('meta[name="csrf-token"]');
        var csrf = csrfMeta ? csrfMeta.getAttribute('content') : '';
        fetch('/api/easter-egg/trigger', {
            method: 'POST',
            headers: { 'X-CSRFToken': csrf, 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: '{}',
        }).catch(function () {});
        // Navigate to the easter egg page after the animation finishes
        setTimeout(function () { window.location.href = '/easter-egg'; }, (30 * 80) + 2500);
    }

    document.addEventListener('keydown', function (e) {
        if (e.keyCode === KONAMI[pos]) {
            pos++;
            if (pos === KONAMI.length) {
                pos = 0;
                launchBananas();
            }
        } else {
            pos = (e.keyCode === KONAMI[0]) ? 1 : 0;
        }
    });
}());

document.addEventListener('DOMContentLoaded', initAnnouncements);

// ---------------------------------------------------------------------------
// Sidebar reorder (up/down arrows for pages and categories)
// ---------------------------------------------------------------------------
(function initReorder() {
    function postReorder(url, ids) {
        return fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            credentials: 'same-origin',
            body: JSON.stringify({ ids: ids }),
        }).then(function(r) { if (!r.ok) throw new Error('reorder failed'); });
    }

    function siblingsOf(el, selector) {
        return Array.from(el.parentNode.children).filter(function(c) {
            return c.matches(selector);
        });
    }

    document.addEventListener('click', function(e) {
        var btn = e.target.closest('.reorder-btn');
        if (!btn) return;
        e.preventDefault();

        var dir = btn.dataset.dir;
        var type = btn.dataset.type;
        var id = parseInt(btn.dataset.id, 10);

        if (type === 'page') {
            var row = btn.closest('.nav-item-row');
            if (!row) return;
            var siblings = siblingsOf(row, '.nav-item-row');
            var idx = siblings.indexOf(row);
            var swapIdx = dir === 'up' ? idx - 1 : idx + 1;
            if (swapIdx < 0 || swapIdx >= siblings.length) return;
            var pageTitleEl = row.querySelector('.nav-item');
            var pageTitle = pageTitleEl ? pageTitleEl.textContent.trim() : 'this page';
            bwConfirm('Are you sure you want to move "' + pageTitle + '" ' + dir + '?', function() {
            // Swap in DOM
            if (dir === 'up') {
                row.parentNode.insertBefore(row, siblings[swapIdx]);
            } else {
                row.parentNode.insertBefore(siblings[swapIdx], row);
            }
            // Collect new order (all page rows in the same container)
            var container = row.parentNode;
            var ids = Array.from(container.querySelectorAll(':scope > .nav-item-row')).map(function(r) {
                return parseInt(r.dataset.pageId, 10);
            });
            postReorder('/api/reorder/pages', ids).catch(function() {});
            });

        } else if (type === 'category') {
            var section = btn.closest('.nav-section');
            if (!section) return;
            var siblings = siblingsOf(section, '.nav-section[data-cat-id]');
            var idx = siblings.indexOf(section);
            var swapIdx = dir === 'up' ? idx - 1 : idx + 1;
            if (swapIdx < 0 || swapIdx >= siblings.length) return;
            var catNameEl = section.querySelector('.nav-section-title');
            var catName = catNameEl ? catNameEl.textContent.trim() : 'this category';
            bwConfirm('Are you sure you want to move "' + catName + '" ' + dir + '?', function() {
            if (dir === 'up') {
                section.parentNode.insertBefore(section, siblings[swapIdx]);
            } else {
                section.parentNode.insertBefore(siblings[swapIdx], section);
            }
            var ids = Array.from(section.parentNode.querySelectorAll(':scope > .nav-section[data-cat-id]')).map(function(s) {
                return parseInt(s.dataset.catId, 10);
            });
            postReorder('/api/reorder/categories', ids).catch(function() {});
            });
        }
    });
}());

// ---------------------------------------------------------------------------
//  Accessibility panel
// ---------------------------------------------------------------------------

// Current in-memory preferences (set via initAccessibility)
var _a11yPrefs = {};
var _a11ySaveTimer = null;

function saveA11ySetting(key, value) {
    _a11yPrefs[key] = value;
    if (_a11ySaveTimer) clearTimeout(_a11ySaveTimer);
    _a11ySaveTimer = setTimeout(function() {
        fetch('/api/accessibility', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify(_a11yPrefs)
        }).catch(function() {});
    }, 600);
}

function applyA11yPrefs(prefs) {
    // Font scale
    var scale = prefs.font_scale || 1.0;
    document.documentElement.style.setProperty('--a11y-font-scale', scale);

    // Contrast: remove old classes and set new one
    for (var i = 0; i <= 5; i++) {
        document.body.classList.remove('a11y-contrast-' + i);
    }
    if (prefs.contrast > 0) {
        document.body.classList.add('a11y-contrast-' + prefs.contrast);
    }

    // Sidebar width
    var sidebar = document.getElementById('sidebar');
    if (sidebar && prefs.sidebar_width && prefs.sidebar_width >= 180 && prefs.sidebar_width <= 500) {
        sidebar.style.width = prefs.sidebar_width + 'px';
        sidebar.style.minWidth = prefs.sidebar_width + 'px';
    }

    // Custom CSS colors
    var root = document.documentElement;
    if (prefs.custom_bg) {
        root.style.setProperty('--bg', prefs.custom_bg);
    } else {
        root.style.removeProperty('--bg');
    }
    if (prefs.custom_text) {
        root.style.setProperty('--text', prefs.custom_text);
    } else {
        root.style.removeProperty('--text');
    }
    if (prefs.custom_primary) {
        root.style.setProperty('--primary', prefs.custom_primary);
    } else {
        root.style.removeProperty('--primary');
    }
    if (prefs.custom_accent) {
        root.style.setProperty('--accent', prefs.custom_accent);
    } else {
        root.style.removeProperty('--accent');
    }

    // Line height
    var lineHeightMap = ['1.8', '2.2', '2.6'];
    var lhIdx = prefs.line_height || 0;
    root.style.setProperty('--a11y-line-height', lineHeightMap[lhIdx] || '1.8');

    // Letter spacing
    var letterSpacingMap = ['normal', '0.04em', '0.08em'];
    var lsIdx = prefs.letter_spacing || 0;
    root.style.setProperty('--a11y-letter-spacing', letterSpacingMap[lsIdx] || 'normal');

    // Reduce motion
    if (prefs.reduce_motion) {
        document.body.classList.add('a11y-reduce-motion');
    } else {
        document.body.classList.remove('a11y-reduce-motion');
    }
}

function _rgbToHex(color) {
    // Convert computed color (rgb or hex) to #rrggbb for color input
    if (!color) return '#000000';
    if (color.charAt(0) === '#') return color;
    var m = color.match(/^rgb\((\d+),\s*(\d+),\s*(\d+)\)$/);
    if (!m) return '#000000';
    return '#' + [m[1], m[2], m[3]].map(function(n) {
        return ('0' + parseInt(n, 10).toString(16)).slice(-2);
    }).join('');
}

function initAccessibility(prefs) {
    _a11yPrefs = prefs || {};

    // Apply stored prefs immediately
    applyA11yPrefs(_a11yPrefs);

    var panel = document.getElementById('a11y-panel');
    var overlay = document.getElementById('a11y-overlay');
    var toggleBtn = document.getElementById('a11y-toggle-btn');
    var closeBtn = document.getElementById('a11y-close-btn');
    if (!panel || !toggleBtn) return;

    function openPanel() {
        panel.style.display = 'flex';
        if (overlay) overlay.classList.add('active');
        // Sync UI controls to current prefs
        syncPanelUI();
    }

    function closePanel() {
        panel.style.display = 'none';
        if (overlay) overlay.classList.remove('active');
    }

    toggleBtn.addEventListener('click', function() {
        if (panel.style.display === 'none' || !panel.style.display) {
            openPanel();
        } else {
            closePanel();
        }
    });

    if (closeBtn) closeBtn.addEventListener('click', closePanel);
    if (overlay) overlay.addEventListener('click', closePanel);

    // Close on Escape
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && panel.style.display !== 'none') {
            closePanel();
        }
    });

    // Font size buttons
    panel.querySelectorAll('.a11y-font-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var scale = parseFloat(btn.dataset.scale);
            _a11yPrefs.font_scale = scale;
            applyA11yPrefs(_a11yPrefs);
            saveA11ySetting('font_scale', scale);
            syncFontBtns();
        });
    });

    // Contrast buttons
    panel.querySelectorAll('.a11y-contrast-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var level = parseInt(btn.dataset.contrast, 10);
            _a11yPrefs.contrast = level;
            applyA11yPrefs(_a11yPrefs);
            saveA11ySetting('contrast', level);
            syncContrastBtns();
        });
    });

    // Line height buttons
    panel.querySelectorAll('.a11y-line-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var idx = parseInt(btn.dataset.lineHeight, 10);
            _a11yPrefs.line_height = idx;
            applyA11yPrefs(_a11yPrefs);
            saveA11ySetting('line_height', idx);
            syncLineBtns();
        });
    });

    // Letter spacing buttons
    panel.querySelectorAll('.a11y-spacing-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var idx = parseInt(btn.dataset.spacing, 10);
            _a11yPrefs.letter_spacing = idx;
            applyA11yPrefs(_a11yPrefs);
            saveA11ySetting('letter_spacing', idx);
            syncSpacingBtns();
        });
    });

    // Reduce motion toggle
    var motionToggle = document.getElementById('a11y-motion-toggle');
    if (motionToggle) {
        motionToggle.addEventListener('change', function() {
            var val = motionToggle.checked ? 1 : 0;
            _a11yPrefs.reduce_motion = val;
            applyA11yPrefs(_a11yPrefs);
            saveA11ySetting('reduce_motion', val);
        });
    }

    // Color inputs
    var colorMap = {
        'bg': { input: document.getElementById('a11y-color-bg'), prop: 'custom_bg' },
        'text': { input: document.getElementById('a11y-color-text'), prop: 'custom_text' },
        'primary': { input: document.getElementById('a11y-color-primary'), prop: 'custom_primary' },
        'accent': { input: document.getElementById('a11y-color-accent'), prop: 'custom_accent' },
    };

    Object.keys(colorMap).forEach(function(key) {
        var entry = colorMap[key];
        if (!entry.input) return;
        entry.input.addEventListener('input', function() {
            _a11yPrefs[entry.prop] = entry.input.value;
            applyA11yPrefs(_a11yPrefs);
            saveA11ySetting(entry.prop, entry.input.value);
        });
    });

    // Clear buttons
    panel.querySelectorAll('.a11y-color-clear').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var target = btn.dataset.target;
            var prop = 'custom_' + target;
            _a11yPrefs[prop] = '';
            applyA11yPrefs(_a11yPrefs);
            saveA11ySetting(prop, '');
            syncColorInputs();
        });
    });

    // Reset all button
    var resetBtn = document.getElementById('a11y-reset-btn');
    if (resetBtn) {
        resetBtn.addEventListener('click', function() {
            bwConfirm('Reset all accessibility settings to default?', function() {
            fetch('/api/accessibility/reset', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
                body: '{}'
            }).then(function(r) { return r.json(); })
            .then(function(d) {
                if (d.defaults) {
                    _a11yPrefs = d.defaults;
                    applyA11yPrefs(_a11yPrefs);
                    syncPanelUI();
                    // Also remove inline styles that were set by server-side rendering
                    var a11yStyle = document.getElementById('a11y-style');
                    if (a11yStyle) a11yStyle.remove();
                }
            }).catch(function() {});
            });
        });
    }

    function syncFontBtns() {
        var scale = _a11yPrefs.font_scale || 1.0;
        panel.querySelectorAll('.a11y-font-btn').forEach(function(btn) {
            btn.classList.toggle('active', parseFloat(btn.dataset.scale) === scale);
        });
    }

    function syncContrastBtns() {
        var level = _a11yPrefs.contrast || 0;
        panel.querySelectorAll('.a11y-contrast-btn').forEach(function(btn) {
            btn.classList.toggle('active', parseInt(btn.dataset.contrast, 10) === level);
        });
    }

    function syncLineBtns() {
        var idx = _a11yPrefs.line_height || 0;
        panel.querySelectorAll('.a11y-line-btn').forEach(function(btn) {
            btn.classList.toggle('active', parseInt(btn.dataset.lineHeight, 10) === idx);
        });
    }

    function syncSpacingBtns() {
        var idx = _a11yPrefs.letter_spacing || 0;
        panel.querySelectorAll('.a11y-spacing-btn').forEach(function(btn) {
            btn.classList.toggle('active', parseInt(btn.dataset.spacing, 10) === idx);
        });
    }

    function syncMotionToggle() {
        var motionToggle = document.getElementById('a11y-motion-toggle');
        if (motionToggle) motionToggle.checked = !!(_a11yPrefs.reduce_motion);
    }

    function syncColorInputs() {
        var root = document.documentElement;
        var computed = getComputedStyle(root);
        Object.keys(colorMap).forEach(function(key) {
            var entry = colorMap[key];
            if (!entry.input) return;
            var stored = _a11yPrefs[entry.prop];
            if (stored) {
                entry.input.value = _rgbToHex(stored);
            } else {
                // Show current computed color as placeholder
                var varName = '--' + (key === 'bg' ? 'bg' : key === 'text' ? 'text' : key === 'primary' ? 'primary' : 'accent');
                var color = computed.getPropertyValue(varName).trim();
                entry.input.value = _rgbToHex(color) || '#000000';
            }
        });
    }

    function syncPanelUI() {
        syncFontBtns();
        syncContrastBtns();
        syncLineBtns();
        syncSpacingBtns();
        syncMotionToggle();
        syncColorInputs();
    }
}

// ---------------------------------------------------------------------------
//  Editor pane resize (split editor/preview in edit mode)
// ---------------------------------------------------------------------------
function initEditorResize() {
    var divider = document.querySelector('.editor-divider');
    var editorPane = document.querySelector('.editor-pane');
    var previewPane = document.querySelector('.preview-pane');
    if (!divider || !editorPane || !previewPane) return;

    var isResizingEditor = false;
    var container = divider.parentElement;

    divider.addEventListener('mousedown', function(e) {
        isResizingEditor = true;
        divider.classList.add('resizing');
        document.body.style.userSelect = 'none';
        document.body.style.cursor = 'col-resize';
        e.preventDefault();
    });

    document.addEventListener('mousemove', function(e) {
        if (!isResizingEditor) return;
        var rect = container.getBoundingClientRect();
        var offsetX = e.clientX - rect.left;
        var totalW = rect.width;
        var pct = Math.max(15, Math.min(85, (offsetX / totalW) * 100));
        editorPane.style.flex = 'none';
        editorPane.style.width = pct + '%';
        previewPane.style.flex = 'none';
        previewPane.style.width = (100 - pct) + '%';
    });

    document.addEventListener('mouseup', function() {
        if (isResizingEditor) {
            isResizingEditor = false;
            divider.classList.remove('resizing');
            document.body.style.userSelect = '';
            document.body.style.cursor = '';
        }
    });
}
