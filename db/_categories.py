"""Category CRUD, tree, and ordering."""

from ._connection import get_db


# ---------------------------------------------------------------------------
#  Category helpers
# ---------------------------------------------------------------------------
def create_category(name, parent_id=None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO categories (name, parent_id) VALUES (?, ?)", (name, parent_id))
    cat_id = cur.lastrowid
    conn.commit()
    conn.close()
    return cat_id


def get_category(cat_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM categories WHERE id=?", (cat_id,)).fetchone()
    conn.close()
    return row


def update_category(cat_id, name):
    conn = get_db()
    conn.execute("UPDATE categories SET name=? WHERE id=?", (name, cat_id))
    conn.commit()
    conn.close()


def is_descendant_of(cat_id, ancestor_id):
    """Return True if ancestor_id is a descendant of cat_id (circular ref check)."""
    conn = get_db()
    current = ancestor_id
    visited = set()
    while current is not None:
        if current == cat_id:
            conn.close()
            return True
        if current in visited:
            break
        visited.add(current)
        row = conn.execute("SELECT parent_id FROM categories WHERE id=?",
                           (current,)).fetchone()
        current = row["parent_id"] if row else None
    conn.close()
    return False


def update_category_parent(cat_id, parent_id):
    """Move a category under a different parent (or to top level if parent_id is None)."""
    conn = get_db()
    conn.execute("UPDATE categories SET parent_id=? WHERE id=?", (parent_id, cat_id))
    conn.commit()
    conn.close()


def delete_category(cat_id, page_action="uncategorize", target_category_id=None):
    """Delete a category and handle its pages.

    page_action:
        "uncategorize" - move pages to uncategorized (default, backward-compatible)
        "delete"       - delete all pages in this category
        "move"         - move pages to target_category_id
    """
    conn = get_db()
    if page_action == "delete":
        # Delete pages (and their history/drafts via CASCADE)
        conn.execute("DELETE FROM pages WHERE category_id=? AND is_home=0", (cat_id,))
    elif page_action == "move" and target_category_id:
        conn.execute("UPDATE pages SET category_id=? WHERE category_id=?",
                     (target_category_id, cat_id))
    else:
        conn.execute("UPDATE pages SET category_id=NULL WHERE category_id=?", (cat_id,))
    conn.execute("UPDATE categories SET parent_id=NULL WHERE parent_id=?", (cat_id,))
    conn.execute("DELETE FROM categories WHERE id=?", (cat_id,))
    conn.commit()
    conn.close()


def count_pages_in_category(cat_id):
    conn = get_db()
    cnt = conn.execute("SELECT COUNT(*) FROM pages WHERE category_id=? AND is_home=0",
                       (cat_id,)).fetchone()[0]
    conn.close()
    return cnt


def list_categories():
    conn = get_db()
    rows = conn.execute("SELECT * FROM categories ORDER BY sort_order, name").fetchall()
    conn.close()
    return rows


def get_category_tree():
    """Return nested category structure with pages."""
    cats = list_categories()
    conn = get_db()
    pages = conn.execute("SELECT * FROM pages WHERE is_home=0 ORDER BY sort_order, title").fetchall()
    conn.close()

    cat_map = {}
    for c in cats:
        cat_map[c["id"]] = {"id": c["id"], "name": c["name"], "parent_id": c["parent_id"],
                            "sequential_nav": c["sequential_nav"],
                            "children": [], "pages": []}

    for p in pages:
        if p["category_id"] and p["category_id"] in cat_map:
            cat_map[p["category_id"]]["pages"].append(dict(p))

    roots = []
    uncategorized_pages = [dict(p) for p in pages if not p["category_id"]]

    for cid, cat in cat_map.items():
        if cat["parent_id"] and cat["parent_id"] in cat_map:
            cat_map[cat["parent_id"]]["children"].append(cat)
        else:
            roots.append(cat)

    return roots, uncategorized_pages


def update_pages_sort_order(ordered_ids):
    """Assign sort_order 0, 1, 2, … to pages given in the specified order."""
    conn = get_db()
    for i, page_id in enumerate(ordered_ids):
        conn.execute("UPDATE pages SET sort_order=? WHERE id=?", (i, page_id))
    conn.commit()
    conn.close()


def update_categories_sort_order(ordered_ids):
    """Assign sort_order 0, 1, 2, … to categories given in the specified order."""
    conn = get_db()
    for i, cat_id in enumerate(ordered_ids):
        conn.execute("UPDATE categories SET sort_order=? WHERE id=?", (i, cat_id))
    conn.commit()
    conn.close()

