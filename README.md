# Career CRM Copilot

Career CRM Copilot is a local AI workflow system that turns fragmented job-search data —
networking notes, job descriptions, coffee-chat recaps, and follow-ups — into structured
relationship intelligence and recommended next actions. Built on Claude, with entity
extraction, hybrid search, a decision-memo dashboard, a confirm-before-write action agent,
and measured AI quality.

---

## 速览（这是什么 / 怎么用）

**一句话**：把你散落在 Notion 里的求职信息（申请、人脉、coffee chat 笔记）集中到一个本地小 app，
让 AI 帮你**抽取结构、看总览、搜索、总结、写跟进**。

**9 个页面（左侧导航）**：

| 页面 | 作用 |
|---|---|
| 🏠 **Home / Dashboard** | 总览:指标卡、分布图(按 status / industry / base / priority)、Tasks + 待跟进清单、最近 coffee chats(可点击跳转)、一键本周 digest。 |
| 🤖 **Assistant** | 用大白话下命令改数据(改 priority、加 tag、建提醒/任务、attach 笔记…)。它先找准对象、遇到重名会**反问**,并把要改的**列成计划让你确认后才落库**。 |
| ✏️ **Add Note** | 粘贴自由文本 → LLM 抽出联系人/公司/总结/insights/跟进草稿 → 确认保存。可**挂到已有联系人**(不重复)。 |
| ⬆️ **Import** | 上传 Notion 导出的 CSV 批量导入;没映射的列自动保留进 notes,不丢信息。 |
| 👤 **Contacts** | 表格 + 筛选 + 点行看完整档案和 **coffee chat 历史**;💬 标记谁聊过;可直接存**逐字笔记**并展开看全文;可删除、导出 CSV。 |
| 💼 **Applications** | 表格 + 筛选 + 点行看完整 JD / fit notes;可删除、清空、导出 CSV。 |
| 🔍 **Search** | 大白话提问 → **hybrid(语义 + 关键词)检索** + LLM 重排,给理由、证据引用和建议动作。有 OpenAI key 时点一下建索引即可启用语义。 |
| 💡 **Insights** | 一键总结最近 interactions:主题、定位信号、空白、下一步重点。 |
| ✉️ **Follow-up** | 选联系人 → 生成可编辑的 **LinkedIn / WeChat / 邮件** 跟进草稿。 |

**怎么打开**（已配好别名）：终端输入 `career-crm` → 浏览器开 `http://localhost:8501`。停止按 Ctrl+C。

**切换模型**：侧边栏底部有 **Claude model** 下拉,可选任意 Claude 模型(opus / sonnet / haiku…),所有 AI 功能都用你选的那个。

**数据在哪**：全部存本地 `data/career_crm.db`（SQLite），不上传任何地方。改代码点浏览器 "Rerun";改主题/`.env`/装库要重启。

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
3. Use the **🤖 Assistant** to change data in plain language — e.g. "把 Lauren 改成 high priority，
   下周五提醒 follow up" or "给没回音超两周的申请加 tag 'no response'". It resolves who/what you
   mean, asks if ambiguous, and shows a plan you **confirm before it writes** (one-step **undo** available).
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
