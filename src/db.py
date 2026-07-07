"""SQLite persistence layer: schema init + CRUD helpers.

Schema mirrors the PRD data model (contacts, companies, applications,
interactions, documents). One connection is opened per operation — fine at the
100–500 record scale this MVP targets, and avoids Streamlit thread-safety issues.
"""
import datetime
import difflib
import json
import sqlite3
from contextlib import contextmanager

from .config import DB_PATH, normalize_tag, normalize_tags, normalize_priority

SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    title TEXT,
    company TEXT,
    background TEXT,
    source_event TEXT,
    relationship_strength TEXT,   -- warm / cold / met once
    tags TEXT,                    -- JSON array
    last_interaction_date TEXT,   -- ISO date
    next_action TEXT,
    priority TEXT,                -- high / medium / low
    raw_notes TEXT
);

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    stage TEXT,
    industry TEXT,
    product_area TEXT,
    tags TEXT,                    -- JSON array
    notes TEXT
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role_title TEXT,
    company TEXT,
    jd_text TEXT,
    status TEXT,                  -- applied / phone screen / rejected / offer
    applied_date TEXT,            -- ISO date
    fit_notes TEXT,
    tags TEXT,                    -- JSON array
    outcome TEXT DEFAULT 'pending' -- terminal disposition (see config.APPLICATION_OUTCOMES)
);

CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id INTEGER,
    date TEXT,                    -- ISO date
    context TEXT,                 -- coffee chat / event / LinkedIn DM
    raw_notes TEXT,
    summary TEXT,                 -- LLM-generated
    key_insights TEXT,            -- LLM-generated (JSON array)
    follow_up_needed INTEGER,     -- 0/1 boolean
    follow_up_draft TEXT,         -- LLM-generated
    FOREIGN KEY (contact_id) REFERENCES contacts(id)
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_type TEXT,                -- contact / jd / interaction / insight
    source_id INTEGER,           -- FK to relevant table
    raw_text TEXT,
    embedding BLOB,              -- numpy float32 array, or NULL
    created_date TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    due_date TEXT,                -- ISO date, nullable
    done INTEGER DEFAULT 0,       -- 0/1
    contact_id INTEGER,          -- nullable link
    application_id INTEGER,      -- nullable link
    created_date TEXT
);

CREATE TABLE IF NOT EXISTS agent_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT,                      -- ISO timestamp
    command TEXT,                 -- the user's natural-language command
    summary TEXT,                 -- what was done (newline-joined)
    actions_json TEXT,            -- the confirmed plan
    undo_json TEXT,               -- snapshot record for revert
    status TEXT                   -- 'applied' | 'undone'
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT,
    kind TEXT,                    -- search_result / follow_up / insight / extraction
    rating INTEGER,               -- 1 = up/useful, 0 = down
    context TEXT,                 -- optional label
    model TEXT
);

CREATE TABLE IF NOT EXISTS extraction_eval (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT,
    kept INTEGER,                 -- LLM filled a field, user kept it as-is (correct)
    edited INTEGER,               -- LLM filled a field, user changed the value
    over INTEGER,                 -- LLM filled a field, user cleared it (over-extraction)
    missed INTEGER,               -- LLM left a field empty, user filled it in (a miss)
    model TEXT
);

CREATE TABLE IF NOT EXISTS emb_cache (
    kind TEXT,                    -- contact / application / interaction
    source_id INTEGER,
    text_hash TEXT,               -- to detect stale vectors
    vector BLOB,                  -- numpy float32
    PRIMARY KEY (kind, source_id)
);
"""


def _parse_date(s):
    """Parse a date from ISO or Notion's 'June 21, 2026' style. None if unknown."""
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


@contextmanager
def get_conn():
    """Yield a connection with dict-like rows and FK enforcement."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
    normalize_all_tags()
    normalize_all_priorities()


def _migrate(conn):
    """Additive migrations for DBs created before a column existed. Idempotent."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(applications)").fetchall()}
    if "outcome" not in cols:
        conn.execute("ALTER TABLE applications ADD COLUMN outcome TEXT DEFAULT 'pending'")


def normalize_all_priorities():
    """Canonicalise contact priority casing (idempotent, changed-only)."""
    with get_conn() as conn:
        for r in conn.execute("SELECT id, priority FROM contacts").fetchall():
            n = normalize_priority(r["priority"])
            if n != (r["priority"] or ""):
                conn.execute("UPDATE contacts SET priority = ? WHERE id = ?", (n, r["id"]))


def normalize_all_tags():
    """Rewrite existing tags through the canonical map (idempotent, changed-only)."""
    with get_conn() as conn:
        for table in ("contacts", "applications", "companies"):
            for r in conn.execute(f"SELECT id, tags FROM {table}").fetchall():
                cur = _load_tags(r["tags"])
                norm = normalize_tags(cur)
                if norm != cur:
                    conn.execute(f"UPDATE {table} SET tags = ? WHERE id = ?",
                                 (json.dumps(norm), r["id"]))


# --- Inserts ----------------------------------------------------------------

def add_contact(conn, *, name, title, company, background, source_event,
                relationship_strength, tags, last_interaction_date,
                next_action, priority, raw_notes):
    cur = conn.execute(
        """INSERT INTO contacts
           (name, title, company, background, source_event, relationship_strength,
            tags, last_interaction_date, next_action, priority, raw_notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (name, title, company, background, source_event, relationship_strength,
         tags, last_interaction_date, next_action, priority, raw_notes),
    )
    return cur.lastrowid


def add_company(conn, *, name, stage, industry, product_area, tags, notes):
    cur = conn.execute(
        """INSERT INTO companies (name, stage, industry, product_area, tags, notes)
           VALUES (?,?,?,?,?,?)""",
        (name, stage, industry, product_area, tags, notes),
    )
    return cur.lastrowid


def add_application(conn, *, role_title, company, jd_text, status,
                    applied_date, fit_notes, tags, outcome="pending"):
    cur = conn.execute(
        """INSERT INTO applications
           (role_title, company, jd_text, status, applied_date, fit_notes, tags, outcome)
           VALUES (?,?,?,?,?,?,?,?)""",
        (role_title, company, jd_text, status, applied_date, fit_notes, tags, outcome),
    )
    return cur.lastrowid


def add_interaction(conn, *, contact_id, date, context, raw_notes, summary,
                    key_insights, follow_up_needed, follow_up_draft):
    cur = conn.execute(
        """INSERT INTO interactions
           (contact_id, date, context, raw_notes, summary, key_insights,
            follow_up_needed, follow_up_draft)
           VALUES (?,?,?,?,?,?,?,?)""",
        (contact_id, date, context, raw_notes, summary, key_insights,
         int(bool(follow_up_needed)), follow_up_draft),
    )
    return cur.lastrowid


def add_document(conn, *, doc_type, source_id, raw_text, embedding, created_date):
    cur = conn.execute(
        """INSERT INTO documents (doc_type, source_id, raw_text, embedding, created_date)
           VALUES (?,?,?,?,?)""",
        (doc_type, source_id, raw_text, embedding, created_date),
    )
    return cur.lastrowid


# --- Reads (used by the view pages) -----------------------------------------

def list_contacts():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, title, company, priority, relationship_strength, "
            "tags, next_action, last_interaction_date FROM contacts ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def list_applications():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, role_title, company, status, applied_date, tags "
            "FROM applications ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def all_contacts():
    """Full contact rows (all columns) — used by search retrieval."""
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM contacts").fetchall()
    return [dict(r) for r in rows]


def all_applications():
    """Full application rows (all columns) — used by search retrieval."""
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM applications").fetchall()
    return [dict(r) for r in rows]


def get_application(application_id):
    """Single full application row, or None."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM applications WHERE id = ?",
                           (application_id,)).fetchone()
    return dict(row) if row else None


def delete_application(application_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM applications WHERE id = ?", (application_id,))


def delete_all_applications():
    with get_conn() as conn:
        conn.execute("DELETE FROM applications")
        # Reset AUTOINCREMENT so a fresh re-import numbers from 1 again.
        conn.execute("DELETE FROM sqlite_sequence WHERE name = 'applications'")


def get_contact(contact_id):
    """Single full contact row, or None."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM contacts WHERE id = ?",
                           (contact_id,)).fetchone()
    return dict(row) if row else None


def latest_interaction_for_contact(contact_id):
    """Most recent interaction for a contact, or None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM interactions WHERE contact_id = ? ORDER BY id DESC LIMIT 1",
            (contact_id,)).fetchone()
    return dict(row) if row else None


def add_verbatim_note(contact_id, text):
    """Attach a note to a contact verbatim (no LLM). Stores the full text in
    raw_notes with a short preview as the summary, and bumps last_interaction_date."""
    today = datetime.date.today().isoformat()
    first = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    preview = (first[:200] + "…") if len(first) > 200 else first
    with get_conn() as conn:
        iid = add_interaction(
            conn, contact_id=contact_id, date=today, context="note",
            raw_notes=text, summary=preview, key_insights="[]",
            follow_up_needed=False, follow_up_draft="")
        conn.execute("UPDATE contacts SET last_interaction_date = ? WHERE id = ?",
                     (today, contact_id))
    return iid


def interaction_counts():
    """Map of contact_id -> number of interactions (for coffee-chat badges)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT contact_id, COUNT(*) AS n FROM interactions "
            "WHERE contact_id IS NOT NULL GROUP BY contact_id").fetchall()
    return {r["contact_id"]: r["n"] for r in rows}


def interactions_for_contact(contact_id):
    """All interactions for a contact, newest first — for the profile view."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM interactions WHERE contact_id = ? "
            "ORDER BY date DESC, id DESC", (contact_id,)).fetchall()
    return [dict(r) for r in rows]


# --- Agent: read helpers (entity resolution) --------------------------------

def find_contacts(query=""):
    """Contacts matching a name/company/tag/keyword substring (all if empty)."""
    q = (query or "").strip().lower()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, title, company, priority, tags, background, next_action "
            "FROM contacts").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if not q:
            out.append(d)
            continue
        blob = " ".join(filter(None, [d.get("name"), d.get("company"), d.get("title"),
                                      d.get("background"), d.get("tags")])).lower()
        if q in blob:
            out.append(d)
    return out


def _norm(s):
    return (s or "").strip().lower()


def _norm_co(s):
    """Company key for comparison — lowercase alphanumerics only, so
    'MeshyAI' and 'Meshy AI' compare equal."""
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def find_duplicate_pairs(threshold=0.72):
    """Heuristic duplicate detection: fuzzy name match + compatible company.

    Returns list of (contact_a, contact_b, reason). Conservative enough that two
    genuinely different people who share only a first name are NOT flagged."""
    rows = find_contacts("")
    pairs = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            a, b = rows[i], rows[j]
            na, nb = _norm(a.get("name")), _norm(b.get("name"))
            if not na or not nb:
                continue
            ratio = difflib.SequenceMatcher(None, na, nb).ratio()
            ta, tb = set(na.split()), set(nb.split())
            shared = ta & tb
            substring = na in nb or nb in na
            name_match = (ratio >= threshold or substring or len(shared) >= 2
                          or (shared and (len(ta) == 1 or len(tb) == 1)))
            if not name_match:
                continue
            ca, cb = _norm_co(a.get("company")), _norm_co(b.get("company"))
            company_ok = (not ca or not cb or ca == cb or ca in cb or cb in ca)
            if not company_ok:
                continue
            bits = []
            if substring or shared:
                bits.append("similar name")
            if ca and cb and (ca == cb or ca in cb or cb in ca):
                bits.append("same company")
            pairs.append((a, b, ", ".join(bits) or "similar name"))
    return pairs


def _load_tags(raw):
    try:
        v = json.loads(raw) if raw else []
        return v if isinstance(v, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def merge_contacts(primary_id, secondary_id):
    """Merge secondary into primary: reassign its interactions/tasks/documents,
    union tags, fill empty primary fields from secondary, delete secondary."""
    if primary_id == secondary_id:
        return
    with get_conn() as conn:
        prim = conn.execute("SELECT * FROM contacts WHERE id = ?", (primary_id,)).fetchone()
        sec = conn.execute("SELECT * FROM contacts WHERE id = ?", (secondary_id,)).fetchone()
        if not prim or not sec:
            return
        prim, sec = dict(prim), dict(sec)

        conn.execute("UPDATE interactions SET contact_id = ? WHERE contact_id = ?",
                     (primary_id, secondary_id))
        conn.execute("UPDATE tasks SET contact_id = ? WHERE contact_id = ?",
                     (primary_id, secondary_id))
        conn.execute("UPDATE documents SET source_id = ? "
                     "WHERE doc_type = 'contact' AND source_id = ?",
                     (primary_id, secondary_id))

        tags = _load_tags(prim.get("tags"))
        for t in _load_tags(sec.get("tags")):
            if t not in tags:
                tags.append(t)

        fills = {"tags": json.dumps(tags)}
        for f in ("title", "company", "background", "next_action", "priority",
                  "relationship_strength", "source_event", "last_interaction_date"):
            if not (prim.get(f) or "").strip() and (sec.get(f) or "").strip():
                fills[f] = sec[f]
        assignments = ", ".join(f"{k} = ?" for k in fills)
        conn.execute(f"UPDATE contacts SET {assignments} WHERE id = ?",
                     (*fills.values(), primary_id))
        conn.execute("DELETE FROM contacts WHERE id = ?", (secondary_id,))


def find_applications(status=None, applied_before_days=None):
    """Applications filtered by exact status and/or applied at least N days ago."""
    cutoff = None
    if applied_before_days is not None:
        cutoff = datetime.date.today() - datetime.timedelta(days=int(applied_before_days))
    out = []
    for a in all_applications():
        if status and (a.get("status") or "").strip().lower() != status.strip().lower():
            continue
        if cutoff is not None:
            d = _parse_date(a.get("applied_date"))
            if d is None or d > cutoff:
                continue
        out.append(a)
    return out


# --- Agent: write helpers (all take an open conn) ---------------------------

_EDITABLE_CONTACT_FIELDS = {
    "priority", "relationship_strength", "next_action",
    "title", "company", "source_event", "background",
}


_EDITABLE_APPLICATION_FIELDS = {
    "role_title", "company", "status", "applied_date", "fit_notes", "jd_text",
    "outcome",
}


def set_contact_field(conn, contact_id, field, value):
    """Set one whitelisted contact field. `field` is validated, so the f-string
    interpolation is safe (no SQL injection surface)."""
    if field not in _EDITABLE_CONTACT_FIELDS:
        raise ValueError(f"Field '{field}' is not editable.")
    conn.execute(f"UPDATE contacts SET {field} = ? WHERE id = ?", (value, contact_id))


def set_application_field(conn, application_id, field, value):
    """Set one whitelisted application field (validated — safe f-string)."""
    if field not in _EDITABLE_APPLICATION_FIELDS:
        raise ValueError(f"Field '{field}' is not editable.")
    conn.execute(f"UPDATE applications SET {field} = ? WHERE id = ?",
                 (value, application_id))


def application_outcome_stats():
    """Counts by outcome plus response & offer rates for the Dashboard funnel.

    - response_rate = replies (interview/offer/rejected) / applications that were
      "reachable" (those three + ghosted). Pending & withdrawn are excluded — you
      can't have a response rate on apps that haven't resolved or you pulled out of.
    - offer_rate    = offers / resolved applications (everything except pending &
      withdrawn). Returns None for a rate when its denominator is 0.
    """
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT COALESCE(NULLIF(TRIM(outcome), ''), 'pending') AS o FROM applications"
        ).fetchall()
    counts = {}
    for r in rows:
        counts[r["o"]] = counts.get(r["o"], 0) + 1
    total = sum(counts.values())
    responded = counts.get("interview", 0) + counts.get("offer", 0) + counts.get("rejected", 0)
    reachable = responded + counts.get("ghosted", 0)
    resolved = total - counts.get("pending", 0) - counts.get("withdrawn", 0)
    return {
        "counts": counts,
        "total": total,
        "response_rate": (responded / reachable) if reachable else None,
        "offer_rate": (counts.get("offer", 0) / resolved) if resolved else None,
    }


def restore_row(conn, table, snapshot):
    """Restore a full contacts/applications row from a snapshot dict (agent undo).

    `table` is whitelisted and `snapshot` keys are real column names (from
    SELECT *), so the f-string interpolation is safe."""
    if table not in ("contacts", "applications"):
        raise ValueError("unsupported table")
    cols = [k for k in snapshot.keys() if k != "id"]
    assignments = ", ".join(f"{c} = ?" for c in cols)
    conn.execute(f"UPDATE {table} SET {assignments} WHERE id = ?",
                 (*[snapshot[c] for c in cols], snapshot["id"]))


def _modify_tags(conn, table, row_id, tag, add=True):
    tag = normalize_tag(tag)
    row = conn.execute(f"SELECT tags FROM {table} WHERE id = ?", (row_id,)).fetchone()
    try:
        tags = json.loads(row["tags"]) if row and row["tags"] else []
        if not isinstance(tags, list):
            tags = []
    except (json.JSONDecodeError, TypeError):
        tags = []
    if add and tag and tag not in tags:
        tags.append(tag)
    elif not add and tag in tags:
        tags.remove(tag)
    conn.execute(f"UPDATE {table} SET tags = ? WHERE id = ?",
                 (json.dumps(tags), row_id))


def add_contact_tag(conn, contact_id, tag):
    _modify_tags(conn, "contacts", contact_id, tag, add=True)


def remove_contact_tag(conn, contact_id, tag):
    _modify_tags(conn, "contacts", contact_id, tag, add=False)


def add_application_tag(conn, application_id, tag):
    _modify_tags(conn, "applications", application_id, tag, add=True)


def remove_application_tag(conn, application_id, tag):
    _modify_tags(conn, "applications", application_id, tag, add=False)


# --- Tasks ------------------------------------------------------------------

def add_task(conn, *, title, due_date=None, contact_id=None, application_id=None):
    cur = conn.execute(
        "INSERT INTO tasks (title, due_date, done, contact_id, application_id, created_date) "
        "VALUES (?,?,0,?,?,?)",
        (title, due_date or None, contact_id, application_id,
         datetime.date.today().isoformat()))
    return cur.lastrowid


def list_tasks(include_done=False):
    q = ("SELECT t.*, c.name AS contact_name FROM tasks t "
         "LEFT JOIN contacts c ON c.id = t.contact_id")
    if not include_done:
        q += " WHERE t.done = 0"
    q += " ORDER BY (t.due_date IS NULL), t.due_date ASC, t.id DESC"
    with get_conn() as conn:
        rows = conn.execute(q).fetchall()
    return [dict(r) for r in rows]


def set_task_done(task_id, done=True):
    with get_conn() as conn:
        conn.execute("UPDATE tasks SET done = ? WHERE id = ?",
                     (1 if done else 0, task_id))


def delete_task(task_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))


# --- Agent audit log --------------------------------------------------------

def add_agent_log(command, summary, actions, undo):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO agent_log (ts, command, summary, actions_json, undo_json, status) "
            "VALUES (?,?,?,?,?, 'applied')",
            (datetime.datetime.now().isoformat(timespec="seconds"),
             command or "", summary or "",
             json.dumps(actions), json.dumps(undo)))


def list_agent_log(limit=20):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM agent_log ORDER BY id DESC LIMIT ?",
                           (int(limit),)).fetchall()
    return [dict(r) for r in rows]


def latest_undoable_log():
    """Most recent applied (not-yet-undone) agent action, or None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM agent_log WHERE status = 'applied' "
            "ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def mark_log_undone(log_id):
    with get_conn() as conn:
        conn.execute("UPDATE agent_log SET status = 'undone' WHERE id = ?", (log_id,))


# --- Feedback (AI-quality metrics) ------------------------------------------

def add_feedback(kind, rating, context=None, model=None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO feedback (ts, kind, rating, context, model) VALUES (?,?,?,?,?)",
            (datetime.datetime.now().isoformat(timespec="seconds"),
             kind, int(rating), context, model))


def feedback_stats():
    """Per-kind positive rate: {kind: {up, total, rate}}."""
    with get_conn() as conn:
        rows = conn.execute("SELECT kind, rating FROM feedback").fetchall()
    agg = {}
    for r in rows:
        up, total = agg.get(r["kind"], (0, 0))
        agg[r["kind"]] = (up + (1 if r["rating"] == 1 else 0), total + 1)
    return {k: {"up": up, "total": total, "rate": (up / total if total else 0)}
            for k, (up, total) in agg.items()}


# --- Extraction quality (online correction-rate instrumentation) ------------

def add_extraction_eval(*, kept, edited, over, missed, model=None):
    """Log one Add-Note save: how the LLM's extraction compared to what the user
    actually saved. The user's edits on the review screen are the ground truth."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO extraction_eval (ts, kept, edited, over, missed, model) "
            "VALUES (?,?,?,?,?,?)",
            (datetime.datetime.now().isoformat(timespec="seconds"),
             int(kept), int(edited), int(over), int(missed), model))


def extraction_eval_stats():
    """Aggregate extraction quality across all saved notes.

    - accuracy        = kept / populated (fields the LLM filled and the user left alone)
    - correction_rate = (edited + over) / populated (fields the user fixed or removed)
    - miss_rate       = missed / (populated + missed) (fields the LLM left for the user)
    Rates are None when their denominator is 0.
    """
    with get_conn() as conn:
        rows = conn.execute("SELECT kept, edited, over, missed FROM extraction_eval").fetchall()
    kept = sum(r["kept"] for r in rows)
    edited = sum(r["edited"] for r in rows)
    over = sum(r["over"] for r in rows)
    missed = sum(r["missed"] for r in rows)
    populated = kept + edited + over
    return {
        "saves": len(rows),
        "kept": kept, "edited": edited, "over": over, "missed": missed,
        "populated": populated,
        "accuracy": (kept / populated) if populated else None,
        "correction_rate": ((edited + over) / populated) if populated else None,
        "miss_rate": (missed / (populated + missed)) if (populated + missed) else None,
    }


# --- Embedding cache (semantic search) --------------------------------------

def upsert_embedding(kind, source_id, text_hash, vector_blob):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO emb_cache (kind, source_id, text_hash, vector) VALUES (?,?,?,?) "
            "ON CONFLICT(kind, source_id) DO UPDATE SET "
            "text_hash = excluded.text_hash, vector = excluded.vector",
            (kind, source_id, text_hash, vector_blob))


def get_embedding_hashes():
    with get_conn() as conn:
        rows = conn.execute("SELECT kind, source_id, text_hash FROM emb_cache").fetchall()
    return {(r["kind"], r["source_id"]): r["text_hash"] for r in rows}


def get_cached_embeddings():
    with get_conn() as conn:
        rows = conn.execute("SELECT kind, source_id, vector FROM emb_cache").fetchall()
    return {(r["kind"], r["source_id"]): r["vector"] for r in rows}


def cached_embedding_count():
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM emb_cache").fetchone()["n"]


def enrich_contact(conn, *, contact_id, date, add_tags, next_action):
    """When attaching a new interaction to an existing contact: merge in any new
    tags, bump last_interaction_date, and optionally update next_action."""
    row = conn.execute("SELECT tags FROM contacts WHERE id = ?",
                       (contact_id,)).fetchone()
    try:
        existing = json.loads(row["tags"]) if row and row["tags"] else []
        if not isinstance(existing, list):
            existing = []
    except (json.JSONDecodeError, TypeError):
        existing = []
    for t in add_tags or []:
        if t and t not in existing:
            existing.append(t)
    fields = {"tags": json.dumps(existing), "last_interaction_date": date}
    if next_action:
        fields["next_action"] = next_action
    assignments = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE contacts SET {assignments} WHERE id = ?",
                 (*fields.values(), contact_id))


def list_interactions(limit=None):
    q = ("SELECT i.id, i.contact_id, i.date, i.context, i.summary, i.key_insights, "
         "i.follow_up_draft, c.name AS contact_name "
         "FROM interactions i LEFT JOIN contacts c ON c.id = i.contact_id "
         "ORDER BY i.id DESC")
    if limit:
        q += f" LIMIT {int(limit)}"
    with get_conn() as conn:
        rows = conn.execute(q).fetchall()
    return [dict(r) for r in rows]
