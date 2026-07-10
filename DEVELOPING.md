# Developing / extending Career CRM Copilot

A builder's guide to the codebase — how it's wired, the conventions to follow, and the
non-obvious gotchas (especially styling Streamlit). If you're here to *use* the app, read
[README.md](README.md) instead.

## Contents
- [Run it locally](#run-it-locally)
- [How the app is wired](#how-the-app-is-wired)
- [Core patterns already in the codebase](#core-patterns-already-in-the-codebase)
- [Styling Streamlit (the recipe)](#styling-streamlit-the-recipe)
- [Common tasks](#common-tasks)
- [Testing](#testing)
- [Gotchas](#gotchas)

---

## Run it locally

```bash
cd career-crm
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # paste your ANTHROPIC_API_KEY (OPENAI_API_KEY optional)
streamlit run app.py          # or the shell alias: career-crm
```

The app runs at `http://localhost:8501`. Data lives in `data/career_crm.db` (SQLite, gitignored).

**Rerun vs restart** — this trips people up:
- **Code edits** → Streamlit auto-reruns; just click "Rerun" (or it hot-reloads). The whole
  script re-executes top-to-bottom every interaction, so module-level code runs each time.
- **Restart required** (`Ctrl+C` then `career-crm`) for: `.streamlit/config.toml` theme changes,
  `.env` changes, new dependencies, and **DB schema/migration changes** (migrations run in `init_db()`
  at startup).

---

## How the app is wired

```
app.py                # entry: page config + injected CSS + sidebar nav + model picker + routing
└── src/
    ├── config.py     # env keys, model list, vocabularies, normalisers (tags/priority)
    ├── db.py         # SQLite schema + ALL data access (CRUD, queries, agent-writes, stats)
    ├── llm.py        # Claude calls (extraction, search synth, decision memo, follow-up)
    ├── agent.py      # the action agent (read tools + propose_plan + apply_plan + undo)
    ├── ingest.py     # the single shared write path (Add Note + Import both call it)
    ├── retrieval.py  # hybrid keyword+embedding retrieval
    ├── embeddings.py # OpenAI embeddings (degrade gracefully to None without a key)
    ├── eval_extraction.py  # extracted-vs-saved diff → extraction-quality counts
    ├── exporting.py · ui.py
    └── pages_ui/     # one render() per page
```

**Routing.** `app.py` holds a `PAGES` dict: `label -> (render_function, bootstrap_icon)`. The
sidebar (`streamlit-option-menu`) picks a label, and `PAGES[choice][0]()` calls that page's
`render()`. **Every page module exposes a single `render()` function** — that's the contract.

**Cross-page navigation.** A page can jump to another by setting
`st.session_state.nav_target = "Contacts"` (+ any payload like `contact_sel_id`) then `st.rerun()`.
`app.py` reads `nav_target` and drives the menu there. See `_open_contact()` in
[home.py](src/pages_ui/home.py).

**Layering rule.** Pages call `db`, `llm`, `agent`, `ingest` — never the reverse. All SQL lives in
`db.py`; no page writes SQL directly. `llm.py` never touches the DB. Keep it that way.

---

## Core patterns already in the codebase

**1. One shared write path.** Both Add Note and Import save through `ingest.save_extraction()`,
which normalises tags and handles attach-to-existing. Don't write a second save path — extend this one.

**2. Confirm-before-write agent.** `agent.py` splits tools into *reads* (run live: `find_contacts`,
`find_applications`) and *writes* (deferred: the model calls `propose_plan`, the user confirms, then
`apply_plan` runs and returns an undo snapshot). To add an agent capability, add an action to the
`propose_plan` enum and handle it in `apply_plan`/`undo_plan` — never let the model write directly.

**3. Whitelisted field writes.** `set_contact_field` / `set_application_field` validate `field`
against `_EDITABLE_*_FIELDS` sets before interpolating into SQL. Add a column to the whitelist to
make it editable; the validation is what keeps the f-string injection-safe.

**4. Additive, idempotent migrations.** `_migrate()` handles three cases: a **new column** (`ALTER
TABLE ADD COLUMN` if missing — see `outcome`); a **new table** (`CREATE TABLE IF NOT EXISTS` in
`SCHEMA`, since `init_db()` runs the whole schema every start — see `extraction_eval`); and a
**one-time data migration** that must not re-run (guard it with `PRAGMA user_version` — see the v1
merge that folds the old `status`+`outcome` into a single `status`). Never rename/drop a column in
place (SQLite makes it painful) — retire it and migrate its data forward.

**5. Measured AI quality.** Two mechanisms, both write to `db` and surface on the Dashboard:
   - `db.add_feedback(kind, rating)` — the 👍/👎 widgets (`ui.feedback_widget`).
   - `db.add_extraction_eval(...)` — logged automatically on each Add Note save by diffing the raw
     extraction against what the user saved (`eval_extraction.diff_counts`). The offline counterpart
     is `scripts/eval_extraction.py` (gold-set benchmark).

**6. Graceful degradation.** No `OPENAI_API_KEY` → embeddings return `None` and search falls back to
keyword-only; the app never crashes on a missing/placeholder key. Mirror this for any new optional
integration.

---

## Styling Streamlit (the recipe)

You write Python; Streamlit renders HTML. To restyle something you inject CSS — but CSS needs a
**selector** that reliably targets the right `<div>`. That's the whole difficulty.

### Don't target `data-testid` by guessing

Streamlit tags components with `data-testid` (e.g. `stMetric`), but these are **internal names that
change between versions**. The bordered container alone has been `stVerticalBlockBorderWrapper`,
then restructured — guessing it wastes time and silently fails when the guess is stale.

### Do use `key=` → the stable `st-key-…` class

Any component that accepts a `key` gets a **guaranteed, version-stable** class `st-key-<key>` on its
DOM element. This is Streamlit's official hook for targeting a specific element. The recipe:

**1. Tag the element with a key** (shared prefix so one rule covers many):
```python
with col.container(border=True, key=f"scard_kpi_{label}"):
    st.metric(label, val)
```

**2. Select by that class prefix** and inject the CSS (see the top of [app.py](app.py)):
```python
_CARD_CSS = """
<style>
[class*="st-key-scard"] {                      /* any element whose class CONTAINS this */
    border-radius: 10px !important;
    box-shadow: 0 1px 2px rgba(30,42,37,.06), 0 2px 8px rgba(30,42,37,.08) !important;
}
</style>
"""
st.markdown(_CARD_CSS, unsafe_allow_html=True)  # unsafe_allow_html lets you inject <style>
```

- `[class*="st-key-scard"]` = "elements whose `class` **contains** `st-key-scard`", so `scard_kpi_…`,
  `scard_task_5`, etc. all match with one rule.
- `!important` overrides Streamlit's own styles when they'd otherwise win on specificity.
- Colours are pulled from the theme's text colour (`#1e2a25`) so shadows stay harmonious.

### When something "won't apply", debug with DevTools — don't guess

1. Right-click the element → **Inspect**.
2. **Elements** panel = the real HTML. Hover nodes to see which `<div>` is the thing you mean.
3. Read its actual `class` / `data-testid` → that's your selector.
4. **Styles** panel shows which rules are winning (and what's crossed-out/overridden).
5. After a CSS change, **hard-refresh** (`Cmd+Shift+R`) — a normal refresh serves cached CSS, which
   is why an injected style can look like it "did nothing".

---

## Common tasks

**Add a page.** Create `src/pages_ui/foo.py` with a `render()` function → import it in `app.py` →
add `"Foo": (foo.render, "some-bootstrap-icon")` to `PAGES`.

**Add an editable field.** Add the column to `SCHEMA` + `_migrate()` in `db.py`, add it to the
relevant `_EDITABLE_*_FIELDS` set, then surface an input in the page (and, if the agent should set
it, mention it in `agent.py`'s system prompt).

**Add an agent action.** Extend the `PROPOSE_PLAN` action enum in `agent.py`, then handle it in
`apply_plan` (do the write, return an undo snapshot) and `undo_plan` (restore it).

**Change the theme.** Edit `.streamlit/config.toml` (requires a restart). For per-element styling
beyond the theme, use the CSS recipe above.

---

## Testing

There's no test framework wired up; the convention is fast, dependency-free checks:

```bash
# 1. Everything compiles
python3 -m py_compile src/*.py src/pages_ui/*.py app.py

# 2. The app imports cleanly (catches bad imports / top-level errors)
.venv/bin/python -c "import app; print('app loads')"

# 3. Non-LLM logic → validate against a temp DB (no API calls, deterministic)
.venv/bin/python -c "
import tempfile, os
from src import config; config.DB_PATH = os.path.join(tempfile.mkdtemp(), 't.db')
from src import db; db.DB_PATH = config.DB_PATH; db.init_db()
# ... exercise db / normalisers / eval logic and assert ...
"
```

Pure logic (normalisers, the extraction diff, funnel math, the status migration) is unit-testable this way —
prefer moving such logic out of the page modules so it can be tested without Streamlit.

---

## Gotchas

- **`RuntimeError: Event loop is closed` on `Ctrl+C`** — harmless Streamlit shutdown noise, not a
  bug in this app. Ignore it.
- **Restart vs rerun** — schema/migration/`.env`/theme changes need a full restart (see above).
- **Model picker** — the active model is `st.session_state["model_id"]` (falls back to
  `config.CLAUDE_MODEL`). `llm._active_model()` / `agent` read it; pass it through for any new LLM call.
- **Keys must be unique** across the app. In loops, suffix with a stable id
  (`key=f"scard_task_{t['id']}"`), not the loop index alone if the list can reorder.
- **Never commit secrets or data** — `.env` and `data/` are gitignored; keep them that way.
