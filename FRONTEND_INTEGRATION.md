# How the frontend uses this backend

The web app in `../Bachelor-buddy` runs entirely against this API and its synthetic data. Its
mock backend (MSW and fixtures) was removed on 2026-11-10, and it signs users in for real. This
page explains how the two connect and what each side relies on.

## 1. Connection

- The app calls relative URLs under `VITE_API_BASE_URL` (default `/api`).
- In development (`npm run dev`, port 5173) and preview, Vite proxies `/api` to
  `API_PROXY_TARGET` (default `http://localhost:8000`). The browser sees one origin, so CORS is
  not involved locally.
- A hosted build that calls the API on another origin sets `VITE_API_BASE_URL` to the full URL
  (for example `https://api.example.com/api`); add the app's origin to `CORS_ORIGINS` here.

Local run order: start this API (`uv run uvicorn app.main:app --reload --port 8000`), then
`npm run dev` in the frontend.

## 2. Sign-in, as the frontend implements it

| Piece | Frontend file | Backend side |
|---|---|---|
| Types | `src/types/auth.ts`, `ApiErrorCode` in `src/types/api.ts` | `app/schemas/auth.py`; checked by `tests/contract/` |
| Calls | `src/lib/api/services/auth.ts` | `POST /auth/register`, `/login`, `/refresh`, `/logout` |
| Session | `src/lib/api/session.ts`, `src/store/sessionStore.ts` | refresh tokens hashed and rotated |
| 401 renewal | `src/lib/api/client.ts` | 401 `UNAUTHORIZED` on a missing, bad or expired access token |
| Pages and guards | `src/routes/pages/{Login,Register}.tsx`, `RequireAuth`, `RequireOnboarding` | `onboarded` on `User` |

How it behaves:

- **Tokens.** The access token (15 minutes) lives in memory only. The refresh token is persisted
  in `localStorage` (`bb-session`). On startup the app exchanges it for a fresh pair before the
  first render; if that fails, the user lands on `/login`.
- **Renewal.** On a 401 `UNAUTHORIZED` from anything except `/auth/*`, the client refreshes once
  and replays the request. Parallel 401s share one refresh, which matters because refresh
  tokens rotate: presenting an already-used one revokes every token from that login.
- **Guards.** Signed out → `/login` (and back to the requested page afterwards). Signed in but
  not onboarded → `/onboarding`, which calls `POST /onboarding` to generate the first budget.
- **Sign out** (sidebar) calls `/auth/logout`, drops the tokens and clears all cached queries.
- **Forms** mirror the server's rules (password 8+ characters with a letter and a number, no
  edge spaces, at most 72 bytes, not the email; age 16 to 100) and show the API's
  `error.message` when the server still refuses.
- `RATE_LIMITED` is shown as an error, not retried automatically.

`DEV_AUTH_BYPASS_EMAIL` still exists for API work without a client (requests with no token act
as that user). The frontend no longer needs it; leave it empty.

## 3. Things the frontend relies on

- **The contract.** `API_CONTRACT.md` here is the master copy; the frontend keeps an identical
  copy and mirrors it in `src/types/`. Change all three together. `tests/contract/` reads the
  frontend's types and contract from `../Bachelor-buddy` and validates live responses.
- **The clock.** `CLOCK_MODE=real` (the wall clock) for real use. The e2e run pins the clock
  instead (below).
- **Seeded IDs and numbers (e2e only).** The Playwright specs use the test database's seed 42
  data: Arjun's ₹14,980 left, food at 70% (₹5,250 of ₹7,500), ₹1,800 left for shopping, the
  delivering mess `food_002` ("Udupi Sringeri Home Mess") and the non-delivering darshini
  `food_001`. Changing the generator, seed or `scripts/seed/anchors.py` means updating them.
- **Chat wording in rules mode.** A few specs match rules-engine sentences ("You have spent
  ₹5,250 on food this month", "Sorry, I can't help with that one", "You live in HSR Layout and
  work in Bellandur"). They pass with `AGENT_MODE=rules`; with `llm` the wording varies.

## 4. The frontend's e2e run

`npm run e2e` never touches the app database (real accounts). It:

1. Runs `scripts/e2e_db.py prepare`, which seeds the **test** database (catalog, the demo user
   Arjun and three synthetic users, anchored at 15 Nov 2026 12:30 IST) if it isn't already.
2. Starts its **own** API on port 8010 with `DATABASE_URL` set to `TEST_DATABASE_URL`,
   `CLOCK_MODE=fixed`, `CLOCK_FIXED_AT=2026-11-15T07:00:00Z` and `RATE_LIMIT_AUTH=1000/minute`
   (every spec signs in), plus a production build on port 4290 that proxies `/api` to it. It
   never reuses a server already on 8010.
3. Signs in as Arjun with `DEMO_USER_PASSWORD` from this repo's `.env` (or `E2E_PASSWORD`).
   Specs that write data register their own `e2e-…@example.com` account, since the read-only
   specs run in parallel.
4. Runs `scripts/e2e_db.py cleanup`, which deletes those accounts and the chats and sign-in
   tokens the run created for seeded users, so the pytest suite sees the database as seeded.

Don't run the pytest suite and the e2e suite at the same time: they share the test database.

## 5. Accounts

The app database holds real accounts only. Register in the app; there is no demo user there.
To try the demo story locally, seed it explicitly: `uv run python scripts/generate_data.py
--demo` (Arjun signs in with `DEMO_USER_PASSWORD`; reseeding without `--demo` removes him).
