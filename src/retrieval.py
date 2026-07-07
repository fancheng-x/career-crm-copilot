"""Retrieval over the local CRM.

`search()` is keyword-only (term overlap, tags weighted higher). `hybrid_search()`
blends that keyword score with OpenAI-embedding cosine similarity using a cached
vector index (`build_index()` / `index_status()`); it degrades to keyword scoring
when no embedding is available. Top candidates are then handed to the LLM for
reranking + synthesis.
"""
import hashlib
import json
import re

import numpy as np

from . import db, embeddings

# Small stopword set so common words don't dominate scoring.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "who", "what", "which", "is", "are", "my", "me", "i", "at", "about",
    "most", "relevant", "related", "someone", "people", "person", "find",
}


def _tokenize(text: str):
    return [t for t in re.findall(r"[a-z0-9]+", text.lower())
            if len(t) > 1 and t not in _STOPWORDS]


def _tags(raw):
    """Parse a JSON-array tags string into a list; tolerate bad/empty values."""
    if not raw:
        return []
    try:
        val = json.loads(raw)
        return val if isinstance(val, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _score(text: str, tags, terms):
    """Term overlap; a term matching a tag counts double."""
    text_l = text.lower()
    tags_l = " ".join(tags).lower()
    score = 0
    for t in terms:
        if t in tags_l:
            score += 2
        elif t in text_l:
            score += 1
    return score


def _candidates():
    """Flatten contacts, applications, interactions into uniform search records."""
    records = []

    for c in db.all_contacts():
        tags = _tags(c.get("tags"))
        text = " | ".join(filter(None, [
            c.get("name"), c.get("title"), c.get("company"),
            c.get("background"), c.get("next_action"), " ".join(tags),
        ]))
        label = " — ".join(filter(None, [
            c.get("name"),
            " @ ".join(filter(None, [c.get("title"), c.get("company")])),
        ]))
        records.append({"kind": "contact", "id": c["id"], "label": label or "(contact)",
                        "text": text, "tags": tags})

    for a in db.all_applications():
        tags = _tags(a.get("tags"))
        text = " | ".join(filter(None, [
            a.get("role_title"), a.get("company"), a.get("status"),
            a.get("fit_notes"), a.get("jd_text"), " ".join(tags),
        ]))
        label = " — ".join(filter(None, [a.get("role_title"), a.get("company")]))
        records.append({"kind": "application", "id": a["id"], "label": label or "(application)",
                        "text": text, "tags": tags})

    for it in db.list_interactions():
        insights = _tags(it.get("key_insights"))
        text = " | ".join(filter(None, [
            it.get("contact_name"), it.get("context"), it.get("summary"),
            " ".join(insights),
        ]))
        label = " — ".join(filter(None, [
            it.get("contact_name") or "interaction", it.get("context"),
        ]))
        records.append({"kind": "interaction", "id": it["id"], "label": label,
                        "text": text, "tags": insights})

    return records


def search(query: str, limit: int = 8):
    """Keyword-only search: up to `limit` scored records (score > 0), best first."""
    terms = _tokenize(query)
    if not terms:
        return []
    scored = []
    for rec in _candidates():
        s = _score(rec["text"], rec["tags"], terms)
        if s > 0:
            scored.append(dict(rec, score=s))
    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[:limit]


# --- Semantic / hybrid ------------------------------------------------------

def _text_hash(text):
    return hashlib.md5((text or "").encode("utf-8")).hexdigest()


def index_status():
    """(#records with a current embedding, #total searchable records)."""
    cands = _candidates()
    have = db.get_embedding_hashes()
    fresh = sum(1 for r in cands if have.get((r["kind"], r["id"])) == _text_hash(r["text"]))
    return fresh, len(cands)


def build_index(progress=None):
    """Embed any new/changed records and cache their vectors. Returns (new, total)."""
    cands = _candidates()
    have = db.get_embedding_hashes()
    n = 0
    for i, rec in enumerate(cands):
        h = _text_hash(rec["text"])
        if have.get((rec["kind"], rec["id"])) != h:
            vec = embeddings.embed_text(rec["text"])
            if vec is not None:
                db.upsert_embedding(rec["kind"], rec["id"], h, embeddings.to_blob(vec))
                n += 1
        if progress:
            progress((i + 1) / len(cands))
    return n, len(cands)


def _cosine(a, b):
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom else 0.0


def hybrid_search(query: str, limit: int = 8, alpha: float = 0.55):
    """Blend semantic similarity (weight `alpha`) with keyword score.

    Falls back to keyword behaviour if the query can't be embedded."""
    cands = _candidates()
    if not cands:
        return []
    terms = _tokenize(query)
    qvec = embeddings.embed_text(query)
    cache = db.get_cached_embeddings()

    kw = [_score(r["text"], r["tags"], terms) for r in cands]
    kw_max = max(kw) if kw else 0
    sem = []
    for r in cands:
        blob = cache.get((r["kind"], r["id"]))
        v = embeddings.from_blob(blob) if blob is not None else None
        sem.append(_cosine(qvec, v) if (qvec is not None and v is not None) else 0.0)
    sem_max = max(sem) if sem else 0

    scored = []
    for r, k, s in zip(cands, kw, sem):
        kn = (k / kw_max) if kw_max else 0.0
        sn = (s / sem_max) if sem_max else 0.0
        combined = alpha * sn + (1 - alpha) * kn
        if combined > 0:
            scored.append(dict(r, score=round(combined, 3)))
    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[:limit]
