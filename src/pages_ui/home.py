"""Home / Dashboard — overview: KPIs, distributions, to-dos, recent chats, digest."""
import datetime
import json
import re

import altair as alt
import pandas as pd
import streamlit as st

from .. import db, llm
from ..config import (ANTHROPIC_API_KEY, normalize_priority, PRIORITY_DISPLAY,
                      OUTCOME_DISPLAY)


def _parse_list(raw):
    try:
        v = json.loads(raw) if raw else []
        return v if isinstance(v, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _trunc(text, n):
    text = (text or "").strip().replace("\n", " ")
    return (text[:n] + "…") if len(text) > n else text


def _counts_by(rows, key, fallback):
    out = {}
    for r in rows:
        v = (r.get(key) or "").strip() or fallback
        out[v] = out.get(v, 0) + 1
    return out


def _tag_freq(rows):
    freq = {}
    for r in rows:
        for t in _parse_list(r.get("tags")):
            freq[t] = freq.get(t, 0) + 1
    return freq


def _geo(app):
    """Base / geo was folded into fit_notes on import ('Geo / Market: Bay Area')."""
    m = re.search(r"Geo\s*/\s*Market:\s*(.+)", app.get("fit_notes") or "")
    return m.group(1).strip() if m else ""


def _bar(title, mapping, top=None):
    st.markdown(f"**{title}**")
    if not mapping:
        st.caption("No data yet.")
        return
    items = sorted(mapping.items(), key=lambda kv: kv[1], reverse=True)
    if top:
        items = items[:top]
    df = pd.DataFrame(items, columns=["label", "count"])
    chart = (
        alt.Chart(df)
        .mark_bar(color="#2f8367", cornerRadiusEnd=3)
        .encode(
            x=alt.X("count:Q", title=None,
                    axis=alt.Axis(format="d", tickMinStep=1),
                    scale=alt.Scale(domainMin=0, nice=False)),
            y=alt.Y("label:N", sort="-x", title=None,
                    axis=alt.Axis(labelLimit=220)),
            tooltip=[alt.Tooltip("label:N", title="Category"),
                     alt.Tooltip("count:Q", title="Count")],
        )
        .properties(height=min(len(df) * 34 + 12, 280))
    )
    st.altair_chart(chart, use_container_width=True)


def _open_contact(contact_id):
    st.session_state.contact_sel_id = contact_id
    st.session_state.nav_target = "Contacts"
    st.rerun()


def _render_start_here():
    st.subheader("👋 Start here")
    st.markdown(
        "1. **Load your data** — upload your Notion CSVs on **📤 Import**, "
        "or paste your first note on **📥 Add Note**.\n"
        "2. **Review** the extracted contacts & applications on **👤 Contacts** / **💼 Applications**.\n"
        "3. **Use it** — ask a question on **🔍 Search**, draft a **✉️ Follow-up**, or tell the "
        "**🤖 Assistant** to update your data in plain language."
    )
    st.info("Once you add data, this page becomes your dashboard: KPIs, distributions, "
            "tasks, recent coffee chats, a weekly decision memo, and measured AI quality.")


def render():
    st.header("Dashboard")
    st.caption("A snapshot of your job-search knowledge base.")

    contacts = db.list_contacts()
    applications = db.all_applications()
    chat_counts = db.interaction_counts()
    interactions = db.list_interactions()
    todos = [c for c in contacts if (c.get("next_action") or "").strip()]

    # --- KPI cards ----------------------------------------------------------
    kpis = [("Contacts", len(contacts)), ("Coffee chats", len(chat_counts)),
            ("Applications", len(applications)), ("Open follow-ups", len(todos))]
    for col, (label, val) in zip(st.columns(4), kpis):
        with col.container(border=True):
            st.metric(label, val)

    if not contacts and not applications:
        _render_start_here()
        return

    dups = db.find_duplicate_pairs()
    if dups:
        st.caption(f"🔗 {len(dups)} possible duplicate contact(s) — review & merge on **Contacts**.")

    # --- Action center (what to do now — above the fold) -------------------
    st.subheader("🎯 Action center")
    left, right = st.columns(2)
    with left:
        st.markdown("**✅ Tasks**")
        _render_tasks(db.list_tasks())
        st.markdown("**⭐ High-priority, no next action**")
        _render_hp_no_action(contacts)
    with right:
        st.markdown("**📌 Follow-ups** (contacts with a next action)")
        _render_followups(todos)

    st.divider()

    # --- Recent intelligence -----------------------------------------------
    st.subheader("🧠 Recent intelligence")
    ci, cd = st.columns(2)
    with ci:
        st.markdown("**🗒️ Recent coffee chats**")
        _render_recent(interactions)
    with cd:
        st.markdown("**🪄 Weekly decision memo**")
        _render_digest()

    st.divider()

    # --- Pipeline overview --------------------------------------------------
    st.subheader("📊 Pipeline")
    r1a, r1b = st.columns(2)
    with r1a:
        _bar("Applications by status", _counts_by(applications, "status", "unknown"))
    with r1b:
        _bar("Applications by industry", _tag_freq(applications), top=8)
    r2a, r2b = st.columns(2)
    with r2a:
        geo = {}
        for a in applications:
            g = _geo(a)
            if g:
                geo[g] = geo.get(g, 0) + 1
        _bar("Applications by base / geo", geo)
    with r2b:
        pri = {}
        for c in contacts:
            p = normalize_priority(c.get("priority")) or "unset"
            lab = PRIORITY_DISPLAY.get(p, p.title())
            pri[lab] = pri.get(lab, 0) + 1
        _bar("Contacts by priority", pri)

    if applications:
        _render_outcomes()

    st.divider()
    _render_quality()


def _render_tasks(tasks):
    today = datetime.date.today().isoformat()
    if not tasks:
        st.caption("No open tasks — create one from the 🤖 Assistant.")
    for t in tasks[:5]:
        with st.container(border=True):
            check, body = st.columns([0.09, 0.91], vertical_alignment="center")
            if check.checkbox("done", key=f"task_{t['id']}", value=False,
                              label_visibility="collapsed"):
                db.set_task_done(t["id"], True)
                st.rerun()
            body.markdown(f"**{_trunc(t.get('title') or 'Task', 64)}**")
            meta = []
            if t.get("contact_name"):
                meta.append(t["contact_name"])
            if t.get("due_date"):
                overdue = t["due_date"] < today
                meta.append(("⚠️ overdue " if overdue else "due ") + t["due_date"])
            if meta:
                body.caption(" · ".join(meta))

    # Completed tasks — collapsible, with a Reopen button (undo an accidental tick).
    completed = [t for t in db.list_tasks(include_done=True) if t.get("done")]
    if completed:
        with st.expander(f"✔ Completed ({len(completed)})"):
            for t in completed[:20]:
                body, btn = st.columns([0.78, 0.22], vertical_alignment="center")
                body.markdown(f"~~{_trunc(t.get('title') or 'Task', 60)}~~")
                if btn.button("Reopen", key=f"reopen_{t['id']}"):
                    db.set_task_done(t["id"], False)
                    st.rerun()


def _render_hp_no_action(contacts):
    hp = [c for c in contacts
          if normalize_priority(c.get("priority")) == "high"
          and not (c.get("next_action") or "").strip()]
    if not hp:
        st.caption("None — every high-priority contact has a next action. 🎉")
        return
    for c in hp[:4]:
        with st.container(border=True):
            body, btn = st.columns([0.78, 0.22], vertical_alignment="center")
            head = c["name"] + (f" · {c['company']}" if c.get("company") else "")
            body.markdown(f"**{head}**")
            body.caption("no next action set")
            if btn.button("Open", key=f"hpna_{c['id']}"):
                _open_contact(c["id"])


def _render_followups(todos):
    if not todos:
        st.caption("No pending next-actions.")
        return
    for c in todos[:5]:
        with st.container(border=True):
            body, btn = st.columns([0.78, 0.22], vertical_alignment="center")
            head = c["name"] + (f" · {c['company']}" if c.get("company") else "")
            body.markdown(f"**{head}**")
            body.caption(_trunc(c["next_action"], 88))
            if btn.button("Open", key=f"todo_{c['id']}"):
                _open_contact(c["id"])


def _render_recent(interactions):
    recent = [it for it in interactions if it.get("summary")][:5]
    if not recent:
        st.caption("No coffee chats logged yet.")
        return
    for it in recent:
        with st.container(border=True):
            body, btn = st.columns([0.78, 0.22], vertical_alignment="center")
            head = " · ".join(filter(None, [it.get("contact_name") or "unknown",
                                            it.get("date")]))
            body.markdown(f"**{head}**")
            body.caption(_trunc(it.get("summary") or "", 120))
            cid = it.get("contact_id")
            if cid and btn.button("Open", key=f"recent_{it['id']}"):
                _open_contact(cid)


def _render_digest():
    if not ANTHROPIC_API_KEY:
        st.caption("Set ANTHROPIC_API_KEY to generate a memo.")
        return
    if st.button("✨ Generate weekly memo"):
        recent = db.list_interactions(limit=10)
        if not recent:
            st.info("No interactions to summarize yet.")
        else:
            with st.spinner("Summarizing…"):
                try:
                    st.session_state["home_digest"] = llm.synthesize_insights(recent)
                except Exception as e:
                    st.error(f"Failed: {e}")
    memo = st.session_state.get("home_digest")
    if not memo:
        st.caption("Generate a memo to surface recurring themes, positioning signals, "
                   "gaps, and next actions from your recent chats.")
        st.markdown("- 📈 Themes\n- 🧭 Positioning signals\n- ✅ Next actions")
        return
    if memo.get("strongest_signals"):
        st.markdown("**📈 Signals:** " + " · ".join(memo["strongest_signals"][:3]))
    if memo.get("positioning_shift"):
        st.caption(memo["positioning_shift"])
    for a in (memo.get("next_actions") or [])[:3]:
        st.markdown(f"- {a}")


def _render_outcomes():
    """Funnel outcome panel: response rate, offer rate, and a breakdown bar."""
    s = db.application_outcome_stats()
    if not s["total"]:
        return
    st.markdown("**🎯 Application outcomes**")
    rr, orr = s["response_rate"], s["offer_rate"]
    m1, m2 = st.columns(2)
    with m1.container(border=True):
        st.metric("Response rate", f"{rr * 100:.0f}%" if rr is not None else "No data")
        st.caption("got a reply ÷ apps that reached a decision")
    with m2.container(border=True):
        st.metric("Offer rate", f"{orr * 100:.0f}%" if orr is not None else "No data")
        st.caption("offers ÷ resolved apps")
    disp = {OUTCOME_DISPLAY.get(k, k.title()): v for k, v in s["counts"].items()}
    _bar("By outcome", disp)
    st.caption("Set an outcome on each row in 💼 Applications to populate this.")


_QUALITY_KINDS = [
    ("search_result", "Search usefulness"),
    ("follow_up", "Follow-up acceptance"),
    ("insight", "Insight value"),
]


def _render_quality():
    st.subheader("📊 AI quality (from your feedback)")
    stats = db.feedback_stats()
    total = sum(s["total"] for s in stats.values()) if stats else 0
    if total == 0:
        st.caption("Rate AI outputs with 👍/👎 on **Search**, **Follow-up**, and **Insights** "
                   "to populate these metrics.")
    for col, (kind, label) in zip(st.columns(len(_QUALITY_KINDS)), _QUALITY_KINDS):
        s = stats.get(kind)
        with col.container(border=True):
            if s and s["total"]:
                st.metric(label, f"{s['rate'] * 100:.0f}%")
                st.caption(f"{s['up']}/{s['total']} 👍")
            else:
                st.metric(label, "No data")
                st.caption("0 ratings yet")
