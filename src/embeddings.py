"""OpenAI embeddings + helpers.

Embeddings power the hybrid (semantic + keyword) search in `retrieval.py`.
If OPENAI_API_KEY is unset or a placeholder, embedding functions degrade
gracefully to None so the rest of the app still works with only an Anthropic key.
"""
import numpy as np

from .config import EMBEDDING_MODEL, EMBEDDING_DIM, OPENAI_API_KEY

_client = None


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI
        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


def _real_key() -> bool:
    """True only for a plausibly-real key (rejects the .env placeholder)."""
    return bool(OPENAI_API_KEY) and "..." not in OPENAI_API_KEY


def embeddings_available() -> bool:
    return _real_key()


def embed_text(text: str):
    """Return a float32 vector for `text`, or None if embeddings unavailable.

    Never raises: a missing/placeholder/invalid key just yields None so the
    caller (e.g. Add Note save) can proceed without embeddings.
    """
    if not text or not _real_key():
        return None
    try:
        resp = _get_client().embeddings.create(
            model=EMBEDDING_MODEL,
            input=text[:8000],  # keep well under the token limit
        )
        return np.array(resp.data[0].embedding, dtype=np.float32)
    except Exception:
        # Bad/revoked key, rate limit, network error — degrade gracefully.
        return None


def to_blob(vec):
    """Serialize a float32 vector for BLOB storage."""
    return None if vec is None else vec.astype(np.float32).tobytes()


def from_blob(blob):
    """Deserialize a BLOB back into a float32 vector."""
    return None if blob is None else np.frombuffer(blob, dtype=np.float32)


def build_faiss_index(vectors):
    """Build an in-memory L2 FAISS index from a list/array of vectors.

    Used by the (Phase 1 feature 4) semantic search page. Returns (index, matrix)
    or (None, None) when there is nothing to index.
    """
    import faiss

    if vectors is None or len(vectors) == 0:
        return None, None
    matrix = np.vstack(vectors).astype(np.float32)
    index = faiss.IndexFlatL2(EMBEDDING_DIM)
    index.add(matrix)
    return index, matrix
