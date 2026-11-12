"""The database setup scripts, tested against a fake connection: no admin access needed.

The point of these tests is the safety rules: what gets created, what is refused, and that no
password ever appears in a statement or a message.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

import psycopg
import pytest
from psycopg import sql
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from scripts import _pg, reset_db, setup_db
from scripts._pg import AdminSettings, Conn, SetupError

APP_PASSWORD = "app-password-very-secret"
ADMIN_PASSWORD = "admin-password-very-secret"
VERIFIER = "SCRAM-SHA-256$4096:fakesalt$fakestored:fakeserver"


def admin_settings(**overrides: Any) -> AdminSettings:
    values: dict[str, Any] = {
        "postgres_host": "localhost",
        "postgres_port": 5432,
        "postgres_admin_user": "postgres",
        "postgres_admin_password": ADMIN_PASSWORD,
        "app_db_name": "bachelorbuddy",
        "app_db_user": "bachelorbuddy_app",
        "app_db_password": APP_PASSWORD,
        "database_url": (
            f"postgresql+asyncpg://bachelorbuddy_app:{APP_PASSWORD}@localhost:5432/bachelorbuddy"
        ),
        "test_database_url": (
            f"postgresql+asyncpg://bachelorbuddy_app:{APP_PASSWORD}"
            "@localhost:5432/bachelorbuddy_test"
        ),
    }
    values.update(overrides)
    return AdminSettings(_env_file=None, **values)


class FakePgConn:
    def __init__(self, ssl_in_use: bool) -> None:
        self.ssl_in_use = ssl_in_use

    def encrypt_password(self, password: bytes, user: bytes, algorithm: bytes) -> bytes:
        assert algorithm == b"scram-sha-256"
        return VERIFIER.encode()


class FakeConn:
    """Answers the catalog queries `_pg` makes and records every statement it runs.

    `rejects_verifiers=True` behaves like Neon, which refuses pre-hashed passwords.
    """

    def __init__(
        self,
        roles: dict[str, tuple[bool, bool]] | None = None,
        databases: dict[str, str] | None = None,
        template1_encoding: str = "UTF8",
        *,
        admin_is_superuser: bool = True,
        admin_has_role: bool = False,
        rejects_verifiers: bool = False,
        ssl_in_use: bool = False,
    ) -> None:
        self.roles = roles or {}
        self.databases = databases or {}
        self.template1_encoding = template1_encoding
        self.admin_is_superuser = admin_is_superuser
        self.admin_has_role = admin_has_role
        self.rejects_verifiers = rejects_verifiers
        self.pgconn = FakePgConn(ssl_in_use)
        self.statements: list[str] = []
        self._last = ""
        self._params: Sequence[object] = ()

    def execute(self, query: str | sql.Composable, params: Sequence[object] = ()) -> FakeConn:
        self._last = query if isinstance(query, str) else query.as_string(None)
        self._params = params
        self.statements.append(self._last)
        if self.rejects_verifiers and "SCRAM-SHA-256$" in self._last:
            raise psycopg.errors.InternalError_(
                'Received HTTP code 400 from control plane: {"error":"Neon only supports being '
                'given plaintext passwords"}'
            )
        return self

    def fetchone(self) -> tuple[object, ...] | None:
        if "WHERE rolname = current_user" in self._last:
            return (self.admin_is_superuser,)
        if "pg_has_role" in self._last:
            return (self.admin_has_role,)
        if "FROM pg_roles" in self._last:
            return self.roles.get(str(self._params[0]))
        if "FROM pg_database d" in self._last:
            name = str(self._params[0])
            owner = self.databases.get(name)
            return (name, owner) if owner else None
        if "template1" in self._last:
            return (self.template1_encoding,)
        return None

    @property
    def ddl(self) -> list[str]:
        return [s for s in self.statements if not s.startswith(("SELECT", "SHOW"))]


def as_conn(fake: FakeConn) -> Conn:
    return cast(Conn, fake)


# ------------------------------------------------------------------ settings


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"app_db_name": "Bachelor-Buddy"}, "lowercase letters"),
        ({"app_db_name": "postgres"}, "system database"),
        ({"app_db_name": "template1"}, "system database"),
        ({"app_db_user": "pg_monitor"}, "system role"),
        ({"app_db_user": "postgres", "postgres_admin_user": "admin"}, "system role"),
        ({"app_db_user": "neon_superuser"}, "system role"),
        ({"app_db_user": "neondb_owner"}, "system role"),
        ({"app_db_name": "neondb"}, "system database"),
        ({"app_db_user": "admin", "postgres_admin_user": "admin"}, "must differ"),
        ({"app_db_password": "change-me"}, "real password"),
    ],
)
def test_unsafe_settings_are_refused(overrides: dict[str, Any], fragment: str) -> None:
    with pytest.raises(ValidationError, match=fragment):
        admin_settings(**overrides)


def test_test_database_name_derives_from_the_app_name() -> None:
    settings = admin_settings()
    assert settings.managed_databases == ("bachelorbuddy", "bachelorbuddy_test")


def test_empty_admin_password_explains_the_fix() -> None:
    with pytest.raises(SetupError, match="POSTGRES_ADMIN_PASSWORD is empty"):
        _pg.require_admin_password(admin_settings(postgres_admin_password=""))


def test_consistent_urls_pass() -> None:
    _pg.check_url_consistency(admin_settings())


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        (
            {
                "database_url": f"postgresql+asyncpg://bachelorbuddy_app:{APP_PASSWORD}@localhost/other"
            },
            "points at database 'other'",
        ),
        (
            {
                "database_url": f"postgresql+asyncpg://someone:{APP_PASSWORD}@localhost/bachelorbuddy"
            },
            "connects as 'someone'",
        ),
        (
            {
                "database_url": "postgresql+asyncpg://bachelorbuddy_app:stale@localhost/bachelorbuddy"
            },
            "does not match APP_DB_PASSWORD",
        ),
        (
            {
                "database_url": f"postgresql://bachelorbuddy_app:{APP_PASSWORD}@localhost/bachelorbuddy"
            },
            "postgresql\\+asyncpg",
        ),
    ],
)
def test_inconsistent_urls_are_explained_without_secrets(
    overrides: dict[str, Any], fragment: str
) -> None:
    with pytest.raises(SetupError, match=fragment) as caught:
        _pg.check_url_consistency(admin_settings(**overrides))
    assert APP_PASSWORD not in str(caught.value)
    assert "stale" not in str(caught.value)


# ------------------------------------------------------------------ connection errors


@pytest.mark.parametrize(
    ("message", "as_admin", "fragment"),
    [
        (
            'FATAL:  password authentication failed for user "postgres"',
            True,
            "POSTGRES_ADMIN_PASSWORD",
        ),
        ('FATAL:  password authentication failed for user "bb"', False, "APP_DB_PASSWORD"),
        ('FATAL:  role "nobody" does not exist', True, "POSTGRES_ADMIN_USER"),
        ("connection refused\n\tIs the server running on that host?", True, "Start the PostgreSQL"),
        ("timeout expired", True, "Start the PostgreSQL"),
        ('no pg_hba.conf entry for host "::1"', True, "pg_hba.conf"),
        ("connection is insecure (try using `sslmode=require`)", True, "POSTGRES_SSLMODE=require"),
        ("something unusual happened\nsecond line", True, "something unusual happened"),
    ],
)
def test_connection_errors_say_what_to_fix(message: str, as_admin: bool, fragment: str) -> None:
    error = _pg.explain_connection_error(
        psycopg.OperationalError(message), host="localhost", port=5432, user="u", as_admin=as_admin
    )
    assert fragment in str(error)
    assert "second line" not in str(error)


def test_unreachable_hosted_server_gets_a_network_hint_not_a_service_hint() -> None:
    error = _pg.explain_connection_error(
        psycopg.OperationalError("timeout expired"),
        host="ep-example.neon.tech",
        port=5432,
        user="neondb_owner",
        as_admin=True,
    )
    assert "console.neon.tech" in str(error)
    assert "services.msc" not in str(error)


# ------------------------------------------------------------------ DDL


def test_missing_role_is_created_with_least_privilege_and_a_hashed_password() -> None:
    fake = FakeConn()
    assert _pg.ensure_role(as_conn(fake), admin_settings()) == "created"
    (statement,) = fake.ddl
    assert statement.startswith('CREATE ROLE "bachelorbuddy_app" WITH LOGIN NOSUPERUSER')
    assert "NOCREATEDB" in statement
    assert VERIFIER in statement
    assert all(APP_PASSWORD not in s for s in fake.statements)


def test_existing_role_gets_its_password_synced() -> None:
    fake = FakeConn(roles={"bachelorbuddy_app": (True, False)})
    assert _pg.ensure_role(as_conn(fake), admin_settings()) == "updated"
    (statement,) = fake.ddl
    assert statement.startswith('ALTER ROLE "bachelorbuddy_app" WITH LOGIN PASSWORD')
    assert all(APP_PASSWORD not in s for s in fake.statements)


def test_a_host_that_rejects_verifiers_gets_plaintext_only_over_tls() -> None:
    fake = FakeConn(rejects_verifiers=True, ssl_in_use=True)
    assert _pg.ensure_role(as_conn(fake), admin_settings()) == "created"
    refused, accepted = fake.ddl
    assert VERIFIER in refused
    assert accepted.startswith('CREATE ROLE "bachelorbuddy_app" WITH LOGIN NOSUPERUSER')
    assert APP_PASSWORD in accepted  # the server hashes it; the channel is encrypted


def test_plaintext_password_is_never_sent_without_tls() -> None:
    fake = FakeConn(rejects_verifiers=True, ssl_in_use=False)
    with pytest.raises(SetupError, match="POSTGRES_SSLMODE=require"):
        _pg.ensure_role(as_conn(fake), admin_settings())
    assert all(APP_PASSWORD not in s for s in fake.statements)


def test_other_role_errors_are_not_swallowed() -> None:
    class PermissionDenied(FakeConn):
        def execute(
            self, query: str | sql.Composable, params: Sequence[object] = ()
        ) -> PermissionDenied:
            super().execute(query, params)
            if self._last.startswith("CREATE ROLE"):
                raise psycopg.errors.InsufficientPrivilege("permission denied to create role")
            return self

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _pg.ensure_role(as_conn(PermissionDenied(ssl_in_use=True)), admin_settings())


def test_a_superuser_admin_needs_no_membership() -> None:
    fake = FakeConn(admin_is_superuser=True)
    assert not _pg.ensure_admin_membership(as_conn(fake), "bachelorbuddy_app")
    assert fake.ddl == []


def test_a_non_superuser_admin_becomes_a_member_of_the_app_role() -> None:
    fake = FakeConn(admin_is_superuser=False, admin_has_role=False)
    assert _pg.ensure_admin_membership(as_conn(fake), "bachelorbuddy_app")
    assert fake.ddl == ['GRANT "bachelorbuddy_app" TO CURRENT_USER WITH INHERIT TRUE, SET TRUE']


def test_membership_is_not_granted_twice() -> None:
    fake = FakeConn(admin_is_superuser=False, admin_has_role=True)
    assert not _pg.ensure_admin_membership(as_conn(fake), "bachelorbuddy_app")
    assert fake.ddl == []


def test_migrations_run_over_the_direct_host_as_the_app_role() -> None:
    pooled = "ep-x-pooler.c-2.ap-southeast-1.aws.neon.tech"
    direct = "ep-x.c-2.ap-southeast-1.aws.neon.tech"
    settings = admin_settings(
        postgres_host=direct,
        postgres_admin_user="neondb_owner",
        database_url=(
            f"postgresql+asyncpg://bachelorbuddy_app:{APP_PASSWORD}@{pooled}:5432/bachelorbuddy"
            "?ssl=require"
        ),
    )
    url = make_url(_pg.migration_url(settings, settings.database_url).get_secret_value())
    assert url.host == direct
    assert (url.username, url.password, url.database) == (
        "bachelorbuddy_app",
        APP_PASSWORD,
        "bachelorbuddy",
    )
    assert url.query == {"ssl": "require"}


def test_missing_database_is_created_utf8_owned_by_the_app_role() -> None:
    fake = FakeConn()
    assert _pg.ensure_database(as_conn(fake), "bachelorbuddy", "bachelorbuddy_app") == "created"
    create, comment = fake.ddl
    assert create == (
        'CREATE DATABASE "bachelorbuddy" WITH OWNER "bachelorbuddy_app" ENCODING \'UTF8\''
    )
    assert comment.startswith('COMMENT ON DATABASE "bachelorbuddy" IS')


def test_non_utf8_template_falls_back_to_template0() -> None:
    fake = FakeConn(template1_encoding="WIN1252")
    _pg.ensure_database(as_conn(fake), "bachelorbuddy", "bachelorbuddy_app")
    assert fake.ddl[0].endswith("ENCODING 'UTF8' TEMPLATE template0")


def test_existing_database_owned_by_the_app_role_is_left_alone() -> None:
    fake = FakeConn(databases={"bachelorbuddy": "bachelorbuddy_app"})
    assert _pg.ensure_database(as_conn(fake), "bachelorbuddy", "bachelorbuddy_app") == "exists"
    assert fake.ddl == []


def test_a_database_owned_by_someone_else_is_never_adopted() -> None:
    fake = FakeConn(databases={"bachelorbuddy": "postgres"})
    with pytest.raises(SetupError, match="Refusing to touch it"):
        _pg.ensure_database(as_conn(fake), "bachelorbuddy", "bachelorbuddy_app")
    assert fake.ddl == []


def test_grants_restrict_the_database_to_the_app_role() -> None:
    fake = FakeConn()
    _pg.apply_grants(as_conn(fake), "bachelorbuddy", "bachelorbuddy_app")
    assert fake.ddl == [
        'REVOKE ALL ON DATABASE "bachelorbuddy" FROM PUBLIC',
        'GRANT CONNECT, TEMPORARY, CREATE ON DATABASE "bachelorbuddy" TO "bachelorbuddy_app"',
    ]


def test_drop_only_touches_managed_databases() -> None:
    fake = FakeConn(databases={"postgres": "postgres", "shop": "bachelorbuddy_app"})
    for name in ("postgres", "shop", "template1"):
        with pytest.raises(SetupError, match="not a BachelorBuddy database"):
            _pg.drop_managed_database(as_conn(fake), admin_settings(), name)
    assert fake.ddl == []


def test_drop_refuses_a_managed_name_owned_by_someone_else() -> None:
    fake = FakeConn(databases={"bachelorbuddy": "postgres"})
    with pytest.raises(SetupError, match="did not create it"):
        _pg.drop_managed_database(as_conn(fake), admin_settings(), "bachelorbuddy")
    assert fake.ddl == []


def test_drop_removes_an_owned_managed_database() -> None:
    fake = FakeConn(databases={"bachelorbuddy_test": "bachelorbuddy_app"})
    assert _pg.drop_managed_database(as_conn(fake), admin_settings(), "bachelorbuddy_test")
    assert fake.ddl == ['DROP DATABASE "bachelorbuddy_test" WITH (FORCE)']
    assert not _pg.drop_managed_database(as_conn(FakeConn()), admin_settings(), "bachelorbuddy")


# ------------------------------------------------------------------ entry points


def test_setup_db_reports_a_missing_admin_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        _pg, "load_admin_settings", lambda: admin_settings(postgres_admin_password="")
    )
    assert setup_db.main([]) == 1
    captured = capsys.readouterr()
    assert "POSTGRES_ADMIN_PASSWORD is empty" in captured.err
    assert APP_PASSWORD not in captured.out + captured.err


def test_reset_db_requires_confirmation_when_not_interactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    with pytest.raises(SetupError, match="--yes"):
        reset_db.confirm(admin_settings(), assume_yes=False)
    assert reset_db.confirm(admin_settings(), assume_yes=True)


def test_reset_db_cancels_on_a_wrong_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "yes")
    assert not reset_db.confirm(admin_settings(), assume_yes=False)
    monkeypatch.setattr("builtins.input", lambda _: "bachelorbuddy")
    assert reset_db.confirm(admin_settings(), assume_yes=False)
