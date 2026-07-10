"""Claude-backed extraction for the Add Note feature.

Uses forced tool use to get reliable structured JSON out of the model — portable
across model versions and cleaner than parsing free-form text.
"""
from .config import (ANTHROPIC_API_KEY, CLAUDE_MODEL, TAG_VOCABULARY,
                     PRIORITY_LEVELS, USER_POSITIONING)

_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def _active_model():
    """The model chosen in the sidebar this session, else the configured default."""
    try:
        import streamlit as st
        return st.session_state.get("model_id") or CLAUDE_MODEL
    except Exception:
        return CLAUDE_MODEL


SYSTEM_PROMPT = (
    "You are a career CRM assistant. The user pastes raw notes from their job "
    "search — a coffee chat recap, a job description, contact info, event notes, "
    "or a mix. Extract structured entities and return them by calling the "
    "save_extraction tool. First decide what the note is: "
    "(a) a job description / posting → put it in `applications` (the user pasting a "
    "JD means they have applied); "
    "(b) a person's info or a coffee-chat recap → put the person in `contacts` and "
    "summarise the conversation in `interaction_summary` + `key_insights`. "
    "A note can be a mix. Prefer tags from the controlled vocabulary, but you "
    "may add a few precise tags outside it when clearly warranted. Be faithful to "
    "the notes; do not invent facts. Leave a field empty if the notes don't "
    "support it."
)

# Forced-tool schema. Every string field is optional so partial notes still parse.
EXTRACTION_TOOL = {
    "name": "save_extraction",
    "description": "Save the structured entities extracted from the user's raw notes.",
    "input_schema": {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "enum": ["contact", "jd", "interaction", "event", "mixed"],
                "description": "The dominant type of the note.",
            },
            "contacts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "title": {"type": "string"},
                        "company": {"type": "string"},
                        "background": {"type": "string",
                                        "description": "1-2 sentence background."},
                        "source_event": {"type": "string",
                                          "description": "Where/how they were met."},
                        "relationship_strength": {
                            "type": "string",
                            "enum": ["warm", "cold", "met once"],
                        },
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "next_action": {"type": "string"},
                        "priority": {"type": "string",
                                      "enum": PRIORITY_LEVELS},
                        "follow_up_draft": {
                            "type": "string",
                            "description": "Personalized LinkedIn message, under 300 chars.",
                        },
                    },
                    "required": ["name"],
                },
            },
            "companies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "stage": {"type": "string",
                                   "description": "e.g. seed, Series A, public."},
                        "industry": {"type": "string"},
                        "product_area": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["name"],
                },
            },
            "applications": {
                "type": "array",
                "description": "Job descriptions / postings the note is about. Pasting a JD "
                               "means the user has applied — no status is needed.",
                "items": {
                    "type": "object",
                    "properties": {
                        "role_title": {"type": "string"},
                        "company": {"type": "string"},
                        "jd_text": {"type": "string",
                                     "description": "The job description text (condense if very long)."},
                        "fit_notes": {"type": "string",
                                       "description": "Why it fits / any gaps, only if the note says so."},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "interaction_summary": {
                "type": "string",
                "description": "2-3 sentence summary of the interaction/notes.",
            },
            "key_insights": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Career-relevant insights from the notes.",
            },
        },
        "required": ["type"],
    },
}


def extract(raw_text: str) -> dict:
    """Run Claude extraction over raw notes. Returns the tool input dict.

    Raises RuntimeError if the model returns no tool call.
    """
    tag_hint = ", ".join(TAG_VOCABULARY)
    user_content = (
        f"Tag vocabulary: [{tag_hint}]\n\n"
        f"Raw notes:\n{raw_text}"
    )

    resp = _get_client().messages.create(
        model=_active_model(),
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=[EXTRACTION_TOOL],
        tool_choice={"type": "tool", "name": "save_extraction"},
        messages=[{"role": "user", "content": user_content}],
    )

    for block in resp.content:
        if block.type == "tool_use" and block.name == "save_extraction":
            return _normalize(block.input)

    raise RuntimeError("Model did not return a save_extraction tool call.")


def _normalize(data: dict) -> dict:
    """Fill in defaults so downstream UI/DB code can rely on the shape."""
    data.setdefault("type", "mixed")
    data.setdefault("contacts", [])
    data.setdefault("companies", [])
    data.setdefault("applications", [])
    data.setdefault("interaction_summary", "")
    data.setdefault("key_insights", [])
    for c in data["contacts"]:
        c.setdefault("name", "")
        c.setdefault("title", "")
        c.setdefault("company", "")
        c.setdefault("background", "")
        c.setdefault("source_event", "")
        c.setdefault("relationship_strength", "met once")
        c.setdefault("tags", [])
        c.setdefault("next_action", "")
        c.setdefault("priority", "medium")
        c.setdefault("follow_up_draft", "")
    for co in data["companies"]:
        co.setdefault("name", "")
        co.setdefault("stage", "")
        co.setdefault("industry", "")
        co.setdefault("product_area", "")
        co.setdefault("tags", [])
    for ap in data["applications"]:
        ap.setdefault("role_title", "")
        ap.setdefault("company", "")
        ap.setdefault("jd_text", "")
        ap.setdefault("fit_notes", "")
        ap.setdefault("tags", [])
    return data


# --- Search synthesis -------------------------------------------------------

SEARCH_SYSTEM = (
    "You are a career CRM search assistant. Given a natural-language query and a "
    "list of candidate records retrieved from the user's own CRM, rerank them by "
    "true relevance to the query and return a synthesized answer via the "
    "rank_results tool. Include only genuinely relevant records — drop weak "
    "matches. For each, explain why it's relevant, quote a short piece of "
    "evidence taken verbatim from that record, and give one concrete recommended "
    "next action. Order most-relevant first. Judge relevance and frame each "
    "recommended action in light of the user's stated positioning / target roles."
)

SEARCH_TOOL = {
    "name": "rank_results",
    "description": "Return the reranked, synthesized answer to the search query.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "1-2 sentence overall answer to the query.",
            },
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string",
                                   "description": "Person / company / role."},
                        "kind": {"type": "string",
                                  "enum": ["contact", "application", "interaction"]},
                        "why_relevant": {"type": "string"},
                        "evidence_quote": {
                            "type": "string",
                            "description": "Short quote taken verbatim from the record.",
                        },
                        "recommended_action": {"type": "string"},
                    },
                    "required": ["title", "why_relevant", "recommended_action"],
                },
            },
        },
        "required": ["results"],
    },
}


def synthesize_search(query: str, candidates: list) -> dict:
    """Rerank + synthesize keyword candidates into the PRD's ranked answer.

    `candidates` is a list of dicts with keys: kind, label, text.
    Returns {"summary": str, "results": [...]}.
    """
    context = "\n\n".join(
        f"[{i + 1}] ({c['kind']}) {c['label']}\n{c['text']}"
        for i, c in enumerate(candidates)
    )
    user_content = (
        f"User's positioning / target roles: {USER_POSITIONING}\n\n"
        f"User query: {query}\n\n"
        f"Candidate records from the CRM (already keyword-matched):\n{context}"
    )

    resp = _get_client().messages.create(
        model=_active_model(),
        max_tokens=2048,
        system=SEARCH_SYSTEM,
        tools=[SEARCH_TOOL],
        tool_choice={"type": "tool", "name": "rank_results"},
        messages=[{"role": "user", "content": user_content}],
    )
    for block in resp.content:
        if block.type == "tool_use" and block.name == "rank_results":
            out = block.input
            out.setdefault("summary", "")
            out.setdefault("results", [])
            return out
    raise RuntimeError("Model did not return a rank_results tool call.")


# --- Insights digest --------------------------------------------------------

INSIGHTS_SYSTEM = (
    "You are a career strategy advisor. Given the user's recent networking "
    "interactions (coffee chats, events, DMs), write a concise weekly DECISION "
    "MEMO — not a bland summary — grounded strictly in these interactions: the "
    "strongest signals this period, specific relationship opportunities (name the "
    "people worth following up and why), how their positioning / target role is "
    "shifting, gaps not yet covered, and 3 concrete next actions. Do not invent "
    "facts not present in the notes.\n"
    "FORMATTING RULES (important): keep every item SHORT — one sentence per array "
    "item, max ~25 words. Do NOT put nested lists or (1)/(2)/(3) enumerations "
    "inside any single field. positioning_shift is at most 2 short sentences "
    "stating the shift only. Put concrete to-dos ONLY in next_actions, one action "
    "per array item (e.g. 'Send Lauren the funnel work sample by Thu').\n"
    "Assess signals, opportunities, and positioning_shift RELATIVE to the user's "
    "stated positioning / target roles (given below) — how each interaction moves "
    "them toward or away from those roles."
)

INSIGHTS_TOOL = {
    "name": "write_memo",
    "description": "Return the weekly career decision memo.",
    "input_schema": {
        "type": "object",
        "properties": {
            "strongest_signals": {
                "type": "array", "items": {"type": "string"},
                "description": "3-5 items. Each ONE short sentence (≤25 words).",
            },
            "relationship_opportunities": {
                "type": "array", "items": {"type": "string"},
                "description": "Each item: one person + why, in one short sentence.",
            },
            "positioning_shift": {
                "type": "string",
                "description": "At most 2 short sentences stating the shift only — "
                               "no embedded lists or numbered to-dos.",
            },
            "gaps": {
                "type": "array", "items": {"type": "string"},
                "description": "Each ONE short sentence (≤20 words).",
            },
            "next_actions": {
                "type": "array", "items": {"type": "string"},
                "description": "Exactly 3 items, one concrete action each (≤20 words).",
            },
        },
        "required": ["strongest_signals", "next_actions"],
    },
}


def synthesize_insights(interactions: list) -> dict:
    """Turn recent interaction dicts (contact_name, context, date, summary,
    key_insights) into a weekly decision memo."""
    lines = []
    for i, it in enumerate(interactions):
        who = it.get("contact_name") or "unknown contact"
        insights = it.get("key_insights") or ""
        lines.append(
            f"[{i + 1}] {it.get('date', '')} · {who} · {it.get('context', '')}\n"
            f"Summary: {it.get('summary', '')}\n"
            f"Insights: {insights}"
        )
    context = "\n\n".join(lines)

    resp = _get_client().messages.create(
        model=_active_model(),
        max_tokens=2048,
        system=INSIGHTS_SYSTEM,
        tools=[INSIGHTS_TOOL],
        tool_choice={"type": "tool", "name": "write_memo"},
        messages=[{"role": "user",
                   "content": f"User's positioning / target roles: {USER_POSITIONING}\n\n"
                              f"Recent interactions:\n\n{context}"}],
    )
    for block in resp.content:
        if block.type == "tool_use" and block.name == "write_memo":
            out = block.input
            out.setdefault("strongest_signals", [])
            out.setdefault("relationship_opportunities", [])
            out.setdefault("positioning_shift", "")
            out.setdefault("gaps", [])
            out.setdefault("next_actions", [])
            return out
    raise RuntimeError("Model did not return a write_memo tool call.")


# --- Follow-up generation ---------------------------------------------------

FOLLOWUP_SYSTEM = (
    "You write personalized professional follow-up messages for a job seeker's "
    "networking contacts. Rules: reference something specific and real from the "
    "notes (never generic like 'great meeting you'); be professional but warm; "
    "no fluff. For LinkedIn, keep it under 280 characters. For email, keep it to "
    "a short 3-4 sentence note. For WeChat, keep it casual and brief (1-3 "
    "sentences); if the contact is clearly a Chinese speaker, write it in "
    "Chinese, otherwise match the language of the notes. Output only the message "
    "text — no preamble, no quotes, no subject line unless it's an email."
)


def generate_follow_up(contact: dict, interaction: dict | None, *,
                       positioning: str, goal: str, channel: str) -> str:
    """Generate a single follow-up message string for one contact."""
    ctx = interaction.get("context", "") if interaction else ""
    date = interaction.get("date", "") if interaction else ""
    summary = interaction.get("summary", "") if interaction else ""

    user_content = (
        f"Contact: {contact.get('name', '')}, {contact.get('title', '')} at "
        f"{contact.get('company', '')}\n"
        f"Background: {contact.get('background', '')}\n"
        f"Last interaction: {ctx} on {date}\n"
        f"Interaction notes: {summary}\n"
        f"User's current positioning: {positioning}\n"
        f"User's goal: {goal}\n"
        f"Channel: {channel}\n\n"
        f"Write the {channel} message now."
    )

    resp = _get_client().messages.create(
        model=_active_model(),
        max_tokens=512,
        system=FOLLOWUP_SYSTEM,
        messages=[{"role": "user", "content": user_content}],
    )
    parts = [b.text for b in resp.content if b.type == "text"]
    return "\n".join(parts).strip()
