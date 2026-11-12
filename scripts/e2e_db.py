"""Prepares and cleans the TEST database for the frontend's end-to-end run.

The Playwright suite in ../Bachelor-buddy starts its own API against the test database (never
the app database, which holds real accounts), pinned to the instant the test data was seeded at.

Usage:
  uv run python scripts/e2e_db.py prepare   # seed the test database if it is not seeded yet
  uv run python scripts/e2e_db.py cleanup   # remove what an e2e run left behind

`cleanup` deletes the e2e-...@example.com accounts the specs register (with everything they
own), and the chat history and sign-in tokens the specs created for the seeded users, so the
pytest suite sees the test database exactly as seeded.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import _pg
from scripts._pg import SetupError
from scripts.seed.anchors import TEST_NOW, TEST_SEED_USERS

CLEANUP = (
    ("e2e accounts", "DELETE FROM users WHERE NOT is_seeded AND email LIKE 'e2e-%@example.com'"),
    ("agent runs", "DELETE FROM agent_runs WHERE user_id IN (SELECT id FROM users WHERE is_seeded)"),
    ("conversations", "DELETE FROM chat_conversations WHERE user_id IN (SELECT id FROM users WHERE is_seeded)"),
    ("sign-in tokens", "DELETE FROM refresh_tokens WHERE user_id IN (SELECT id FROM users WHERE is_seeded)"),
)  # fmt: skip


def prepare() -> None:
    from scripts import generate_data

    generate_data.run(
        users=TEST_SEED_USERS, demo=True, test_db=True, anchor_now=TEST_NOW, quiet=True
    )
    print("  [ok] test database ready for e2e", flush=True)


def cleanup() -> None:
    admin = _pg.load_admin_settings()
    with _pg.connect(admin, dbname=admin.test_db_name, as_admin=False, autocommit=False) as conn:
        for label, statement in CLEANUP:
            removed = conn.execute(statement).rowcount
            print(f"  [ok] removed {removed} {label}", flush=True)
        conn.commit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare or clean the test database for e2e.")
    parser.add_argument("command", choices=("prepare", "cleanup"))
    args = parser.parse_args(argv)
    try:
        prepare() if args.command == "prepare" else cleanup()
    except SetupError as exc:
        print(f"  [error] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
