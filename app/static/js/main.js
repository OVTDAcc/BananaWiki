/* BananaWiki – Main JS */

// CSRF token helper
function getCsrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
}

// Auto-dismiss flash messages after 5 seconds
document.addEventListener('DOMContentLoaded', function() {
    setTimeout(function() {
        document.querySelectorAll('.flash').forEach(function(el) {
            el.style.opacity = '0';
            setTimeout(function() { el.remove(); }, 300);
        });
    }, 5000);

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
var _autosavePaused = false;

function initAutosave(pageId) {
    var titleEl = document.getElementById('edit-title');
    var contentEl = document.getElementById('edit-content');
    if (!titleEl || !contentEl) return;

    var saveTimer = null;
    _autosavePaused = false;

    function setIndicator(state) {
        var indicator = document.getElementById('save-indicator');
        if (!indicator) return;
        indicator.className = 'save-indicator';
        if (state === 'syncing') {
            indicator.textContent = 'Syncing…';
            indicator.classList.add('save-syncing');
        } else if (state === 'synced') {
            indicator.textContent = 'All changes saved';
            indicator.classList.add('save-synced');
        } else if (state === 'error') {
            indicator.textContent = 'Error syncing';
            indicator.classList.add('save-error');
        } else {
            indicator.textContent = '';
        }
    }

    function doSave() {
        if (_autosavePaused) return;
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
            if (!_autosavePaused) setIndicator('synced');
        }).catch(function(err) {
            if (!_autosavePaused) setIndicator('error');
        });
    }

    function scheduleSave() {
        if (_autosavePaused) return;
        if (saveTimer) clearTimeout(saveTimer);
        saveTimer = setTimeout(doSave, 1500);
    }

    titleEl.addEventListener('input', scheduleSave);
    contentEl.addEventListener('input', scheduleSave);

    // Expose save function for Save Draft and Close button
    window._doManualSave = doSave;
    window._cancelAutosave = function() {
        _autosavePaused = true;
        if (saveTimer) clearTimeout(saveTimer);
    };

    // Check for other drafts periodically
    setInterval(function() {
        fetch('/api/draft/others/' + pageId)
            .then(function(r) {
                if (!r.ok) throw new Error('Failed to check drafts');
                return r.json();
            })
            .then(function(drafts) {
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
    if (window._cancelAutosave) window._cancelAutosave();
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

function saveDraftAndClose(pageId) {
    if (window._cancelAutosave) window._cancelAutosave();
    var titleEl = document.getElementById('edit-title');
    var contentEl = document.getElementById('edit-content');
    fetch('/api/draft/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        body: JSON.stringify({
            page_id: pageId,
            title: titleEl ? titleEl.value : '',
            content: contentEl ? contentEl.value : ''
        })
    }).then(function(r) {
        if (!r.ok) throw new Error('Save failed');
        return r.json();
    }).then(function() {
        var form = document.getElementById('editForm');
        if (form) {
            var cancelLink = form.querySelector('a.btn.btn-outline');
            if (cancelLink) {
                window.location.href = cancelLink.href;
                return;
            }
        }
        window.location.href = '/';
    }).catch(function() {
        alert('Failed to save draft.');
    });
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
