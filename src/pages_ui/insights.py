"""Insights Digest — synthesize themes/signals/gaps from recent interactions."""
import streamlit as st

from .. import db, llm, ui
from ..config import ANTHROPIC_API_KEY


def render():
    st.header("💡 Insights")
    st.caption(
        "A weekly career decision memo from your recent interactions: strongest "
        "signals, relationship opportunities, positioning shift, gaps, and next actions."
    )

    if not ANTHROPIC_API_KEY:
        st.error("ANTHROPIC_API_KEY is not set.")
        return

    total = len(db.list_interactions())
    if total == 0:
        st.info("No interactions yet. Add some notes from 📥 Add Note first.")
        return

    n = st.slider("How many recent interactions to include", 1,
                  max(total, 1), min(10, total))

    if st.button("✨ Generate weekly decision memo", type="primary"):
        interactions = db.list_interactions(limit=n)
        with st.spinner("Synthesizing..."):
            try:
                st.session_state["digest"] = llm.synthesize_insights(interactions)
            except Exception as e:
                st.error(f"Synthesis failed: {e}")
                return

    digest = st.session_state.get("digest")
    if digest:
        _render(digest)


def _render(memo):
    st.divider()
    st.subheader("🗞️ Weekly decision memo")
    if memo.get("strongest_signals"):
        st.markdown("**📈 Strongest signals**")
        for s in memo["strongest_signals"]:
            st.markdown(f"- {s}")
    if memo.get("relationship_opportunities"):
        st.markdown("**🤝 Relationship opportunities**")
        for r in memo["relationship_opportunities"]:
            st.markdown(f"- {r}")
    if memo.get("positioning_shift"):
        st.markdown("**🧭 Positioning shift**")
        st.info(memo["positioning_shift"])
    if memo.get("gaps"):
        st.markdown("**🕳️ Gaps**")
        for g in memo["gaps"]:
            st.markdown(f"- {g}")
    if memo.get("next_actions"):
        st.markdown("**✅ Next actions**")
        for a in memo["next_actions"]:
            st.markdown(f"- {a}")
    st.divider()
    ui.feedback_widget("insight", key="fb_insight", label="Was this memo actionable?")
