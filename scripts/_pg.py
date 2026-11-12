"""Shared helpers for `setup_db.py` and `reset_db.py`: admin settings, connections, DDL.

Safety rules enforced here:
- Only two databases are ever created or dropped: APP_DB_NAME and APP_DB_NAME + "_test".
- An existing database is never touched unless the app role owns it.
- System databases and roles (postgres, template0/1, pg_*, and Neon's own) are refused outright.
- Passwords are never printed. The app role's password is sent to the server as a SCRAM
  verifier computed client-side, so it doesn't appear in server logs either.

Works with a local server (admin = the `postgres` superuser) and with hosted PostgreSQL such as
Neon (admin = `neondb_owner`, which has CREATEROLE and CREATEDB but is not a superuser). For a
non-superuser admin, the admin is made a member of the app role so it can create databases owned
by that role, manage them, and browse their tables in the provider's console.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import psycopg
from psycopg import sql
from psycopg.rows import TupleRow
from pydantic import SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from app.core.config import ENV_FILE, PROJECT_ROOT

Conn = psycopg.Connection[TupleRow]

IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,50}$")
PROTECTED_DATABASES = frozenset({"postgres", "template0", "template1", "neondb"})
PROTECTED_ROLES = frozenset(
    {"postgres", "neondb_owner", "neon_superuser", "neon_service", "cloud_admin"}
)
DB_COMMENT = (
    "BachelorBuddy database. Managed by scripts/setup_db.py; safe to drop with reset_db.py."
)
#: Generous, because a hosted compute that has scaled to zero takes a few seconds to wake.
CONNECT_TIMEOUT_SECONDS = 15
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
SslMode = Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"]

START_SERVICE_HINT = (
    "Start the PostgreSQL service. Windows: open services.msc and start 'postgresql-x64-18' "
    "(or run `net start postgresql-x64-18` in an administrator terminal). macOS: "
    "`brew services start postgresql`. Linux: `sudo systemctl start postgresql`. "
    "Then check POSTGRES_HOST and POSTGRES_PORT in .env."
)
REMOTE_HOST_HINT = (
    "Check POSTGRES_HOST and POSTGRES_PORT in .env and your internet connection. For Neon, "
    "make sure the project and its compute exist at console.neon.tech."
)


class SetupError(Exception):
    """A problem the user can fix. The message says how, and never contains a secret."""


class AdminSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_admin_user: str = "postgres"
    postgres_admin_password: SecretStr = SecretStr("")
    #: "require" for hosted PostgreSQL (Neon needs TLS); "prefer" is fine locally.
    postgres_sslmode: SslMode = "prefer"

    app_db_name: str = "bachelorbuddy"
    app_db_user: str = "bachelorbuddy_app"
    app_db_password: SecretStr
    database_url: SecretStr
    test_database_url: SecretStr

    @field_validator("app_db_name", "app_db_user")
    @classmethod
    def _safe_identifier(cls, value: str) -> str:
        if not IDENTIFIER.fullmatch(value):
            raise ValueError(
                "use lowercase letters, digits and underscores, starting with a letter "
                "(at most 51 characters)"
            )
        return value

    @field_validator("app_db_name")
    @classmethod
    def _not_system_database(cls, value: str) -> str:
        if value in PROTECTED_DATABASES:
            raise ValueError(f"{value!r} is a PostgreSQL system database")
        return value

    @field_validator("app_db_user")
    @classmethod
    def _not_system_role(cls, value: str) -> str:
        if value in PROTECTED_ROLES or value.startswith("pg_"):
            raise ValueError(f"{value!r} is a PostgreSQL system role")
        return value

    @field_validator("app_db_password")
    @classmethod
    def _real_password(cls, value: SecretStr) -> SecretStr:
        if value.get_secret_value() in {"", "change-me"}:
            raise ValueError("set a real password (it is only used by the app role)")
        return value

    @model_validator(mode="after")
    def _app_role_is_not_admin(self) -> AdminSettings:
        if self.app_db_user == self.postgres_admin_user:
            raise ValueError("APP_DB_USER must differ from POSTGRES_ADMIN_USER")
        return self

    @property
    def test_db_name(self) -> str:
        return f"{self.app_db_name}_test"

    @property
    def managed_databases(self) -> tuple[str, str]:
        return (self.app_db_name, self.test_db_name)


def load_admin_settings() -> AdminSettings:
    if not ENV_FILE.exists():
        raise SetupError(
            f"No .env file at {ENV_FILE}. Copy .env.example to .env and fill in the blanks."
        )
    try:
        return AdminSettings()
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']).upper() or 'settings'}: {err['msg']}"
            for err in exc.errors()
        )
        raise SetupError(f"Fix these values in .env: {problems}") from None


def require_admin_password(settings: AdminSettings) -> None:
    if not settings.postgres_admin_password.get_secret_value():
        raise SetupError(
            "POSTGRES_ADMIN_PASSWORD is empty in .env. Fill in the password of your local "
            f"PostgreSQL '{settings.postgres_admin_user}' user, then run this again."
        )


def check_url_consistency(settings: AdminSettings) -> None:
    """DATABASE_URL and TEST_DATABASE_URL must match APP_DB_NAME / APP_DB_USER / APP_DB_PASSWORD."""
    expected = (
        ("DATABASE_URL", settings.database_url, settings.app_db_name),
        ("TEST_DATABASE_URL", settings.test_database_url, settings.test_db_name),
    )
    for label, secret_url, db_name in expected:
        try:
            url = make_url(secret_url.get_secret_value())
        except Exception:
            raise SetupError(f"{label} in .env is not a valid database URL.") from None
        if url.drivername != "postgresql+asyncpg":
            raise SetupError(f"{label} must start with postgresql+asyncpg://")
        if url.database != db_name:
            raise SetupError(
                f"{label} points at database '{url.database}', but it should be '{db_name}' "
                "(from APP_DB_NAME). Update one of them in .env."
            )
        if url.username != settings.app_db_user:
            raise SetupError(
                f"{label} connects as '{url.username}', but APP_DB_USER is "
                f"'{settings.app_db_user}'. Update one of them in .env."
            )
        if url.password != settings.app_db_password.get_secret_value():
            raise SetupError(
                f"The password in {label} does not match APP_DB_PASSWORD. Keep them in sync in "
                ".env."
            )


def explain_connection_error(
    exc: psycopg.Error, *, host: str, port: int, user: str, as_admin: bool
) -> SetupError:
    """Turn a psycopg connection failure into a message that says what to fix."""
    text = str(exc)
    lowered = text.lower()
    sqlstate = getattr(exc, "sqlstate", None)
    password_key = "POSTGRES_ADMIN_PASSWORD" if as_admin else "APP_DB_PASSWORD"
    user_key = "POSTGRES_ADMIN_USER" if as_admin else "APP_DB_USER"

    if sqlstate == "28P01" or "password authentication failed" in lowered:
        return SetupError(
            f"PostgreSQL rejected the password for user '{user}'. Check {password_key} in .env."
        )
    if "role" in lowered and "does not exist" in lowered:
        return SetupError(f"PostgreSQL has no user named '{user}'. Check {user_key} in .env.")
    if "sslmode" in lowered or "insecure" in lowered or "ssl is required" in lowered:
        return SetupError(
            f"{host} only accepts encrypted connections. Set POSTGRES_SSLMODE=require in .env, "
            "and end DATABASE_URL and TEST_DATABASE_URL with ?ssl=require."
        )
    if sqlstate == "28000" or "no pg_hba.conf entry" in lowered:
        return SetupError(
            f"PostgreSQL refused the connection for user '{user}' (pg_hba.conf). Allow local "
            "password logins for this user, or check the user name in .env."
        )
    if any(
        marker in lowered
        for marker in (
            "connection refused",
            "could not connect",
            "timeout expired",
            "timed out",
            "is the server running",
            "could not translate host name",
        )
    ):
        hint = START_SERVICE_HINT if host in LOCAL_HOSTS else REMOTE_HOST_HINT
        return SetupError(f"Cannot reach PostgreSQL at {host}:{port}. {hint}")
    first_line = text.strip().splitlines()[0] if text.strip() else type(exc).__name__
    return SetupError(f"Could not connect to PostgreSQL at {host}:{port} as '{user}': {first_line}")


def connect(
    settings: AdminSettings, *, dbname: str, as_admin: bool, autocommit: bool = True
) -> Conn:
    if as_admin:
        user, password = settings.postgres_admin_user, settings.postgres_admin_password
    else:
        user, password = settings.app_db_user, settings.app_db_password
    try:
        return psycopg.connect(
            host=settings.postgres_host,
            port=settings.postgres_port,
            user=user,
            password=password.get_secret_value(),
            dbname=dbname,
            sslmode=settings.postgres_sslmode,
            autocommit=autocommit,
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
            application_name="bachelorbuddy-setup",
        )
    except psycopg.Error as exc:
        raise explain_connection_error(
            exc,
            host=settings.postgres_host,
            port=settings.postgres_port,
            user=user,
            as_admin=as_admin,
        ) from None


# ------------------------------------------------------------------ catalog queries


@dataclass(frozen=True)
class DatabaseInfo:
    name: str
    owner: str


def server_version(conn: Conn) -> str:
    row = conn.execute("SHOW server_version").fetchone()
    return str(row[0]) if row else "unknown"


def role_info(conn: Conn, role: str) -> tuple[bool, bool] | None:
    """(can_login, is_superuser) for a role, or None if it doesn't exist."""
    row = conn.execute(
        "SELECT rolcanlogin, rolsuper FROM pg_roles WHERE rolname = %s", (role,)
    ).fetchone()
    return (bool(row[0]), bool(row[1])) if row else None


def database_info(conn: Conn, name: str) -> DatabaseInfo | None:
    row = conn.execute(
        "SELECT d.datname, r.rolname FROM pg_database d "
        "JOIN pg_roles r ON r.oid = d.datdba WHERE d.datname = %s",
        (name,),
    ).fetchone()
    return DatabaseInfo(name=str(row[0]), owner=str(row[1])) if row else None


def template1_is_utf8(conn: Conn) -> bool:
    row = conn.execute(
        "SELECT pg_encoding_to_char(encoding) FROM pg_database WHERE datname = 'template1'"
    ).fetchone()
    return row is not None and str(row[0]).upper() == "UTF8"


# ------------------------------------------------------------------ DDL


def scram_verifier(conn: Conn, role: str, password: SecretStr) -> str:
    """Hash the password client-side (like psql's \\password) so it never reaches server logs."""
    verifier = conn.pgconn.encrypt_password(
        password.get_secret_value().encode(), role.encode(), b"scram-sha-256"
    )
    return verifier.decode()


_CREATE_ROLE = sql.SQL(
    "CREATE ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}"
)
_ALTER_ROLE = sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}")


def _requires_plaintext_password(exc: psycopg.Error) -> bool:
    # Neon hashes passwords itself (to check their strength) and rejects SCRAM verifiers.
    return "plaintext password" in str(exc).lower()


def ensure_role(conn: Conn, settings: AdminSettings) -> Literal["created", "updated"]:
    """Create the app role, or sync its password from .env. Least privilege either way.

    The password goes over as a client-side SCRAM verifier where the server accepts one. A host
    that insists on plaintext (Neon) gets it only over an encrypted connection.
    """
    role = settings.app_db_user
    created = role_info(conn, role) is None
    template = _CREATE_ROLE if created else _ALTER_ROLE
    verifier = scram_verifier(conn, role, settings.app_db_password)
    try:
        conn.execute(template.format(sql.Identifier(role), sql.Literal(verifier)))
    except psycopg.Error as exc:
        if not _requires_plaintext_password(exc):
            raise
        if not conn.pgconn.ssl_in_use:
            raise SetupError(
                f"{settings.postgres_host} needs the password in plaintext, which is only safe "
                "over TLS. Set POSTGRES_SSLMODE=require in .env."
            ) from None
        conn.execute(
            template.format(
                sql.Identifier(role), sql.Literal(settings.app_db_password.get_secret_value())
            )
        )
    return "created" if created else "updated"


def ensure_admin_membership(conn: Conn, role: str) -> bool:
    """Let a non-superuser admin (e.g. Neon's `neondb_owner`) act for the app role.

    Since PostgreSQL 16, creating a role grants the creator only ADMIN OPTION on it. Without
    membership the admin can't create a database owned by the app role, manage it, or read its
    tables. A superuser already can, so nothing changes locally. Returns True if it granted.
    """
    row = conn.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user").fetchone()
    if row is not None and row[0]:
        return False
    row = conn.execute(
        "SELECT pg_has_role(current_user, %s, 'USAGE') AND pg_has_role(current_user, %s, 'SET')",
        (role, role),
    ).fetchone()
    if row is not None and row[0]:
        return False
    conn.execute(
        sql.SQL("GRANT {} TO CURRENT_USER WITH INHERIT TRUE, SET TRUE").format(sql.Identifier(role))
    )
    return True


def ensure_database(conn: Conn, name: str, owner: str) -> Literal["created", "exists"]:
    """Create a managed database owned by the app role. Never adopts someone else's database."""
    info = database_info(conn, name)
    if info is not None:
        if info.owner != owner:
            raise SetupError(
                f"Database '{name}' already exists and is owned by '{info.owner}', not "
                f"'{owner}'. Refusing to touch it. Choose a different APP_DB_NAME in .env, or "
                "change its owner yourself if it really is BachelorBuddy's."
            )
        return "exists"

    template = sql.SQL("") if template1_is_utf8(conn) else sql.SQL(" TEMPLATE template0")
    conn.execute(
        sql.SQL("CREATE DATABASE {} WITH OWNER {} ENCODING 'UTF8'{}").format(
            sql.Identifier(name), sql.Identifier(owner), template
        )
    )
    conn.execute(
        sql.SQL("COMMENT ON DATABASE {} IS {}").format(
            sql.Identifier(name), sql.Literal(DB_COMMENT)
        )
    )
    return "created"


def apply_grants(conn: Conn, name: str, role: str) -> None:
    """Only the app role (and superusers) may connect; the role may create its own schema objects.

    Since PostgreSQL 15 the `public` schema belongs to `pg_database_owner`, so the owning app role
    can create tables in it without further grants.
    """
    conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name)))
    conn.execute(
        sql.SQL("GRANT CONNECT, TEMPORARY, CREATE ON DATABASE {} TO {}").format(
            sql.Identifier(name), sql.Identifier(role)
        )
    )


def verify_app_login(settings: AdminSettings, dbname: str) -> None:
    """Log in as the app role (the account the API uses) and check it can create tables."""
    with connect(settings, dbname=dbname, as_admin=False) as conn:
        row = conn.execute(
            "SELECT current_user, has_schema_privilege(current_user, 'public', 'CREATE')"
        ).fetchone()
    if not row or row[0] != settings.app_db_user or not row[1]:
        raise SetupError(
            f"The app role can log in to '{dbname}' but cannot create tables in the public "
            "schema. Run reset_db.py to recreate the database."
        )


def drop_managed_database(conn: Conn, settings: AdminSettings, name: str) -> bool:
    """Drop one of the two managed databases. Returns False if it didn't exist."""
    if name not in settings.managed_databases:
        raise SetupError(f"Refusing to drop '{name}': it is not a BachelorBuddy database.")
    info = database_info(conn, name)
    if info is None:
        return False
    if info.owner != settings.app_db_user:
        raise SetupError(
            f"Refusing to drop '{name}': it is owned by '{info.owner}', not "
            f"'{settings.app_db_user}', so setup_db.py did not create it."
        )
    conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
    return True


# ------------------------------------------------------------------ migrations


def migration_url(settings: AdminSettings, database_url: SecretStr) -> SecretStr:
    """The app's URL pointed at POSTGRES_HOST:POSTGRES_PORT, still as the app role.

    With Neon, DATABASE_URL uses the pooled (PgBouncer) host while POSTGRES_HOST is the direct
    one. Schema migrations should run over a direct connection. Locally both hosts are the same.
    """
    url = make_url(database_url.get_secret_value()).set(
        host=settings.postgres_host, port=settings.postgres_port
    )
    return SecretStr(url.render_as_string(hide_password=False))


def run_migrations(database_url: SecretStr) -> None:
    """`alembic upgrade head` against one database."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.attributes["database_url"] = database_url.get_secret_value()
    command.upgrade(cfg, "head")


def current_revision(settings: AdminSettings, dbname: str) -> str | None:
    with connect(settings, dbname=dbname, as_admin=False) as conn:
        exists = conn.execute("SELECT to_regclass('public.alembic_version')").fetchone()
        if not exists or exists[0] is None:
            return None
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    return str(row[0]) if row else None


def say(status: str, message: str) -> None:
    """Plain ASCII status lines, so Windows consoles never choke on the output."""
    print(f"  [{status}] {message}", flush=True)
