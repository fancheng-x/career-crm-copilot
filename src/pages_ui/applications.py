"""Applications view — table of applications + click-into full JD & fit notes."""
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


def _filter_applications(rows):
    with st.expander("🔎 Filters", expanded=False):
        c1, c2 = st.columns(2)
        status = c1.multiselect("Status", _distinct(rows, "status"))
        company = c2.multiselect("Company", _distinct(rows, "company"))
        tags = st.multiselect("Tags (any match)", _all_tags(rows))
        query = st.text_input("Search role / company", "")
    q = query.strip().lower()
    out = []
    for r in rows:
        if status and (r.get("status") or "").strip() not in status:
            continue
        if company and (r.get("company") or "").strip() not in company:
            continue
        if tags and not (set(_parse_list(r.get("tags"))) & set(tags)):
            continue
        if q:
            blob = " ".join(filter(None, [r.get("role_title"), r.get("company")])).lower()
            if q not in blob:
                continue
        out.append(r)
    return out


def render():
    st.header("💼 Applications")
    all_rows = db.list_applications()
    if not all_rows:
        st.info("No applications yet. Paste a JD from 📥 Add Note, or import from 📤 Import.")
        return

    rows = _filter_applications(all_rows)
    st.caption(f"Showing {len(rows)} of {len(all_rows)} · click a row to open it")
    if not rows:
        st.info("No applications match the current filters.")
        return

    ids = {r["id"] for r in rows}
    if st.session_state.get("app_sel_id") not in ids:
        st.session_state.app_sel_id = rows[0]["id"]

    # Hide internal id; tags become a real list so they render as chips.
    display = [{k: (_parse_list(v) if k == "tags" else v)
                for k, v in r.items() if k != "id"} for r in rows]
    event = st.dataframe(
        display, use_container_width=True, hide_index=True,
        on_select="rerun", selection_mode="single-row", key="apps_df",
        column_config={"tags": st.column_config.ListColumn("Tags")},
    )

    export_rows = [{**{k: v for k, v in r.items() if k != "id"},
                    "tags": ", ".join(_parse_list(r.get("tags")))} for r in rows]
    st.download_button("⬇️ Export shown applications (CSV)",
                       data=exporting.to_csv_bytes(export_rows),
                       file_name="applications.csv", mime="text/csv")

    sel_rows = list(event.selection.rows) if getattr(event, "selection", None) else []
    if sel_rows and sel_rows != st.session_state.get("_apps_prev_sel"):
        st.session_state.app_sel_id = rows[sel_rows[0]]["id"]
    st.session_state["_apps_prev_sel"] = sel_rows

    st.divider()
    st.subheader("Open an application")

    labels, label_to_id = [], {}
    for r in rows:
        lab = " — ".join(filter(None, [r.get("role_title"), r.get("company")]))
        lab = f"{lab or '(application)'}  (#{r['id']})"
        labels.append(lab)
        label_to_id[lab] = r["id"]

    cur_label = next((l for l, i in label_to_id.items()
                      if i == st.session_state.app_sel_id), labels[0])
    st.session_state["apps_pick"] = cur_label
    st.selectbox("Or pick from the list", labels, key="apps_pick",
                 on_change=_on_pick, args=(label_to_id,))

    _render_detail(st.session_state.app_sel_id)

    with st.expander("⚠️ Bulk cleanup (duplicates from a double import?)"):
        st.caption("Clear everything here, then re-import ONCE from 📤 Import "
                   "(upload only one CSV).")
        if st.checkbox("Yes, delete ALL applications", key="confirm_clear_apps"):
            if st.button("Delete all applications", type="primary"):
                db.delete_all_applications()
                st.session_state.pop("app_sel_id", None)
                st.success("Cleared. Re-import from 📤 Import.")
                st.rerun()


def _on_pick(label_to_id):
    st.session_state.app_sel_id = label_to_id[st.session_state["apps_pick"]]


def _render_detail(app_id):
    a = db.get_application(app_id)
    if not a:
        return

    st.markdown(f"### {a.get('role_title') or '(role)'}")
    if a.get("company"):
        st.caption(a["company"])

    cols = st.columns(3)
    cols[0].markdown(f"**Status:** {a.get('status') or '—'}")
    cols[1].markdown(f"**Applied:** {a.get('applied_date') or '—'}")
    tags = _parse_list(a.get("tags"))
    cols[2].markdown("**Tags:** " + (ui.tag_chips(tags) if tags else "—"))

    if a.get("fit_notes"):
        with st.expander("Fit notes / positioning / imported columns", expanded=True):
            st.write(a["fit_notes"])
    if a.get("jd_text"):
        with st.expander("Job description (JD)"):
            st.write(a["jd_text"])

    if st.button("🗑 Delete this application", key=f"del_app_{app_id}"):
        db.delete_application(app_id)
        st.session_state.pop("app_sel_id", None)
        st.rerun()
