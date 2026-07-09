"""Search — hybrid (semantic + keyword) retrieval + LLM rerank/synthesis.

Uses `retrieval.hybrid_search()` once a vector index is built (OpenAI key present),
otherwise falls back to `retrieval.search()` (keyword-only). The LLM then reranks
and synthesizes a ranked answer with an evidence quote per result.
"""
import streamlit as st

from .. import retrieval, llm, ui, embeddings, db
from ..config import ANTHROPIC_API_KEY

_KIND_ICON = {"contact": "👤", "application": "💼", "interaction": "🗒️"}


def render():
    st.header("🔍 Search")
    st.caption(
        "Ask a natural-language question. Retrieval finds candidate records; the "
        "LLM reranks them and explains why each is relevant with an evidence quote."
    )

    # Semantic index controls (only when an OpenAI key is present).
    sem_available = embeddings.embeddings_available()
    if sem_available:
        fresh, total = retrieval.index_status()
        c1, c2 = st.columns([3, 1])
        c1.caption(f"🧠 Semantic index: **{fresh}/{total}** records embedded"
                   + ("" if fresh == total else " — rebuild to include the rest"))
        if c2.button("🔄 Build / refresh"):
            with st.spinner("Embedding records…"):
                bar = st.progress(0.0)
                n, tot = retrieval.build_index(progress=lambda p: bar.progress(p))
                bar.empty()
            st.success(f"Embedded {n} new/changed of {tot}.")
            st.rerun()
    else:
        st.caption("Set OPENAI_API_KEY to enable semantic (hybrid) search — "
                   "currently keyword-only.")

    query = st.text_input(
        "Query",
        placeholder="who is most relevant to product analytics?",
    )
    use_llm = st.checkbox(
        "Synthesize with LLM (rerank + reasons + actions)",
        value=True,
        help="Uncheck for a faster, raw ranked list with no LLM call.",
    )

    if not st.button("Search", type="primary"):
        return
    if not query.strip():
        st.warning("Type a query first.")
        return

    # Use hybrid (semantic + keyword) when the index has vectors; else keyword.
    use_hybrid = sem_available and db.cached_embedding_count() > 0
    if use_hybrid:
        candidates = retrieval.hybrid_search(query)
        st.caption("Mode: 🧠 hybrid (semantic + keyword)")
    else:
        candidates = retrieval.search(query)
        if sem_available:
            st.caption("Mode: keyword — click **Build / refresh** above to enable semantic.")

    if not candidates:
        st.info("No matching records. Add some notes first, or try different keywords.")
        return

    if use_llm and ANTHROPIC_API_KEY:
        with st.spinner("Reranking and synthesizing..."):
            try:
                answer = llm.synthesize_search(query, candidates)
                _render_synthesis(answer)
            except Exception as e:
                st.error(f"LLM synthesis failed — showing raw matches instead. ({e})")
                _render_raw(candidates)
    else:
        if use_llm and not ANTHROPIC_API_KEY:
            st.info("ANTHROPIC_API_KEY not set — showing raw keyword matches.")
        _render_raw(candidates)

    # Always offer the underlying keyword matches for transparency.
    with st.expander("🔎 Raw keyword matches (retrieval debug)"):
        _render_raw(candidates)


def _render_synthesis(answer):
    if answer.get("summary"):
        st.markdown(f"**{answer['summary']}**")
    results = answer.get("results", [])
    if not results:
        st.info("The LLM found nothing genuinely relevant among the matches.")
        return
    for i, r in enumerate(results):
        icon = _KIND_ICON.get(r.get("kind", ""), "•")
        with st.container(border=True, key=f"scard_search_{i}"):
            st.markdown(f"### {icon} {r.get('title', '(untitled)')}")
            if r.get("why_relevant"):
                st.markdown(f"**Why relevant:** {r['why_relevant']}")
            if r.get("evidence_quote"):
                st.markdown(f"> {r['evidence_quote']}")
            if r.get("recommended_action"):
                st.markdown(f"**Recommended action:** {r['recommended_action']}")
            ui.feedback_widget("search_result",
                               key=f"fb_sr_{i}_{r.get('title', '')[:24]}",
                               context=r.get("title"), label="Useful?")


def _render_raw(candidates):
    for c in candidates:
        icon = _KIND_ICON.get(c["kind"], "•")
        st.markdown(f"{icon} **{c['label']}**  ·  score `{c['score']}`  ·  _{c['kind']}_")
        st.caption(c["text"][:300] + ("…" if len(c["text"]) > 300 else ""))
