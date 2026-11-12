# BachelorBuddy backend

FastAPI + PostgreSQL backend and AI agents for [BachelorBuddy](../Bachelor-buddy), a money app for
young bachelors in Bangalore. The web app runs entirely against it and its synthetic data:
the paths, envelope and DTOs are in [`API_CONTRACT.md`](./API_CONTRACT.md), checked by contract
tests against the frontend's TypeScript types, with email and password sign-in.

- **Run (API):** `uv run uvicorn app.main:app --reload --port 8000`
- **Run (scheduler, separate terminal):** `uv run python -m app.scheduler`
- **Docs while running:** <http://localhost:8000/docs>

## What's inside

| | |
|---|---|
| **API** | 35 endpoints under `/api`: auth, profile, budget, expenses, food, groceries, products, offers, homes, savings, notifications, chat; plus `/health`, `/ready`, `/docs` |
| **Database** | PostgreSQL 18 on Neon (or local), 34 tables, Alembic migrations, money stored in paise |
| **Agents** | A Concierge plus 7 specialists on Groq with validated tool calling, server-built cards and a number check; a rules mode that needs no key ([AGENTS.md](./AGENTS.md)) |
| **Scheduler** | 7 proactive jobs (budget warnings, lunch suggestions, price drops, savings report…) in a separate process |
| **Data** | A deterministic synthetic Bangalore dataset: 165 eateries, 216 products with 180-day price history, 127 homes, 51 users, ~30k expenses ([DATA.md](./DATA.md)) |
| **Quality** | ruff, mypy strict, 300+ tests (unit, API, contract, agents, scheduler, generator) |

## Prerequisites

- **[uv](https://docs.astral.sh/uv/).** It installs Python 3.12 for this project by itself.
- **PostgreSQL 16+.** This repo uses a [Neon](https://neon.tech) project; a local server works
  too. Docker is not needed.

## Setup

```bash
uv sync                                        # Python 3.12 and all dependencies into .venv
cp .env.example .env                           # then fill in the values below
uv run python scripts/setup_db.py --seed       # role, databases, migrations, synthetic data
```

| `.env` variable | What to put there |
|---|---|
| `POSTGRES_HOST` | Neon: the **direct** host (your connection string's host without `-pooler`). Local: `localhost` |
| `POSTGRES_ADMIN_USER` / `POSTGRES_ADMIN_PASSWORD` | Neon: the owner role (`neondb_owner`). Local: `postgres`. Only the setup scripts use these |
| `POSTGRES_SSLMODE` | `require` for Neon, `prefer` locally |
| `APP_DB_PASSWORD` | A strong password (12+ random characters) for the app role. Repeat it in both URLs below |
| `DATABASE_URL` / `TEST_DATABASE_URL` | `postgresql+asyncpg://bachelorbuddy_app:<pw>@<host>:5432/bachelorbuddy[_test]`. Neon: the **pooled** host and `?ssl=require` |
| `JWT_SECRET` | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `DEMO_USER_PASSWORD` | The password of the demo user `arjun@demo.com`, which exists only in the test database (and the app database if you seed with `--demo`) |
| `GROQ_API_KEY` | Only for `AGENT_MODE=llm` (from console.groq.com) |

`setup_db.py` is safe to rerun.
- **Role and databases:** it creates a least-privilege `bachelorbuddy_app` role and the
  `bachelorbuddy` and `bachelorbuddy_test` databases, closed to other roles. It never touches any
  other database (Neon's `neondb` is left alone).
- **Migrations and seed:** it migrates both databases over the direct host, then with `--seed`
  loads the data. Passwords are never printed.

`scripts/reset_db.py` drops and recreates **only** those two databases (it asks first; `--yes`
skips the prompt).

## Run

```bash
uv run uvicorn app.main:app --reload --port 8000     # the API
uv run python -m app.scheduler                        # the scheduler (separate terminal, optional)
```

- API: <http://localhost:8000/api/...> · Docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/health> (process up) · <http://localhost:8000/ready> (database up)
- Sign in: `POST /api/auth/register` (or `/api/auth/login`), then send
  `Authorization: Bearer <accessToken>`. In `/docs`, use **Authorize**.

Scheduler jobs can also be run by hand:

```bash
uv run python -m app.scheduler list
uv run python -m app.scheduler run lunch_suggestion     # skipped if it already ran today
uv run python -m app.scheduler run budget_check --force
```

## Connect the frontend

With this API running on port 8000:

```bash
cd ../Bachelor-buddy
npm install
npm run dev        # http://localhost:5173, /api is proxied to http://localhost:8000
```

Create an account and go through onboarding (the app database holds real accounts only; there
is no demo user). No frontend env changes or CORS setup are needed locally;
see [FRONTEND_INTEGRATION.md](./FRONTEND_INTEGRATION.md) for hosted setups, the auth flow and
the frontend's e2e run.

## Configuration

Everything comes from environment variables or `.env`; see [`.env.example`](./.env.example). The
main ones besides those above:

| Variable | Default | Meaning |
|---|---|---|
| `CLOCK_MODE` | `real` | `real` is the wall clock (required when `APP_ENV=production`). `demo` pins "now" to the 15th of the month, 12:30 IST. `fixed` pins `CLOCK_FIXED_AT` (the frontend's e2e run) |
| `AGENT_MODE` | `rules` | `llm` uses Groq (falls back to rules per request); `rules` needs no key |
| `GROQ_MODEL` / `GROQ_FAST_MODEL` | `openai/gpt-oss-120b` / `openai/gpt-oss-20b` | Concierge / specialists |
| `AGENT_DIRECT_TOOLS` | `false` | Token saver: no separate specialist model calls |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated; `*` is refused |
| `RATE_LIMIT_AUTH` / `RATE_LIMIT_CHAT` | `10/minute` / `20/minute` | Per IP / per user |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` / `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `15` / `7` | Token lifetimes |
| `DEV_AUTH_BYPASS_EMAIL` | empty | Development only; refused in production |
| `APP_ENV` | `development` | `production` adds HSTS and forbids the bypass |
| `LOG_LEVEL` / `LOG_FORMAT` | `INFO` / `json` | JSON lines with request IDs, or `text` |

## Architecture

```
app/
├─ main.py, factory.py     ASGI app, middleware (CORS → request IDs, security headers, 500s)
├─ api/                    routes/ (auth, users, budget, catalog, activity, chat), deps, params
├─ services/               DB reads/writes + calc; shared by routes, agents and jobs
├─ calc/                   pure money math: budget, savings, delivery, grocery, offers, products, homes
├─ agents/                 Concierge, specialists, tools, evidence, rules engine, Groq client
├─ scheduler/              7 jobs, the APScheduler process, the manual CLI
├─ schemas/                Pydantic DTOs mirroring the frontend's src/types (camelCase on the wire)
├─ db/                     models (34 tables), Rupees type (paise in DB), async engine/sessions
└─ core/                   config, clock, errors, logging, security, rate limiting, money
migrations/                Alembic (async); the URL comes from .env
scripts/                   setup_db.py, reset_db.py, generate_data.py, seed/ (data generator)
tests/                     unit/, api/, agents/, scheduler/, contract/, seed/, scripts/, db/
```

How the pieces fit:
- **Money math** lives in `calc/` as pure functions with unit tests. The agents never do
  arithmetic; their tools call the same services as the endpoints.
- **Responses** use the envelope `{success, data, meta, error}`, JSON is camelCase, money is
  integer rupees, and timestamps are UTC ISO strings (`2026-11-15T07:00:00.000Z`).
- **Security:**
  - Auth: JWT access tokens, plus rotated and hashed refresh tokens with reuse detection.
  - Passwords: bcrypt.
  - Data isolation: every query is scoped to the user (cross-user access is a 404).
  - Limits: rate limits on auth and chat, a 64 KB body limit.
  - Headers: CSP, nosniff, frame-deny, no-store (HSTS in production).
  - Logs: secrets are redacted.

## Tests

```bash
uv run ruff format . && uv run ruff check . && uv run mypy
uv run pytest --cov
```

Tests run against `TEST_DATABASE_URL`, never the dev database.
- **Seeding:** the test database is seeded once (the demo user Arjun plus three users) with the
  clock pinned to 15 Nov 2026 12:30 IST (`scripts/seed/anchors.py`). The frontend's e2e run
  uses the same database (`scripts/e2e_db.py prepare|cleanup`).
- **Isolation:** each test runs in a transaction that is rolled back.
- **Without a database:** database tests are skipped with the reason shown.
- **Contract tests:** they read `../Bachelor-buddy/src/types`, and are skipped if the frontend
  isn't next to this repo.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Cannot reach PostgreSQL at <neon host>` | Check your internet connection and `POSTGRES_HOST`, and that the Neon project exists. A suspended compute wakes on the next connection (the first request takes about 1 s) |
| `... only accepts encrypted connections` | `POSTGRES_SSLMODE=require`, and end both URLs with `?ssl=require` |
| `Cannot reach PostgreSQL at localhost:5432` | Start the service: `services.msc` → `postgresql-x64-18` → Start (or `net start postgresql-x64-18` as administrator) |
| `PostgreSQL rejected the password for user '...'` | Fix `POSTGRES_ADMIN_PASSWORD` (a Neon password reset invalidates the old one) |
| `The password in DATABASE_URL does not match APP_DB_PASSWORD` | Use the same password in all three places, then rerun `setup_db.py` (it syncs the role) |
| API refuses to start: `JWT_SECRET must be at least 32 characters` | Generate one with the command above |
| `/ready` returns 503 | The API can't reach the database as the app role: run `setup_db.py`, check `DATABASE_URL` |
| Every endpoint returns 409 `onboarded: false` | That user hasn't called `POST /api/onboarding` yet |
| Chat answers look keyword-based / `agent_runs.status = fallback` | `AGENT_MODE=llm` needs `GROQ_API_KEY`; otherwise check `agent_runs.error` |
| Groq 429s (`rate limited (retry after Ns)`) | The free tier is about 8K tokens/minute. Set `AGENT_DIRECT_TOOLS=true`, wait, or upgrade; requests fall back to rules meanwhile |
| Offers or price history look stale | Keep the scheduler running (`uv run python -m app.scheduler`): it moves prices daily. Or rerun `uv run python scripts/generate_data.py --force` to rebuild the catalog around today (accounts are untouched) |
| Slow requests (300-900 ms) | Neon's Singapore region is ~50 ms per query from India; each endpoint makes a few |

## Documentation

- [API_CONTRACT.md](./API_CONTRACT.md): every endpoint, including auth
- [FRONTEND_INTEGRATION.md](./FRONTEND_INTEGRATION.md): how the web app connects, signs in and tests against this
- [AGENTS.md](./AGENTS.md): the agents, tools, guardrails and scheduler jobs
- [DATA.md](./DATA.md): the synthetic data and how to regenerate it
- [CLAUDE.md](./CLAUDE.md): project rules and build progress
