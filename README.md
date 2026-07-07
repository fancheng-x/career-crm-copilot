# Career CRM Copilot

Career CRM Copilot is a local AI workflow system that turns fragmented job-search data —
networking notes, job descriptions, coffee-chat recaps, and follow-ups — into structured
relationship intelligence and recommended next actions. Built on Claude, with entity
extraction, hybrid search, a decision-memo dashboard, a confirm-before-write action agent,
and measured AI quality.

---

## Quick tour (what it is / how to use it)

**In one line:** consolidate the job-search data scattered across your Notion (applications,
contacts, coffee-chat notes) into one local app, and let AI **structure it, summarize it,
search it, and draft your follow-ups**.

**Nine pages (left sidebar):**

| Page | What it does |
|---|---|
| 🏠 **Home / Dashboard** | Overview: KPI cards, distribution charts (by status / industry / base / priority), an action center (tasks + pending follow-ups), recent coffee chats (click to jump), and a one-click weekly memo. |
| 🤖 **Assistant** | Change data with plain-language commands (set priority, add a tag, create a reminder/task, attach a note…). It resolves who you mean, **asks when a name is ambiguous**, and turns every change into a **plan you confirm before it writes**. |
| ✏️ **Add Note** | Paste free text → the LLM extracts contacts / companies / summary / insights / a follow-up draft → confirm to save. Can **attach to an existing contact** (no duplicates). |
| ⬆️ **Import** | Bulk-import CSVs exported from Notion; unmapped columns are preserved into notes so nothing is lost. |
| 👤 **Contacts** | Filterable table → click a row for the full profile and **coffee-chat history**; 💬 marks who you've talked to; store **verbatim notes** and expand the full text; delete or export to CSV. |
| 💼 **Applications** | Filterable table → click a row for the full JD / fit notes; delete, clear, or export to CSV. |
| 🔍 **Search** | Ask in plain language → **hybrid (semantic + keyword) retrieval** + LLM re-ranking, with reasons, evidence quotes, and suggested actions. With an OpenAI key, one click builds the index to enable semantic search. |
| 💡 **Insights** | One click summarizes recent interactions: themes, positioning signals, gaps, and next-step priorities. |
| ✉️ **Follow-up** | Pick a contact → generate an editable **LinkedIn / WeChat / email** follow-up draft. |

**How to open** (alias preconfigured): run `career-crm` in the terminal → open
`http://localhost:8501` in the browser. Press Ctrl+C to stop.

**Switch models:** a **Claude model** dropdown at the bottom of the sidebar lets you pick any
Claude model (opus / sonnet / haiku…); every AI feature uses the one you select.

**Where the data lives:** everything is stored locally in `data/career_crm.db` (SQLite) and is
never uploaded. Code edits → click "Rerun" in the browser; theme / `.env` / dependency changes
need a restart.

---

## Features (detail)

- **Dashboard.** KPI cards; an **Action center** (open tasks, high-priority contacts with no
  next action, and pending follow-ups); **Recent intelligence** (latest coffee chats + a one-click
  weekly decision memo); a **Pipeline** view of distribution bar charts (applications by status /
  industry / base, contacts by priority); and an **AI quality** panel measured from your feedback.
  Records are clickable — jump straight to the contact. Shows a **"Start here"** guide on an empty DB.
- **Add Note → structured extraction.** Paste any free text; Claude returns contacts, companies,
  a summary, key insights, and a follow-up draft. Save each contact as **new** or **attach to an
  existing contact** (no duplicates — the picker auto-detects same-name contacts).
- **Import from Notion CSV.** Column-mapping UI with auto-guessing; unmapped columns are preserved
  into notes. Coffee-chat notes can be run through the same LLM extraction row-by-row.
- **Contacts / Applications.** Filterable tables (priority, tags, company, relationship, status…),
  click a row to open a full profile / interaction history / JD, delete single rows or clear all,
  and export the filtered view to CSV. Tags render as chips. On a contact you can also **add a note
  verbatim (no AI)** and read the **full text** of any interaction via a "Full note" expander.
- **Search.** **Hybrid retrieval** — keyword scoring blended with OpenAI-embedding semantic
  similarity (build/refresh a cached vector index from the Search page; falls back to keyword-only
  without a key) — across contacts + applications + interactions, then Claude re-ranks and
  synthesizes a ranked answer with a relevance reason, evidence quote, and next action.
- **Insights / decision memo.** Synthesizes recent interactions into recurring themes,
  positioning signals, gaps, and recommended next actions.
- **Follow-up generator.** Editable LinkedIn / WeChat / email draft per contact, grounded in their
  background + your positioning + your chosen goal.
- **Action agent (Assistant).** Natural-language commands that mutate the CRM via Claude tool
  use: it resolves which records you mean (asking when a name is ambiguous), then proposes a
  **plan you confirm before anything is written**. Backed by a `tasks` table for reminders/to-dos.
- **Model picker.** Switch the Claude model for all AI features from the sidebar.

## Highlight — a confirm-before-write action agent

Most AI agents become risky the moment they can mutate user data. The **Assistant** here uses a
**confirm-before-write** pattern: the agent may *read* the database and resolve which records you
mean (asking when a name is ambiguous), but every *write* is turned into a **proposed plan the user
must approve** before anything changes — with **one-step undo** afterward, and any action that
matches zero records is flagged rather than silently reported as done.

This makes an action agent safe, debuggable, and appropriate for personal data. It reflects the same
principle that matters for real enterprise-AI / field-deployment work: an AI system has to be
*controllable, explainable, and confirmable* — not just "able to do the thing."

## Typical workflow

1. **Import** your Notion trackers once → contacts + applications land in the DB.
2. For each coffee chat, either paste the notes into **Add Note** (AI extracts a summary + insights
   and attaches them to the existing contact) or open the contact and **add the note verbatim** —
   both are readable later under the contact's interaction history ("Full note").
3. Use the **🤖 Assistant** to change data in plain language — e.g. "set Lauren to high priority
   and remind me to follow up next Friday" or "tag applications with no response for over two weeks
   as 'no response'". It resolves who/what you mean, asks if ambiguous, and shows a plan you
   **confirm before it writes** (one-step **undo** available).
4. Use the **Dashboard** for a daily overview (tasks, to-dos, distributions), **Search** / **Insights**
   to reason across everything, and **Follow-up** to draft outreach. Rate AI outputs with 👍/👎
   to populate the Dashboard's AI-quality panel. Export filtered lists for a coach.

## Tech stack

| Layer | Choice |
|---|---|
| Frontend | Streamlit + `streamlit-option-menu` (sidebar nav) |
| Theme | Muted green, via `.streamlit/config.toml` |
| Database | SQLite (`data/career_crm.db`) |
| LLM | Claude (default `claude-sonnet-4-6`; switchable in the sidebar) |
| Structured extraction | Claude forced tool use (reliable JSON) |
| Search | Hybrid retrieval: keyword + OpenAI `text-embedding-3-small` (cached vectors), then LLM re-ranking |
| Config | `.env` auto-loaded via `python-dotenv` |

## Setup & run

```bash
cd career-crm
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# .env holds the keys (auto-loaded — no need to export):
cp .env.example .env        # then edit and paste your real key
#   ANTHROPIC_API_KEY=sk-ant-...   (required)
#   OPENAI_API_KEY=...            (optional; enables semantic embedding search;
#                                  otherwise falls back to keyword search)
#   CAREER_CRM_MODEL=claude-opus-4-8   (optional; sets the default model)

streamlit run app.py        # or, with the shell alias: career-crm
```

## Data & privacy

- Everything is **local**: the SQLite DB and your `.env` never leave your machine.
- `data/` and `.env` are gitignored — safe to push the repo to GitHub without leaking data or keys.

## Project structure

```
career-crm/
├── app.py                     # Streamlit entry: sidebar nav + model picker + routing
├── requirements.txt · .env.example · .gitignore
├── .streamlit/config.toml     # green theme
├── data/                      # SQLite DB (gitignored)
└── src/
    ├── config.py              # env keys, model list, tag vocabulary + synonyms, paths
    ├── db.py                  # schema (contacts/companies/applications/interactions/documents/
    │                          #   tasks/agent_log/feedback/emb_cache) + CRUD, queries, agent-write
    │                          #   helpers, dedup/merge, tag + priority normalisation
    ├── llm.py                 # Claude: extraction, search synthesis, decision memo, follow-up
    ├── agent.py               # action agent: read tools + propose_plan + apply_plan + undo_plan
    ├── ingest.py              # shared write path (Add Note + Import both use it)
    ├── retrieval.py           # hybrid retrieval (keyword + embedding) + vector index build
    ├── embeddings.py          # OpenAI embeddings + blob/cosine helpers (powers hybrid search)
    ├── exporting.py           # CSV export
    ├── ui.py                  # small UI helpers (tag chips, feedback thumbs widget)
    └── pages_ui/              # one render() per page: home, assistant, add_note,
                               #   import_page, contacts, applications, search, insights, follow_up
```

## Evaluation — AI workflow quality metrics

I treat this as an **AI-feature evaluation problem, not just a feature build**. The metrics I track
to judge whether the AI features are genuinely useful:

| Metric | Definition | Target |
|---|---|---|
| **Extraction correction rate** | share of extracted fields I manually fix per note | < 20% |
| **Top-3 search usefulness** | useful results among the top 3 returned | ≥ 2 of 3 |
| **Follow-up draft acceptance** | drafts usable with only light edits | ≥ 70% |
| **Time saved per note** | time to structure one coffee-chat note vs. by hand | < 3 min (vs. 10–15) |
| **Insight value** | actionable insights per weekly digest | ≥ 3 |

Framing the project around these metrics keeps the focus on whether each AI feature actually saves
time and produces trustworthy output — the way an AI product/analytics team would evaluate it.

**These are measured, not just aspirational:** search results, follow-up drafts, and the insights
memo each carry a 👍/👎 control; the ratings are stored locally and the resulting positive-rate
metrics are shown on the **Dashboard → AI quality** panel.

## Status & roadmap

**Done:** dashboard, action agent (Assistant) with confirm-before-write + tasks/reminders,
weekly **decision memo**, agent **audit log + persistent multi-step undo**, contact **dedup / merge**,
**feedback ratings** with a measured AI-quality panel, **hybrid (semantic + keyword) search**, Notion
CSV import, attach-to-existing, verbatim notes, filters, profile/JD drill-down, delete/clear, CSV
export, tag chips, green theme, model picker, LinkedIn/WeChat/email follow-ups.

Plus **tag + priority normalisation** (data hygiene — canonicalises tag synonyms and the
High/Medium/Low casing mix from the Notion import) and a **"Start here" onboarding** block on the Dashboard.

**Next:** driven by real usage — collect feedback ratings over a few weeks to populate the AI-quality
metrics, then iterate on whatever the data shows is weakest. A possible net-new feature is résumé ↔ JD
matching — a natural next step because it extends the same relationship-intelligence layer from
people/company fit to role/résumé fit. (Deliberately still out of scope: mobile, multi-user,
two-way Notion sync, auto-send.)

**Deliberately out of scope** (would explode scope without sharpening the core): mobile, multi-user,
two-way Notion sync, auto-sending LinkedIn/email, heavier UI. The north star stays: *turn fragmented
career data into relationship intelligence and next actions.*
