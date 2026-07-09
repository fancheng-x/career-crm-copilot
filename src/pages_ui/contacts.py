"""Contacts view — table of all contacts + click-into profile & interaction history."""
import json

import streamlit as st

from .. import db, exporting, ui


def _parse_list(raw):
    try:
        v = json.loads(raw) if raw else []
        return v if isinstance(v, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _distinct(rows, key):
    return sorted({(r.get(key) or "").strip() for r in rows if (r.get(key) or "").strip()})


def _all_tags(rows):
    s = set()
    for r in rows:
        s.update(_parse_list(r.get("tags")))
    return sorted(s)


def _filter_contacts(rows, counts):
    with st.expander("🔎 Filters", expanded=False):
        c1, c2, c3 = st.columns(3)
        pri = c1.multiselect("Priority", _distinct(rows, "priority"))
        rel = c2.multiselect("Relationship", _distinct(rows, "relationship_strength"))
        comp = c3.multiselect("Company", _distinct(rows, "company"))
        c4, c5 = st.columns([3, 1])
        tags = c4.multiselect("Tags (any match)", _all_tags(rows))
        chats_only = c5.checkbox("💬 chatted only")
    out = []
    for r in rows:
        if pri and (r.get("priority") or "").strip() not in pri:
            continue
        if rel and (r.get("relationship_strength") or "").strip() not in rel:
            continue
        if comp and (r.get("company") or "").strip() not in comp:
            continue
        if tags and not (set(_parse_list(r.get("tags"))) & set(tags)):
            continue
        if chats_only and not counts.get(r["id"]):
            continue
        out.append(r)
    return out


def render():
    st.header("👤 Contacts")
    all_rows = db.list_contacts()
    if not all_rows:
        st.info("No contacts yet. Add a note from 📥 Add Note, or import from 📤 Import.")
        return

    _render_dedup()

    counts = db.interaction_counts()
    rows = _filter_contacts(all_rows, counts)
    chatted = sum(1 for r in rows if counts.get(r["id"]))
    st.caption(f"Showing {len(rows)} of {len(all_rows)} · 💬 {chatted} with coffee "
               "chats · click a row to open it")
    if not rows:
        st.info("No contacts match the current filters.")
        return

    # Keep a valid current selection in session state.
    ids = {r["id"] for r in rows}
    if st.session_state.get("contact_sel_id") not in ids:
        st.session_state.contact_sel_id = rows[0]["id"]

    # Table with a leading 💬 column + single-row click selection.
    # Internal id is hidden; tags become a real list so they render as chips.
    display = []
    for r in rows:
        d = {"💬": (f"💬 {counts[r['id']]}" if counts.get(r["id"]) else "")}
        for k, v in r.items():
            if k == "id":
                continue
            d[k] = _parse_list(v) if k == "tags" else v
        display.append(d)
    event = st.dataframe(
        display, use_container_width=True, hide_index=True,
        on_select="rerun", selection_mode="single-row", key="contacts_df",
        column_config={"tags": st.column_config.ListColumn("Tags")},
    )

    export_rows = [{**{k: v for k, v in r.items() if k != "id"},
                    "tags": ", ".join(_parse_list(r.get("tags")))} for r in rows]
    st.download_button("⬇️ Export shown contacts (CSV)",
                       data=exporting.to_csv_bytes(export_rows),
                       file_name="contacts.csv", mime="text/csv")

    # A table click drives the selection — but only when it actually changes,
    # so the dropdown below can still override it.
    sel_rows = list(event.selection.rows) if getattr(event, "selection", None) else []
    if sel_rows and sel_rows != st.session_state.get("_contacts_prev_sel"):
        st.session_state.contact_sel_id = rows[sel_rows[0]]["id"]
    st.session_state["_contacts_prev_sel"] = sel_rows

    st.divider()
    st.subheader("Open a contact")

    # Contacts with coffee chats float to the top (stable within each group).
    ordered = sorted(rows, key=lambda r: 0 if counts.get(r["id"]) else 1)
    labels, label_to_id = [], {}
    for r in ordered:
        n = counts.get(r["id"], 0)
        badge = f"💬{n} " if n else ""
        lab = f"{badge}{r['name']}" + (f" — {r['company']}" if r.get("company") else "")
        lab = f"{lab}  (#{r['id']})"          # keep unique
        labels.append(lab)
        label_to_id[lab] = r["id"]

    # Sync the dropdown to the current selection (so a table click updates it too).
    cur_label = next((l for l, i in label_to_id.items()
                      if i == st.session_state.contact_sel_id), labels[0])
    st.session_state["contacts_pick"] = cur_label
    st.selectbox("Or pick from the list", labels, key="contacts_pick",
                 on_change=_on_pick, args=(label_to_id,))

    _render_detail(st.session_state.contact_sel_id)


def _on_pick(label_to_id):
    st.session_state.contact_sel_id = label_to_id[st.session_state["contacts_pick"]]


def _render_dedup():
    pairs = db.find_duplicate_pairs()
    if not pairs:
        return
    with st.expander(f"🔗 Possible duplicate contacts ({len(pairs)})"):
        st.caption("Merging moves the other contact's interactions, tasks, and tags "
                   "into the one you keep, fills any empty fields, then deletes the duplicate.")
        for a, b, reason in pairs[:12]:
            st.markdown(f"**{a['name']}** ({a.get('company') or '—'})  ⟷  "
                        f"**{b['name']}** ({b.get('company') or '—'})  ·  _{reason}_")
            c1, c2, c3 = st.columns([1, 1, 2])
            if c1.button(f"Keep {a['name'][:18]}", key=f"mrgA_{a['id']}_{b['id']}"):
                db.merge_contacts(a["id"], b["id"])
                st.rerun()
            if c2.button(f"Keep {b['name'][:18]}", key=f"mrgB_{a['id']}_{b['id']}"):
                db.merge_contacts(b["id"], a["id"])
                st.rerun()
            c3.caption("or ignore")
            st.divider()


def _render_detail(contact_id):
    c = db.get_contact(contact_id)
    if not c:
        return

    st.markdown(f"### {c['name']}")
    meta = " · ".join(filter(None, [c.get("title"), c.get("company")]))
    if meta:
        st.caption(meta)

    cols = st.columns(3)
    cols[0].markdown(f"**Priority:** {c.get('priority') or '—'}")
    cols[1].markdown(f"**Relationship:** {c.get('relationship_strength') or '—'}")
    cols[2].markdown(f"**Last interaction:** {c.get('last_interaction_date') or '—'}")

    tags = _parse_list(c.get("tags"))
    if tags:
        st.markdown("**Tags:** " + ui.tag_chips(tags))
    if c.get("next_action"):
        st.markdown(f"**Next action:** {c['next_action']}")
    if c.get("source_event"):
        st.caption(f"Source: {c['source_event']}")

    if c.get("background"):
        with st.expander("Background / imported notes", expanded=True):
            st.write(c["background"])

    st.markdown("#### 🗒️ Interaction history")

    with st.expander("➕ Add a note to this contact (saved verbatim — no AI)"):
        note = st.text_area("Note", key=f"newnote_{contact_id}", height=160,
                            placeholder="Paste your full coffee-chat notes here…")
        if st.button("Save note", key=f"savenote_{contact_id}"):
            if note.strip():
                db.add_verbatim_note(contact_id, note)
                st.success("Saved.")
                st.rerun()
            else:
                st.warning("Write something first.")

    interactions = db.interactions_for_contact(contact_id)
    if not interactions:
        st.info("No coffee chats / notes logged yet. Add one above, or via 📥 Add Note.")
        return

    for it in interactions:
        with st.container(border=True, key=f"scard_int_{it['id']}"):
            head = " · ".join(filter(None, [it.get("date"), it.get("context")]))
            st.markdown(f"**{head}**")
            if it.get("summary"):
                st.write(it["summary"])
            insights = _parse_list(it.get("key_insights"))
            if insights:
                st.markdown("**Key insights:**")
                for ins in insights:
                    st.markdown(f"- {ins}")
            if it.get("follow_up_draft"):
                st.markdown("**Follow-up draft:**")
                st.caption(it["follow_up_draft"])
            # Full verbatim text (present for attached notes and manual notes).
            raw = (it.get("raw_notes") or "").strip()
            if raw and raw != (it.get("summary") or "").strip():
                with st.expander("📄 Full note"):
                    st.write(raw)
