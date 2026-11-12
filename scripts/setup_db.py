"""Create the BachelorBuddy role and databases on PostgreSQL (Neon or local), then migrate.

    uv run python scripts/setup_db.py

What it does (safe to run any number of times):
1. Reads the admin and app settings from .env.
2. Connects to the "postgres" maintenance database as the admin user (POSTGRES_HOST, which for
   Neon is the direct host, not the pooler).
3. Creates the app role (APP_DB_USER) with least privilege, or syncs its password from .env.
   If the admin isn't a superuser (Neon's neondb_owner), makes it a member of the app role.
4. Creates APP_DB_NAME and APP_DB_NAME_test (UTF8, owned by the app role) if missing.
5. Restricts both databases to the app role (and its members).
6. Logs in as the app role to prove the API's credentials work.
7. Runs Alembic migrations on both databases over the direct host (skip with
   --skip-migrations).
8. With --seed, loads the synthetic data into the app database (scripts/generate_data.py).

It never drops anything and never touches a database it doesn't own. Passwords are never
printed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import _pg
from scripts._pg import SetupError, say


def run(*, migrate: bool = True, seed: bool = False, seed_value: int | None = None) -> None:
    settings = _pg.load_admin_settings()
    _pg.require_admin_password(settings)
    _pg.check_url_consistency(settings)

    print(f"PostgreSQL at {settings.postgres_host}:{settings.postgres_port}", flush=True)
    with _pg.connect(settings, dbname="postgres", as_admin=True) as admin:
        say(
            "ok",
            f"connected as admin '{settings.postgres_admin_user}' "
            f"(server {_pg.server_version(admin)})",
        )

        role_result = _pg.ensure_role(admin, settings)
        say(
            "ok",
            f"role '{settings.app_db_user}' created"
            if role_result == "created"
            else f"role '{settings.app_db_user}' exists; password synced from .env",
        )
        if _pg.ensure_admin_membership(admin, settings.app_db_user):
            say(
                "ok",
                f"admin '{settings.postgres_admin_user}' can now manage '{settings.app_db_user}' "
                "objects (not a superuser)",
            )

        for name in settings.managed_databases:
            db_result = _pg.ensure_database(admin, name, settings.app_db_user)
            _pg.apply_grants(admin, name, settings.app_db_user)
            say("ok", f"database '{name}' {'created' if db_result == 'created' else 'exists'}")

    for name in settings.managed_databases:
        _pg.verify_app_login(settings, name)
        say("ok", f"app role can log in to '{name}' and create tables")

    if not migrate:
        say("skip", "migrations (--skip-migrations)")
        return

    targets = (
        (settings.app_db_name, settings.database_url),
        (settings.test_db_name, settings.test_database_url),
    )
    for name, url in targets:
        try:
            _pg.run_migrations(_pg.migration_url(settings, url))
        except Exception as exc:
            first_line = (str(exc).strip().splitlines() or [type(exc).__name__])[0]
            raise SetupError(
                f"Migrations failed on '{name}': {first_line}. Run `uv run alembic upgrade head` "
                "for the full error."
            ) from None
        revision = _pg.current_revision(settings, name)
        say(
            "ok",
            f"migrations on '{name}' at head ({revision})"
            if revision
            else f"migrations on '{name}': none defined yet",
        )

    if seed:
        from scripts import generate_data

        print("Synthetic data", flush=True)
        generate_data.run(seed=seed_value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument(
        "--skip-migrations", action="store_true", help="create the role and databases only"
    )
    parser.add_argument("--seed", action="store_true", help="load synthetic data afterwards")
    parser.add_argument("--seed-value", type=int, default=None, help="random seed (SEED_VALUE)")
    args = parser.parse_args(argv)
    if args.seed and args.skip_migrations:
        parser.error("--seed needs the migrations; drop --skip-migrations")
    try:
        run(migrate=not args.skip_migrations, seed=args.seed, seed_value=args.seed_value)
    except SetupError as exc:
        print(f"  [error] {exc}", file=sys.stderr)
        return 1
    except psycopg.Error as exc:
        # Server error messages never echo the statement, so no password can leak here.
        first_line = (str(exc).strip().splitlines() or [type(exc).__name__])[0]
        print(f"  [error] PostgreSQL refused a setup step: {first_line}", file=sys.stderr)
        return 1
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
