"""Generate deterministic synthetic Bangalore data and load it into PostgreSQL.

    uv run python scripts/generate_data.py                 # the app database
    uv run python scripts/generate_data.py --test          # the test database
    uv run python scripts/generate_data.py --force         # reload even if unchanged
    uv run python scripts/setup_db.py --seed               # same as the first line

The same seed, volumes and anchor day always give the same data. A run with the same
fingerprint as the last one is skipped unless --force is given. Only seeded rows are replaced;
accounts you registered yourself are kept.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.clock import build_clock
from app.core.config import Settings
from app.core.security import hash_password
from scripts import _pg
from scripts._pg import SetupError, say
from scripts.seed.catalog import build_catalog
from scripts.seed.checks import row_counts, run_checks
from scripts.seed.common import GENERATOR_VERSION, Anchor
from scripts.seed.load import load
from scripts.seed.users import build_users

#: The app database gets the catalog only; real people sign up. Tests and demos opt in to users.
DEFAULT_USERS = 0


def fingerprint(seed: int, users: int, anchor: Anchor, demo: bool = False) -> str:
    payload = json.dumps(
        {
            "version": GENERATOR_VERSION,
            "seed": seed,
            "users": users,
            "demo": demo,
            "anchor": anchor.now.isoformat(),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def run(
    *,
    seed: int | None = None,
    users: int = DEFAULT_USERS,
    demo: bool = False,
    test_db: bool = False,
    force: bool = False,
    anchor_now: datetime | None = None,
    quiet: bool = False,
) -> dict[str, int]:
    admin = _pg.load_admin_settings()
    settings = Settings()
    seed_value = settings.seed_value if seed is None else seed
    anchor = Anchor((anchor_now or build_clock(settings).now()).astimezone(UTC))
    dbname = admin.test_db_name if test_db else admin.app_db_name
    print_ = (lambda *_: None) if quiet else say
    print_(
        "ok", f"seeding '{dbname}' with seed {seed_value}, anchor {anchor.local:%Y-%m-%d %H:%M} IST"
    )

    fp = fingerprint(seed_value, users, anchor, demo)
    with _pg.connect(admin, dbname=dbname, as_admin=False, autocommit=False) as conn:
        last = conn.execute("SELECT fingerprint FROM seed_runs ORDER BY id DESC LIMIT 1").fetchone()
        conn.commit()
        if last and last[0] == fp and not force:
            print_("skip", "data is already seeded with this seed and anchor (use --force)")
            return row_counts(conn)

        started = time.perf_counter()
        catalog = build_catalog(seed_value, anchor)
        people = build_users(catalog, seed_value, anchor, users, include_demo=demo)
        built = time.perf_counter()
        print_("ok", f"generated in {built - started:.1f}s")

        password = (
            settings.demo_user_password.get_secret_value() if settings.demo_user_password else ""
        )
        if people and len(password) < 8:
            raise SetupError("Set DEMO_USER_PASSWORD in .env (8+ characters) before seeding.")
        # Seeded people sign in with DEMO_USER_PASSWORD; with nobody seeded it is never used.
        password_hash = (
            hash_password(password, settings.bcrypt_rounds if not test_db else 4) if people else ""
        )
        load(
            conn,
            catalog,
            people,
            password_hash=password_hash,
            seed_run={
                "fingerprint": fp,
                "seed_value": seed_value,
                "anchor": anchor.now,
                "volumes": {"users": len(people), "version": GENERATOR_VERSION},
            },
        )
        conn.commit()
        print_("ok", f"loaded in {time.perf_counter() - built:.1f}s")

        failures = run_checks(
            conn, anchor.today, anchor.now, demo_day=demo and anchor.today.day == 15
        )
        conn.commit()
        if failures:
            raise SetupError("Consistency checks failed: " + "; ".join(failures))
        print_("ok", "consistency checks passed")
        counts = row_counts(conn)
    if not quiet:
        width = max(len(t) for t in counts)
        for table, count in counts.items():
            print(f"      {table:<{width}}  {count:>7,}")
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load synthetic data into PostgreSQL.")
    parser.add_argument("--seed-value", type=int, default=None, help="random seed (SEED_VALUE)")
    parser.add_argument(
        "--users", type=int, default=DEFAULT_USERS, help="synthetic users to create (default 0)"
    )
    parser.add_argument(
        "--demo", action="store_true", help="also create the demo user (arjun@demo.com)"
    )
    parser.add_argument("--test", action="store_true", help="seed the test database instead")
    parser.add_argument("--force", action="store_true", help="reload even if nothing changed")
    args = parser.parse_args(argv)
    try:
        run(
            seed=args.seed_value,
            users=args.users,
            demo=args.demo,
            test_db=args.test,
            force=args.force,
        )
    except SetupError as exc:
        print(f"  [error] {exc}", file=sys.stderr)
        return 1
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
