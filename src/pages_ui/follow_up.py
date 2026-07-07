"""Follow-up Generator — draft an editable LinkedIn / WeChat / email message per contact."""
import streamlit as st

from .. import db, llm, ui
from ..config import ANTHROPIC_API_KEY, USER_POSITIONING

GOALS = ["coffee chat", "referral ask", "stay warm"]
CHANNELS = ["LinkedIn message", "WeChat message", "email"]


def render():
    st.header("✉️ Follow-up")
    st.caption(
        "Pick a contact and generate a personalized, editable draft based on "
        "their background and your last interaction."
    )

    if not ANTHROPIC_API_KEY:
        st.error("ANTHROPIC_API_KEY is not set.")
        return

    contacts = db.list_contacts()
    if not contacts:
        st.info("No contacts yet. Add some notes from 📥 Add Note first.")
        return

    # Contact picker: label -> id
    labels = {
        f"{c['name']}"
        + (f" — {c['company']}" if c.get("company") else ""): c["id"]
        for c in contacts
    }
    choice = st.selectbox("Contact", list(labels.keys()))
    contact_id = labels[choice]

    col1, col2 = st.columns(2)
    with col1:
        goal = st.selectbox("Goal", GOALS)
    with col2:
        channel = st.selectbox("Channel", CHANNELS)
    positioning = st.text_area("Your positioning", USER_POSITIONING, height=70)

    if st.button("✨ Generate draft", type="primary"):
        contact = db.get_contact(contact_id)
        interaction = db.latest_interaction_for_contact(contact_id)
        with st.spinner("Drafting..."):
            try:
                draft = llm.generate_follow_up(
                    contact, interaction,
                    positioning=positioning, goal=goal, channel=channel,
                )
                st.session_state["draft"] = draft
                st.session_state["draft_for"] = contact_id
            except Exception as e:
                st.error(f"Generation failed: {e}")
                return

    # Show the editable draft only for the currently selected contact.
    if st.session_state.get("draft") and st.session_state.get("draft_for") == contact_id:
        st.divider()
        edited = st.text_area("Draft (edit freely, then copy)",
                              st.session_state["draft"], height=160, key="draft_edit")
        count = len(edited)
        note = "  ⚠️ over 280" if (channel == "LinkedIn message" and count > 280) else ""
        st.caption(f"{count} characters{note}")
        st.caption("Select the text above and copy (Cmd/Ctrl+C).")
        ui.feedback_widget("follow_up", key=f"fb_fu_{contact_id}",
                           context=f"{goal} / {channel}", label="Was this draft usable?")
