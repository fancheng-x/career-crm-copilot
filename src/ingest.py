"""Shared persistence for an extracted/edited note payload.

Used by both Add Note (one manual note) and Import (a batch of coffee-chat notes)
so the write path — contacts + companies + interactions + documents — lives in
exactly one place.
"""
import datetime
import json

from . import db, embeddings
from .config import normalize_tags


def save_extraction(payload: dict, raw_text: str) -> dict:
    """Persist a normalized extraction payload.

    payload keys: contacts[], companies[], applications[], interaction_summary, key_insights[].
    Returns counts: {"contacts", "attached", "companies", "applications", "interactions"}.
    """
    today = datetime.date.today().isoformat()
    summary = payload.get("interaction_summary", "") or ""
    insights = payload.get("key_insights", []) or []
    insights_json = json.dumps(insights)
    counts = {"contacts": 0, "attached": 0, "companies": 0,
              "applications": 0, "interactions": 0}

    with db.get_conn() as conn:
        for ap in payload.get("applications", []):
            role = (ap.get("role_title") or "").strip()
            company = (ap.get("company") or "").strip()
            if not role and not company:
                continue
            # Pasting a JD means the user applied → default status "applied", dated today.
            aid = db.add_application(
                conn, role_title=role, company=company,
                jd_text=(ap.get("jd_text") or raw_text or "").strip(),
                status=ap.get("status") or "applied",
                applied_date=ap.get("applied_date") or today,
                fit_notes=(ap.get("fit_notes") or "").strip(),
                tags=json.dumps(normalize_tags(ap.get("tags", []))),
            )
            counts["applications"] += 1
            jd_doc = " | ".join(filter(None, [
                role, company, ap.get("fit_notes") or "", ap.get("jd_text") or ""]))
            db.add_document(
                conn, doc_type="jd", source_id=aid, raw_text=jd_doc,
                embedding=embeddings.to_blob(embeddings.embed_text(jd_doc)),
                created_date=today,
            )

        for co in payload.get("companies", []):
            name = (co.get("name") or "").strip()
            if not name:
                continue
            db.add_company(
                conn, name=name, stage=co.get("stage", ""),
                industry=co.get("industry", ""),
                product_area=co.get("product_area", ""),
                tags=json.dumps(normalize_tags(co.get("tags", []))), notes="",
            )
            counts["companies"] += 1

        for c in payload.get("contacts", []):
            name = (c.get("name") or "").strip()
            company = (c.get("company") or "").strip()
            background = (c.get("background") or "").strip()
            attach_id = c.get("attach_to_id")

            if attach_id:
                # Attach this interaction to an existing contact — no new row.
                cid = attach_id
                db.enrich_contact(
                    conn, contact_id=cid, date=today,
                    add_tags=c.get("tags", []), next_action=c.get("next_action", ""),
                )
                counts["attached"] += 1
            else:
                # Keep any contact with real signal; drop only truly empty ones.
                if not name and not (company or background):
                    continue
                if not name:
                    name = f"(unknown) {company or 'contact'}"
                cid = db.add_contact(
                    conn, name=name, title=c.get("title", ""), company=company,
                    background=background, source_event=c.get("source_event", ""),
                    relationship_strength=c.get("relationship_strength", "met once"),
                    tags=json.dumps(normalize_tags(c.get("tags", []))),
                    last_interaction_date=today,
                    next_action=c.get("next_action", ""),
                    priority=c.get("priority", "medium"), raw_notes=raw_text,
                )
                counts["contacts"] += 1
                # Fresh contact search-document (attached ones already have one).
                contact_text = " | ".join(filter(None, [
                    name, c.get("title", ""), company, background,
                    " ".join(c.get("tags", [])),
                ]))
                db.add_document(
                    conn, doc_type="contact", source_id=cid, raw_text=contact_text,
                    embedding=embeddings.to_blob(embeddings.embed_text(contact_text)),
                    created_date=today,
                )

            follow_up = c.get("follow_up_draft", "")
            iid = db.add_interaction(
                conn, contact_id=cid, date=today,
                context=c.get("source_event", "") or "note", raw_notes=raw_text,
                summary=summary, key_insights=insights_json,
                follow_up_needed=bool(follow_up), follow_up_draft=follow_up,
            )
            counts["interactions"] += 1

            interaction_text = summary + ("\n" + "\n".join(insights) if insights else "")
            db.add_document(
                conn, doc_type="interaction", source_id=iid,
                raw_text=interaction_text,
                embedding=embeddings.to_blob(embeddings.embed_text(interaction_text)),
                created_date=today,
            )

    return counts
