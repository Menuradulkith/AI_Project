# IFS Jira Ticket Classifier

An AI-powered internal dashboard that identifies **Localisation** defects from IFS customer-raised Jira tickets. The system runs in **read + classify + store** mode to support fast localisation triage.

---

## What it does

- Fetches open tickets from the **FIZ** Jira project (Support Issues & Defects)
- Classifies each ticket as **Localisation** or **Not Localisation** using **GPT-4o-mini**
- Stores all results in **SQLite** (no re-classification unless the ticket changes)
- Flags uncertain items for **manual review**
- Displays a live React dashboard for localisation triage

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  React Dashboard  (Vite, port 5173)                         │
│  /dashboard/src/                                            │
└───────────────────────┬─────────────────────────────────────┘
                        │ /api/*  (proxied)
┌───────────────────────▼─────────────────────────────────────┐
│  Flask REST API  (port 5000)                                │
│  api.py                                                     │
└──────┬────────────────┬────────────────────────────────────-┘
       │                │
┌──────▼──────┐  ┌──────▼──────────────────────────────────┐
│ jira_fetcher│  │ categorizer.py  (thin wrapper)           │
│   .py       │  └──────┬──────────────────────────────────-┘
│             │         │
│ Jira REST   │  ┌──────▼──────────────────────────────────┐
│ API v3      │  │  agents/                                 │
└─────────────┘  │  ├── base.py       LLM singleton, retry  │
                 │  ├── router.py     Smart Router          │
                 │  └── gray_zone.py  Investigator          │
                 └──────┬──────────────────────────────────-┘
                        │
                 ┌──────▼──────┐
                 │  cache.py   │
                 │  SQLite DB  │
                 └─────────────┘
```

---

## Classification agents

### Agent 1 — Smart Router (`agents/router.py`)

Decides per-ticket how much work is needed:

| Condition | Action | LLM calls |
|---|---|---|
| Ticket in cache & unchanged | Return cached result | **0** |
| High/medium confidence, no gray zone | Return directly | **1** |
| Low confidence or gray zone | Escalate to investigator | **2** |

### Agent 3 — Gray Zone Investigator (`agents/gray_zone.py`)

Only runs when the router is uncertain. It:
1. Searches past classifications in SQLite for tickets with overlapping keywords (free — no LLM)
2. Sends a **compact** prompt with the initial result + evidence from similar past tickets
3. Makes a final decision with an evidence trail

### Shared foundation (`agents/base.py`)

- **LLM singleton** — `ChatOpenAI` created once on startup, reused for every call
- **Retry with backoff** — 3 attempts, 2s → 4s → 8s between retries
- **Hard timeout** — 30 s per call, so Flask workers never hang
- **Token cost logging** — logs `in/out tokens + $cost` per call
- **System prompt cache** — loaded from disk once, kept in memory

---

## Cost model

| Scenario | LLM calls | Approx cost |
|---|---|---|
| Cached ticket (unchanged) | 0 | **$0.000000** |
| Clear classification | 1 | **~$0.000200** |
| Gray zone investigation | 2 | **~$0.000380** |
| Typical batch of 50 tickets (est. 15% gray zone) | ~58 | **~$0.013** |

Token waste is minimised by:
- The JSON output schema lives only in the system prompt (not repeated in every human message)
- Gray zone call 2 sends a compact ticket reference, not the full description again

---

## Project structure

```
AI_Project/
├── api.py                  Flask REST API
├── categorizer.py          Public classification entry point (thin wrapper)
├── jira_fetcher.py         Jira REST API v3 client
├── cache.py                SQLite cache (classifications.db)
├── start.ps1               One-command launcher (Flask + Vite)
├── requirements.txt
├── .env                    Secrets (not committed)
│
├── agents/
│   ├── __init__.py         Exports smart_classify
│   ├── base.py             LLM singleton, retry, prompt builder, JSON parser
│   ├── router.py           Agent 1 — Smart Ticket Router
│   └── gray_zone.py        Agent 3 — Gray Zone Investigator
│
├── prompts/
│   └── system_prompt.md    Classification rules (Localisation vs Not Localisation)
│
└── dashboard/              React + Vite frontend
    └── src/
        ├── App.jsx
        ├── api.js
        ├── hooks/
        │   ├── useTickets.js
        │   └── useClassify.js
        └── components/
            ├── TicketCard.jsx
            ├── TicketModal.jsx
            ├── ClassifyBadge.jsx
            ├── StatusBadge.jsx
            ├── PriorityDot.jsx
            └── StatsBar.jsx
```

---

## Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- VPN connected to IFS network
- Atlassian API token ([generate here](https://id.atlassian.com/manage-profile/security/api-tokens))
- OpenAI API key ([generate here](https://platform.openai.com/api-keys))

### 1. Clone and create virtual environment

```powershell
cd c:\IFS_WORK\AI_Project
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

### 2. Install frontend dependencies

```powershell
cd dashboard
npm install
```

### 3. Create `.env` file

```env
JIRA_BASE_URL=https://ifsdev.atlassian.net
JIRA_EMAIL=your.name@ifs.com
JIRA_API_TOKEN=your_atlassian_api_token
JIRA_PROJECT_KEY=FIZ
OPENAI_API_KEY=sk-...
```

> ⚠️ Never commit `.env` to source control.

### 4. Start everything

```powershell
powershell -ExecutionPolicy Bypass -File start.ps1
```

This starts both the Flask API (port 5000) and the Vite dev server (port 5173) in a single command.

Or start them separately:

```powershell
# Terminal 1 — Flask API
.venv\Scripts\python.exe api.py

# Terminal 2 — React dashboard
cd dashboard
npm run dev
```

Open **http://localhost:5173**

---

## API endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Liveness check |
| `GET` | `/api/fiz` | List FIZ tickets from SQLite |
| `GET` | `/api/gclz` | List GCLZ tickets from SQLite |
| `GET` | `/api/dashboard/stats` | Dashboard statistics |
| `GET` | `/api/ticket/<id>` | Single ticket detail (live Jira fetch) |
| `POST` | `/api/chat` | Chat assistant for ticket queries |
| `POST` | `/api/sync/trigger` | Trigger sync in background |
| `POST` | `/api/sync/trigger-blocking` | Trigger sync and wait for results |
| `GET` | `/api/sync/status` | Sync status + recent runs |
| `GET` | `/api/sync/manual-review` | Tickets flagged for manual review |
| `POST` | `/api/sync/manual-review/<id>/clear` | Clear manual review flag |
| `POST` | `/api/scheduler/start` | Start scheduler |
| `POST` | `/api/scheduler/stop` | Stop scheduler |
| `GET` | `/api/scheduler/status` | Scheduler status |
| `POST` | `/api/webhook/jira` | Jira webhook (issue created/updated) |

---

## Token expiry

Atlassian API tokens expire periodically. When they do, the dashboard shows a clear `401` banner instead of crashing.

To renew:
1. Go to [Atlassian API tokens](https://id.atlassian.com/manage-profile/security/api-tokens)
2. Create a new token
3. Update `JIRA_API_TOKEN` in `.env`
4. Restart Flask (`CTRL+C` then run `api.py` again)

No dashboard restart needed.

---

## Jira filter

Only `issuetype in ("Support Issue", "Defect")` tickets are fetched. Other issue types (Tasks, Stories, etc.) are excluded.

---

## Cache behaviour

## Read-only mode

- Jira tickets are **not modified** by this system.
- All actions are read, classify, store, and report.

## Cache behaviour

- Cache key: `ticket_id` + `updated_at` timestamp
- If a ticket is edited in Jira, the cache entry is considered **stale** and the ticket is re-classified automatically on next access
