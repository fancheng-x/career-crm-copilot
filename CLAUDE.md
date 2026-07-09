# CLAUDE.md

Guidance for AI agents (Claude Code) working in this repo. Keep changes consistent with the
patterns below. For depth, read [DEVELOPING.md](DEVELOPING.md); for the product, [README.md](README.md).

## What this is
A local Streamlit + SQLite + Claude personal CRM for a job search: it turns fragmented notes,
JDs, and coffee chats into structured relationship intelligence, hybrid search, follow-ups, and a
confirm-before-write action agent — with measured AI quality. Portfolio project (product-analytics /
AI-workflow framing).

## Environment & commands
- Python venv is **`.venv/`** (Python 3.13) — NOT the conda `base`/`dl` env. Use `.venv/bin/python`.
- Run: `streamlit run app.py` (alias `career-crm`). App at `http://localhost:8501`.
- Save & push: `career-save "message"` (alias: add + commit + push).
- Verify after any change (no test framework — use these):
  ```bash
  python3 -m py_compile src/*.py src/pages_ui/*.py app.py
  .venv/bin/python -c "import app; print('app loads')"
  ```
  For non-LLM logic, assert against a temp DB (`config.DB_PATH = <tmp>`; see DEVELOPING.md).

## Architecture (one line each)
- `app.py` — entry: injected CSS + sidebar nav + model picker + routing via the `PAGES` dict.
- `src/db.py` — the ONLY place SQL lives (schema, CRUD, queries, agent-writes, stats).
- `src/llm.py` — Claude calls; never touches the DB.
- `src/agent.py` — action agent (read tools live; writes go through propose → confirm → apply → undo).
- `src/ingest.py` — the single shared write path (Add Note + Import both use it).
- `src/pages_ui/*.py` — one `render()` per page; that's the routing contract.

## Conventions (follow these)
- **Layering:** pages call `db`/`llm`/`agent`/`ingest`, never the reverse. All SQL stays in `db.py`.
- **One write path:** extend `ingest.save_extraction()`; don't add a second save path.
- **Agent safety:** the model never writes directly. New capability = new action in `propose_plan` +
  handlers in `apply_plan`/`undo_plan`. Keep confirm-before-write and the undo snapshot.
- **Editable fields:** add the column to `_EDITABLE_*_FIELDS` (the whitelist is what makes the
  f-string SQL injection-safe).
- **Migrations:** new column → add to `SCHEMA` AND `_migrate()`; new table → `CREATE TABLE IF NOT
  EXISTS` in `SCHEMA`. `init_db()` runs at startup.
- **Optional keys degrade gracefully:** no `OPENAI_API_KEY` → embeddings return `None`, search falls
  back to keyword. Never crash on a missing/placeholder key.
- **Styling Streamlit:** don't guess `data-testid` (changes per version). Add `key="…"` to the
  component and target the stable `st-key-<key>` class in injected CSS. See DEVELOPING.md §Styling.
- **Docs & language:** README/DEVELOPING are **English only**. After any user-facing change, keep
  `README.md` (and `DEVELOPING.md` if patterns change) in sync — the user expects docs kept current.

## Gotchas
- **Restart** (`Ctrl+C` → `career-crm`) is required for schema/migration, `.env`, dependency, or
  theme changes. Code edits just rerun.
- `RuntimeError: Event loop is closed` on `Ctrl+C` is harmless Streamlit shutdown noise.
- Active model = `st.session_state["model_id"]` (fallback `config.CLAUDE_MODEL`); thread it into new LLM calls.
- **Never commit** `.env` or `data/` (gitignored). Don't paste real API keys anywhere.
