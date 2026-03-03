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
    function onScroll() {
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
    }
    // Desktop: content element scrolls independently
    contentEl.addEventListener('scroll', onScroll);
    // Mobile: body/window scrolls (content has overflow-y:visible on small screens)
    window.addEventListener('scroll', onScroll);
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

    // Content resize handle
    var contentResizeHandle = document.getElementById('content-resize-handle');
    var mainContent = document.getElementById('main-content');
    if (contentResizeHandle && mainContent) {
        var isContentResizing = false;
        contentResizeHandle.addEventListener('mousedown', function(e) {
            isContentResizing = true;
            contentResizeHandle.classList.add('resizing');
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
            e.preventDefault();
        });
        document.addEventListener('mousemove', function(e) {
            if (!isContentResizing) return;
            var layoutLeft = mainContent.getBoundingClientRect().left;
            var newWidth = e.clientX - layoutLeft;
            var minWidth = 400;
            var maxWidth = window.innerWidth - layoutLeft - 8;
            if (newWidth >= minWidth && newWidth <= maxWidth) {
                document.documentElement.style.setProperty('--content-max-width', newWidth + 'px');
            }
        });
        document.addEventListener('mouseup', function() {
            if (isContentResizing) {
                isContentResizing = false;
                contentResizeHandle.classList.remove('resizing');
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
                var w = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--content-max-width'), 10);
                if (w >= 400) {
                    saveA11ySetting('content_max_width', w);
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
                    openImageOptionsModal(result.data.url, file.name, contentEl);
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

// Image options modal
var _imgModalUrl = '', _imgModalInsertPos = 0, _imgModalEl = null;
// 'insert' = new image, 'edit' = update existing image properties
var _imgModalMode = 'insert', _imgModalOrigSrc = '';

function openImageOptionsModal(url, filename, contentEl) {
    _imgModalUrl = url;
    _imgModalOrigSrc = '';
    _imgModalMode = 'insert';
    _imgModalEl = contentEl;
    _imgModalInsertPos = contentEl ? (contentEl.selectionStart || contentEl.value.length) : 0;
    var preview = document.getElementById('img-preview');
    if (preview) { preview.src = url; preview.style.display = ''; }
    var altInput = document.getElementById('img-alt-input');
    if (altInput) altInput.value = filename ? filename.replace(/\.[^.]+$/, '') : '';
    var widthInput = document.getElementById('img-width-input');
    if (widthInput) widthInput.value = '';
    document.querySelectorAll('.img-align-btn').forEach(function(b) {
        b.classList.remove('active');
        b.classList.add('btn-outline');
    });
    var noneBtn = document.querySelector('.img-align-btn[data-align="none"]');
    if (noneBtn) { noneBtn.classList.add('active'); noneBtn.classList.remove('btn-outline'); }
    var modal = document.getElementById('image-options-modal');
    if (modal) {
        var h3 = modal.querySelector('h3');
        if (h3) h3.textContent = 'Insert Image';
        var insertBtn = modal.querySelector('#img-insert-btn');
        if (insertBtn) insertBtn.textContent = 'Insert';
        modal.style.display = 'flex';
    }
}

function openEditImageModal(src, alt, width, align, textareaEl) {
    _imgModalUrl = src;
    _imgModalOrigSrc = src;
    _imgModalMode = 'edit';
    _imgModalEl = textareaEl;
    _imgModalInsertPos = 0;
    var preview = document.getElementById('img-preview');
    if (preview) { preview.src = src; preview.style.display = ''; }
    var altInput = document.getElementById('img-alt-input');
    if (altInput) altInput.value = alt || '';
    var widthInput = document.getElementById('img-width-input');
    if (widthInput) widthInput.value = width || '';
    document.querySelectorAll('.img-align-btn').forEach(function(b) {
        b.classList.remove('active');
        b.classList.add('btn-outline');
    });
    var alignBtn = document.querySelector('.img-align-btn[data-align="' + (align || 'none') + '"]');
    if (!alignBtn) alignBtn = document.querySelector('.img-align-btn[data-align="none"]');
    if (alignBtn) { alignBtn.classList.add('active'); alignBtn.classList.remove('btn-outline'); }
    var modal = document.getElementById('image-options-modal');
    if (modal) {
        var h3 = modal.querySelector('h3');
        if (h3) h3.textContent = 'Edit Image';
        var insertBtn = modal.querySelector('#img-insert-btn');
        if (insertBtn) insertBtn.textContent = 'Update';
        modal.style.display = 'flex';
    }
}

function closeImageOptionsModal() {
    var modal = document.getElementById('image-options-modal');
    if (modal) modal.style.display = 'none';
}

function confirmImageInsert() {
    var ta = _imgModalEl;
    if (!ta) return;
    var altEl = document.getElementById('img-alt-input');
    var widthEl = document.getElementById('img-width-input');
    var alt = (altEl ? altEl.value || '' : '').trim();
    var width = (widthEl ? widthEl.value || '' : '').trim();
    var activeBtn = document.querySelector('.img-align-btn.active');
    var alignVal = activeBtn ? activeBtn.dataset.align : 'none';
    var url = escapeHtml(_imgModalUrl);
    var md;
    if (alignVal === 'none' && !width) {
        md = '\n![' + alt + '](' + _imgModalUrl + ')\n';
    } else if (alignVal === 'none') {
        md = '\n<img src="' + url + '" alt="' + escapeHtml(alt) + '" width="' + escapeHtml(width) + '">\n';
    } else {
        var cls = 'wiki-img-' + alignVal;
        var imgTag = '<img src="' + url + '" alt="' + escapeHtml(alt) + '"' + (width ? ' width="' + escapeHtml(width) + '"' : '') + '>';
        var caption = alt ? '<figcaption>' + escapeHtml(alt) + '</figcaption>' : '';
        md = '\n<figure class="' + cls + '">' + imgTag + caption + '</figure>\n';
    }
    if (_imgModalMode === 'edit' && _imgModalOrigSrc) {
        updateImageInEditor(ta, _imgModalOrigSrc, md.trim());
    } else {
        ta.value = ta.value.substring(0, _imgModalInsertPos) + md + ta.value.substring(_imgModalInsertPos);
    }
    ta.dispatchEvent(new Event('input'));
    ta.focus();
    closeImageOptionsModal();
}

document.addEventListener('DOMContentLoaded', function() {
    var insertBtn = document.getElementById('img-insert-btn');
    var cancelBtn = document.getElementById('img-cancel-btn');
    var modal = document.getElementById('image-options-modal');
    if (insertBtn) insertBtn.addEventListener('click', confirmImageInsert);
    if (cancelBtn) cancelBtn.addEventListener('click', closeImageOptionsModal);
    if (modal) {
        modal.addEventListener('click', function(e) { if (e.target === this) closeImageOptionsModal(); });
    }
    document.querySelectorAll('.img-align-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            document.querySelectorAll('.img-align-btn').forEach(function(b) {
                b.classList.remove('active');
                b.classList.add('btn-outline');
            });
            btn.classList.add('active');
            btn.classList.remove('btn-outline');
        });
    });
});


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

    // Filter out session-dismissed announcements (only for removable ones)
    var dismissed = [];
    try {
        dismissed = JSON.parse(sessionStorage.getItem('dismissed_announcements') || '[]');
    } catch (e) { dismissed = []; }

    var slides = allSlides.filter(function(s) {
        if (s.dataset.notRemovable === '1') return true;
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

    // Countdown timer logic
    function updateCountdowns() {
        var anyExpired = false;
        slides.forEach(function(s) {
            if (s.dataset.showCountdown !== '1') return;
            var cdEl = s.querySelector('.ann-countdown');
            if (!cdEl) return;
            var expiresAt = s.dataset.expiresAt;
            if (!expiresAt) {
                cdEl.style.display = 'inline';
                cdEl.textContent = '⚠ no expiry set';
                return;
            }
            // Strip any existing timezone offset (e.g. +00:00) or Z suffix so we can
            // re-append 'Z' to force UTC interpretation by the Date constructor.
            var normalized = expiresAt.replace(/[+-]\d{2}:\d{2}$/, '').replace(/Z$/, '');
            var expDate = new Date(normalized + 'Z');
            if (isNaN(expDate.getTime())) {
                cdEl.style.display = 'inline';
                cdEl.textContent = '⚠ invalid date';
                return;
            }
            var now = new Date();
            var diff = expDate.getTime() - now.getTime();
            if (diff <= 0) {
                // Timer expired – hide the announcement
                s.style.display = 'none';
                anyExpired = true;
                return;
            }
            var totalSec = Math.floor(diff / 1000);
            var days = Math.floor(totalSec / 86400);
            var hours = Math.floor((totalSec % 86400) / 3600);
            var minutes = Math.floor((totalSec % 3600) / 60);
            var seconds = totalSec % 60;
            var parts = [];
            if (days > 0) parts.push(days + 'd');
            if (hours > 0) parts.push(hours + 'h');
            parts.push(minutes + 'm');
            parts.push(seconds + 's');
            cdEl.style.display = 'inline';
            cdEl.textContent = parts.join(' ');
        });

        if (anyExpired) {
            // Rebuild slides list excluding expired and dismissed ones
            slides = Array.from(bar.querySelectorAll('.announcement-slide')).filter(function(s) {
                if (s.dataset.showCountdown === '1' && s.dataset.expiresAt) {
                    var norm = s.dataset.expiresAt.replace(/[+-]\d{2}:\d{2}$/, '').replace(/Z$/, '');
                    var expDate = new Date(norm + 'Z');
                    if (!isNaN(expDate.getTime()) && expDate.getTime() <= Date.now()) return false;
                }
                if (s.dataset.notRemovable === '1') return true;
                return dismissed.indexOf(parseInt(s.dataset.annId, 10)) === -1;
            });
            if (!slides.length) { bar.style.display = 'none'; return; }
            if (current >= slides.length) current = slides.length - 1;
            showSlide(current);
        }
    }

    updateCountdowns();
    setInterval(updateCountdowns, 1000);

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
// Collapse all sidebar categories by default; remember expanded ones
// ---------------------------------------------------------------------------
(function initCategoryCollapse() {
    var STORAGE_KEY = 'bw_expanded_cats';

    function getExpanded() {
        try {
            var raw = localStorage.getItem(STORAGE_KEY);
            return raw ? JSON.parse(raw) : [];
        } catch(e) { return []; }
    }

    function saveExpanded(ids) {
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(ids)); } catch(e) {}
    }

    document.addEventListener('DOMContentLoaded', function() {
        var expanded = getExpanded();
        document.querySelectorAll('.nav-section[data-cat-id]').forEach(function(section) {
            var catId = section.dataset.catId;
            // If the category contains the currently active page, expand it
            var hasActive = section.querySelector('.nav-item.active');
            if (!hasActive && expanded.indexOf(catId) === -1) {
                section.classList.add('collapsed');
            }
        });

        // Listen for toggle clicks and persist state
        document.addEventListener('click', function(e) {
            // Skip clicks on admin action buttons (reorder, settings)
            if (e.target.closest('.cat-actions')) return;

            var toggle = e.target.closest('.cat-toggle');
            if (toggle) {
                // The toggle button already toggles via onclick in HTML;
                // just persist state after the click
                setTimeout(persistState, 0);
                return;
            }

            // Allow clicking anywhere on the section header to toggle
            var header = e.target.closest('.nav-section-header');
            if (header) {
                var section = header.closest('.nav-section');
                if (section && section.dataset.catId) {
                    section.classList.toggle('collapsed');
                    persistState();
                }
            }
        });

        function persistState() {
            var ids = [];
            document.querySelectorAll('.nav-section[data-cat-id]').forEach(function(s) {
                if (!s.classList.contains('collapsed')) {
                    ids.push(s.dataset.catId);
                }
            });
            saveExpanded(ids);
        }
    });
}());

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

    // Content max width
    var root = document.documentElement;
    if (prefs.content_max_width && prefs.content_max_width > 0) {
        root.style.setProperty('--content-max-width', prefs.content_max_width + 'px');
    } else {
        root.style.removeProperty('--content-max-width');
    }

    // Editor pane horizontal split
    var editorPane = document.querySelector('.editor-pane');
    var previewPane = document.querySelector('.preview-pane');
    if (editorPane && previewPane) {
        if (prefs.editor_pane_width > 0) {
            editorPane.style.flex = 'none';
            editorPane.style.width = prefs.editor_pane_width + '%';
            previewPane.style.flex = 'none';
            previewPane.style.width = (100 - prefs.editor_pane_width) + '%';
        } else {
            editorPane.style.flex = '';
            editorPane.style.width = '';
            previewPane.style.flex = '';
            previewPane.style.width = '';
        }
    }

    // Editor container height
    var editorContainer = document.querySelector('.editor-container');
    if (editorContainer) {
        if (prefs.editor_height > 0) {
            editorContainer.style.minHeight = prefs.editor_height + 'px';
            editorContainer.style.height = prefs.editor_height + 'px';
        } else {
            editorContainer.style.minHeight = '';
            editorContainer.style.height = '';
        }
    }

    // Custom CSS colors
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
    if (prefs.custom_secondary) {
        root.style.setProperty('--secondary', prefs.custom_secondary);
    } else {
        root.style.removeProperty('--secondary');
    }
    if (prefs.custom_accent) {
        root.style.setProperty('--accent', prefs.custom_accent);
    } else {
        root.style.removeProperty('--accent');
    }
    if (prefs.custom_sidebar) {
        root.style.setProperty('--sidebar', prefs.custom_sidebar);
    } else {
        root.style.removeProperty('--sidebar');
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
    // Convert computed color (rgb or hex) to #rrggbb for color input.
    // Returns null when the value cannot be parsed so callers can skip
    // setting the input value and avoid accidentally persisting a fallback
    // black (#000000) that would turn the entire site black.
    if (!color) return null;
    if (color.charAt(0) === '#') return color;
    var m = color.match(/^rgb\((\d+),\s*(\d+),\s*(\d+)\)$/);
    if (!m) return null;
    return '#' + [m[1], m[2], m[3]].map(function(n) {
        return ('0' + parseInt(n, 10).toString(16)).slice(-2);
    }).join('');
}

// Rebuild the server-rendered <style id="a11y-style"> element to reflect the
// current _a11yPrefs custom-color state.  This must be called whenever a
// custom color is cleared so that the stale server-rendered CSS rule (e.g.
// --bg:#000) no longer overrides the site's default, which would otherwise
// keep the site black even after the user clicks the ✕ clear button.
function _syncA11yStyleBlock() {
    var el = document.getElementById('a11y-style');
    if (!el) return;
    var rules = [];
    if (_a11yPrefs.custom_bg)        rules.push('--bg:'        + _a11yPrefs.custom_bg);
    if (_a11yPrefs.custom_text)      rules.push('--text:'      + _a11yPrefs.custom_text);
    if (_a11yPrefs.custom_primary)   rules.push('--primary:'   + _a11yPrefs.custom_primary);
    if (_a11yPrefs.custom_secondary) rules.push('--secondary:' + _a11yPrefs.custom_secondary);
    if (_a11yPrefs.custom_accent)    rules.push('--accent:'    + _a11yPrefs.custom_accent);
    if (_a11yPrefs.custom_sidebar)   rules.push('--sidebar:'   + _a11yPrefs.custom_sidebar);
    el.textContent = rules.length ? ':root{' + rules.join(';') + '}' : '';
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
        'bg': { input: document.getElementById('a11y-color-bg'), prop: 'custom_bg', cssVar: '--bg' },
        'text': { input: document.getElementById('a11y-color-text'), prop: 'custom_text', cssVar: '--text' },
        'primary': { input: document.getElementById('a11y-color-primary'), prop: 'custom_primary', cssVar: '--primary' },
        'secondary': { input: document.getElementById('a11y-color-secondary'), prop: 'custom_secondary', cssVar: '--secondary' },
        'accent': { input: document.getElementById('a11y-color-accent'), prop: 'custom_accent', cssVar: '--accent' },
        'sidebar': { input: document.getElementById('a11y-color-sidebar'), prop: 'custom_sidebar', cssVar: '--sidebar' },
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
            // Rebuild the server-rendered <style id="a11y-style"> so the stale
            // CSS rule is removed immediately and the site colour reverts to the
            // site default instead of remaining black until the next page load.
            _syncA11yStyleBlock();
            syncColorInputs();
        });
    });

    // Reset all button
    var resetBtn = document.getElementById('a11y-reset-btn');
    if (resetBtn) {
        resetBtn.addEventListener('click', function() {
            bwConfirm('Reset all customization settings to default?', function() {
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
            var hex;
            if (stored) {
                hex = _rgbToHex(stored);
            } else {
                // Show current computed color as placeholder
                var color = computed.getPropertyValue(entry.cssVar).trim();
                hex = _rgbToHex(color);
            }
            // Only update the input when we have a valid, parseable color.
            // Skipping on null prevents an unresolvable CSS variable from
            // silently setting the picker to #000000 and later being saved
            // as a custom color that turns the whole site black.
            if (hex) entry.input.value = hex;
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
//  Resizable images in edit preview pane
// ---------------------------------------------------------------------------
function initResizableImages(previewEl, textareaEl) {
    if (!previewEl || !textareaEl) return;
    previewEl.querySelectorAll('img').forEach(function(img) {
        if (img.dataset.bwResizable) return;
        img.dataset.bwResizable = '1';

        var container;
        var parentFig = img.closest('figure');
        if (parentFig) {
            container = parentFig;
            container.style.position = 'relative';
        } else {
            var wrap = document.createElement('div');
            wrap.className = 'preview-img-wrap';
            img.parentNode.insertBefore(wrap, img);
            wrap.appendChild(img);
            container = wrap;
        }

        var handle = document.createElement('span');
        handle.className = 'preview-img-resize-handle';
        handle.title = 'Drag to resize image';
        container.appendChild(handle);

        // Click-to-edit: clicking the image (not the resize handle) opens edit modal
        img.style.cursor = 'pointer';
        img.title = 'Click to edit image size / position';
        img.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            var src = img.getAttribute('src') || '';
            var alt = img.getAttribute('alt') || '';
            var widthAttr = img.getAttribute('width') || '';
            var align = 'none';
            var fig = img.closest('figure');
            if (fig) {
                if (fig.classList.contains('wiki-img-left')) align = 'left';
                else if (fig.classList.contains('wiki-img-right')) align = 'right';
                else if (fig.classList.contains('wiki-img-center')) align = 'center';
            }
            openEditImageModal(src, alt, widthAttr, align, textareaEl);
        });

        handle.addEventListener('mousedown', function(e) {
            e.preventDefault();
            e.stopPropagation();
            var startX = e.clientX;
            var startW = img.getBoundingClientRect().width;
            document.body.style.userSelect = 'none';
            document.body.style.cursor = 'ew-resize';

            function onMove(ev) {
                var newW = Math.max(50, Math.round(startW + (ev.clientX - startX)));
                img.style.width = newW + 'px';
                img.style.maxWidth = 'none';
            }

            function onUp() {
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
                document.body.style.userSelect = '';
                document.body.style.cursor = '';
                var finalW = Math.round(img.getBoundingClientRect().width);
                updateImageWidthInEditor(textareaEl, img.getAttribute('src'), finalW);
            }

            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
    });

    // Make embedded videos resizable in the preview pane
    previewEl.querySelectorAll('.video-embed').forEach(function(embed) {
        if (embed.dataset.bwResizable) return;
        embed.dataset.bwResizable = '1';

        // Ensure the iframe doesn't steal pointer events from the resize handle
        var iframe = embed.querySelector('iframe');
        var handle = document.createElement('span');
        handle.className = 'preview-img-resize-handle';
        handle.title = 'Drag to resize video';
        handle.style.opacity = '0';
        handle.style.zIndex = '10';
        embed.style.position = 'relative';
        embed.appendChild(handle);
        embed.addEventListener('mouseenter', function() { handle.style.opacity = '.85'; });
        embed.addEventListener('mouseleave', function() { handle.style.opacity = '0'; });

        handle.addEventListener('mousedown', function(e) {
            e.preventDefault();
            e.stopPropagation();
            var startX = e.clientX;
            var startW = embed.getBoundingClientRect().width;
            document.body.style.userSelect = 'none';
            document.body.style.cursor = 'ew-resize';
            // Disable iframe pointer events during drag to prevent stealing mousemove
            if (iframe) iframe.style.pointerEvents = 'none';

            function onMove(ev) {
                var newW = Math.max(200, Math.round(startW + (ev.clientX - startX)));
                embed.style.width = newW + 'px';
                embed.style.maxWidth = '100%';
                embed.style.paddingBottom = Math.round(newW * 0.5625) + 'px';
            }

            function onUp() {
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
                document.body.style.userSelect = '';
                document.body.style.cursor = '';
                if (iframe) iframe.style.pointerEvents = '';
            }

            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
    });
}

function updateImageWidthInEditor(textarea, src, width) {
    if (!textarea || !src || !width) return;
    var content = textarea.value;
    var updated;

    // Update any existing HTML <img> tag whose src matches
    updated = content.replace(/<img\b([^>]*)>/gi, function(match, attrs) {
        var srcMatch = attrs.match(/\bsrc=(?:"([^"]*)"|'([^']*)')/i);
        if (!srcMatch) return match;
        var tagSrc = srcMatch[1] !== undefined ? srcMatch[1] : srcMatch[2];
        if (tagSrc !== src) return match;
        // Remove any existing width attribute and add the new one
        var newAttrs = attrs.replace(/\s+width=(?:"[^"]*"|'[^']*'|\S+)/gi, '').replace(/\s+/g, ' ').trimEnd();
        return '<img' + newAttrs + ' width="' + width + '">';
    });

    // If no HTML <img> was matched, the image may be in Markdown format: ![alt](src)
    if (updated === content) {
        var escapedSrc = src.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        updated = content.replace(
            new RegExp('!\\[([^\\]]*)\\]\\(' + escapedSrc + '\\)', 'g'),
            function(match, alt) {
                return '<img src="' + escapeHtml(src) + '" alt="' + escapeHtml(alt) + '" width="' + width + '">';
            }
        );
    }

    if (updated !== content) {
        textarea.value = updated;
        textarea.dispatchEvent(new Event('input'));
    }
}

// Replace an existing image/figure in the editor with new markup (for edit mode).
// Searches for the image by src and replaces the surrounding figure (if any) or
// the bare <img> / markdown ![...](src) token.
function updateImageInEditor(textarea, src, newMarkdown) {
    if (!textarea || !src) return;
    var content = textarea.value;
    var updated = content;
    var escapedSrc = src.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

    // 1. <figure ...><img src="src"...>...</figure>  (only double- or single-quoted src)
    var figRe = new RegExp('<figure[^>]*>\\s*<img[^>]+src=(?:"' + escapedSrc + '"|\''+escapedSrc+'\'\\b)[^>]*>(?:\\s*<figcaption>[^]*?</figcaption>)?\\s*</figure>', 'i');
    if (figRe.test(updated)) {
        updated = updated.replace(figRe, newMarkdown);
    } else {
        // 2. Plain <img src="src"...> (not inside a figure)
        var imgRe = new RegExp('<img\\b([^>]*)>', 'gi');
        var replaced = false;
        updated = content.replace(imgRe, function(match, attrs) {
            if (replaced) return match;
            var srcMatch = attrs.match(/\bsrc=(?:"([^"]*)"|'([^']*)')/i);
            if (!srcMatch) return match;
            var tagSrc = srcMatch[1] !== undefined ? srcMatch[1] : srcMatch[2];
            if (tagSrc !== src) return match;
            replaced = true;
            return newMarkdown;
        });
        // 3. Markdown: ![alt](src)
        if (!replaced) {
            updated = content.replace(
                new RegExp('!\\[([^\\]]*)\\]\\(' + escapedSrc + '\\)', 'g'),
                newMarkdown
            );
        }
    }

    if (updated !== content) {
        textarea.value = updated;
        textarea.dispatchEvent(new Event('input'));
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

    function isMobileLayout() {
        return window.innerWidth <= 768;
    }

    function applyHorizSplit(clientX) {
        var rect = container.getBoundingClientRect();
        var offsetX = clientX - rect.left;
        var totalW = rect.width;
        var pct = Math.max(15, Math.min(85, (offsetX / totalW) * 100));
        editorPane.style.flex = 'none';
        editorPane.style.width = pct + '%';
        previewPane.style.flex = 'none';
        previewPane.style.width = (100 - pct) + '%';
        return pct;
    }

    function applyVertSplit(clientY) {
        var rect = container.getBoundingClientRect();
        var offsetY = clientY - rect.top;
        var totalH = rect.height;
        var pct = Math.max(15, Math.min(85, (offsetY / totalH) * 100));
        editorPane.style.flex = 'none';
        editorPane.style.height = pct + '%';
        previewPane.style.flex = 'none';
        previewPane.style.height = (100 - pct) + '%';
        return pct;
    }

    // Mouse events – horizontal split on desktop
    divider.addEventListener('mousedown', function(e) {
        if (isMobileLayout()) return;
        isResizingEditor = true;
        divider.classList.add('resizing');
        document.body.style.userSelect = 'none';
        document.body.style.cursor = 'col-resize';
        e.preventDefault();
    });

    document.addEventListener('mousemove', function(e) {
        if (!isResizingEditor) return;
        applyHorizSplit(e.clientX);
    });

    document.addEventListener('mouseup', function() {
        if (isResizingEditor) {
            isResizingEditor = false;
            divider.classList.remove('resizing');
            document.body.style.userSelect = '';
            document.body.style.cursor = '';
            var pct = parseFloat(editorPane.style.width);
            if (pct >= 15 && pct <= 85) {
                saveA11ySetting('editor_pane_width', pct);
            }
        }
    });

    // Touch events – horizontal on desktop, vertical on mobile (stacked layout)
    divider.addEventListener('touchstart', function(e) {
        if (e.touches.length !== 1) return;
        isResizingEditor = true;
        divider.classList.add('resizing');
        e.preventDefault();
    }, { passive: false });

    divider.addEventListener('touchmove', function(e) {
        if (!isResizingEditor || e.touches.length !== 1) return;
        e.preventDefault();
        var touch = e.touches[0];
        if (isMobileLayout()) {
            applyVertSplit(touch.clientY);
        } else {
            applyHorizSplit(touch.clientX);
        }
    }, { passive: false });

    divider.addEventListener('touchend', function() {
        if (!isResizingEditor) return;
        isResizingEditor = false;
        divider.classList.remove('resizing');
        if (!isMobileLayout()) {
            var pct = parseFloat(editorPane.style.width);
            if (pct >= 15 && pct <= 85) {
                saveA11ySetting('editor_pane_width', pct);
            }
        }
    });

    // Vertical resize handle for editor container height
    var vertHandle = document.getElementById('editor-resize-handle');
    var editorContainer = document.querySelector('.editor-container');
    if (vertHandle && editorContainer) {
        var isResizingVert = false;
        var startY, startH;

        function startVertResize(clientY) {
            isResizingVert = true;
            startY = clientY;
            startH = editorContainer.offsetHeight;
            vertHandle.classList.add('resizing');
            document.body.style.userSelect = 'none';
            document.body.style.cursor = 'row-resize';
        }

        function moveVertResize(clientY) {
            var newH = startH + (clientY - startY);
            if (newH >= 300 && newH <= 2000) {
                editorContainer.style.minHeight = newH + 'px';
                editorContainer.style.height = newH + 'px';
            }
        }

        function endVertResize() {
            if (!isResizingVert) return;
            isResizingVert = false;
            vertHandle.classList.remove('resizing');
            document.body.style.userSelect = '';
            document.body.style.cursor = '';
            var h = parseInt(editorContainer.style.height, 10);
            if (h >= 300 && h <= 2000) {
                saveA11ySetting('editor_height', h);
            }
        }

        vertHandle.addEventListener('mousedown', function(e) {
            startVertResize(e.clientY);
            e.preventDefault();
        });
        document.addEventListener('mousemove', function(e) {
            if (!isResizingVert) return;
            moveVertResize(e.clientY);
        });
        document.addEventListener('mouseup', endVertResize);

        vertHandle.addEventListener('touchstart', function(e) {
            if (e.touches.length !== 1) return;
            startVertResize(e.touches[0].clientY);
            e.preventDefault();
        }, { passive: false });
        vertHandle.addEventListener('touchmove', function(e) {
            if (!isResizingVert || e.touches.length !== 1) return;
            e.preventDefault();
            moveVertResize(e.touches[0].clientY);
        }, { passive: false });
        vertHandle.addEventListener('touchend', endVertResize);
    }
}
