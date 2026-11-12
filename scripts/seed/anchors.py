"""The fixed instant and size the test database is seeded with. Shared by the pytest fixtures and
the frontend's end-to-end run (scripts/e2e_db.py), which pins the API clock to the same instant
(CLOCK_MODE=fixed, CLOCK_FIXED_AT) so the demo user's numbers never drift."""

from __future__ import annotations

from datetime import UTC, datetime

#: The 15th, 12:30 IST: the demo story (food at 70%, ₹14,980 left) holds at this instant.
TEST_NOW = datetime(2026, 11, 15, 7, 0, tzinfo=UTC)
#: Synthetic users besides the demo user.
TEST_SEED_USERS = 3
