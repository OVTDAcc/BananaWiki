/* BananaWiki – Main JS */

// Auto-dismiss flash messages after 5 seconds
document.addEventListener('DOMContentLoaded', function() {
    setTimeout(function() {
        document.querySelectorAll('.flash').forEach(function(el) {
            el.style.opacity = '0';
            setTimeout(function() { el.remove(); }, 300);
        });
    }, 5000);
});

// Autosave for editor
function initAutosave(pageId) {
    var titleEl = document.getElementById('edit-title');
    var contentEl = document.getElementById('edit-content');
    if (!titleEl || !contentEl) return;

    var saveTimer = null;

    function doSave() {
        fetch('/api/draft/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                page_id: pageId,
                title: titleEl.value,
                content: contentEl.value
            })
        }).then(function(r) {
            if (!r.ok) throw new Error('Save failed');
            return r.json();
        }).then(function(d) {
            var indicator = document.getElementById('save-indicator');
            if (indicator) {
                indicator.textContent = 'Draft saved';
                setTimeout(function() { indicator.textContent = ''; }, 2000);
            }
        }).catch(function(err) {
            var indicator = document.getElementById('save-indicator');
            if (indicator) {
                indicator.textContent = 'Save error';
                setTimeout(function() { indicator.textContent = ''; }, 3000);
            }
        });
    }

    function scheduleSave() {
        if (saveTimer) clearTimeout(saveTimer);
        saveTimer = setTimeout(doSave, 1500);
    }

    titleEl.addEventListener('input', scheduleSave);
    contentEl.addEventListener('input', scheduleSave);

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
                    notice.appendChild(document.createTextNode('\u26A0\uFE0F Other users editing this page: '));
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
        headers: { 'Content-Type': 'application/json' },
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
    fetch('/api/draft/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
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

// Image upload via drag & drop or file input
function initImageUpload(contentEl) {
    if (!contentEl) return;

    var dropZone = document.getElementById('drop-zone');

    function uploadFile(file) {
        var fd = new FormData();
        fd.append('file', file);
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
