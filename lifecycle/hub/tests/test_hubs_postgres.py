from __future__ import annotations

import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import psycopg
import pytest
from lifecycle.hub.tests.test_remote_catalog import approve, source_for
from psycopg import sql
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from fdai_lifecycle_hub import models
from fdai_lifecycle_hub.migrations import migrate, require_schema
from fdai_lifecycle_hub.remote_catalog import RemoteCatalog, initialize_trust
from fdai_lifecycle_hub.store import HubStore
from fdai_release_hub.store import CatalogError, Change, ReleaseStore


@pytest.fixture
def databases(loopback_postgres_url):
    """Two task-owned DBs/roles on validation 5433, never the shared runtime cluster."""
    url = make_url(loopback_postgres_url)
    if url.port != 5433:
        raise pytest.UsageError("Hub PostgreSQL tests require isolated validation port 5433.")
    suffix = secrets.token_hex(4)
    names = {kind: f"hubs_{kind}_{suffix}" for kind in ("release", "target")}
    engines = {}
    admin_url = url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(admin_url, autocommit=True) as admin:
        try:
            for kind, name in names.items():
                password = secrets.token_urlsafe(32)
                admin.execute(
                    sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                        sql.Identifier(name),
                        sql.Literal(password),
                    )
                )
                admin.execute(
                    sql.SQL("CREATE DATABASE {} OWNER {}").format(
                        sql.Identifier(name),
                        sql.Identifier(name),
                    )
                )
                admin.execute(
                    sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name))
                )
                engines[kind] = create_engine(
                    url.set(username=name, password=password, database=name),
                    hide_parameters=True,
                    connect_args={"connect_timeout": 3},
                )
            yield engines
        finally:
            for engine in engines.values():
                engine.dispose()
            for name in names.values():
                admin.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
                )
                admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(name)))


@pytest.mark.parametrize("channel", ["DEV", "custom-pilot"])
def test_postgres_two_hubs_persistence_plan_recall_and_cross_db_denial(
    databases,
    tmp_path,
    key,
    catalog,
    installation,
    enroll,
    now,
    channel,
):
    from dataclasses import replace

    from fdai_deployment_cli.contracts import canonical_bytes

    vendor_engine, target_engine = databases["release"], databases["target"]
    vendor = ReleaseStore(vendor_engine, key, clock=lambda: now)
    source = source_for(key)

    def initialize(connection):
        models.Base.metadata.create_all(connection)
        initialize_trust(connection, source)

    migrate(target_engine, "lifecycle_hub", initialize)
    require_schema(target_engine, "lifecycle_hub")
    hub = HubStore(target_engine)
    for version in ("1.5.0", "1.6.0"):
        for action in ("register", "publish"):
            vendor.change(
                action,
                version,
                Change(
                    revision=vendor.snapshot()["revision"],
                    confirmation=version,
                    reason="Synthetic PostgreSQL validation",
                    manifest=canonical_bytes(catalog.releases[version].to_mapping()).decode()
                    if action == "register"
                    else None,
                ),
            )
    if channel.startswith("custom-"):
        for version in ("1.5.0", "1.6.0"):
            vendor.change(
                "contribute",
                version,
                Change(
                    revision=vendor.snapshot()["revision"],
                    confirmation=version,
                    reason="Reviewed custom PostgreSQL membership",
                    channel=channel,
                    channel_confirmation=channel,
                ),
                actor="approved-vendor",
            )
    accepted_revision = vendor.snapshot()["revision"]
    raw = vendor.export()[0]
    target = RemoteCatalog(target_engine, source, fetch=lambda _: raw)
    approve(target, raw, now)
    target.import_once(actor="customer-operator", now=now)
    installation = replace(
        installation,
        settings=replace(
            installation.settings, channel=channel, plan_duration=timedelta(minutes=25)
        ),
        reported=replace(installation.reported, observed_at=now),
    )
    enroll(hub, installation)
    outcome = target.recompute(hub, installation.installation_id, key, now=now)
    assert outcome.plan.target_release_id == "1.6.0"
    target_engine.dispose()
    restarted = HubStore(create_engine(target_engine.url))
    assert (
        restarted.current_plan(installation.installation_id, now=now).plan_id
        == outcome.plan.plan_id
    )
    assert RemoteCatalog(restarted.engine, source).status()["minimum_revision"] == accepted_revision
    assert ReleaseStore(vendor_engine, key, initialize=False).snapshot()["channels"][channel] == [
        "1.5.0",
        "1.6.0",
    ]
    vendor.change(
        "recall",
        "1.6.0",
        Change(
            revision=accepted_revision,
            confirmation="1.6.0",
            reason="Withdraw synthetic release",
        ),
    )
    raw = vendor.export()[0]
    approve(target, raw, now)
    target.import_once(actor="customer-operator", now=now)
    decision = target.recompute(restarted, installation.installation_id, key, now=now)
    assert decision.plan.target_release_id == "1.5.0"
    assert (
        ReleaseStore(vendor_engine, key, initialize=False).snapshot()["releases"][0]["state"]
        == "recalled"
    )
    for own, other in ((vendor_engine, target_engine), (target_engine, vendor_engine)):
        wrong = own.url.set(database=other.url.database, drivername="postgresql")
        with pytest.raises(psycopg.OperationalError, match="permission denied"):
            psycopg.connect(wrong.render_as_string(hide_password=False), connect_timeout=3)
    restarted.engine.dispose()


def test_postgres_publication_serializes_concurrent_revisions(databases, key, now, catalog):
    from fdai_deployment_cli.contracts import canonical_bytes

    engine = databases["release"]
    vendor = ReleaseStore(engine, key, clock=lambda: now)
    manifest = canonical_bytes(catalog.releases["1.6.0"].to_mapping()).decode()

    def register(version):
        try:
            vendor.change(
                "register",
                version,
                Change(
                    revision=0,
                    confirmation=version,
                    reason="Concurrent publication review",
                    manifest=manifest,
                ),
            )
            return "committed"
        except CatalogError as error:
            assert error.status == 409
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(register, ["1.5.0", "1.6.0"])) == ["committed", "conflict"]
    assert vendor.snapshot()["revision"] == 1


def test_postgres_custom_contributions_serialize_and_preserve_original_event(
    databases, key, now, catalog
):
    import threading

    from fdai_deployment_cli.contracts import canonical_bytes

    engine = databases["release"]
    vendor = ReleaseStore(engine, key, clock=lambda: now)
    for action in ("register", "publish"):
        vendor.change(
            action,
            "1.6.0",
            Change(
                revision=vendor.snapshot()["revision"],
                confirmation="1.6.0",
                reason="Prepare synthetic publication",
                manifest=canonical_bytes(catalog.releases["1.6.0"].to_mapping()).decode()
                if action == "register"
                else None,
            ),
        )
    ready = threading.Barrier(2, timeout=10)

    def contribute(actor):
        ready.wait()
        try:
            vendor.change(
                "contribute",
                "1.6.0",
                Change(
                    revision=2,
                    confirmation="1.6.0",
                    reason="Reviewed concurrent destination",
                    channel="custom-pilot",
                    channel_confirmation="custom-pilot",
                ),
                actor=actor,
            )
            return "committed"
        except CatalogError as error:
            assert error.status == 409
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(contribute, ["operator-a", "operator-b"])) == [
            "committed",
            "conflict",
        ]
    original = vendor.snapshot()
    assert original["revision"] == 3
    assert original["channels"]["custom-pilot"] == ["1.6.0"]
    assert original["events"][0]["actor"] in {"operator-a", "operator-b"}
    assert ReleaseStore(engine, key, clock=lambda: now, initialize=False).snapshot() == original
