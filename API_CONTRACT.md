# BachelorBuddy API Contract

The API the BachelorBuddy web app (`../Bachelor-buddy`) is built against. This copy is the
master: when it changes, copy it over the frontend's `API_CONTRACT.md` and update the
frontend's `src/types/` in the same step. The contract tests (`tests/contract/`) validate live
responses against those TypeScript types.

**Status legend:** ✅ implemented in the backend and used by the frontend. 🆕 added by the
backend after the original frontend contract (auth); the frontend implements these too, see
FRONTEND_INTEGRATION.md.

---

## Conventions

- **Base URL:** `VITE_API_BASE_URL` (default `/api`).
- **Casing:** JSON is `camelCase`.
- **Dates:** ISO 8601 strings in UTC (`2026-10-15T07:00:00.000Z`). The UI renders them in IST.
- **IDs:** prefixed strings — `area_hsr`, `food_012`, `prod_007`, `home_004`, `exp_031`,
  `offer_009`, `notif_003`, `msg_014`.
- **Money:** integer rupees. No paise, no floats. All money math happens server-side; the
  frontend only formats.
- **Auth:** `Authorization: Bearer <access token>` is required on everything except
  `/meta/*`, `/auth/*`, `/health` and `/ready`. A missing, invalid or expired token is a 401
  `UNAUTHORIZED`. Every query is scoped to the signed-in user; another user's row is a 404.

### Response envelope

Every successful response:

```json
{
  "success": true,
  "data": {},
  "meta": { "page": 1, "pageSize": 12, "total": 40 },
  "error": null
}
```

`meta` is `null` for non-paginated endpoints.

Every failure:

```json
{
  "success": false,
  "data": null,
  "meta": null,
  "error": { "code": "NOT_FOUND", "message": "Food listing was not found.", "details": null }
}
```

### Error codes

| Code | HTTP | Meaning |
|---|---|---|
| `NOT_FOUND` | 404 | The requested resource does not exist |
| `VALIDATION_ERROR` | 422 | Body failed validation; `details` carries field errors |
| `BAD_REQUEST` | 400 | Malformed or contradictory query parameters |
| `CONFLICT` | 409 | The change conflicts with current state (duplicate email, profile not onboarded yet) |
| `UNAUTHORIZED` 🆕 | 401 | Missing, invalid or expired access token; wrong email or password |
| `RATE_LIMITED` 🆕 | 429 | Too many requests; `Retry-After` header and `details.retryAfterSeconds` |
| `SERVER_ERROR` | 500 | Unexpected server failure |
| `NETWORK_ERROR` | — | Client-side only; the request never reached the server |

### Pagination

List endpoints accept `page` (1-based, default `1`) and `pageSize` (default `12`). The
envelope's `meta` carries `page`, `pageSize` and `total`.

### Behaviour of the real backend

- **Not onboarded yet.** Every endpoint that needs the profile returns 409 `CONFLICT` with
  `details: { "onboarded": false }` until `POST /onboarding` has been called.
- **Validation errors** carry user-facing messages. A bad body is 422
  `VALIDATION_ERROR` and a bad query parameter is 400 `BAD_REQUEST`. `details.fields` lists
  `{ field, message, type }`, and submitted values are never echoed back.
- **Clock.** `CLOCK_MODE=demo` pins "now" to the 15th of the current month at 12:30 IST,
  so the synthetic data always looks current. `real` uses the wall clock.
- **Rate limits.** Auth endpoints allow `RATE_LIMIT_AUTH` per client IP (default 10/minute).
  Chat allows `RATE_LIMIT_CHAT` per user (default 20/minute).
- **Requests over 64 KB** are refused with 413 `BAD_REQUEST`.

---

## 🆕 Auth

Tokens: a short-lived JWT access token (`JWT_ACCESS_TOKEN_EXPIRE_MINUTES`, default 15) and an
opaque refresh token (`JWT_REFRESH_TOKEN_EXPIRE_DAYS`, default 7). Refresh tokens are stored
hashed and rotated on every use. Presenting an already-rotated token revokes every token from
that login.

`AuthTokens`:

```json
{ "accessToken": "eyJ…", "refreshToken": "q3J…", "tokenType": "bearer", "expiresIn": 900, "refreshExpiresIn": 604800 }
```

### 🆕 POST /auth/register

```json
{ "name": "Arjun", "email": "arjun@example.com", "password": "budget2026", "age": 24, "occupation": "Software Engineer" }
```

Password rules: 8+ characters, at most 72 bytes, at least one letter and one number, no leading
or trailing space, and not the email address. Age is 16 to 100. The email is stored lowercased.

**Response 200**: `{ "user": User, "tokens": AuthTokens }`. The new user has `onboarded: false`,
`salary` and `savingsGoal` set to 0, empty area ids and names, and `foodPreference: "veg"` until
onboarding.

**Errors:** `VALIDATION_ERROR`, `CONFLICT` (the email is already registered), `RATE_LIMITED`.

### 🆕 POST /auth/login

`{ "email": "...", "password": "..." }` → `{ "user": User, "tokens": AuthTokens }`.

**Errors:** `UNAUTHORIZED` ("Email or password is incorrect.", the same for an unknown email),
`VALIDATION_ERROR`, `RATE_LIMITED`.

### 🆕 POST /auth/refresh

`{ "refreshToken": "..." }` → `AuthTokens` (a new pair; the presented token stops working).

**Errors:** `UNAUTHORIZED` (unknown, expired, revoked or reused token), `RATE_LIMITED`.

### 🆕 POST /auth/logout

`{ "refreshToken": "..." }` → `{ "loggedOut": true }`. Revokes every token from that login.
Always succeeds, even for an unknown token.

### Health (outside `/api`)

`GET /health` → `{ status: "ok", version, serverNow }`, the liveness check; it never touches
the database. `GET /ready` → `{ status: "ready", checks: { database: "ok" } }`, or 503
`SERVER_ERROR` with `details: { database: "unavailable" }`.

---

## Endpoints

### ✅ GET /meta/areas

Bangalore areas and tech parks. Public, cacheable, changes rarely. This is the only source of
area and tech-park options in the app — components never hard-code them.

**Parameters:** none.

**Response 200**

```json
{
  "success": true,
  "data": {
    "areas": [
      { "id": "area_hsr", "name": "HSR Layout", "lat": 12.9121, "lng": 77.6446, "popular": true },
      { "id": "area_bellandur", "name": "Bellandur", "lat": 12.9304, "lng": 77.6784, "popular": true }
    ],
    "techParks": [
      {
        "id": "park_orbit",
        "name": "Orbit Tech Campus",
        "areaId": "area_bellandur",
        "areaName": "Bellandur",
        "lat": 12.9256,
        "lng": 77.6815
      }
    ]
  },
  "meta": null,
  "error": null
}
```

**Errors:** `SERVER_ERROR`.

---

### ✅ POST /onboarding

Saves the profile and generates the first monthly budget.

**Request**

```json
{
  "salary": 40000,
  "savingsGoal": 8000,
  "homeAreaId": "area_hsr",
  "officeAreaId": "area_bellandur",
  "techParkId": "park_orbit",
  "foodPreference": "veg",
  "cards": [{ "id": "card_hdfc_cc", "bank": "HDFC", "type": "credit", "label": "HDFC Credit Card" }]
}
```

`foodPreference` is one of `veg`, `nonVeg`, `eggetarian`, `vegan`. `techParkId` may be `null`.

**Response 200** — `data` is `{ "user": User, "budget": Budget }`.

The server splits the salary into category limits: the savings goal is honoured first, the rest
is distributed across rent, food, groceries, shopping, travel, bills and misc, and misc absorbs
the rounding remainder so the limits total the salary exactly.

**Errors:** `VALIDATION_ERROR` (salary under ₹5,000, non-integer rupees, savings goal not less
than salary, unknown area or tech park, missing food preference), `SERVER_ERROR`.

---

### ✅ GET /me

Profile, preferences, cards and onboarding status.

**Response 200**

```json
{
  "success": true,
  "data": {
    "id": "user_001",
    "name": "Arjun",
    "email": "arjun@example.com",
    "age": 24,
    "occupation": "Software Engineer",
    "avatarInitials": "A",
    "onboarded": true,
    "joinedAt": "2026-04-18T07:30:00.000Z",
    "preferences": {
      "salary": 40000,
      "savingsGoal": 8000,
      "homeAreaId": "area_hsr",
      "homeAreaName": "HSR Layout",
      "officeAreaId": "area_bellandur",
      "officeAreaName": "Bellandur",
      "techParkId": "park_orbit",
      "techParkName": "Orbit Tech Campus",
      "foodPreference": "veg",
      "cards": [
        { "id": "card_hdfc_cc", "bank": "HDFC", "type": "credit", "label": "HDFC Credit Card" }
      ]
    }
  },
  "meta": null,
  "error": null
}
```

**Errors:** `NOT_FOUND`, `SERVER_ERROR`.

---

### ✅ PUT /me/preferences

Updates any subset of the preferences. Omitted fields keep their current value. Changing the
salary or the savings goal regenerates the category limits.

**Request:** same shape as `POST /onboarding`, every field optional.
**Response 200:** the updated `User`.
**Errors:** `VALIDATION_ERROR`, `SERVER_ERROR`.

---

### ✅ GET /budget/current

The current month's budget. `spent`, `remaining`, `percentUsed` and `status` are derived from
the expense list on every read, so logging an expense changes them immediately.

**Response 200**

```json
{
  "success": true,
  "data": {
    "month": "2026-10",
    "salary": 40000,
    "totalLimit": 40000,
    "totalSpent": 25020,
    "totalRemaining": 14980,
    "percentUsed": 63,
    "daysLeftInMonth": 16,
    "dailySafeSpend": 436,
    "categories": [
      {
        "id": "food",
        "label": "Food",
        "limit": 7500,
        "spent": 5250,
        "remaining": 2250,
        "percentUsed": 70,
        "status": "warning"
      }
    ]
  },
  "meta": null,
  "error": null
}
```

Category ids: `rent`, `food`, `groceries`, `shopping`, `travel`, `bills`, `misc`, `savings`.
`status` is `ok` below 70% used, `warning` from 70%, `danger` from 90%.
`dailySafeSpend` excludes the savings set-aside, so following it never eats into the goal.

**Errors:** `SERVER_ERROR`.

---

### ✅ PUT /budget/current

Updates category limits. The server validates the whole set, not only the changed rows.

**Request**

```json
{ "categories": [{ "id": "food", "limit": 8000 }, { "id": "misc", "limit": 1500 }] }
```

**Response 200:** the recalculated `Budget`.

**Errors:** `VALIDATION_ERROR` — the limits total more than the salary (`details` carries
`{ total, salary }`), a negative limit, a fractional rupee amount, or an unknown category id.

---

### ✅ GET /expenses

Paginated, newest first.

**Query parameters**

| Name | Type | Default | Notes |
|---|---|---|---|
| `month` | `YYYY-MM` | current month | Must match the pattern. The backend always filters to one month |
| `category` | category id | all | One of the eight ids, or omitted |
| `page` | integer | 1 | 1-based |
| `pageSize` | integer | 20 | |

**Response 200** — `data` is `{ "expenses": Expense[], "filteredTotal": number }`.
`filteredTotal` sums every expense matching the filter, not just the returned page, so the UI
never adds money up client-side. `meta` carries the pagination.

```json
{
  "success": true,
  "data": {
    "expenses": [
      {
        "id": "exp_031",
        "category": "food",
        "categoryLabel": "Food",
        "title": "Lunch — full meals",
        "note": null,
        "amount": 120,
        "merchant": "Annapoorna Mess",
        "source": "manual",
        "spentAt": "2026-10-15T09:14:00.000Z",
        "createdAt": "2026-10-15T09:14:00.000Z"
      }
    ],
    "filteredTotal": 25020
  },
  "meta": { "page": 1, "pageSize": 20, "total": 63 },
  "error": null
}
```

`source` is one of `manual`, `delivery`, `subscription`, `recurring`.

**Errors:** `BAD_REQUEST` (malformed month, unknown category), `SERVER_ERROR`.

---

### ✅ POST /expenses

**Request**

```json
{
  "category": "food",
  "title": "Lunch at the mess",
  "amount": 120,
  "merchant": "Annapoorna Mess",
  "note": null,
  "spentAt": "2026-10-15T09:14:00.000Z"
}
```

`spentAt` is optional and defaults to the server's now. `amount` is integer rupees.

**Response 200** — `data` is `{ "expense": Expense, "category": BudgetCategory }`. The updated
category lets the client reconcile the budget without a second request.

**Errors:** `VALIDATION_ERROR` (unknown or missing category, blank title, non-integer or
non-positive amount, amount above ₹10,00,000, invalid date, a date in the future), `SERVER_ERROR`.

---

### ✅ DELETE /expenses/:id

**Response 200** — `data` is `{ "id": string, "category": BudgetCategory }`.

**Errors:** `NOT_FOUND`, `SERVER_ERROR`.

---

### ✅ GET /savings/monthly

**Query:** `month` (`YYYY-MM`, defaults to the current month).

**Response 200**

```json
{
  "success": true,
  "data": {
    "month": "2026-10",
    "monthLabel": "October 2026",
    "saved": 6980,
    "goal": 8000,
    "percentOfGoal": 87,
    "onTrack": true,
    "projectedByMonthEnd": 11447,
    "byCategory": [{ "category": "food", "label": "Food", "saved": 2250, "percentOfTotal": 32 }],
    "byRecommendation": [
      {
        "id": "rec_001",
        "title": "Switched weekday lunch from delivery to Annapoorna Mess",
        "agent": "food",
        "saved": 1680,
        "followedAt": "2026-10-03T07:00:00.000Z"
      }
    ],
    "headline": "On track to save ₹11,447 this month, past your ₹8,000 goal."
  },
  "meta": null,
  "error": null
}
```

**Savings formula** (`app/calc/savings.py`). Let d be today's day of the month in IST and D the
number of days in the month.

- Fixed categories (rent, bills) are expected in full from the 1st. Variable categories (food,
  groceries, shopping, travel, misc) are expected pro rata: `limit × d / D`.
- `saved` = max(0, goal × d / D + Σ(expected − spent)). For a finished month this is exactly
  `salary − total spent`.
- `projectedByMonthEnd` = salary − projected spend. Fixed categories count at
  max(limit, spent); variable categories continue at their current daily rate. For a finished
  month it equals `saved`.
- `byCategory` lists only the underspending categories, biggest first.
- `byRecommendation` lists followed recommendations, each worth
  `(alternative − chosen) × times`. They explain where savings came from and are **not** added
  to `saved`, which would count the same rupee twice.

For the demo user on the 15th this gives ₹2,730 saved and ₹5,140 projected, ₹2,860 short of the
₹8,000 goal.

A past month is computed from that month's budget and expenses. A month with no budget is 404
`NOT_FOUND`, and a future month is 400 `BAD_REQUEST`.

**Errors:** `BAD_REQUEST` (malformed month), `SERVER_ERROR`.

---

### ✅ GET /savings/history

**Query:** `months` (integer 1–24, default 6). The points are the finished months before the current one, oldest first. A month-end snapshot is used where one exists; otherwise the month is computed with the formula above.

**Response 200** — `data` is
`{ months: SavingsHistoryPoint[], averageSaved, bestMonth, totalSaved, trendPercent, summary }`.
`summary` is a sentence describing the trend, used as the chart's text alternative.

**Errors:** `BAD_REQUEST` (months outside 1–24 or not an integer), `SERVER_ERROR`.

---

### ✅ GET /notifications

**Response 200** — `data` is
`{ items: AgentNotification[], unreadCount: number, serverNow: string }`.
`serverNow` lets the UI render relative times ("3h ago") against the server's clock rather than
the browser's.

```json
{
  "success": true,
  "data": {
    "items": [
      {
        "id": "notif_001",
        "kind": "mealSuggestion",
        "agent": "food",
        "title": "Lunch near your office for ₹120",
        "body": "Annapoorna Mess in Bellandur is serving full meals at ₹120…",
        "link": "/food?near=office&maxPrice=150",
        "read": false,
        "createdAt": "2026-10-15T07:05:00.000Z"
      }
    ],
    "unreadCount": 4,
    "serverNow": "2026-10-15T07:00:00.000Z"
  },
  "meta": null,
  "error": null
}
```

`kind` is one of `budgetWarning`, `mealSuggestion`, `priceDrop`, `groceryReminder`,
`offerExpiring`, `savingsReport`, `tip`. `agent` is one of the eight agent names.

**Errors:** `SERVER_ERROR`.

---

### ✅ PATCH /notifications/:id/read

Marks one notification read. **Response 200:** the full notifications payload.

**Errors:** `NOT_FOUND`, `SERVER_ERROR`.

---

### ✅ PATCH /notifications/read-all

Marks every notification read. **Response 200:** the full notifications payload.

**Errors:** `SERVER_ERROR`.

---
---

### ✅ GET /food/nearby

Paginated list of eateries, filtered and sorted. Returns summaries; the full menu comes from
`GET /food/:id`.

**Query parameters**

| Name | Type | Default | Notes |
|---|---|---|---|
| `area` | area id | all areas | Must be a known area id |
| `near` | `home` \| `office` | `home` | Which anchor distances and sorting use |
| `maxPrice` | integer | none | Filters on `avgMealPrice`, must be above zero |
| `type` | `darshini` \| `mess` \| `tiffin` \| `restaurant` | all | |
| `veg` | boolean | all | `true` keeps only pure-veg places |
| `sort` | `price` \| `distance` \| `rating` | `price` | |
| `page` | integer | 1 | |
| `pageSize` | integer | 12 | |

**Response 200**

```json
{
  "success": true,
  "data": [
    {
      "id": "food_003",
      "name": "Annapoorna Mess",
      "type": "mess",
      "areaId": "area_hsr",
      "areaName": "HSR Layout",
      "veg": true,
      "rating": 4.6,
      "reviewCount": 599,
      "priceMin": 30,
      "priceMax": 120,
      "avgMealPrice": 102,
      "distanceFromHomeKm": 0.3,
      "distanceFromOfficeKm": 4.7,
      "tags": ["Unlimited rice", "Home style", "Lunch"],
      "openNow": true,
      "timings": "11:30 – 22:00",
      "thumbnailSeed": 4812,
      "sponsored": false,
      "monthlyPlanPrice": null
    }
  ],
  "meta": { "page": 1, "pageSize": 12, "total": 35 },
  "error": null
}
```

`avgMealPrice` is the headline number used for sorting and the `maxPrice` filter. For a tiffin
service it is the monthly plan divided by the meals it covers, so plans and per-dish places can
be compared on the same scale; `monthlyPlanPrice` carries the plan price itself.

**Trust rule:** `sponsored` listings are labelled in the UI and are never re-ranked above a
cheaper option — the server applies the honest sort and leaves them wherever it puts them.

**Errors:** `BAD_REQUEST` (unknown area, type or sort, `near` other than home/office,
`maxPrice` of zero or less), `SERVER_ERROR`.

---

### ✅ GET /food/:id

One listing with its full menu, timings and distances.

**Response 200** — the summary fields above plus:

```json
{
  "description": "Unlimited rice, sambar, rasam and two palyas on a banana leaf.",
  "address": "19th Main, Sector 3, HSR Layout",
  "openingTime": "11:30",
  "closingTime": "22:00",
  "deliveryAvailable": true,
  "menu": [
    { "id": "food_003_item_01", "name": "Full Meals (unlimited rice)", "price": 120, "veg": true, "popular": true }
  ]
}
```

**Errors:** `NOT_FOUND`, `SERVER_ERROR`.

---

### ✅ GET /food/:id/compare-delivery

The same dish eaten in person versus delivered, with every fee itemised. This is the
calculation behind the product's core claim, so all of it happens server-side.

**Query:** `dish` (optional menu item name, case-insensitive). Defaults to a popular main, never
a monthly plan.

**Response 200**

```json
{
  "success": true,
  "data": {
    "listingId": "food_003",
    "listingName": "Annapoorna Mess",
    "dish": "Full Meals (unlimited rice)",
    "dineInPrice": 120,
    "cheapestDelivery": {
      "platform": "DabbaRun",
      "itemPrice": 134,
      "deliveryFee": 61,
      "platformFee": 8,
      "packagingFee": 15,
      "taxes": 7,
      "total": 225
    },
    "deliveryOptions": [],
    "amountSaved": 105,
    "percentSaved": 47,
    "monthlySavingIfSwitched": 2310
  },
  "meta": null,
  "error": null
}
```

`deliveryOptions` holds every platform, cheapest first; `cheapestDelivery` is the first of them.
Within each breakdown `itemPrice + deliveryFee + platformFee + packagingFee + taxes` equals
`total` exactly — each part is rounded to whole rupees so the bill always reconciles. Delivery
platforms list a marked-up item price, which is why `itemPrice` exceeds `dineInPrice`. Delivery
fees add a per-km charge beyond the first two kilometres. `monthlySavingIfSwitched` projects
the per-meal saving over 22 weekday meals.

**Errors:** `NOT_FOUND`, `BAD_REQUEST` (the place does not deliver), `SERVER_ERROR`.

---

### ✅ POST /chat/messages

The Concierge agent. The handler matches the message against keyword intents and then calls the
same calculation modules and database queries the other endpoints use, so a number quoted in
chat always matches the number on the corresponding page.

**Request**

```json
{ "message": "I have ₹150 and I am hungry near office", "conversationId": null }
```

`conversationId` is `null` on the first message; the reply carries the id to send next time.

**Response 200**

```json
{
  "success": true,
  "data": {
    "messageId": "msg_1042",
    "conversationId": "conv_1041",
    "text": "With ₹150 near your office in Bellandur, Tea Tapri is your best option…",
    "cards": [{ "type": "food", "listing": {} }],
    "agentsUsed": ["concierge", "food", "budget"],
    "steps": ["Checking your budget…", "Finding meals near Bellandur…"],
    "suggestedFollowUps": ["Is delivery cheaper than going there?"],
    "createdAt": "2026-10-15T07:00:00.000Z"
  },
  "meta": null,
  "error": null
}
```

`agentsUsed` is drawn from `concierge`, `budget`, `food`, `grocery`, `shopping`, `deals`,
`home`, `savings`. With `AGENT_MODE=rules` (the default) the backend matches keyword
intents (`app/agents/rules.py`). With `AGENT_MODE=llm` the Concierge and its specialists run on Groq and
fall back to rules for that request on any failure (see AGENTS.md). Either way, every card is
built server-side from the data a tool returned. An unknown or foreign `conversationId` starts
a new conversation instead of failing. A `ChatCard` is one of `food`, `product`, `home`, `budgetSummary`, `offer`
or `groceryPlan`.

**Recognised intents (rules mode):** questions about the user (profile, places, salary, cards),
spending by category and in total, recent or biggest expenses, logging an expense the user
states ("I spent ₹120 on lunch"), alerts and price alerts, food nearby (one pick or a sorted
list), delivery versus dine-in, a product with a deadline, the grocery list and plan, homes,
budget, savings this month and past months, card offers, and small talk. Anything else gets an
honest "Sorry, I can't help with that one" with suggestions. See AGENTS.md.

A single best food pick keeps only places that are open now and within walking distance of the
chosen anchor, widening the radius only when nothing nearby fits — a cheaper place eight
kilometres away is not an answer to someone who is hungry now.

**Errors:** `VALIDATION_ERROR` (empty message, or longer than 500 characters), `SERVER_ERROR`.

---

### ✅ GET /chat/conversations

The signed-in user's past conversations, most recent activity first. Paginated (`page`,
`pageSize`, default 20, at most 50); `meta` carries the total.

**Response 200** — `data` is `ConversationSummary[]`:

```json
[
  {
    "id": "conv_012",
    "title": "give me hotels list nearby me in the order of lowest to highest prices",
    "preview": "Here are 6 places to eat within walking distance of your home in HSR Layout…",
    "messageCount": 4,
    "createdAt": "2026-11-10T06:58:02.000Z",
    "updatedAt": "2026-11-10T07:01:40.000Z"
  }
]
```

`title` is the first thing the user asked and `preview` the latest message, each shortened to
one line (60 and 90 characters, ending in "…" when cut).

---

### ✅ GET /chat/conversations/:id

One conversation, oldest message first, to continue it: send its `id` as `conversationId` with
the next `POST /chat/messages`.

**Response 200** — `data` is `ConversationDetail`:

```json
{
  "id": "conv_012",
  "title": "give me hotels list nearby me in the order of lowest to highest prices",
  "createdAt": "2026-11-10T06:58:02.000Z",
  "updatedAt": "2026-11-10T07:01:40.000Z",
  "messages": [
    {
      "id": "msg_101",
      "role": "user",
      "text": "give me hotels list nearby me in the order of lowest to highest prices",
      "cards": [],
      "agentsUsed": [],
      "steps": [],
      "suggestedFollowUps": [],
      "createdAt": "2026-11-10T06:58:02.000Z"
    }
  ]
}
```

Each message has the shape of the client's `ChatMessage`. Assistant messages carry the cards,
agents, steps and follow-ups exactly as they were shown at the time.

**Errors:** `NOT_FOUND` (unknown id, or another user's conversation).

---

### ✅ DELETE /chat/conversations/:id

Deletes the conversation and its messages. **Response 200**:
`{ "deleted": true, "conversationId": "conv_012" }`.

**Errors:** `NOT_FOUND` (unknown id, or another user's conversation).

---

### Grocery pricing rules

These definitions are implemented in `app/calc/grocery.py`.
Every value is integer rupees.

- **Store types**, always returned in this column order: `quickCommerce`, `supermarket`,
  `kirana`, `onlineBulk`. The backend has two stores per type (e.g. ZipCart and SwiftCrate). For
  each type, the comparison, the list and the catalog all use whichever of its stores is
  cheaper for the user's whole list; the primary store (ZipCart, FreshAisle Supermarket, Sri
  Lakshmi Kirana, StockUp Wholesale) is used when the list is empty or on a tie. The labels
  name the store actually used.
- **Line total at a store** = `quantity × prices[store]`. At `onlineBulk` only, when the item has
  a bulk pack and `quantity ≥ bulkMultiple`, the line is
  `floor(quantity / bulkMultiple) × bulkPrice + (quantity mod bulkMultiple) × prices.onlineBulk`
  if that is cheaper (`bulkApplied: true`).
- **Cheapest store for a line** = lowest line total. Ties go to `kirana`, then `supermarket`, then
  `onlineBulk`, then `quickCommerce` (nearest first). The same rule picks the cheapest single store.
- **`mixedBasketTotal`** = sum of every line at its own cheapest store (buying each item where it is
  cheapest). `GroceryList.estimatedTotal` is the same number.
- **`quickCommerceExtra`** = whole list at `quickCommerce` − `mixedBasketTotal` (never negative): the
  price of convenience.
- **`bulkSaving`** = whole list at `quickCommerce` (several small top-up orders) − whole list at
  `onlineBulk` (one monthly stock-up), never negative.
- **`splitSaving`** = cheapest single store's total − `mixedBasketTotal`: what splitting the list
  across stores saves beyond choosing the best single store.
- Ids: catalog items `groc_001`…, list lines `gli_001` (derived from the item id, stable across
  saves), the list itself `glist_YYYYMM`.

---

### ✅ GET /groceries/catalog

Every item the list can contain, so the client can add items. Not paginated (the catalog is ~66
items).

**Query parameters**

| Name | Type | Default | Notes |
|---|---|---|---|
| `q` | string | — | Case-insensitive match on the item name |
| `category` | string | all | Exact category name, e.g. `Vegetables` |

Categories: `Rice, flour & dal`, `Oil, ghee & sugar`, `Spices & masala`, `Coffee & tea`,
`Dairy & batter`, `Vegetables`, `Fruit`, `Bakery & breakfast`, `Snacks`, `Household & toiletries`.

**Response 200** — `data` is `GroceryCatalogItem[]`.

```json
{
  "success": true,
  "data": [
    {
      "id": "groc_001",
      "name": "Sona masoori rice",
      "unit": "1 kg",
      "category": "Rice, flour & dal",
      "prices": { "quickCommerce": 78, "supermarket": 68, "kirana": 64, "onlineBulk": 60 },
      "bulkUnit": "5 kg bag",
      "bulkPrice": 285,
      "bulkMultiple": 5
    }
  ],
  "meta": null,
  "error": null
}
```

`prices` is the price of one `unit`. `bulkUnit`, `bulkPrice` and `bulkMultiple` are all `null` for
items with no online-bulk pack.

**Errors:** `BAD_REQUEST` (unknown category; `details` carries `{ categories }`), `SERVER_ERROR`.

---

### ✅ GET /groceries/list

The user's monthly list, each line priced at its cheapest store.

**Response 200** — `data` is `GroceryList`. On the first visit of a month, last month's list is carried over.

```json
{
  "success": true,
  "data": {
    "id": "glist_202611",
    "month": "2026-11",
    "items": [
      {
        "id": "gli_001",
        "itemId": "groc_001",
        "name": "Sona masoori rice",
        "unit": "1 kg",
        "category": "Rice, flour & dal",
        "quantity": 5,
        "cheapestStore": "onlineBulk",
        "cheapestStoreLabel": "StockUp Wholesale",
        "cheapestUnitPrice": 57,
        "lineTotal": 285,
        "bulkApplied": true
      },
      {
        "id": "gli_005",
        "itemId": "groc_005",
        "name": "Toor dal",
        "unit": "1 kg",
        "category": "Rice, flour & dal",
        "quantity": 1,
        "cheapestStore": "onlineBulk",
        "cheapestStoreLabel": "StockUp Wholesale",
        "cheapestUnitPrice": 152,
        "lineTotal": 152,
        "bulkApplied": false
      }
    ],
    "itemCount": 22,
    "estimatedTotal": 2398,
    "updatedAt": "2026-11-15T07:00:00.000Z"
  },
  "meta": null,
  "error": null
}
```

`cheapestUnitPrice` is the effective price of one unit at the cheapest store,
`round(lineTotal / quantity)`, so bulk packs are reflected. `bulkApplied` is true only when the
cheapest line is an online-bulk line using bulk packs. Lines keep the order they were saved in.

**Errors:** `SERVER_ERROR`.

---

### ✅ PUT /groceries/list

Replaces the whole list (add, remove and change quantity are all a replace).

**Request**

```json
{
  "items": [
    { "itemId": "groc_001", "quantity": 5 },
    { "itemId": "groc_005", "quantity": 1 },
    { "itemId": "groc_029", "quantity": 6 }
  ]
}
```

An empty `items` array is allowed and clears the list.

**Response 200** — the updated `GroceryList`, as for `GET /groceries/list`, with `updatedAt` set
to the server's now.

**Errors:** `VALIDATION_ERROR` — `items` is not an array, more than 80 lines, an unknown `itemId`,
the same `itemId` twice, or a `quantity` that is not a whole number from 1 to 50.
`SERVER_ERROR`.

---

### ✅ GET /groceries/compare

Every line on the saved list priced at all four store types, with whole-list totals.

**Response 200** — `data` is `GroceryComparison`.

```json
{
  "success": true,
  "data": {
    "month": "2026-11",
    "itemCount": 22,
    "rows": [
      {
        "itemId": "groc_001",
        "name": "Sona masoori rice",
        "unit": "1 kg",
        "category": "Rice, flour & dal",
        "quantity": 5,
        "prices": { "quickCommerce": 78, "supermarket": 68, "kirana": 64, "onlineBulk": 60 },
        "cheapestStore": "onlineBulk",
        "lineTotals": { "quickCommerce": 390, "supermarket": 340, "kirana": 320, "onlineBulk": 285 },
        "bulkApplied": true
      }
    ],
    "storeTotals": [
      { "store": "quickCommerce", "label": "ZipCart", "total": 3046, "isCheapest": false, "differenceFromCheapest": 505, "cheapestItemCount": 0 },
      { "store": "supermarket", "label": "FreshAisle Supermarket", "total": 2665, "isCheapest": false, "differenceFromCheapest": 124, "cheapestItemCount": 1 },
      { "store": "kirana", "label": "Sri Lakshmi Kirana", "total": 2541, "isCheapest": true, "differenceFromCheapest": 0, "cheapestItemCount": 9 },
      { "store": "onlineBulk", "label": "StockUp Wholesale", "total": 2636, "isCheapest": false, "differenceFromCheapest": 95, "cheapestItemCount": 12 }
    ],
    "cheapestStore": "kirana",
    "cheapestStoreLabel": "Sri Lakshmi Kirana",
    "mixedBasketTotal": 2398,
    "bulkSaving": 410,
    "quickCommerceExtra": 648,
    "splitSaving": 143
  },
  "meta": null,
  "error": null
}
```

`rows[].bulkApplied` is true when the row's `onlineBulk` line total uses bulk packs (whether or not
online bulk is the cheapest store for that row). `storeTotals[].cheapestItemCount` is how many rows
are cheapest at that store. See *Grocery pricing rules* for every derived field.

**Errors:** `SERVER_ERROR`.

---

### Chat card: `groceryPlan`

`GroceryPlanSummary`, built from the same comparison:

```json
{ "month": "2026-11", "itemCount": 22, "estimatedTotal": 2398, "cheapestStoreLabel": "Sri Lakshmi Kirana", "bulkSaving": 410 }
```

`estimatedTotal` is `mixedBasketTotal`; `cheapestStoreLabel` is the cheapest single store.

### ✅ GET /products/search

Paginated product summaries across the three platforms (ShopNest, TrendKart, StyleBay). Each
summary carries the lowest in-stock price today. The header search in the app lands on
`/shop?q=<term>`, which calls this endpoint.

**Query parameters**

| Name | Type | Default | Notes |
|---|---|---|---|
| `q` | string | none | Case-insensitive match on name, brand and category; max 80 characters |
| `category` | `shirts` \| `jeans` \| `formalShoes` \| `backpacks` \| `earphones` \| `watches` \| `raincoats` \| `helmets` | all | |
| `maxPrice` | integer | none | Filters on `lowestPrice`; must be above zero |
| `sort` | `price` \| `rating` \| `discount` | `price` | `price` is lowest first; `discount` is biggest % off MRP first |
| `page` | integer | 1 | |
| `pageSize` | integer | 12 | |

**Response 200**

```json
{
  "success": true,
  "data": [
    {
      "id": "prod_009",
      "name": "Oxford Leather Formal Shoes",
      "brand": "Stridewell",
      "category": "formalShoes",
      "categoryLabel": "Formal shoes",
      "lowestPrice": 1649,
      "highestPrice": 1999,
      "mrp": 2999,
      "discountPercent": 45,
      "rating": 4.3,
      "reviewCount": 2184,
      "cheapestPlatform": "ShopNest",
      "fastestDeliveryDays": 2,
      "thumbnailSeed": 37,
      "sponsored": false
    }
  ],
  "meta": { "page": 1, "pageSize": 12, "total": 32 },
  "error": null
}
```

**Trust rule:** `sponsored` products are labelled in the UI and keep the position the honest
sort gives them — they are never moved above a cheaper option.

**Errors:** `BAD_REQUEST` (`q` over 80 characters, unknown category or sort, `maxPrice` of zero
or less), `SERVER_ERROR`.

---

### ✅ GET /products/:id

One product with today's price on every platform, the buy-now-or-wait verdict, and the best
offer the user can actually use.

**Response 200** — the summary fields above plus:

```json
{
  "description": "Polished black Oxfords in genuine leather — the safe choice for an interview.",
  "highlights": ["Genuine leather upper", "Cushioned insole", "Black, sizes 6–11"],
  "platforms": [
    {
      "platform": "ShopNest",
      "price": 1649,
      "mrp": 2999,
      "discountPercent": 45,
      "inStock": true,
      "deliveryDays": 2,
      "deliveryBy": "2026-11-17T14:30:00.000Z",
      "sponsored": false,
      "isCheapest": true
    },
    {
      "platform": "TrendKart",
      "price": 1899,
      "mrp": 2999,
      "discountPercent": 37,
      "inStock": true,
      "deliveryDays": 4,
      "deliveryBy": "2026-11-19T14:30:00.000Z",
      "sponsored": false,
      "isCheapest": false
    }
  ],
  "verdict": "buyNow",
  "verdictReason": "₹1,649 is the lowest price in 90 days, down from ₹2,199 — buy now.",
  "lowest90Day": 1649,
  "highest90Day": 2249,
  "average90Day": 2161,
  "aboveLowest90Day": 0,
  "bestOffer": { "id": "offer_001", "title": "10% off with HDFC credit cards", "…": "full Offer, see GET /offers" },
  "bestDealPlatform": "ShopNest",
  "bestDealBasePrice": 1649,
  "finalPrice": 1485,
  "offerSaving": 164,
  "totalSavingVsMrp": 1514,
  "hasAlert": true,
  "alertTargetPrice": 1799
}
```

| Field | Meaning |
|---|---|
| `platforms` | In-stock first, then cheapest first. `isCheapest` marks the lowest in-stock price |
| `deliveryBy` | When an order placed now would arrive (8 PM IST on that day) |
| `verdict` | `buyNow` or `wait`, computed from the 90-day history of the daily lowest price |
| `verdictReason` | One sentence explaining the verdict with the numbers that drove it |
| `aboveLowest90Day` | Today's lowest price minus the 90-day low; `0` means today is the low |
| `bestOffer` | The usable offer giving the lowest final price on any platform, or `null` |
| `bestDealPlatform` / `bestDealBasePrice` | Where that final price is, and the price there before the offer |
| `finalPrice` | `bestDealBasePrice − offerSaving`. Equals `lowestPrice` when no offer applies |
| `totalSavingVsMrp` | `mrp − finalPrice`, floored at 0 |

**Verdict rules** (`app/calc/products.py`):

1. Today within 3% of the 90-day low → `buyNow`.
2. A sale ended recently and today sits near or above the average → `wait`, quoting the last
   sale price, how often sales recur and when the next one is likely.
3. Today more than 6% above the 90-day average (seasonal demand) → `wait`.
4. Otherwise the price is steady → `buyNow`.

**Errors:** `NOT_FOUND`, `SERVER_ERROR`.

---

### ✅ GET /products/:id/price-history

Daily price per platform, oldest first, ending today.

**Query parameters**

| Name | Type | Default | Notes |
|---|---|---|---|
| `days` | integer | 90 | Whole number from 7 to 90 |

**Response 200**

```json
{
  "success": true,
  "data": {
    "productId": "prod_009",
    "days": 90,
    "platforms": ["ShopNest", "TrendKart", "StyleBay"],
    "points": [
      { "date": "2026-08-18", "prices": { "ShopNest": 2199, "TrendKart": 1899, "StyleBay": 1999 } }
    ],
    "lowest": 1649,
    "highest": 2249,
    "average": 2161,
    "currentLowest": 1649,
    "summary": "Over the last 90 days the lowest price ranged from ₹1,649 to ₹2,249, averaging ₹2,161. Today it is ₹1,649 on ShopNest — the lowest in this window."
  },
  "meta": null,
  "error": null
}
```

`date` is a `YYYY-MM-DD` day in IST. The stats are over the cheapest in-stock price per day.
History is generated from a seeded random source, so it is identical on every load.

**Errors:** `BAD_REQUEST` (`days` outside 7–90), `NOT_FOUND`, `SERVER_ERROR`.

---

### ✅ GET /products/alerts

The user's price alerts, newest first, each with today's price.

**Response 200**

```json
{
  "success": true,
  "data": [
    {
      "id": "alert_001",
      "productId": "prod_009",
      "productName": "Stridewell Oxford Leather Formal Shoes",
      "targetPrice": 1799,
      "currentPrice": 1649,
      "gapToTarget": 0,
      "triggered": true,
      "createdAt": "2026-11-05T15:45:00.000Z"
    }
  ],
  "meta": null,
  "error": null
}
```

`gapToTarget` is how much further the price must fall (`0` once triggered).

**Errors:** `SERVER_ERROR`.

---

### ✅ POST /products/:id/price-alert

Creates the product's alert, or moves its target if one exists (one alert per product).

**Request body**

```json
{ "targetPrice": 1499 }
```

**Response 200** — the saved `PriceAlert` (shape as above).

**Errors:** `VALIDATION_ERROR` (target not a whole number above zero, or not below today's
lowest price — `details.currentPrice` carries that price), `NOT_FOUND`, `SERVER_ERROR`.

---

### ✅ DELETE /products/:id/price-alert

Removes the product's alert.

**Response 200**

```json
{ "success": true, "data": { "productId": "prod_009" }, "meta": null, "error": null }
```

**Errors:** `NOT_FOUND` (unknown product or no alert set), `SERVER_ERROR`.

---

### ✅ GET /offers

Live bank card offers, coupons and cashback across shopping, food-delivery and grocery
platforms. **By default only offers the user can use** are returned: card offers matching a
saved card (bank and card type), plus offers that need no card.

**Query parameters**

| Name | Type | Default | Notes |
|---|---|---|---|
| `platform` | string | all | e.g. `ShopNest`, `FeastDrop`, `ZipCart`; case-insensitive |
| `card` | saved card id | any | e.g. `card_hdfc_cc`; keeps only card offers usable with that card. Must be one of the user's cards |
| `expiringWithinDays` | integer | none | 0–60; keeps offers ending within that many days |
| `eligibleOnly` | boolean | `true` | `false` also returns offers the user cannot use, each with `ineligibleReason` |

**Response 200**

```json
{
  "success": true,
  "data": {
    "offers": [
      {
        "id": "offer_001",
        "kind": "card",
        "title": "10% off with HDFC credit cards",
        "description": "10% instant discount up to ₹500 on ShopNest orders above ₹1,500.",
        "platform": "ShopNest",
        "platformCategory": "shopping",
        "bank": "HDFC",
        "cardType": "credit",
        "code": null,
        "discountPercent": 10,
        "flatDiscount": null,
        "maxDiscount": 500,
        "minOrderValue": 1500,
        "validFrom": "2026-11-01T18:29:00.000Z",
        "validTill": "2026-11-17T18:29:00.000Z",
        "expiringSoon": true,
        "daysLeft": 2,
        "eligible": true,
        "ineligibleReason": null,
        "example": { "orderValue": 2499, "discount": 249, "finalPrice": 2250, "effectivePercent": 10 }
      }
    ],
    "totalCount": 18,
    "eligibleCount": 14,
    "expiringSoonCount": 4,
    "biggestExampleSaving": 500
  },
  "meta": null,
  "error": null
}
```

| Field | Meaning |
|---|---|
| `platformCategory` | `shopping`, `food` or `groceries` — what the platform sells |
| `daysLeft` | Whole days until `validTill` on the server clock, floored at 0 |
| `expiringSoon` | `daysLeft ≤ 3` |
| `eligible` / `ineligibleReason` | Whether the user's saved cards unlock it; otherwise why not, e.g. "Needs a Kotak credit card" |
| `example` | The **true final price** on a typical order (shopping ₹2,499, food ₹349, groceries ₹899, raised to `minOrderValue` when higher). `effectivePercent` is the discount after the cap, which is often below the headline % |
| `totalCount` / `eligibleCount` / `expiringSoonCount` / `biggestExampleSaving` | Headline counts across all live offers, independent of the filters |

Offers are ordered soonest-ending first, then by the size of the worked-example discount.

**Discount rules** (`app/calc/offers.py`): below `minOrderValue` the discount is 0; a
percent offer is `floor(order × percent / 100)`, capped at `maxDiscount`; a flat offer is its
amount, never more than the order.

**Errors:** `BAD_REQUEST` (`expiringWithinDays` outside 0–60, `card` not one of the user's
saved cards), `SERVER_ERROR`.

---

### ✅ GET /homes/search

Bachelor-friendly PGs, co-living spaces and shared flats, each compared with the market average
rent for its area and type. Rent is per person per month (for a shared flat, one person's share).
Results are sorted by rent ascending, with rating breaking ties. **Trust rule:** sponsored
listings carry `sponsored: true` and keep their honest position — they are never moved above a
cheaper home.

**Query parameters**

| Name | Type | Default | Notes |
|---|---|---|---|
| `area` | string | — | Area id from `/meta/areas`, e.g. `area_marathahalli` |
| `maxRent` | integer | — | Rupees per month; must be > 0 |
| `type` | `pg` \| `coliving` \| `sharedFlat` | all | `all` or empty means no filter |
| `foodIncluded` | boolean | — | `true` keeps only homes with meals; `false` keeps only homes without |
| `maxDistanceKm` | number | — | Road distance to the reference tech park; must be > 0 |
| `techPark` | string | user's `techParkId` | Tech park id the distances are measured to. If neither is set, the nearest tech park is used |
| `page` | integer | 1 | ≥ 1 |
| `pageSize` | integer | 12 | 1–50 |

**Response** — `data` holds the page of homes plus an `insight` computed across **every** match,
not just the page. `meta` is the standard pagination block.

```json
{
  "success": true,
  "data": {
    "homes": [
      {
        "id": "home_002",
        "name": "Green Leaf PG for Men",
        "type": "pg",
        "typeLabel": "PG",
        "areaId": "area_marathahalli",
        "areaName": "Marathahalli",
        "rent": 7200,
        "deposit": 10000,
        "sharing": "triple",
        "sharingLabel": "Triple sharing",
        "foodIncluded": true,
        "bachelorFriendly": true,
        "areaAverageRent": 10500,
        "differenceFromAverage": -3300,
        "belowAverage": true,
        "nearestTechParkKm": 0.9,
        "nearestTechParkName": "Crestline Corporate Park",
        "techParkDistanceKm": 6.8,
        "techParkName": "Orbit Tech Campus",
        "rating": 4.2,
        "reviewCount": 187,
        "thumbnailSeed": 214,
        "sponsored": false
      }
    ],
    "insight": {
      "rentBudget": 14000,
      "matchCount": 3,
      "withinBudgetCount": 3,
      "belowAverageCount": 3,
      "averageRent": 8500,
      "cheapestHomeId": "home_002",
      "cheapestHomeName": "Green Leaf PG for Men",
      "cheapestRent": 7200,
      "monthlySavingVsBudget": 6800,
      "yearlySavingVsBudget": 81600
    }
  },
  "meta": { "page": 1, "pageSize": 12, "total": 3 },
  "error": null
}
```

Field notes:

- `differenceFromAverage` = `rent − areaAverageRent`; negative means cheaper than the area.
  `belowAverage` is `differenceFromAverage < 0`.
- `areaAverageRent` is market reference data per area × home type, not an average of the
  listings returned.
- `techParkDistanceKm` / `techParkName` are for the reference tech park (the `techPark` param,
  else the user's); both are `null` when there is no reference park. `nearestTechParkKm` /
  `nearestTechParkName` are always set.
- `insight.rentBudget` is the user's current `rent` budget limit (`GET /budget/current`).
  `monthlySavingVsBudget` = `max(0, rentBudget − cheapestRent)`, `yearlySavingVsBudget` = that × 12.
  `averageRent`, `cheapestHomeId`, `cheapestHomeName` and `cheapestRent` are `null` when nothing
  matches.

**Errors:** `BAD_REQUEST` (unknown `type`, `area` or `techPark`; `maxRent` or `maxDistanceKm` ≤ 0;
`page` < 1 or not whole; `pageSize` outside 1–50), `SERVER_ERROR`.

---

### ✅ GET /homes/:id

One home with amenities, deposit, food details, availability and the commute to every tech park.

**Path parameters:** `id` — home id, e.g. `home_007`.

**Response** — every `HomeSummary` field (distances anchored on the user's tech park), plus:

```json
{
  "success": true,
  "data": {
    "id": "home_007",
    "name": "Private room in 3BHK, BTM 2nd Stage",
    "type": "sharedFlat",
    "typeLabel": "Shared flat",
    "areaId": "area_btm",
    "areaName": "BTM Layout",
    "rent": 11000,
    "deposit": 35000,
    "sharing": "single",
    "sharingLabel": "Private room",
    "foodIncluded": false,
    "bachelorFriendly": true,
    "areaAverageRent": 12500,
    "differenceFromAverage": -1500,
    "belowAverage": true,
    "nearestTechParkKm": 9.2,
    "nearestTechParkName": "Orbit Tech Campus",
    "techParkDistanceKm": 9.2,
    "techParkName": "Orbit Tech Campus",
    "rating": 4.3,
    "reviewCount": 96,
    "thumbnailSeed": 118,
    "sponsored": false,
    "description": "A bright room in a 3BHK with two working flatmates…",
    "address": "16th Main, BTM 2nd Stage, BTM Layout, Bengaluru",
    "amenities": ["Wi-Fi", "Washing machine", "Semi furnished", "Balcony", "Two-wheeler parking"],
    "foodDetails": null,
    "mealsPerDay": null,
    "noticePeriodDays": 30,
    "maintenanceIncluded": true,
    "commutes": [
      {
        "techParkId": "park_orbit",
        "techParkName": "Orbit Tech Campus",
        "techParkAreaName": "Bellandur",
        "distanceKm": 9.2,
        "bikeMinutes": 29,
        "busMinutes": 51
      }
    ],
    "availableFrom": "2026-11-12T04:30:00.000Z",
    "availableNow": true,
    "moveInCost": 46000,
    "yearlyDifferenceFromAverage": -18000,
    "rentBudget": 14000,
    "differenceFromRentBudget": -3000
  },
  "meta": null,
  "error": null
}
```

Field notes:

- `commutes` covers every tech park from `/meta/areas`, nearest first. `distanceKm` is road
  distance; `bikeMinutes` and `busMinutes` are typical weekday travel times.
- `moveInCost` = `rent + deposit`. `yearlyDifferenceFromAverage` = `differenceFromAverage × 12`.
- `differenceFromRentBudget` = `rent − rentBudget`; negative means it fits inside the user's rent
  budget.
- `availableNow` is `true` when `availableFrom` is on or before the server's current time.

**Errors:** `NOT_FOUND` (no home with that id), `SERVER_ERROR`.

