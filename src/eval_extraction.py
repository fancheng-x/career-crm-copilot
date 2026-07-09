"""Extraction-quality helpers.

Two evaluation methods share the normalisation logic here:

- **Online (Method A):** `diff_counts()` compares the LLM's raw extraction against
  what the user actually saved on the Add Note review screen. Every user edit is a
  free ground-truth correction, so real usage measures the model for you. The counts
  are logged via `db.add_extraction_eval()` and surfaced on the Dashboard.
- **Offline (Method B):** the same normalisers back `scripts/eval_extraction.py`,
  which benchmarks `llm.extract()` against a hand-labelled gold set.

Fields with a UI-injected default (relationship_strength, priority) are deliberately
excluded — a default the user never touched must not read as a correction.
"""

# Scalar fields shown as editable for a NEW contact (defaults excluded, see above).
_CONTACT_NEW_SCALARS = ["name", "title", "company", "background",
                        "source_event", "next_action", "follow_up_draft"]
# In "attach to existing" mode only these are shown for editing.
_CONTACT_ATTACH_SCALARS = ["next_action", "follow_up_draft"]
_COMPANY_SCALARS = ["name", "stage", "industry", "product_area"]
# status/applied_date are excluded — they carry UI defaults the user never "typed".
_APPLICATION_SCALARS = ["role_title", "company", "fit_notes", "jd_text"]


def _norm(v):
    """Normalise a scalar for comparison (trim + lowercase)."""
    if v is None:
        return ""
    return str(v).strip().lower()


def _norm_set(v):
    """Normalise a list of strings into a set for order-insensitive comparison."""
    return {_norm(x) for x in (v or []) if _norm(x)}


def _classify(raw_v, final_v):
    """Bucket one scalar field into kept / edited / over / missed (or None to skip)."""
    r, f = _norm(raw_v), _norm(final_v)
    if r and f:
        return "kept" if r == f else "edited"
    if not r and f:
        return "missed"
    if r and not f:
        return "over"
    return None  # both empty — nothing to score


def _classify_list(raw_v, final_v):
    r, f = _norm_set(raw_v), _norm_set(final_v)
    if r and f:
        return "kept" if r == f else "edited"
    if not r and f:
        return "missed"
    if r and not f:
        return "over"
    return None


def diff_counts(extraction, edited, summary, insights):
    """Compare the raw LLM `extraction` to the user's saved values.

    `edited` is the dict built by the Add Note review screen
    ({"contacts": [...], "companies": [...]}); `summary` and `insights` are the
    final interaction summary and key-insight list. Returns
    {"kept", "edited", "over", "missed"} field counts.
    """
    tally = {"kept": 0, "edited": 0, "over": 0, "missed": 0}

    def bump(cat):
        if cat:
            tally[cat] += 1

    raw_contacts = extraction.get("contacts") or []
    for i, ec in enumerate(edited.get("contacts") or []):
        rc = raw_contacts[i] if i < len(raw_contacts) else {}
        if "attach_to_id" in ec:
            fields = _CONTACT_ATTACH_SCALARS
        else:
            fields = _CONTACT_NEW_SCALARS
        for fld in fields:
            bump(_classify(rc.get(fld), ec.get(fld)))
        bump(_classify_list(rc.get("tags"), ec.get("tags")))

    raw_companies = extraction.get("companies") or []
    for i, eco in enumerate(edited.get("companies") or []):
        rco = raw_companies[i] if i < len(raw_companies) else {}
        for fld in _COMPANY_SCALARS:
            bump(_classify(rco.get(fld), eco.get(fld)))
        bump(_classify_list(rco.get("tags"), eco.get("tags")))

    raw_apps = extraction.get("applications") or []
    for i, ea in enumerate(edited.get("applications") or []):
        ra = raw_apps[i] if i < len(raw_apps) else {}
        for fld in _APPLICATION_SCALARS:
            bump(_classify(ra.get(fld), ea.get(fld)))
        bump(_classify_list(ra.get("tags"), ea.get("tags")))

    bump(_classify(extraction.get("interaction_summary"), summary))
    bump(_classify_list(extraction.get("key_insights"), insights))
    return tally
