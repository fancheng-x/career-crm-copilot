"""🤖 Assistant — natural-language commands that change your data (with confirm).

Reads run live so the agent can resolve who/what you mean; any write is shown as
a plan you must confirm before it touches the database. Every applied plan is
recorded in a persistent audit log, and undo pops the most recent applied action
(so it survives restarts and supports multiple steps back).
"""
import json

import streamlit as st

from .. import agent, db
from ..config import ANTHROPIC_API_KEY

_EXAMPLES = [
    "把 Lauren Vamos 的 priority 改成 high，下周一提醒我 follow up",
    "给所有投了但没回音超过两周的申请加 tag 'no response'",
    "把 Power 的 work sample 进度加到 next actions",
]


def _reset():
    st.session_state.agent_msgs = []
    st.session_state.agent_chat = []
    st.session_state.pending_plan = None
    st.session_state.pending_command = ""


def render():
    st.header("🤖 Assistant")
    st.caption("Tell it what to change. It resolves who/what you mean, asks if "
               "anything is ambiguous, and shows a plan you confirm before it writes.")

    if not ANTHROPIC_API_KEY:
        st.error("ANTHROPIC_API_KEY is not set.")
        return

    st.session_state.setdefault("agent_msgs", [])
    st.session_state.setdefault("agent_chat", [])
    st.session_state.setdefault("pending_plan", None)
    st.session_state.setdefault("pending_command", "")

    with st.expander("Examples"):
        for e in _EXAMPLES:
            st.markdown(f"- {e}")

    undoable = db.latest_undoable_log()
    cols = st.columns(2)
    if st.session_state.agent_chat and cols[0].button("🧹 New conversation"):
        _reset()
        st.rerun()
    if undoable and cols[1].button("↩️ Undo last action"):
        kept = agent.undo_plan(json.loads(undoable["undo_json"]))
        db.mark_log_undone(undoable["id"])
        msg = f"↩️ Reverted: {undoable['summary'].splitlines()[0] if undoable['summary'] else 'last action'}"
        if kept:
            msg += f"  ({kept} attached note(s) left in place — not undoable.)"
        st.session_state.agent_chat.append(("assistant", msg))
        st.rerun()

    # Conversation so far.
    for role, text in st.session_state.agent_chat:
        with st.chat_message("user" if role == "user" else "assistant"):
            st.markdown(text)

    # A pending plan blocks new input until confirmed / cancelled.
    if st.session_state.pending_plan is not None:
        _render_plan(st.session_state.pending_plan)
    else:
        prompt = st.chat_input("e.g. 把 Terry 标记成 high priority，下周五提醒 follow up")
        if prompt:
            st.session_state.agent_chat.append(("user", prompt))
            st.session_state.agent_msgs.append({"role": "user", "content": prompt})
            with st.spinner("Thinking…"):
                try:
                    outcome = agent.run_agent(st.session_state.agent_msgs)
                except Exception as e:
                    outcome = {"type": "message", "text": f"⚠️ Error: {e}"}
            if outcome["type"] == "message":
                st.session_state.agent_chat.append(("assistant", outcome["text"]))
            else:
                st.session_state.pending_plan = outcome["actions"]
                st.session_state.pending_command = prompt
                st.session_state.agent_chat.append(
                    ("assistant", "Here's the plan — review and confirm below. ⬇️"))
            st.rerun()

    _render_audit_log()


def _render_plan(actions):
    with st.chat_message("assistant"):
        st.markdown("**Proposed changes** (nothing is saved until you confirm):")
        if not actions:
            st.info("The plan is empty.")
        for a in actions:
            st.markdown(f"- {a.get('summary', '(action)')}")
        c1, c2 = st.columns(2)
        if c1.button("✅ Confirm & apply", type="primary", use_container_width=True):
            try:
                done, undo = agent.apply_plan(actions)
                db.add_agent_log(st.session_state.get("pending_command", ""),
                                 "\n".join(done), actions, undo)
                msg = "✅ Done:\n" + "\n".join(f"- {d}" for d in done)
                if undo.get("attach_notes"):
                    msg += "\n\n_(Attached notes can't be undone.)_"
                st.session_state.agent_chat.append(("assistant", msg))
            except Exception as e:
                st.session_state.agent_chat.append(("assistant", f"⚠️ Failed: {e}"))
            st.session_state.pending_plan = None
            st.session_state.pending_command = ""
            st.session_state.agent_msgs = []
            st.rerun()
        if c2.button("✖ Cancel", use_container_width=True):
            st.session_state.pending_plan = None
            st.session_state.pending_command = ""
            st.session_state.agent_msgs = []
            st.session_state.agent_chat.append(("assistant", "Cancelled — nothing changed."))
            st.rerun()


def _render_audit_log():
    entries = db.list_agent_log(limit=20)
    if not entries:
        return
    with st.expander("🧾 Action history (audit log)"):
        for e in entries:
            icon = "↩️ undone" if e["status"] == "undone" else "✅ applied"
            st.markdown(f"**{e['ts']}** · {icon}")
            if e.get("command"):
                st.caption(f"“{e['command']}”")
            for line in (e.get("summary") or "").splitlines():
                st.markdown(f"- {line}")
            st.divider()
