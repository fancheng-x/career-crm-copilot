"""Add Note page."""
import datetime, json
import streamlit as st
from .. import db, llm, embeddings, ingest, eval_extraction
from ..config import ANTHROPIC_API_KEY, TAG_VOCABULARY, PRIORITY_LEVELS, RELATIONSHIP_STRENGTHS

DEMO_NOTE = """Met two people at an ACL side event tonight.

First: works at Abaka AI, former Apple SWE for 3 years, just joined Abaka two weeks ago. We talked about AI productization, how 2C AI apps are at risk of being absorbed by ChatGPT, why enterprise AI needs FDE-style implementation, and what its like to transition from Big Tech to an early-stage AI startup. Very insightful, high energy.

Second: Ziyao, Yale PhD student working on multimodal learning for agents and robotics. Research areas: VLMs, world models, 3D vision, AI for Science. We talked about the gap between frontier research and real-world productization."""

def _tag_options(tags):
    opts = list(TAG_VOCABULARY)
    for t in tags:
        if t not in opts:
            opts.append(t)
    return opts

def render():
    st.header("📥 Add Note")
    st.caption("Paste a coffee chat recap, JD, contact info, or event notes. The LLM extracts contacts, companies, a summary, insights, and follow-up drafts.")

    if not ANTHROPIC_API_KEY:
        st.error("ANTHROPIC_API_KEY is not set. Export it and restart the app.")
        return

    raw_text = st.text_area("Raw note", value=st.session_state.get("raw_text", ""), height=220, placeholder="Paste your unstructured note here...")

    col_a, col_b = st.columns([1, 1])
    with col_a:
        if st.button("✨ Extract", type="primary", use_container_width=True):
            if not raw_text.strip():
                st.warning("Paste a note first.")
            else:
                with st.spinner("Extracting with the LLM..."):
                    try:
                        st.session_state["extraction"] = llm.extract(raw_text)
                        st.session_state["raw_text"] = raw_text
                        st.rerun()
                    except Exception as e:
                        st.error(f"Extraction failed: {e}")
    with col_b:
        if st.button("Load demo note", use_container_width=True):
            st.session_state["raw_text"] = DEMO_NOTE
            st.session_state.pop("extraction", None)
            st.rerun()

    extraction = st.session_state.get("extraction")
    if extraction:
        _render_review(extraction, st.session_state.get("raw_text", raw_text))

def _render_review(extraction, raw_text):
    st.divider()
    st.subheader("Review & edit")
    st.write(f"**Detected type:** `{extraction.get('type', 'mixed')}`")
    edited = {"contacts": [], "companies": []}

    st.markdown("### 👤 Contacts")
    existing = db.list_contacts()
    attach_labels = ["🆕 New contact"]
    attach_id_by_label = {}
    for ec in existing:
        lab = ec["name"] + (f" — {ec['company']}" if ec.get("company") else "")
        if lab in attach_id_by_label:            # keep labels unique
            lab = f"{lab} (#{ec['id']})"
        attach_labels.append(lab)
        attach_id_by_label[lab] = ec["id"]

    for i, c in enumerate(extraction["contacts"]):
        label = c.get("name") or "(unnamed)"
        with st.expander(f"Contact {i+1}: {label}", expanded=True):
            # Auto-select an existing contact with the same name → dedupes coffee-chat re-imports.
            default_idx, cname = 0, (c.get("name") or "").strip().lower()
            if cname:
                for j, ec in enumerate(existing):
                    if (ec["name"] or "").strip().lower() == cname:
                        default_idx = j + 1
                        break
            choice = st.selectbox("Save as", attach_labels, index=default_idx, key=f"x_c_mode_{i}")

            if choice == "🆕 New contact":
                name = st.text_input("Name", value=c.get("name",""), key=f"x_c_name_{i}")
                if not name.strip():
                    st.caption("⚠️ No name in the note — add one, or it saves under a placeholder (won't be dropped).")
                title      = st.text_input("Title",   value=c.get("title",""),   key=f"x_c_title_{i}")
                company    = st.text_input("Company", value=c.get("company",""), key=f"x_c_company_{i}")
                background = st.text_area( "Background", value=c.get("background",""), key=f"x_c_bg_{i}", height=80)
                src        = st.text_input("Source event", value=c.get("source_event",""), key=f"x_c_src_{i}")
                col1, col2 = st.columns(2)
                with col1:
                    rel = c.get("relationship_strength","met once")
                    rel_idx = RELATIONSHIP_STRENGTHS.index(rel) if rel in RELATIONSHIP_STRENGTHS else 2
                    relationship = st.selectbox("Relationship", RELATIONSHIP_STRENGTHS, index=rel_idx, key=f"x_c_rel_{i}")
                with col2:
                    pri = c.get("priority","medium")
                    pri_idx = PRIORITY_LEVELS.index(pri) if pri in PRIORITY_LEVELS else 1
                    priority = st.selectbox("Priority", PRIORITY_LEVELS, index=pri_idx, key=f"x_c_pri_{i}")
                tags      = st.multiselect("Tags", _tag_options(c.get("tags",[])), default=c.get("tags",[]), key=f"x_c_tags_{i}")
                next_act  = st.text_input("Next action", value=c.get("next_action",""), key=f"x_c_next_{i}")
                follow_up = st.text_area("Follow-up draft", value=c.get("follow_up_draft",""), key=f"x_c_follow_{i}", height=80)
                edited["contacts"].append({"name":name,"title":title,"company":company,"background":background,"source_event":src,"relationship_strength":relationship,"tags":tags,"next_action":next_act,"priority":priority,"follow_up_draft":follow_up})
            else:
                # Attach mode — compact: interaction + insights go onto the existing contact.
                st.caption(f"↪ Attaching this note's interaction & insights to **{choice}** — no new contact created.")
                tags      = st.multiselect("Tags to merge in", _tag_options(c.get("tags",[])), default=c.get("tags",[]), key=f"x_c_tags_{i}")
                next_act  = st.text_input("Update next action (optional)", value=c.get("next_action",""), key=f"x_c_next_{i}")
                follow_up = st.text_area("Follow-up draft", value=c.get("follow_up_draft",""), key=f"x_c_follow_{i}", height=80)
                edited["contacts"].append({"attach_to_id": attach_id_by_label[choice], "tags": tags, "next_action": next_act, "follow_up_draft": follow_up})

    st.markdown("### 🏢 Companies")
    for i, co in enumerate(extraction["companies"]):
        label = co.get("name") or "(unnamed)"
        with st.expander(f"Company {i+1}: {label}", expanded=True):
            name         = st.text_input("Name",         value=co.get("name",""),         key=f"x_co_name_{i}")
            col1, col2   = st.columns(2)
            with col1:
                stage    = st.text_input("Stage",        value=co.get("stage",""),        key=f"x_co_stage_{i}")
                industry = st.text_input("Industry",     value=co.get("industry",""),     key=f"x_co_ind_{i}")
            with col2:
                prod_area= st.text_input("Product area", value=co.get("product_area",""), key=f"x_co_pa_{i}")
            tags         = st.multiselect("Tags", _tag_options(co.get("tags",[])), default=co.get("tags",[]), key=f"x_co_tags_{i}")
            edited["companies"].append({"name":name,"stage":stage,"industry":industry,"product_area":prod_area,"tags":tags})

    st.markdown("### 🧠 Summary & insights")
    summary       = st.text_area("Interaction summary",      value=extraction.get("interaction_summary",""),           height=80,  key="x_summary")
    insights_text = st.text_area("Key insights (one per line)", value="\n".join(extraction.get("key_insights",[])), height=120, key="x_insights")

    st.divider()
    if not embeddings.embeddings_available():
        st.caption("ℹ️ OPENAI_API_KEY not set — saving without embeddings (semantic search will be limited).")

    if st.button("💾 Confirm & Save", type="primary"):
        insights = [ln.strip() for ln in insights_text.splitlines() if ln.strip()]
        try:
            counts = _save(edited, summary, insights, raw_text)
        except Exception as e:
            st.error(f"Save failed: {e}")
            return
        # Measure extraction quality: how the LLM's output compared to what you saved.
        # Logging must never block a save, so it's best-effort.
        try:
            ev = eval_extraction.diff_counts(extraction, edited, summary, insights)
            db.add_extraction_eval(**ev, model=st.session_state.get("model_id"))
        except Exception:
            pass
        st.success(
            f"Saved {counts['contacts']} new contact(s), "
            f"attached {counts['attached']} to existing, "
            f"{counts['interactions']} interaction(s), "
            f"{counts['companies']} company(ies)."
        )
        st.session_state.pop("extraction", None)
        st.session_state.pop("raw_text", None)
        st.balloons()

def _save(edited, summary, insights, raw_text):
    # Delegates to the shared write path (also used by the Import page).
    return ingest.save_extraction({
        "contacts": edited["contacts"],
        "companies": edited["companies"],
        "interaction_summary": summary,
        "key_insights": insights,
    }, raw_text)
