"""Central configuration: env-based API keys, model IDs, paths, tag/priority hygiene."""
import os
from pathlib import Path

# Auto-load a .env file at the project root (if present). Real environment
# variables always win — load_dotenv does not override already-set values —
# so `export ANTHROPIC_API_KEY=...` still takes precedence over .env.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass  # python-dotenv optional; falls back to plain environment variables

# --- API keys (read from environment) ---------------------------------------
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# --- Models -----------------------------------------------------------------
# Default Claude model (used unless the user picks another in the sidebar).
# Override the default via the CAREER_CRM_MODEL env var.
CLAUDE_MODEL = os.environ.get("CAREER_CRM_MODEL", "claude-sonnet-4-6")

# Selectable models in the sidebar picker (any valid Claude model id works).
CLAUDE_MODELS = [
    "claude-opus-4-8",
    "claude-sonnet-4-6",
    "claude-opus-4-6",
    "claude-haiku-4-5",
]
if CLAUDE_MODEL not in CLAUDE_MODELS:
    CLAUDE_MODELS.insert(0, CLAUDE_MODEL)
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536

# --- Paths ------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "career_crm.db"

# --- Controlled tag vocabulary (from PRD) -----------------------------------
TAG_VOCABULARY = [
    "product analytics",
    "AI workflow",
    "RAG",
    "LLM evaluation",
    "FDE",
    "enterprise AI",
    "AI startup",
    "data analyst",
    "analytics engineering",
    "robotics",
    "multimodal agents",
    "AI for science",
    "operations analytics",
    "fraud analytics",
    "bizops",
    "GTM analytics",
    "career switcher",
    "warm contact",
    "referral potential",
]

# The user's career positioning — fed into follow-up, search, and insights so AI
# output aligns with their real direction. Kept deliberately concise: it goes into
# multiple prompts, so length here is a cost. Edit this to retune all three at once.
USER_POSITIONING = (
    "Analytics-driven product & operations problem solver focused on AI-enabled "
    "workflows; MSBA at UCSD. Role-driven, not industry-driven. Target roles: product "
    "analytics, product operations, operations analytics, AI/workflow analyst. Turns "
    "ambiguous product/ops problems into metrics, experiments, simulations, and "
    "executable recommendations; bridges business and technical (eng/data/AI) teams. "
    "Not seeking pure SWE / MLE / AI-research / mature-PM roles. Industry-flexible, "
    "leaning AI-native / enterprise AI, healthtech, robotics, marketplaces, and "
    "tech-enabled operations. Based in California (Bay Area / San Diego)."
)

PRIORITY_LEVELS = ["high", "medium", "low"]
RELATIONSHIP_STRENGTHS = ["warm", "cold", "met once"]

# Single canonical application pipeline (stage + terminal result in one field),
# in funnel order. Replaces the old split status/outcome model. Powers the
# Dashboard funnel (response rate, offer rate).
APPLICATION_STATUSES = [
    "applied", "screening", "interviewing", "offer",   # open / in progress
    "accepted", "rejected", "ghosted", "withdrawn",    # terminal
]
STATUS_DISPLAY = {
    "applied": "Applied", "screening": "Screening", "interviewing": "Interviewing",
    "offer": "Offer", "accepted": "Accepted", "rejected": "Rejected",
    "ghosted": "Ghosted", "withdrawn": "Withdrawn",
}
# For funnel maths: a company responded (a rejection IS a response); "applied" =
# still waiting, "ghosted" = no response; these two + "withdrawn" aren't "responses".
RESPONDED_STATUSES = {"screening", "interviewing", "offer", "accepted", "rejected"}
OFFER_STATUSES = {"offer", "accepted"}
OPEN_STATUSES = {"applied", "screening", "interviewing", "offer"}

# Map legacy / free-form status values onto the canonical set.
_STATUS_ALIASES = {
    "phone screen": "screening", "phone-screen": "screening", "screen": "screening",
    "interview": "interviewing", "interviews": "interviewing",
    "final round": "interviewing", "onsite": "interviewing", "": "applied",
}


def normalize_status(s):
    """Canonicalise a single status value (maps legacy values forward)."""
    k = (s or "").strip().lower()
    if k in APPLICATION_STATUSES:
        return k
    return _STATUS_ALIASES.get(k, k or "applied")

# Tag hygiene: map obvious variants to a canonical form (keys are lowercased).
# Conservative on purpose — only clear equivalents, so custom tags survive.
TAG_SYNONYMS = {
    "ai-native startup": "AI startup",
    "ai native startup": "AI startup",
    "ai startups": "AI startup",
    "early-stage ai": "AI startup",
    "early stage ai": "AI startup",
    "product analyst": "product analytics",
    "forward deployed engineer": "FDE",
    "forward-deployed engineer": "FDE",
    "implementation engineer": "FDE",
}

_VOCAB_LOWER = {t.lower(): t for t in TAG_VOCABULARY}


def normalize_tag(tag):
    """Map a tag to its canonical form: synonyms first, then vocabulary casing;
    otherwise keep it as-is (trimmed)."""
    key = (tag or "").strip()
    low = key.lower()
    if low in TAG_SYNONYMS:
        return TAG_SYNONYMS[low]
    if low in _VOCAB_LOWER:
        return _VOCAB_LOWER[low]
    return key


def normalize_tags(tags):
    """Normalize + de-duplicate a list of tags, preserving order."""
    out = []
    for t in tags or []:
        n = normalize_tag(t)
        if n and n not in out:
            out.append(n)
    return out


# Canonical priority (stored lowercase; displayed Title-cased). Fixes the
# High/high/Medium/medium/Medium-High casing mix from the Notion import.
def normalize_priority(p):
    k = (p or "").strip().lower().replace(" ", "-")
    if k in ("high", "medium-high", "medium", "low"):
        return k
    return {"h": "high", "m": "medium", "med": "medium", "l": "low"}.get(k, k)


PRIORITY_DISPLAY = {"high": "High", "medium-high": "Medium-High",
                    "medium": "Medium", "low": "Low"}
