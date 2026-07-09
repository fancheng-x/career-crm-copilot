"""Action agent: turn a natural-language command into DB mutations.

Design: read tools (find_contacts / find_applications) run live so Claude can
resolve which records the user means. Writes are never executed by the model —
Claude ends with `propose_plan`, which we render for the user; only on explicit
confirmation does `apply_plan` mutate the database.
"""
import datetime
import json

from . import db, llm, ingest

# --- Read tools (executed live) ---------------------------------------------

FIND_CONTACTS = {
    "name": "find_contacts",
    "description": "Look up contacts by a name / company / tag / keyword substring "
                   "(empty query returns all). Use this to resolve who the user means.",
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
}

FIND_APPLICATIONS = {
    "name": "find_applications",
    "description": "Look up applications, optionally filtered by exact status "
                   "(e.g. 'Applied') and/or applied at least N days ago.",
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "applied_before_days": {"type": "integer"},
        },
    },
}

# --- Terminal tool: the proposal (NOT executed by the model) ----------------

PROPOSE_PLAN = {
    "name": "propose_plan",
    "description": "Propose the concrete set of changes to make, using real ids "
                   "you resolved. This is a proposal the user must confirm — it "
                   "does not execute anything.",
    "input_schema": {
        "type": "object",
        "properties": {
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["create_contact", "create_application",
                                     "set_contact_field", "set_application_field",
                                     "add_tag", "remove_tag", "create_task", "attach_note"],
                        },
                        "summary": {"type": "string",
                                     "description": "One-line human-readable description."},
                        "contact_ids": {"type": "array", "items": {"type": "integer"}},
                        "application_ids": {"type": "array", "items": {"type": "integer"}},
                        "field": {
                            "type": "string",
                            "description": "Field to set. Contact fields: priority, "
                                           "relationship_strength, next_action, title, company, "
                                           "source_event, background. Application fields: status, "
                                           "applied_date, role_title, company, fit_notes.",
                        },
                        "value": {"type": "string",
                                   "description": "The new value for the field."},
                        "tag": {"type": "string"},
                        "note_text": {"type": "string"},
                        "title": {"type": "string",
                                   "description": "Task title (create_task) or contact title/role "
                                                  "(create_contact)."},
                        "due_date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
                        "contact_id": {"type": "integer"},
                        "name": {"type": "string",
                                  "description": "Contact name — required for create_contact."},
                        "role_title": {"type": "string",
                                        "description": "Role title — for create_application."},
                        "company": {"type": "string",
                                     "description": "Company name — for create_contact / create_application."},
                        "status": {"type": "string",
                                    "description": "Application status for create_application "
                                                   "(e.g. applied); defaults to 'applied'."},
                    },
                    "required": ["action", "summary"],
                },
            }
        },
        "required": ["actions"],
    },
}

_TOOLS = [FIND_CONTACTS, FIND_APPLICATIONS, PROPOSE_PLAN]


def _system():
    today = datetime.date.today()
    return (
        "You are an action assistant for a personal job-search CRM. The user issues "
        "commands to CREATE or UPDATE their data (contacts, applications, tasks). "
        "To add records, use create_contact (needs name; optional title, company) or "
        "create_application (needs role_title and/or company; optional status, default 'applied'). "
        "You can change "
        "contact fields via set_contact_field (priority, relationship_strength e.g. 'Tier 1', "
        "next_action, title, company, source_event, background) and application fields via "
        "set_application_field (status, applied_date, role_title, company, fit_notes, "
        "outcome — one of pending/interview/offer/rejected/ghosted/withdrawn). "
        "Use find_contacts / find_applications to look up exactly which records they mean. "
        "NEVER guess when a name is ambiguous — if several records match, reply in "
        "plain text asking the user which one (do not call a tool). Only once every "
        "entity is unambiguously resolved to concrete ids, call propose_plan ONCE, by "
        "itself, with concrete actions and real ids. Do not execute anything yourself; "
        "propose_plan is only a proposal the user will confirm. "
        f"Today is {today.isoformat()} ({today.strftime('%A')}). Resolve relative dates "
        "like 'next Monday' or 'in two weeks' to an ISO date (YYYY-MM-DD). If you lack "
        "info you need (e.g. the text of a coffee-chat note to attach), ask for it. "
        "Every action must include a short human-readable 'summary'."
    )


def _fmt_contacts(rows):
    slim = [{"id": r["id"], "name": r.get("name"), "company": r.get("company"),
             "priority": r.get("priority"), "tags": r.get("tags")} for r in rows[:40]]
    return json.dumps({"count": len(rows), "contacts": slim})


def _fmt_apps(rows):
    slim = [{"id": r["id"], "role_title": r.get("role_title"), "company": r.get("company"),
             "status": r.get("status"), "applied_date": r.get("applied_date")}
            for r in rows[:60]]
    return json.dumps({"count": len(rows), "applications": slim})


def run_agent(messages, max_steps=6):
    """Drive the read/resolve loop. `messages` is mutated in place (valid history).

    Returns one of:
      {"type": "plan", "actions": [...]}       — a proposal awaiting confirmation
      {"type": "message", "text": "..."}       — a clarifying question / info reply
    """
    client = llm._get_client()
    for _ in range(max_steps):
        resp = client.messages.create(
            model=llm._active_model(),
            max_tokens=2048,
            system=_system(),
            tools=_TOOLS,
            messages=messages,
        )
        reads = [b for b in resp.content
                 if b.type == "tool_use" and b.name in ("find_contacts", "find_applications")]
        plan = next((b for b in resp.content
                     if b.type == "tool_use" and b.name == "propose_plan"), None)

        # Resolve reads first (a plan built before seeing results would be premature).
        if reads:
            messages.append({"role": "assistant", "content": resp.content})
            results = []
            for b in reads:
                if b.name == "find_contacts":
                    payload = _fmt_contacts(db.find_contacts(b.input.get("query", "")))
                else:
                    payload = _fmt_apps(db.find_applications(
                        b.input.get("status"), b.input.get("applied_before_days")))
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": payload})
            messages.append({"role": "user", "content": results})
            continue

        if plan is not None:
            # Terminal: do NOT append this turn — the command ends here pending
            # confirmation, and history stays valid (all prior tool_uses paired).
            return {"type": "plan", "actions": plan.input.get("actions", [])}

        # Plain text — a question or an answer. Append so the chat can continue.
        text = "\n".join(b.text for b in resp.content if b.type == "text").strip()
        messages.append({"role": "assistant", "content": resp.content})
        return {"type": "message", "text": text or "(no response)"}

    return {"type": "message", "text": "Sorry — I couldn't resolve that in a few steps. "
                                       "Try rephrasing or being more specific."}


def _cids(a):
    """Contact ids for an action — accept both plural and singular forms."""
    ids = list(a.get("contact_ids") or [])
    if a.get("contact_id") is not None:
        ids.append(a["contact_id"])
    return ids


def _aids(a):
    """Application ids for an action — accept both plural and singular forms."""
    ids = list(a.get("application_ids") or [])
    if a.get("application_id") is not None:
        ids.append(a["application_id"])
    return ids


def apply_plan(actions):
    """Execute a confirmed plan.

    Returns (done, undo):
      done — list of human-readable result strings.
      undo — a record usable by undo_plan() to revert the reversible parts
             (field edits, tag changes, created tasks). attach_note is NOT undoable.
    """
    done = []
    undo = {"contacts": [], "applications": [], "created_task_ids": [],
            "created_contact_ids": [], "created_application_ids": [], "attach_notes": 0}
    today = datetime.date.today().isoformat()

    # Which rows will direct writes touch (for before-snapshots)?
    touched_contacts, touched_apps = set(), set()
    for a in actions:
        t = a.get("action")
        if t in ("set_contact_field", "add_tag", "remove_tag"):
            touched_contacts.update(_cids(a))
        if t in ("set_application_field", "add_tag", "remove_tag"):
            touched_apps.update(_aids(a))

    with db.get_conn() as conn:
        for cid in touched_contacts:
            row = conn.execute("SELECT * FROM contacts WHERE id = ?", (cid,)).fetchone()
            if row:
                undo["contacts"].append(dict(row))
        for aid in touched_apps:
            row = conn.execute("SELECT * FROM applications WHERE id = ?", (aid,)).fetchone()
            if row:
                undo["applications"].append(dict(row))

        for a in actions:
            t = a.get("action")
            if t == "attach_note":
                continue  # handled below (own extraction + connection); not undoable
            n = 0
            if t == "create_contact":
                name = (a.get("name") or "").strip()
                if name:
                    cid = db.add_contact(
                        conn, name=name, title=a.get("title", "") or "",
                        company=a.get("company", "") or "", background="", source_event="",
                        relationship_strength="met once", tags="[]",
                        last_interaction_date=today, next_action="",
                        priority="medium", raw_notes="")
                    undo["created_contact_ids"].append(cid)
                    n = 1
            elif t == "create_application":
                role = (a.get("role_title") or a.get("title") or "").strip()
                company = (a.get("company") or "").strip()
                if role or company:
                    aid = db.add_application(
                        conn, role_title=role, company=company, jd_text="",
                        status=(a.get("status") or "applied"), applied_date=today,
                        fit_notes="", tags="[]")
                    undo["created_application_ids"].append(aid)
                    n = 1
            elif t == "set_contact_field":
                for cid in _cids(a):
                    db.set_contact_field(conn, cid, a.get("field", ""), a.get("value", ""))
                    n += 1
            elif t == "set_application_field":
                for aid in _aids(a):
                    db.set_application_field(conn, aid, a.get("field", ""), a.get("value", ""))
                    n += 1
            elif t == "add_tag":
                for cid in _cids(a):
                    db.add_contact_tag(conn, cid, a.get("tag", ""))
                    n += 1
                for aid in _aids(a):
                    db.add_application_tag(conn, aid, a.get("tag", ""))
                    n += 1
            elif t == "remove_tag":
                for cid in _cids(a):
                    db.remove_contact_tag(conn, cid, a.get("tag", ""))
                    n += 1
                for aid in _aids(a):
                    db.remove_application_tag(conn, aid, a.get("tag", ""))
                    n += 1
            elif t == "create_task":
                tid = db.add_task(conn, title=a.get("title") or "Task",
                                  due_date=a.get("due_date"), contact_id=a.get("contact_id"))
                undo["created_task_ids"].append(tid)
                n = 1
            summary = a.get("summary") or t
            if n == 0 and t != "create_task":
                if t in ("create_contact", "create_application"):
                    summary += "  ⚠️ (missing required fields — nothing created)"
                else:
                    summary += "  ⚠️ (no matching records — nothing changed)"
            done.append(summary)

    # attach_note: extract the note and attach the interaction to the contact.
    for a in actions:
        if a.get("action") != "attach_note":
            continue
        cid = a.get("contact_id") or next(iter(a.get("contact_ids") or []), None)
        note = a.get("note_text", "")
        if cid and note:
            extraction = llm.extract(note)
            fu = ""
            if extraction.get("contacts"):
                fu = extraction["contacts"][0].get("follow_up_draft", "")
            ingest.save_extraction({
                "contacts": [{"attach_to_id": cid, "follow_up_draft": fu}],
                "companies": [],
                "interaction_summary": extraction.get("interaction_summary", ""),
                "key_insights": extraction.get("key_insights", []),
            }, note)
            undo["attach_notes"] += 1
        done.append(a.get("summary") or "attach note")

    return done, undo


def undo_plan(undo):
    """Revert a plan applied by apply_plan(). Returns the count of non-undoable
    attach_note actions (which are left in place)."""
    with db.get_conn() as conn:
        for snap in undo.get("contacts", []):
            db.restore_row(conn, "contacts", snap)
        for snap in undo.get("applications", []):
            db.restore_row(conn, "applications", snap)
        for tid in undo.get("created_task_ids", []):
            conn.execute("DELETE FROM tasks WHERE id = ?", (tid,))
        for cid in undo.get("created_contact_ids", []):
            conn.execute("DELETE FROM contacts WHERE id = ?", (cid,))
        for aid in undo.get("created_application_ids", []):
            conn.execute("DELETE FROM applications WHERE id = ?", (aid,))
    return undo.get("attach_notes", 0)
