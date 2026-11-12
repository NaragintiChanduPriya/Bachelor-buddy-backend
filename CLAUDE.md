# BachelorBuddy backend: project context

Read this at the start of every session. If a request conflicts with it, ask before acting.

## What this is

The real backend for the BachelorBuddy React app in `../Bachelor-buddy`. Since 2026-11-10 that
app has no mocks: it signs in for real and every page reads this API (Vite proxies `/api` to
port 8000). See `FRONTEND_INTEGRATION.md`.

**Sources of truth:** `API_CONTRACT.md` here (the master; the frontend keeps an identical copy)
and the frontend's `src/types/` (shapes, casing, error codes). Change them together. The money
logic was ported from the frontend's former `src/mocks/calc/` (still in its git history). Data
is generated, never copied.

**Stack:** Python 3.12 (uv), FastAPI, SQLAlchemy 2 async + asyncpg, Alembic, psycopg (setup
scripts), Pydantic v2, PostgreSQL 18 on **Neon** (Singapore region; no Docker), APScheduler,
Groq SDK for agents, JWT + bcrypt, slowapi, ruff + mypy strict + pytest.

**Database (since 2026-11-09, at the user's request):** Neon, not the local server.
- **Admin:** `neondb_owner`, not a superuser, used only by `scripts/`.
- **Endpoints:** the API and tests connect as `bachelorbuddy_app` through the pooled
  endpoint; migrations use the direct endpoint (`POSTGRES_HOST`).
- **Databases:** `bachelorbuddy` and `bachelorbuddy_test`, inside the Neon project. Never
  touch `neondb`.
- **Local leftovers:** the local server still has an empty `bachelorbuddy` role and databases
  from before the switch. The old local settings are commented out in `.env` and saved in
  `.env.local-backup`.

## Non-negotiable rules

1. **Contract first.** Paths, params, envelope, camelCase JSON and DTOs match the frontend
   exactly. If the backend needs a contract change, list it in `FRONTEND_INTEGRATION.md` and
   update both contracts together.
2. **Money math is deterministic code in services, never the LLM.** Store paise, return integer
   rupees, and apply the contract's rounding rules in rupees. Agents only choose what to look up
   and explain the results; every number in a reply comes from a tool result.
3. **One clock.** Everything asks `app.core.clock.Clock`. `CLOCK_MODE=demo` = the 15th of the
   current month at 12:30 IST, which the frontend's e2e specs and demo story rely on.
4. **Timezone-aware timestamps only**, stored UTC, serialized like `toISOString()`. Never rely
   on the session time zone (Neon ignores it): convert with `AT TIME ZONE 'Asia/Kolkata'` or in
   Python.
5. **Few round trips.** Each query to Neon costs about 50 ms from here. Load what an endpoint
   needs in as few queries as possible: no N+1, eager loading, aggregates in SQL.
6. **Every query is scoped to the current user.** Another user's row is `NOT_FOUND`.
7. **Secrets:** env only. Never print or log a password, token or key. The API never loads the
   PostgreSQL admin password; only `scripts/` do.
8. **Database safety:** the scripts only create or drop `APP_DB_NAME` and `APP_DB_NAME_test`,
   and only when the app role owns them.
9. **Invented brand names only**, as in the frontend's CLAUDE.md §3.6.
10. **Gates:** after each phase, run `ruff format`, `ruff check`, `mypy` and `pytest` with zero
   errors. Then summarize what was built and what's next, and **wait for approval** before
   starting the next phase.

## Commands

```bash
uv sync
uv run python scripts/setup_db.py        # idempotent: role, databases, migrations
uv run python scripts/reset_db.py        # drops and recreates only the two BachelorBuddy DBs
uv run uvicorn app.main:app --reload --port 8000
uv run ruff format . && uv run ruff check . && uv run mypy && uv run pytest --cov
```

## Phases

0. Environment check and plan (done 2026-11-09). The plan with the proposed schema, savings
   formula, buy-or-wait rule, data volumes and Groq models is in that session's report.
1. Skeleton, config, logging, error envelope, health checks, `setup_db.py`, Alembic
2. Models and migrations for all tables; auth and users
3. Synthetic data generator and seed (`setup_db.py --seed`)
4. Budget, expenses, food, groceries endpoints
5. Products, price history, alerts, offers, homes, savings, notifications
6. Agents (rules mode, then Groq llm mode), chat endpoint, agent_runs
7. Scheduler jobs, price fluctuation job, manual trigger CLI
8. Contract tests, security review, docs, and an end-to-end check against the frontend

### Decisions (taken 2026-11-09 when the user asked to complete all phases; easy to revisit)
- **Savings formula:** the honest pro-rata formula (app/calc/savings.py, documented in
  API_CONTRACT.md). Demo user on the 15th: ₹2,730 saved, ₹5,140 projected.
- **`CLOCK_MODE=demo`** is the local default; `real` for deployment.
- **Registration collects age and occupation**, so the frontend's `User` type is unchanged.
- **The frontend was first left unmodified** (2026-11-09), then on 2026-11-10 the user asked for
  its mocks to go: it now has real login and no MSW. `DEV_AUTH_BYPASS_EMAIL` remains for
  client-less API work only. The frontend's CLAUDE.md and README were updated to match.
- **Grocery stores:** 2 per type. Per type, the store cheaper for the user's list is used.

## Progress

All phases are complete as of 2026-11-09.
- [x] **Phase 1:** skeleton, config, logging, envelope, health, setup scripts, Alembic. Moved
      to Neon (TLS, admin membership, plaintext role password over TLS only, migrations over
      the direct host).
- [x] **Phase 2:** 34-table schema (Rupees type = paise), initial migration, auth (JWT +
      rotated hashed refresh tokens with reuse detection), users, onboarding, preferences.
- [x] **Phase 3:** deterministic generator (scripts/seed/), loader that replaces only seeded
      rows, consistency checks. Dev DB is seeded: 51 users, ~30k expenses, 108k price points.
- [x] **Phases 4-5:** every contract endpoint, with the money math ported from the mock calc
      modules (js_round for JavaScript rounding).
- [x] **Phase 6:** rules engine (the mock's intents), Concierge + 7 specialists on Groq with
      validated tools, server-built cards, number check, fallback, agent_runs. Groq is untested
      live: no GROQ_API_KEY yet.
- [x] **Phase 7:** 7 idempotent jobs (job_runs + notification dedupe keys), the APScheduler
      process with a PostgreSQL job store, the manual CLI.
- [x] **Phase 8:** contract tests against the frontend's TypeScript types and API_CONTRACT.md
      headings, route-wide auth tests, body-size limit, docs (README, API_CONTRACT,
      FRONTEND_INTEGRATION, AGENTS, DATA), Dockerfile. 340+ tests; ruff and mypy clean.
- [x] **Frontend switched over (2026-11-10):** the frontend's mocks were removed and real login
      added there. This repo's API_CONTRACT.md became the master copy (mock references gone);
      a contract test now covers the auth DTOs against `src/types/auth.ts`, and 🆕 headings
      count in the endpoint check. The frontend's Playwright run starts its own API on port
      8010 with `RATE_LIMIT_AUTH=1000/minute`, never writes to the demo user, and leaves three
      `e2e-…@example.com` users behind per run.
- [x] **Agent understanding (2026-11-10):** "give me hotels list nearby me … lowest to highest
      prices" got the grocery plan ("rice" matched inside "prices"). Rules mode now matches whole
      words, knows eatery words (hotel = place to eat in Bangalore), answers list/sort requests
      with a numbered list, infers "near me", parses "10k" and short area names, resolves "there"
      from the previous reply (deliveryCompare), and every follow-up chip routes. LLM mode: food
      tool takes sort/limit, prompts carry the local meanings, history names the cards shown.
- [x] **Real data only, agent knows the user (2026-11-10):** per the user, every seeded user was
      deleted from the app database (Arjun + 50); only chandupriyanaraginti@gmail.com remains,
      with the full catalog rebuilt around today. `generate_data.py` now seeds no people unless
      `--demo`/`--users N`; the test database keeps Arjun + 3 (`scripts/seed/anchors.py`).
      `CLOCK_MODE` defaults to `real` (required in production); new `fixed` mode +
      `CLOCK_FIXED_AT`. The frontend's e2e run moved to the test database with a pinned clock
      (`scripts/e2e_db.py prepare|cleanup`). Rules agent: profile, any-category spend, expense
      lists, logging an expense on request, alerts, grocery list, savings history, small talk,
      honest fallback (`app/agents/personal.py`). LLM: user context has email and join date,
      new tools get_recent_expenses, get_notifications, get_price_alerts.
- [x] **Chat history (2026-11-10):** `GET /chat/conversations` (paginated, newest activity
      first, title = first user message, preview = latest message), `GET /chat/conversations/:id`
      (messages with cards exactly as shown), `DELETE /chat/conversations/:id`; scoped to the
      user (another user's id is a 404); `app/services/chat_history.py`; contract + API tests.

## Lessons (keep following these)
- Neon: ~50 ms per round trip from India. Keep queries per endpoint low.
- Rules keywords match whole words only (`has_word`); substring matching sent "prices" (rice) to
  the grocery plan. Add a routing test for every new phrasing.
- SQLAlchemy 2.1: `select(Model)` is `Select[Model]`; `Result.tuples()` is deprecated (the test
  config turns app deprecation warnings into errors).
- FastAPI 0.162 doesn't flatten included routers into `app.routes`; use `app.openapi()`.
- Tests run in a rolled-back transaction (`join_transaction_mode="create_savepoint"`). Never
  call `session.rollback()` in request code: it expires the loaded user (lazy="raise").
- On Windows, stop servers by PID; Git Bash `pkill` can't see Windows processes.
- The app database holds real accounts. Never seed people into it or run e2e against it; use
  the test database (`scripts/e2e_db.py`).
- Shell heredocs here mangle backslashes (a doubled backslash arrives as one): make edits that
  contain regexes or newline escapes with the Edit tool, then grep for control characters.
- The local PostgreSQL server also holds unrelated databases (`elze*`, `app_e2e`); never touch them.
