"""Page CRUD, history, search, sequential nav, and page attachments."""

import re
from datetime import datetime, timezone

from ._connection import get_db


# ---------------------------------------------------------------------------
#  Page helpers
# ---------------------------------------------------------------------------
def update_category_sequential_nav(cat_id, enabled):
    """Enable or disable sequential prev/next navigation for pages in a category."""
    conn = get_db()
    conn.execute("UPDATE categories SET sequential_nav=? WHERE id=?", (1 if enabled else 0, cat_id))
    conn.commit()
    conn.close()


def get_adjacent_pages(page_id):
    """Return (prev_page, next_page) for sequential navigation within the same category.

    Both values are sqlite3 Row objects (with id, title, slug) or None.
    Returns (None, None) if the page's category does not have sequential_nav enabled.
    """
    conn = get_db()
    row = conn.execute("SELECT category_id, sort_order FROM pages WHERE id=?", (page_id,)).fetchone()
    if not row or not row["category_id"]:
        conn.close()
        return None, None
    cat = conn.execute("SELECT sequential_nav FROM categories WHERE id=?",
                       (row["category_id"],)).fetchone()
    if not cat or not cat["sequential_nav"]:
        conn.close()
        return None, None
    cat_id = row["category_id"]
    sort_order = row["sort_order"]
    prev_page = conn.execute(
        "SELECT id, title, slug FROM pages WHERE category_id=? AND sort_order<? AND is_home=0 AND is_deindexed=0 "
        "ORDER BY sort_order DESC LIMIT 1",
        (cat_id, sort_order),
    ).fetchone()
    next_page = conn.execute(
        "SELECT id, title, slug FROM pages WHERE category_id=? AND sort_order>? AND is_home=0 AND is_deindexed=0 "
        "ORDER BY sort_order ASC LIMIT 1",
        (cat_id, sort_order),
    ).fetchone()
    conn.close()
    return prev_page, next_page


def update_page_slug(page_id, new_slug):
    """Change a page's URL slug and rewrite all internal links in other pages' content.

    Any occurrence of /page/<old_slug> in page content is updated to /page/<new_slug>.
    Returns the old slug so callers can redirect.
    """
    conn = get_db()
    old_row = conn.execute("SELECT slug FROM pages WHERE id=?", (page_id,)).fetchone()
    if not old_row:
        conn.close()
        return None
    old_slug = old_row["slug"]
    if old_slug == new_slug:
        conn.close()
        return old_slug
    # Update the slug on the page itself
    conn.execute("UPDATE pages SET slug=? WHERE id=?", (new_slug, page_id))
    # Rewrite internal links in all other pages' content
    old_link = f"/page/{old_slug}"
    new_link = f"/page/{new_slug}"
    pages = conn.execute("SELECT id, content FROM pages WHERE id!=?", (page_id,)).fetchall()
    for p in pages:
        if old_link in (p["content"] or ""):
            updated = p["content"].replace(old_link, new_link)
            conn.execute("UPDATE pages SET content=? WHERE id=?", (updated, p["id"]))
    # Also rewrite in any open drafts
    drafts = conn.execute("SELECT id, content FROM drafts").fetchall()
    for d in drafts:
        if old_link in (d["content"] or ""):
            updated = d["content"].replace(old_link, new_link)
            conn.execute("UPDATE drafts SET content=? WHERE id=?", (updated, d["id"]))
    conn.commit()
    conn.close()
    return old_slug


def search_pages(query, limit=15, include_deindexed=False):
    """Return pages whose title matches *query* (case-insensitive prefix/substring).

    Used by the link-insertion autocomplete endpoint.  Deindexed pages are
    excluded by default; pass ``include_deindexed=True`` for editors/admins.
    """
    conn = get_db()
    pattern = f"%{query}%"
    deindex_clause = "" if include_deindexed else " AND is_deindexed=0"
    rows = conn.execute(
        f"SELECT id, title, slug FROM pages WHERE is_home=0{deindex_clause} AND title LIKE ? "
        "ORDER BY title LIMIT ?",
        (pattern, limit),
    ).fetchall()
    conn.close()
    return rows


def search_pages_full(query, limit=20, include_deindexed=False, search_content=False):
    """Return pages matching *query* in title and optionally content.

    Returns dicts with ``id``, ``title``, ``slug`` and ``category_id``.
    Deindexed pages are excluded by default.
    When ``search_content`` is True, also matches within page body text.
    """
    conn = get_db()
    pattern = f"%{query}%"
    if search_content:
        if include_deindexed:
            sql = (
                "SELECT id, title, slug, category_id FROM pages "
                "WHERE is_home=0 AND (title LIKE ? OR content LIKE ?) "
                "ORDER BY CASE WHEN title LIKE ? THEN 0 ELSE 1 END, title LIMIT ?"
            )
        else:
            sql = (
                "SELECT id, title, slug, category_id FROM pages "
                "WHERE is_home=0 AND is_deindexed=0 AND (title LIKE ? OR content LIKE ?) "
                "ORDER BY CASE WHEN title LIKE ? THEN 0 ELSE 1 END, title LIMIT ?"
            )
        rows = conn.execute(sql, (pattern, pattern, pattern, limit)).fetchall()
    else:
        if include_deindexed:
            sql = (
                "SELECT id, title, slug, category_id FROM pages "
                "WHERE is_home=0 AND title LIKE ? "
                "ORDER BY title LIMIT ?"
            )
        else:
            sql = (
                "SELECT id, title, slug, category_id FROM pages "
                "WHERE is_home=0 AND is_deindexed=0 AND title LIKE ? "
                "ORDER BY title LIMIT ?"
            )
        rows = conn.execute(sql, (pattern, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_page(title, slug, content="", category_id=None, user_id=None):
    """Create a new wiki page and record the initial history entry.  Returns the new page ID."""
    conn = get_db()
    try:
        cur = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        # New pages go to the bottom: pick max sort_order + 1 within the same category scope
        max_row = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) FROM pages WHERE is_home=0 AND category_id IS ?"
            if category_id is None else
            "SELECT COALESCE(MAX(sort_order), -1) FROM pages WHERE is_home=0 AND category_id=?",
            (category_id,),
        ).fetchone()
        next_sort = (max_row[0] + 1) if max_row else 0
        cur.execute(
            "INSERT INTO pages (title, slug, content, category_id, last_edited_by, last_edited_at, sort_order) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (title, slug, content, category_id, user_id, now, next_sort),
        )
        page_id = cur.lastrowid
        if user_id:
            cur.execute(
                "INSERT INTO page_history (page_id, title, content, edited_by, edit_message) "
                "VALUES (?, ?, ?, ?, ?)",
                (page_id, title, content, user_id, "Page created"),
            )
        conn.commit()
    finally:
        conn.close()
    return page_id


def get_page(page_id):
    """Return the page row for the given *page_id*, or None if not found."""
    conn = get_db()
    row = conn.execute("SELECT * FROM pages WHERE id=?", (page_id,)).fetchone()
    conn.close()
    return row


def get_page_by_slug(slug):
    """Return the page row matching *slug*, or None if not found."""
    conn = get_db()
    row = conn.execute("SELECT * FROM pages WHERE slug=?", (slug,)).fetchone()
    conn.close()
    return row


def get_home_page():
    """Return the designated home page row, or None if none has been set."""
    conn = get_db()
    row = conn.execute("SELECT * FROM pages WHERE is_home=1").fetchone()
    conn.close()
    return row


def update_page(page_id, title, content, user_id, edit_message="", is_revert=False):
    """Update a page's title and content, recording a history snapshot."""
    conn = get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE pages SET title=?, content=?, last_edited_by=?, last_edited_at=? WHERE id=?",
            (title, content, user_id, now, page_id),
        )
        conn.execute(
            "INSERT INTO page_history (page_id, title, content, edited_by, edit_message, is_revert) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (page_id, title, content, user_id, edit_message, 1 if is_revert else 0),
        )
        conn.commit()
    finally:
        conn.close()


def update_page_title(page_id, title, user_id):
    """Update only the title of a page, recording a history entry for the change."""
    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    page = conn.execute("SELECT title, content FROM pages WHERE id=?", (page_id,)).fetchone()
    conn.execute("UPDATE pages SET title=?, last_edited_by=?, last_edited_at=? WHERE id=?",
                 (title, user_id, now, page_id))
    if page:
        conn.execute(
            "INSERT INTO page_history (page_id, title, content, edited_by, edit_message) "
            "VALUES (?, ?, ?, ?, ?)",
            (page_id, title, page["content"], user_id, f"Title changed from '{page['title']}' to '{title}'"),
        )
    conn.commit()
    conn.close()


def update_page_category(page_id, category_id):
    """Move a page into the given category (or uncategorized if *category_id* is None)."""
    conn = get_db()
    conn.execute("UPDATE pages SET category_id=? WHERE id=?", (category_id, page_id))
    conn.commit()
    conn.close()


VALID_DIFFICULTY_TAGS = ("", "beginner", "easy", "intermediate", "expert", "extra", "custom")


def update_page_tag(page_id, difficulty_tag, custom_label="", custom_color=""):
    """Set the difficulty tag for a page.

    *difficulty_tag* must be one of :data:`VALID_DIFFICULTY_TAGS`.  Custom label
    and color are only persisted when ``difficulty_tag == 'custom'``; they are
    cleared otherwise.
    """
    if difficulty_tag not in VALID_DIFFICULTY_TAGS:
        raise ValueError(f"Invalid difficulty tag: {difficulty_tag!r}")
    # Only persist custom fields when the custom tag type is chosen
    if difficulty_tag != "custom":
        custom_label = ""
        custom_color = ""
    conn = get_db()
    conn.execute(
        "UPDATE pages SET difficulty_tag=?, tag_custom_label=?, tag_custom_color=? WHERE id=?",
        (difficulty_tag, custom_label, custom_color, page_id),
    )
    conn.commit()
    conn.close()


def set_page_deindexed(page_id, is_deindexed):
    """Set or clear the deindexed flag for a page."""
    conn = get_db()
    conn.execute("UPDATE pages SET is_deindexed=? WHERE id=?", (1 if is_deindexed else 0, page_id))
    conn.commit()
    conn.close()


def delete_page(page_id):
    """Delete a non-home page by ID.  Home pages are protected and cannot be deleted this way."""
    conn = get_db()
    conn.execute("DELETE FROM pages WHERE id=? AND is_home=0", (page_id,))
    conn.commit()
    conn.close()


def get_page_history(page_id):
    """Return all history entries for a page, newest first, with editor usernames joined."""
    conn = get_db()
    rows = conn.execute(
        "SELECT ph.*, "
        "CASE WHEN ph.edited_by IS NULL THEN '[removed]' "
        "     ELSE COALESCE(u.username, '[deleted user]') END AS username "
        "FROM page_history ph "
        "LEFT JOIN users u ON ph.edited_by=u.id "
        "WHERE ph.page_id=? ORDER BY ph.created_at DESC, ph.id DESC",
        (page_id,),
    ).fetchall()
    conn.close()
    return rows


def get_history_entry(entry_id):
    """Return a single page history entry by its *entry_id*, with editor username joined."""
    conn = get_db()
    row = conn.execute(
        "SELECT ph.*, "
        "CASE WHEN ph.edited_by IS NULL THEN '[removed]' "
        "     ELSE COALESCE(u.username, '[deleted user]') END AS username "
        "FROM page_history ph LEFT JOIN users u ON ph.edited_by=u.id "
        "WHERE ph.id=?", (entry_id,)
    ).fetchone()
    conn.close()
    return row


def transfer_history_attribution(entry_id, new_user_id):
    """Transfer a single page history entry's attribution to a different user."""
    conn = get_db()
    conn.execute(
        "UPDATE page_history SET edited_by=? WHERE id=?",
        (new_user_id, entry_id),
    )
    conn.commit()
    conn.close()


def bulk_transfer_history_attribution(page_id, from_user_id, to_user_id):
    """Transfer all page history entries for a page from one user to another.

    Returns the number of entries updated.
    """
    conn = get_db()
    cur = conn.execute(
        "UPDATE page_history SET edited_by=? WHERE page_id=? AND edited_by=?",
        (to_user_id, page_id, from_user_id),
    )
    count = cur.rowcount
    conn.commit()
    conn.close()
    return count


def delete_history_entry(entry_id):
    """Delete a single page history entry by ID.

    Returns True if an entry was deleted, False if it did not exist.
    """
    conn = get_db()
    cur = conn.execute("DELETE FROM page_history WHERE id=?", (entry_id,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def clear_page_history(page_id):
    """Delete all history entries for a page.

    Returns the number of entries deleted.
    """
    conn = get_db()
    cur = conn.execute("DELETE FROM page_history WHERE page_id=?", (page_id,))
    count = cur.rowcount
    conn.commit()
    conn.close()
    return count


_UPLOAD_REF_RE = re.compile(r'/static/uploads/([^\s)"\']+)')


def get_all_referenced_image_filenames():
    """Return a set of upload filenames referenced in any page content or history.

    Scans both the live ``pages.content`` and every ``page_history.content``
    entry so that images still present in the revision history are never
    removed.
    """
    conn = get_db()
    filenames = set()
    for row in conn.execute("SELECT content FROM pages").fetchall():
        filenames.update(_UPLOAD_REF_RE.findall(row["content"]))
    for row in conn.execute("SELECT content FROM page_history").fetchall():
        filenames.update(_UPLOAD_REF_RE.findall(row["content"]))
    conn.close()
    return filenames



# ---------------------------------------------------------------------------
#  Page Attachments
# ---------------------------------------------------------------------------
def add_page_attachment(page_id, filename, original_name, file_size, user_id):
    """Record a new attachment for a page."""
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    cur.execute(
        "INSERT INTO page_attachments (page_id, filename, original_name, file_size, uploaded_by, uploaded_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (page_id, filename, original_name, file_size, user_id, now),
    )
    attachment_id = cur.lastrowid
    conn.commit()
    conn.close()
    return attachment_id


def get_page_attachments(page_id):
    """Return all attachments for a page, ordered oldest first."""
    conn = get_db()
    rows = conn.execute(
        "SELECT pa.*, COALESCE(u.username, 'deleted user') AS uploader_name "
        "FROM page_attachments pa LEFT JOIN users u ON pa.uploaded_by=u.id "
        "WHERE pa.page_id=? ORDER BY pa.uploaded_at ASC",
        (page_id,),
    ).fetchall()
    conn.close()
    return rows


def get_page_attachment(attachment_id):
    """Return a single attachment row by ID."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM page_attachments WHERE id=?", (attachment_id,)
    ).fetchone()
    conn.close()
    return row


def delete_page_attachment(attachment_id):
    """Delete an attachment record."""
    conn = get_db()
    conn.execute("DELETE FROM page_attachments WHERE id=?", (attachment_id,))
    conn.commit()
    conn.close()

