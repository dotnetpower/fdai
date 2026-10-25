"""Real PostgreSQL recovery checks, restricted to the isolated validation cluster."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from uuid import uuid4

import pytest
from azure.core.exceptions import AzureError
from lifecycle.hub.tests.test_prepared_migration import legacy_schema, no_initialization
from sqlalchemy import MetaData, create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import InternalError, ProgrammingError

from fdai_lifecycle_hub import database_inspection as check
from fdai_lifecycle_hub.migrations import _versions, migrate

pytestmark = pytest.mark.skipif(
    not os.environ.get("FDAI_DATABASE_URL"), reason="Use with-local-test-database.py (5433)."
)


@pytest.fixture
def database():
    url = make_url(os.environ["FDAI_DATABASE_URL"])
    check._require_endpoint_binding(url)
    assert url.host in {"127.0.0.1", "localhost", "::1"} and url.port == 5433
    schema = "hub_inspection_" + uuid4().hex
    admin = create_engine(url, hide_parameters=True)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url, connect_args={"options": f"-csearch_path={schema}"}, hide_parameters=True
    )
    try:
        yield engine, admin, schema
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def initialize(engine, kind):
    tables = check._tables(kind)
    namespace = "release_hub" if kind == "release" else "lifecycle_hub"

    def create(connection):
        metadata = MetaData()
        for table in tables:
            table.to_metadata(metadata)
        metadata.create_all(connection)

    migrate(engine, namespace, create)


@pytest.mark.parametrize("revision", [1, 5])
def test_completed_preparation_remains_inspectable(database, revision):
    engine, _, schema = database
    initialize(engine, "target")
    before = check.observe(engine, "target", "source")
    with engine.begin() as connection:
        _versions("lifecycle_hub").drop(connection)
    legacy_schema(engine, revision)
    migrate(engine, "lifecycle_hub", no_initialization, prepare=True)
    migrate(engine, "lifecycle_hub", no_initialization)
    baseline = check.observe(engine, "target", "source")
    version = "lifecycle_hub_schema_revision"
    assert baseline.tables[version].rows == 1
    assert baseline.tables[version].columns_sha256 != before.tables[version].columns_sha256
    assert baseline.tables[version].sample_sha256 != before.tables[version].sample_sha256
    alternate = create_engine(
        engine.url.set(host="localhost" if engine.url.host != "localhost" else "127.0.0.1"),
        connect_args={"options": f"-csearch_path={schema}"},
        hide_parameters=True,
    )
    try:
        restored = check.observe(alternate, "target", "restored", baseline)
        assert restored.tables == baseline.tables
    finally:
        alternate.dispose()
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE lifecycle_hub_schema_revision ALTER COLUMN prepared_revision TYPE BIGINT"
        )
    with pytest.raises(check.InspectionError, match="schema_column_type_mismatch"):
        check.observe(engine, "target", "source")


ROUTING_OVERRIDES = [
    ("host", "source.example.com"),
    ("hostaddr", "127.0.0.1"),
    ("port", "5433"),
    ("dbname", "synthetic"),
    ("user", "synthetic"),
    ("service", "synthetic"),
]


@pytest.mark.parametrize("key,value", [*ROUTING_OVERRIDES, ("port", "5432")])
def test_database_fixture_rejects_query_routing_before_engine_creation(
    monkeypatch, request, key, value
):
    monkeypatch.setenv(
        "FDAI_DATABASE_URL",
        f"postgresql+psycopg://synthetic@localhost:5433/synthetic?{key}={value}",
    )

    def must_not_create(*args, **kwargs):
        pytest.fail("Unsafe fixture URLs must fail before either engine is created.")

    monkeypatch.setattr(sys.modules[__name__], "create_engine", must_not_create)
    with pytest.raises(check.InspectionError, match="database_routing_override_not_allowed"):
        request.getfixturevalue("database")


@pytest.mark.parametrize("key,value", ROUTING_OVERRIDES)
def test_observation_rejects_query_routing_before_connect(key, value):
    engine = create_engine(
        f"postgresql+psycopg://synthetic@restore.example.com/synthetic?{key}={value}",
        hide_parameters=True,
    )

    @event.listens_for(engine, "do_connect")
    def must_not_connect(*args):
        pytest.fail("Routing overrides must fail before a connection attempt.")

    try:
        with pytest.raises(check.InspectionError, match="database_routing_override_not_allowed"):
            check.observe(engine, "release", "source")
    finally:
        engine.dispose()


@pytest.mark.parametrize("target", ["source", "restored"])
@pytest.mark.parametrize("key,value", ROUTING_OVERRIDES)
def test_cli_rejects_query_routing_before_engine_creation(
    monkeypatch, tmp_path, capsys, target, key, value
):
    original = f"postgresql+psycopg://synthetic@source.example.com/synthetic?{key}={value}"
    monkeypatch.setenv("FDAI_RELEASE_HUB_DATABASE_URL", original)

    def must_not_create(kind):
        pytest.fail("Routing overrides must fail before creating the remote engine.")

    monkeypatch.setattr(check, "remote_engine", must_not_create)
    output = tmp_path / "result"
    arguments = ["inspect", "--kind", "release", "--target", target, "--output", str(output)]
    if target == "restored":
        baseline = tmp_path / "baseline"
        baseline.write_text(
            check.Receipt(
                kind="release",
                target="source",
                database_binding="0" * 64,
                host_binding="1" * 64,
                tables={},
            ).model_dump_json()
        )
        arguments += ["--restored-host", "restore.example.com", "--baseline", str(baseline)]
    monkeypatch.setattr(sys, "argv", arguments)
    with pytest.raises(SystemExit) as error:
        check.main()
    assert error.value.code == 1
    assert not output.exists()
    assert os.environ["FDAI_RELEASE_HUB_DATABASE_URL"] == original
    printed = capsys.readouterr()
    assert not printed.out
    assert "database_routing_override_not_allowed" in printed.err
    assert "step=configuration" in printed.err
    assert "synthetic" not in printed.err
    assert "example.com" not in printed.err


@pytest.mark.parametrize(
    ("kind", "optional"),
    [
        ("release", ["catalog_role_root", "catalog_role_state"]),
        ("target", ["catalog_integrity_state"]),
    ],
)
def test_signed_role_tables_are_fingerprinted_only_when_present(database, kind, optional):
    engine, _, _ = database
    initialize(engine, kind)
    assert not set(optional) & set(check.observe(engine, kind, "source").tables)
    if kind == "release":
        from fdai_release_hub.role_tables import role_metadata as metadata
    else:
        from fdai_lifecycle_hub.catalog_integrity_state import metadata
    metadata.create_all(engine)
    baseline = check.observe(engine, kind, "source")
    assert set(optional) <= set(baseline.tables)
    with engine.begin() as connection:
        connection.execute(text(f"DROP TABLE {optional[0]}"))
    assert optional[0] not in check.observe(engine, kind, "source").tables


@pytest.mark.parametrize("kind", ["release", "target"])
def test_empty_product_and_same_state_compare_in_readonly_transaction(database, kind):
    engine, _, schema = database
    initialize(engine, kind)
    states = []

    @event.listens_for(engine, "before_cursor_execute")
    def record(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("SELECT current_database"):
            cursor.execute("SHOW transaction_read_only")
            states.append(cursor.fetchone()[0])

    before = inspect(engine).get_table_names()
    baseline = check.observe(engine, kind, "source")
    assert baseline.revision == (2 if kind == "target" else 1)
    assert sum(table.rows for table in baseline.tables.values()) == 1
    assert states and all(value == "on" for value in states)
    alternate = create_engine(
        engine.url.set(host="localhost" if engine.url.host != "localhost" else "127.0.0.1"),
        connect_args={"options": f"-csearch_path={schema}"},
        hide_parameters=True,
    )
    try:
        compared = check.observe(alternate, kind, "restored", baseline)
        assert compared.tables == baseline.tables
    finally:
        alternate.dispose()
    assert inspect(engine).get_table_names() == before
    with engine.connect() as connection:
        assert connection.scalar(text("SHOW transaction_read_only")) == "off"


def test_persisted_state_changes_and_schema_differences_fail(database):
    engine, _, schema = database
    initialize(engine, "release")
    sentinel = "synthetic-private-payload-never-print"
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO metadata VALUES (:value)"), {"value": sentinel})
    baseline = check.observe(engine, "release", "source")
    assert baseline.tables["metadata"].rows == 1
    assert sentinel not in baseline.model_dump_json()
    alternate = create_engine(
        engine.url.set(host="localhost" if engine.url.host != "localhost" else "127.0.0.1"),
        connect_args={"options": f"-csearch_path={schema}"},
        hide_parameters=True,
    )
    try:
        assert check.observe(alternate, "release", "restored", baseline).tables == baseline.tables
        with engine.begin() as connection:
            connection.execute(text("UPDATE metadata SET created_at = 'changed'"))
        with pytest.raises(check.InspectionError, match="restored_state_mismatch"):
            check.observe(alternate, "release", "restored", baseline)
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE metadata ADD COLUMN extra text"))
        with pytest.raises(check.InspectionError, match="schema_columns_mismatch"):
            check.observe(engine, "release", "source")
    finally:
        alternate.dispose()


@pytest.mark.parametrize("revision", [None, 3])
def test_empty_database_or_wrong_revision_fails_without_mutation(database, revision):
    engine, _, _ = database
    if revision is not None:
        initialize(engine, "release")
        with engine.begin() as connection:
            connection.execute(text("UPDATE release_hub_schema_revision SET revision = 3"))
    before = inspect(engine).get_table_names()
    with pytest.raises(check.InspectionError, match="schema_revision_mismatch"):
        check.observe(engine, "release", "source")
    assert inspect(engine).get_table_names() == before


def test_permissions_are_checked_using_real_postgres_roles(database):
    engine, admin, schema = database
    initialize(engine, "release")
    role = "hub_inspection_role_" + uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
        connection.execute(text(f'GRANT USAGE, CREATE ON SCHEMA "{schema}" TO "{role}"'))
        connection.execute(
            text(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES "
                f'IN SCHEMA "{schema}" TO "{role}"'
            )
        )
        connection.execute(text(f'GRANT USAGE ON ALL SEQUENCES IN SCHEMA "{schema}" TO "{role}"'))
    restricted = create_engine(
        engine.url,
        connect_args={"options": f"-csearch_path={schema} -crole={role}"},
        hide_parameters=True,
    )
    try:
        check.observe(restricted, "release", "source")
        with admin.begin() as connection:
            connection.execute(text(f'REVOKE DELETE ON "{schema}".metadata FROM "{role}"'))
        with pytest.raises(
            check.InspectionError, match="runtime_privileges_missing stage=table_metadata"
        ):
            check.observe(restricted, "release", "source")
        with admin.begin() as connection:
            connection.execute(text(f'GRANT DELETE ON "{schema}".metadata TO "{role}"'))
            connection.execute(
                text(f'REVOKE USAGE ON ALL SEQUENCES IN SCHEMA "{schema}" FROM "{role}"')
            )
        with pytest.raises(check.InspectionError, match="runtime_sequence_privileges_missing"):
            check.observe(restricted, "release", "source")
    finally:
        restricted.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP OWNED BY "{role}"'))
            connection.execute(text(f'DROP ROLE "{role}"'))


def test_row_bound_and_multiple_revision_rows_fail(database):
    engine, _, _ = database
    initialize(engine, "release")
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO metadata SELECT n::text FROM generate_series(1,1000) n")
        )
    assert check.observe(engine, "release", "source").tables["metadata"].rows == 1000
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO metadata VALUES ('1001')"))
    with pytest.raises(check.InspectionError, match="table_row_bound_exceeded"):
        check.observe(engine, "release", "source")
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE metadata"))
        connection.execute(text("INSERT INTO release_hub_schema_revision VALUES (3)"))
    with pytest.raises(check.InspectionError, match="schema_revision_row_count_mismatch"):
        check.observe(engine, "release", "source")


def test_connection_failure_and_cli_never_print_secret(database, monkeypatch, tmp_path, capsys):
    engine, _, _ = database
    broken = create_engine(
        engine.url.set(port=1, password="synthetic-secret"), hide_parameters=True
    )
    try:
        with pytest.raises(check.InspectionError, match="database_connect_failed"):
            check.observe(broken, "release", "source")
    finally:
        broken.dispose()
    monkeypatch.setattr(check, "remote_engine", lambda kind: broken)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "inspect",
            "--kind",
            "release",
            "--target",
            "source",
            "--output",
            str(tmp_path / "receipt"),
        ],
    )
    with pytest.raises(SystemExit) as error:
        check.main()
    assert error.value.code == 1
    output = capsys.readouterr()
    assert "database_connect_failed" in output.err
    assert not any(
        value in output.out + output.err
        for value in ["synthetic-secret", str(engine.url), "127.0.0.1", "Traceback"]
    )
    assert not (tmp_path / "receipt").exists()


def test_previous_sql_function_error_and_transaction_behavior(database):
    engine, _, _ = database
    with engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT md5(coalesce(string_agg(table_name || ':' || column_name || ':' || "
                "data_type || ':' || is_nullable, '|' ORDER BY table_name, ordinal_position), '')) "
                "FROM information_schema.columns WHERE table_schema = current_schema()"
            )
        )
        connection.rollback()
        # Standard PostgreSQL doesn't provide the Azure server-level Entra extension.
        with pytest.raises(ProgrammingError) as error:
            connection.execute(text("SELECT * FROM pgaadauth_list_principals(false)"))
        assert error.value.orig.sqlstate == "42883"
        connection.rollback()
        connection.execute(text("SET TRANSACTION READ ONLY"))
        with pytest.raises(InternalError) as write:
            connection.execute(text("CREATE TABLE forbidden_write (id integer)"))
        assert write.value.orig.sqlstate == "25006"
        connection.rollback()
        assert connection.scalar(text("SHOW transaction_read_only")) == "off"
    assert "forbidden_write" not in inspect(engine).get_table_names()


def test_fingerprints_cover_exactly_the_first_32_primary_keys(database):
    engine, _, _ = database
    initialize(engine, "release")
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO metadata SELECT lpad(n::text, 4, '0') FROM generate_series(1,33) n")
        )
    before = check.observe(engine, "release", "source").tables["metadata"]
    with engine.begin() as connection:
        connection.execute(text("UPDATE metadata SET created_at='0034' WHERE created_at='0033'"))
    outside = check.observe(engine, "release", "source").tables["metadata"]
    assert before == outside
    with engine.begin() as connection:
        connection.execute(text("UPDATE metadata SET created_at='0000' WHERE created_at='0001'"))
    inside = check.observe(engine, "release", "source").tables["metadata"]
    assert inside.rows == before.rows == 33
    assert inside.sample_sha256 != before.sample_sha256


@pytest.mark.parametrize(
    "kind,table", [("release", "metadata"), ("target", "lifecycle_configuration_revision")]
)
def test_populated_product_records_survive_observation(database, kind, table):
    engine, _, _ = database
    initialize(engine, kind)
    with engine.begin() as connection:
        if kind == "release":
            connection.execute(text("INSERT INTO metadata VALUES ('synthetic-persisted-state')"))
        else:
            connection.execute(
                text(
                    "INSERT INTO lifecycle_configuration_revision (digest,body,imported_at) "
                    "VALUES ('synthetic-digest', '{}', '2026-01-01T00:00:00Z')"
                )
            )
    before = check.observe(engine, kind, "source")
    after = check.observe(engine, kind, "source")
    assert before.tables == after.tables
    assert before.tables[table].rows == 1
    assert "synthetic-" not in after.model_dump_json()


def test_timestamp_fingerprints_do_not_depend_on_session_timezone(database):
    engine, _, schema = database
    initialize(engine, "target")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO lifecycle_configuration_revision (digest,body,imported_at) "
                "VALUES ('synthetic-digest', '{}', '2026-01-01T00:00:00Z')"
            )
        )
    alternate = create_engine(
        engine.url,
        connect_args={"options": f"-csearch_path={schema} -cTimeZone=Asia/Seoul"},
        hide_parameters=True,
    )
    try:
        before = check.observe(engine, "target", "source")
        after = check.observe(alternate, "target", "source")
        assert before.tables == after.tables
        with alternate.connect() as connection:
            assert connection.scalar(text("SHOW TimeZone")) == "Asia/Seoul"
    finally:
        alternate.dispose()


def test_fingerprints_do_not_depend_on_insertion_order(database):
    engine, _, _ = database
    initialize(engine, "release")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO metadata SELECT n::text FROM generate_series(1,40) n"))
    before = check.observe(engine, "release", "source")
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE metadata"))
        connection.execute(
            text("INSERT INTO metadata SELECT n::text FROM generate_series(40,1,-1) n")
        )
    assert check.observe(engine, "release", "source").tables == before.tables


def test_schema_column_type_and_missing_table_fail(database):
    engine, _, _ = database
    initialize(engine, "release")
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE metadata ALTER COLUMN created_at TYPE varchar(80)"))
    with pytest.raises(check.InspectionError, match="schema_column_type_mismatch"):
        check.observe(engine, "release", "source")
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE metadata ALTER COLUMN created_at TYPE text"))
        connection.execute(text("DROP TABLE metadata"))
    with pytest.raises(check.InspectionError):
        check.observe(engine, "release", "source")


def test_observer_database_write_is_rejected_and_rolled_back(database, monkeypatch):
    engine, _, _ = database
    initialize(engine, "release")

    def accidental_write(connection, table):
        connection.execute(text("INSERT INTO metadata VALUES ('must-not-persist')"))

    monkeypatch.setattr(check, "_observe_table", accidental_write)
    with pytest.raises(check.InspectionError, match="sqlstate=25006"):
        check.observe(engine, "release", "source")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM metadata")) == 0
        assert connection.scalar(text("SHOW transaction_read_only")) == "off"


def test_baseline_target_host_and_principal_guards(database):
    engine, _, _ = database
    initialize(engine, "release")
    source = check.observe(engine, "release", "source")
    with pytest.raises(check.InspectionError, match="source_baseline_required"):
        check.observe(engine, "release", "restored")
    with pytest.raises(check.InspectionError, match="restored_host_must_differ"):
        check.observe(engine, "release", "restored", source)
    with pytest.raises(check.InspectionError, match="baseline_target_mismatch"):
        check.observe(engine, "release", "restored", source.model_copy(update={"kind": "target"}))
    with pytest.raises(check.InspectionError, match="database_or_principal_mismatch"):
        check.observe(
            engine,
            "release",
            "restored",
            source.model_copy(update={"host_binding": "0" * 64, "database_binding": "0" * 64}),
        )


@pytest.mark.parametrize("existing", ["regular", "symlink"])
def test_cli_source_receipt_is_private_and_not_overwritten(
    database, monkeypatch, tmp_path, capsys, existing
):
    engine, _, _ = database
    initialize(engine, "release")
    monkeypatch.setattr(check, "remote_engine", lambda kind: engine)
    path = tmp_path / "source.json"
    monkeypatch.setattr(
        sys, "argv", ["inspect", "--kind", "release", "--target", "source", "--output", str(path)]
    )
    check.main()
    assert path.stat().st_mode & 0o777 == 0o600
    receipt = check.Receipt.model_validate_json(path.read_bytes())
    assert receipt.target == "source"
    if existing == "symlink":
        retained = tmp_path / "retained.json"
        path.rename(retained)
        path.symlink_to(retained)
    before = path.read_bytes()
    with pytest.raises(SystemExit):
        check.main()
    assert path.read_bytes() == before
    assert path.is_symlink() == (existing == "symlink")
    assert "configuration_or_receipt_invalid" in capsys.readouterr().err


@pytest.mark.parametrize("failure", ["write", "sync"])
def test_cli_receipt_storage_failure_removes_incomplete_file(
    database, monkeypatch, tmp_path, capsys, failure
):
    engine, _, _ = database
    initialize(engine, "release")
    monkeypatch.setattr(check, "remote_engine", lambda kind: engine)
    path = tmp_path / "source.json"
    monkeypatch.setattr(
        sys, "argv", ["inspect", "--kind", "release", "--target", "source", "--output", str(path)]
    )
    fdopen = os.fdopen

    @contextmanager
    def failing_stream(descriptor, mode):
        with fdopen(descriptor, mode) as stream:
            stream.write("partial")
            stream.flush()
            yield stream
            raise OSError("synthetic-private-storage-error")

    def failing_sync(descriptor):
        raise OSError("synthetic-private-storage-error")

    if failure == "write":
        monkeypatch.setattr(check.os, "fdopen", failing_stream)
    else:
        monkeypatch.setattr(check.os, "fsync", failing_sync)
    with pytest.raises(SystemExit) as error:
        check.main()
    assert error.value.code == 1
    assert not path.exists()
    output = capsys.readouterr()
    assert not output.out
    assert "configuration_or_receipt_invalid" in output.err
    assert "step=receipt" in output.err
    assert "synthetic-private" not in output.err


def test_cli_restored_comparison_and_environment_preservation(
    database, monkeypatch, tmp_path, capsys
):
    engine, _, schema = database
    initialize(engine, "release")
    baseline = tmp_path / "source.json"
    baseline.write_text(check.observe(engine, "release", "source").model_dump_json())
    alternate_host = "localhost" if engine.url.host != "localhost" else "127.0.0.1"
    alternate = create_engine(
        engine.url.set(host=alternate_host),
        connect_args={"options": f"-csearch_path={schema}"},
        hide_parameters=True,
    )
    monkeypatch.setenv(
        "FDAI_RELEASE_HUB_DATABASE_URL", engine.url.render_as_string(hide_password=False)
    )
    original = os.environ["FDAI_RELEASE_HUB_DATABASE_URL"]
    hosts = []

    def build(kind):
        hosts.append(make_url(os.environ["FDAI_RELEASE_HUB_DATABASE_URL"]).host)
        return alternate

    monkeypatch.setattr(check, "remote_engine", build)
    output = tmp_path / "restored.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "inspect",
            "--kind",
            "release",
            "--target",
            "restored",
            "--restored-host",
            alternate_host,
            "--baseline",
            str(baseline),
            "--output",
            str(output),
        ],
    )
    check.main()
    assert check.Receipt.model_validate_json(output.read_bytes()).target == "restored"
    assert hosts == [alternate_host]
    assert os.environ["FDAI_RELEASE_HUB_DATABASE_URL"] == original
    assert "hub_database_inspection_ok target=restored" in capsys.readouterr().out


@pytest.mark.parametrize(
    "failure",
    ["malformed_baseline", "credential", "missing_host", "missing_database", "invalid_database"],
)
def test_cli_invalid_inputs_and_credential_error_are_sanitized(
    database, monkeypatch, tmp_path, capsys, failure
):
    engine, _, _ = database
    baseline = tmp_path / "baseline"
    baseline.write_text("synthetic-secret-not-json")
    arguments = [
        "inspect",
        "--kind",
        "release",
        "--target",
        "source",
        "--output",
        str(tmp_path / "result"),
    ]
    if failure == "malformed_baseline":
        arguments[4] = "restored"
        arguments += ["--restored-host", "restore.example.com", "--baseline", str(baseline)]
    elif failure == "missing_host":
        arguments[4] = "restored"
    elif failure == "missing_database":
        monkeypatch.delenv("FDAI_RELEASE_HUB_DATABASE_URL", raising=False)
    elif failure == "invalid_database":
        monkeypatch.setenv("FDAI_RELEASE_HUB_DATABASE_URL", "synthetic-secret-not-a-dsn")
    else:

        def unavailable(kind):
            raise AzureError("synthetic-secret-credential")

        monkeypatch.setattr(check, "remote_engine", unavailable)
    monkeypatch.setattr(sys, "argv", arguments)
    with pytest.raises(SystemExit):
        check.main()
    printed = capsys.readouterr()
    assert "hub_database_inspection_failed" in printed.err
    assert "step=" in printed.err
    assert "synthetic-secret" not in printed.out + printed.err
    assert not (tmp_path / "result").exists()
