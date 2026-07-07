"""📤 Import — bring Notion (or any) CSV exports into the CRM.

Three modes:
  • Contacts / Applications — column-mapped direct insert (no LLM). Any columns
    you don't map are preserved (appended into notes) so nothing is lost — useful
    because a rich Notion tracker has far more columns than the CRM schema.
  • Coffee-chat notes — pick the note-text column; each row runs through the same
    LLM extraction as Add Note and is saved via the shared ingest path.

Notion export: open the database → ••• → Export → "Markdown & CSV".
"""
import csv
import datetime
import io
import json

import streamlit as st

from .. import db, llm, ingest
from ..config import ANTHROPIC_API_KEY

_NONE = "— none —"

CONTACT_FIELDS = [
    ("name", "Name"), ("title", "Title"), ("company", "Company"),
    ("background", "Background"), ("source_event", "Source event"),
    ("relationship_strength", "Relationship"), ("tags", "Tags (comma-separated)"),
    ("next_action", "Next action"), ("priority", "Priority"),
]
APPLICATION_FIELDS = [
    ("role_title", "Role title"), ("company", "Company"), ("jd_text", "JD text"),
    ("status", "Status"), ("applied_date", "Applied date"),
    ("fit_notes", "Fit notes"), ("tags", "Tags (comma-separated)"),
]

# Header-name hints for auto-mapping common Notion columns (case-insensitive).
_GUESS = {
    "name": ["people name", "name", "full name"],
    "title": ["role", "title", "position"],
    "company": ["company", "organization"],
    "background": ["description", "background", "bio", "notes"],
    "source_event": ["platform", "source", "channel"],
    "relationship_strength": ["relationship tier", "relationship", "tier", "status"],
    "tags": ["insight tags", "tags", "industry cluster", "role category"],
    "next_action": ["next action", "next step"],
    "priority": ["priority"],
    "role_title": ["role title", "role", "title", "position"],
    "jd_text": ["jd (paste)", "jd", "job description", "jd text"],
    "status": ["stage", "status"],
    "applied_date": ["applied date", "date applied", "applied"],
    "fit_notes": ["notes", "fit notes", "positioning angle"],
}


def _read_csv(uploaded):
    raw = uploaded.getvalue()
    try:
        text = raw.decode("utf-8-sig")  # Notion/Excel export → UTF-8 (+ BOM)
    except UnicodeDecodeError:
        text = raw.decode("latin-1")     # last-resort fallback, never crash
    reader = csv.DictReader(io.StringIO(text))
    rows = [dict(r) for r in reader]
    return (reader.fieldnames or []), rows


def _split_tags(raw):
    if not raw:
        return []
    parts = [t.strip() for t in raw.replace(";", ",").split(",") if t.strip()]
    from ..config import normalize_tags
    return normalize_tags(parts)


def _guess(field, headers):
    """Pick the best-matching header for a field, or None."""
    hints = _GUESS.get(field, [])
    lower = {h.lower(): h for h in headers if h}
    for hint in hints:                       # exact match first
        if hint in lower:
            return lower[hint]
    for hint in hints:                       # then substring
        for h in headers:
            if h and hint in h.lower():
                return h
    return None


def _mapper(fields, headers, prefix):
    """Render one selectbox per target field; return {field: header|None}."""
    mapping = {}
    cols = st.columns(2)
    options = [_NONE] + headers
    for i, (field, label) in enumerate(fields):
        with cols[i % 2]:
            guess = _guess(field, headers)
            idx = options.index(guess) if guess in options else 0
            picked = st.selectbox(label, options, index=idx, key=f"{prefix}_{field}")
            mapping[field] = None if picked == _NONE else picked
    return mapping


def _extra_notes(row, mapping, headers, preserve):
    """Build a 'Header: value' block from columns not mapped to any field."""
    if not preserve:
        return ""
    used = {v for v in mapping.values() if v}
    lines = []
    for h in headers:
        if h and h not in used:
            val = (row.get(h) or "").strip()
            if val:
                lines.append(f"{h}: {val}")
    return "\n".join(lines)


def render():
    st.header("📤 Import")
    st.caption("Upload a CSV exported from Notion (database → ••• → Export → "
               "Markdown & CSV). Map columns, then import.")

    uploaded = st.file_uploader("CSV file", type=["csv"])
    if not uploaded:
        st.info("Export each Notion database as CSV and upload it here. Structured "
                "trackers map directly; coffee-chat notes run through LLM extraction.")
        return

    headers, rows = _read_csv(uploaded)
    if not rows:
        st.warning("That CSV has no data rows.")
        return
    st.success(f"Loaded **{len(rows)}** rows · **{len(headers)}** columns.")
    with st.expander("Preview first 5 rows (check the text looks right, not garbled)"):
        st.dataframe(rows[:5], use_container_width=True)

    target = st.radio(
        "Import these rows as",
        ["Contacts", "Applications", "Coffee-chat notes (LLM extract)"],
        horizontal=True,
    )

    if target == "Contacts":
        _import_structured(headers, rows, CONTACT_FIELDS, "contact", _save_contacts)
    elif target == "Applications":
        _import_structured(headers, rows, APPLICATION_FIELDS, "app", _save_applications)
    else:
        _import_notes(headers, rows)


# --- Structured import (contacts / applications) ----------------------------

def _import_structured(headers, rows, fields, prefix, save_fn):
    st.markdown("#### Map columns")
    st.caption("Auto-guessed where possible — check and adjust the dropdowns.")
    mapping = _mapper(fields, headers, prefix)
    preserve = st.checkbox(
        "Keep unmapped columns (append them into notes so nothing is lost)",
        value=True,
    )
    if st.button(f"Import {len(rows)} rows", type="primary"):
        if all(v is None for v in mapping.values()):
            st.warning("Map at least one column first.")
            return
        imported, skipped = save_fn(rows, mapping, headers, preserve)
        st.success(f"Imported **{imported}** row(s).")
        if skipped:
            st.caption(f"Skipped {skipped} row(s) with no usable data.")


def _save_contacts(rows, m, headers, preserve):
    today = datetime.date.today().isoformat()
    imported = skipped = 0
    with db.get_conn() as conn:
        for r in rows:
            def g(f):
                return (r.get(m[f]) or "").strip() if m.get(f) else ""
            name, company, background = g("name"), g("company"), g("background")
            if not name and not (company or background):
                skipped += 1
                continue
            extra = _extra_notes(r, m, headers, preserve)
            full_bg = background + (("\n\n" + extra) if extra else "")
            db.add_contact(
                conn, name=name or f"(unknown) {company or 'contact'}",
                title=g("title"), company=company, background=full_bg,
                source_event=g("source_event"),
                relationship_strength=g("relationship_strength") or "met once",
                tags=json.dumps(_split_tags(g("tags"))),
                last_interaction_date=today, next_action=g("next_action"),
                priority=g("priority") or "medium", raw_notes=extra,
            )
            imported += 1
    return imported, skipped


def _save_applications(rows, m, headers, preserve):
    imported = skipped = 0
    with db.get_conn() as conn:
        for r in rows:
            def g(f):
                return (r.get(m[f]) or "").strip() if m.get(f) else ""
            role, company = g("role_title"), g("company")
            if not role and not company:
                skipped += 1
                continue
            extra = _extra_notes(r, m, headers, preserve)
            full_notes = g("fit_notes") + (("\n\n" + extra) if extra else "")
            db.add_application(
                conn, role_title=role, company=company, jd_text=g("jd_text"),
                status=g("status"), applied_date=g("applied_date"),
                fit_notes=full_notes, tags=json.dumps(_split_tags(g("tags"))),
            )
            imported += 1
    return imported, skipped


# --- Coffee-chat notes (LLM extraction per row) -----------------------------

def _import_notes(headers, rows):
    if not ANTHROPIC_API_KEY:
        st.error("ANTHROPIC_API_KEY is not set — needed to extract notes.")
        return
    note_col = st.selectbox("Which column holds the note text?", headers)
    non_empty = sum(1 for r in rows if (r.get(note_col) or "").strip())
    st.warning(
        f"This runs **{non_empty}** LLM extraction calls (one per non-empty row) — "
        "it costs API tokens and may take a while for large exports. "
        "Try a small CSV first."
    )
    if st.button(f"Extract & import {non_empty} note(s)", type="primary"):
        totals = {"contacts": 0, "companies": 0, "interactions": 0}
        errors = 0
        progress = st.progress(0.0, text="Starting...")
        for i, r in enumerate(rows):
            text = (r.get(note_col) or "").strip()
            if text:
                try:
                    extraction = llm.extract(text)
                    c = ingest.save_extraction(extraction, text)
                    for k in totals:
                        totals[k] += c[k]
                except Exception:
                    errors += 1
            progress.progress((i + 1) / len(rows),
                              text=f"Processed {i + 1}/{len(rows)}")
        progress.empty()
        st.success(
            f"Imported {totals['contacts']} contact(s), "
            f"{totals['companies']} company(ies), "
            f"{totals['interactions']} interaction(s)."
        )
        if errors:
            st.warning(f"{errors} row(s) failed to extract and were skipped.")
