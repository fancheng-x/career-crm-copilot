"""Small shared UI helpers."""
import streamlit as st

from . import db


def _record_feedback(kind, key, context):
    val = st.session_state.get(key)
    if val is not None:
        db.add_feedback(kind, 1 if val == 1 else 0, context=context)


def feedback_widget(kind, key, context=None, label="Helpful?"):
    """A thumbs up/down widget that records the rating to the feedback table."""
    if label:
        st.caption(label)
    st.feedback("thumbs", key=key,
                on_change=_record_feedback, args=(kind, key, context))


def tag_chips(tags) -> str:
    """Render tags as inline Streamlit colored-background 'chips' (theme-aware).

    Returns a markdown string like ':blue-background[FinTech] :blue-background[RAG]'.
    """
    chips = []
    for t in tags:
        s = str(t).strip().replace("[", "(").replace("]", ")")  # brackets break the syntax
        if s:
            chips.append(f":green-background[{s}]")
    return " ".join(chips)
