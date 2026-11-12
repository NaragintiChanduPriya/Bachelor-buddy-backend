"""Drop and recreate the BachelorBuddy databases. DESTROYS ALL THEIR DATA.

    uv run python scripts/reset_db.py          # asks you to type the database name
    uv run python scripts/reset_db.py --yes    # no prompt (for scripts)

Only APP_DB_NAME and APP_DB_NAME_test are dropped, and only if the app role owns them. No other
database is ever touched. The app role itself is kept. Afterwards it runs setup_db.py.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import _pg, setup_db
from scripts._pg import SetupError, say


def confirm(settings: _pg.AdminSettings, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        raise SetupError("This deletes data. Re-run with --yes to confirm without a prompt.")
    names = " and ".join(f"'{name}'" for name in settings.managed_databases)
    answer = input(
        f"This permanently deletes {names} and all their data.\n"
        f"Type '{settings.app_db_name}' to continue: "
    )
    return answer.strip() == settings.app_db_name


def run(*, assume_yes: bool, migrate: bool) -> bool:
    settings = _pg.load_admin_settings()
    _pg.require_admin_password(settings)
    _pg.check_url_consistency(settings)

    if not confirm(settings, assume_yes):
        print("Cancelled. Nothing was changed.")
        return False

    with _pg.connect(settings, dbname="postgres", as_admin=True) as admin:
        # Check both before dropping either, so a refusal never leaves things half-reset.
        for name in settings.managed_databases:
            info = _pg.database_info(admin, name)
            if info is not None and info.owner != settings.app_db_user:
                raise SetupError(
                    f"Refusing to reset: '{name}' is owned by '{info.owner}', not "
                    f"'{settings.app_db_user}'."
                )
        for name in settings.managed_databases:
            dropped = _pg.drop_managed_database(admin, settings, name)
            say(
                "ok" if dropped else "skip",
                f"dropped '{name}'" if dropped else f"'{name}' did not exist",
            )

    setup_db.run(migrate=migrate)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Drop and recreate the BachelorBuddy databases.")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    parser.add_argument(
        "--skip-migrations", action="store_true", help="recreate without running migrations"
    )
    args = parser.parse_args(argv)
    try:
        done = run(assume_yes=args.yes, migrate=not args.skip_migrations)
    except SetupError as exc:
        print(f"  [error] {exc}", file=sys.stderr)
        return 1
    if done:
        print("Done.")
    return 0 if done else 1


if __name__ == "__main__":
    raise SystemExit(main())
