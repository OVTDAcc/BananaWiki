/* BananaWiki – Main JS */

// CSRF token helper
function getCsrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
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

document.addEventListener('DOMContentLoaded', function() {
    initFlashMessages();

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
    if (!confirm('Transfer this draft to your account? Your current draft will be replaced.')) return;
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
    if (!confirm('Discard this draft? All unsaved changes will be lost.')) return;
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
                    + '<td style="white-space:nowrap;font-size:.85rem;opacity:.7">' + escapeHtml(d.updated_at) + '</td>'
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
    if (!confirm('Discard this draft? This cannot be undone.')) return;
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
    return confirm(msg);
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

        // Notify the backend (fire-and-forget, best effort)
        var csrfMeta = document.querySelector('meta[name="csrf-token"]');
        var csrf = csrfMeta ? csrfMeta.getAttribute('content') : '';
        fetch('/api/easter-egg/trigger', {
            method: 'POST',
            headers: { 'X-CSRFToken': csrf, 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: '{}',
        }).catch(function () {});
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

        } else if (type === 'category') {
            var section = btn.closest('.nav-section');
            if (!section) return;
            var siblings = siblingsOf(section, '.nav-section[data-cat-id]');
            var idx = siblings.indexOf(section);
            var swapIdx = dir === 'up' ? idx - 1 : idx + 1;
            if (swapIdx < 0 || swapIdx >= siblings.length) return;
            if (dir === 'up') {
                section.parentNode.insertBefore(section, siblings[swapIdx]);
            } else {
                section.parentNode.insertBefore(siblings[swapIdx], section);
            }
            var ids = Array.from(section.parentNode.querySelectorAll(':scope > .nav-section[data-cat-id]')).map(function(s) {
                return parseInt(s.dataset.catId, 10);
            });
            postReorder('/api/reorder/categories', ids).catch(function() {});
        }
    });
}());
