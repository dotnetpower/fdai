from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier

import pytest
from fdai_deployment_cli.contracts import canonical_bytes
from lifecycle.hub.tests.test_remote_catalog import approve, source_for, vendor_for
from sqlalchemy import create_engine, inspect, select, text

from fdai_lifecycle_hub import local_channels, models
from fdai_lifecycle_hub.domain import Issued
from fdai_lifecycle_hub.local_channels import LocalChannelError, LocalChannelRequest, entries
from fdai_lifecycle_hub.migrations import migrate, require_schema
from fdai_lifecycle_hub.remote_catalog import RemoteCatalog, initialize_trust, trust_state
from fdai_lifecycle_hub.store import HubStore
from fdai_release_hub.store import Change


def prepare(tmp_path, key, catalog, now, *, engine=None):
    vendor = vendor_for(tmp_path, key, catalog, now)
    for version in ("1.5.0", "1.6.0"):
        vendor.change(
            "contribute",
            version,
            Change(
                revision=vendor.snapshot()["revision"],
                confirmation=version,
                reason="Reviewed vendor RELEASE member",
                channel="RELEASE",
            ),
        )
    engine = engine or create_engine(f"sqlite:///{tmp_path / 'target.db'}")
    source = source_for(key)

    def initialize(connection):
        models.Base.metadata.create_all(connection)
        initialize_trust(connection, source)

    migrate(engine, "lifecycle_hub", initialize)
    target = RemoteCatalog(engine, source, fetch=lambda _: vendor.export()[0])
    approve(target, vendor.export()[0], now)
    target.import_once(actor="customer-operator", now=now)
    return vendor, target, HubStore(engine)


def request_for(target, catalog, now, **updates):
    state = target.local_channels(now=now)
    material = {
        "revision": state["revision"],
        "channel": "local-reviewed",
        "release_id": "1.6.0",
        "release_digest": catalog.releases["1.6.0"].digest,
        "accepted_sha256": state["accepted_sha256"],
        "reason": "Reviewed exact customer selection",
        "confirmation": "add 1.6.0 to local-reviewed",
    }
    return LocalChannelRequest.model_validate(material | updates)


@pytest.fixture
def local(tmp_path, key, catalog, now):
    return prepare(tmp_path, key, catalog, now)


def test_local_membership_is_durable_narrowing_and_does_not_rewrite_vendor(local, catalog, now):
    vendor, target, _store = local
    original = vendor.export()
    before = target.catalog(now)
    assert before.local_curation is None
    result = target.add_local_channel(
        request_for(target, catalog, now), actor="approved-customer", now=now
    )
    assert result["revision"] == 1
    assert result["execution_authority"] is False
    assert result["entries"][0]["actor"] == "approved-customer"
    assert result["entries"][0]["eligible"] is True
    effective = target.catalog(now)
    assert effective.channels["local-reviewed"] == frozenset({"1.6.0"})
    assert effective.channels["RELEASE"] == before.channels["RELEASE"]
    assert effective.local_curation.digest == result["digest"]
    assert vendor.export() == original
    with target.engine.connect() as connection:
        retained = connection.execute(select(trust_state.c.payload)).scalar_one()
        assert hashlib.sha256(retained).hexdigest() == original[1]
    reopened = RemoteCatalog(target.engine, target.source)
    assert reopened.local_channels(now=now) == result


@pytest.mark.parametrize(
    "changes",
    [
        {"revision": 1},
        {"accepted_sha256": "0" * 64},
        {"release_digest": "0" * 64},
        {"release_id": "9.0.0", "confirmation": "add 9.0.0 to local-reviewed"},
    ],
)
def test_stale_or_unbound_inputs_leave_no_local_audit(local, catalog, now, changes):
    _vendor, target, _store = local
    before = target.local_channels(now=now)
    with pytest.raises(LocalChannelError):
        target.add_local_channel(
            request_for(target, catalog, now, **changes), actor="operator", now=now
        )
    assert target.local_channels(now=now) == before


@pytest.mark.parametrize(
    "changes",
    [
        {"channel": "local-"},
        {"channel": "local-Pilot"},
        {"channel": "local-a--b"},
        {"channel": "local-a\n"},
        {"channel": " local-a"},
        {"channel": "custom-pilot"},
        {"channel": "local-" + "a" * 59},
        {"confirmation": "add"},
        {"reason": "   "},
        {"revision": True},
    ],
)
def test_request_contract_rejects_ambiguous_input(local, catalog, now, changes):
    _vendor, target, _store = local
    with pytest.raises(ValueError):
        request_for(target, catalog, now, **changes)
    assert target.local_channels(now=now)["revision"] == 0


def test_duplicate_actor_and_post_insert_failure_are_atomic(local, catalog, now, monkeypatch):
    _vendor, target, _store = local
    change = request_for(target, catalog, now)
    with pytest.raises(LocalChannelError, match="attributed"):
        target.add_local_channel(change, actor="   ", now=now)
    original_view = local_channels.view

    def failed_readback(*args, **kwargs):
        raise LocalChannelError("Synthetic evidence readback failure", 503)

    monkeypatch.setattr(local_channels, "view", failed_readback)
    with pytest.raises(LocalChannelError, match="readback"):
        target.add_local_channel(change, actor="operator", now=now)
    monkeypatch.setattr(local_channels, "view", original_view)
    assert target.local_channels(now=now)["revision"] == 0
    target.add_local_channel(change, actor="operator", now=now)
    with pytest.raises(LocalChannelError, match="already belongs"):
        target.add_local_channel(request_for(target, catalog, now), actor="operator", now=now)
    assert target.local_channels(now=now)["revision"] == 1


def test_local_planning_keeps_pin_and_revision_provenance(
    local, catalog, installation, enroll, key, now
):
    _vendor, target, store = local
    state = target.add_local_channel(request_for(target, catalog, now), actor="operator", now=now)
    selected = replace(
        installation,
        settings=replace(
            installation.settings, channel="local-reviewed", plan_duration=timedelta(minutes=25)
        ),
    )
    enroll(store, selected)
    outcome = target.recompute(store, selected.installation_id, key, now=now)
    assert isinstance(outcome, Issued)
    assert outcome.plan.target_release_id == "1.6.0"
    with target.engine.connect() as connection:
        audit = (
            connection.execute(
                select(models.AuditRecord).where(models.AuditRecord.action == "plan.evaluated")
            )
            .mappings()
            .one()
        )
    assert audit["payload"]["local_curation"]["revision"] == 1
    assert audit["payload"]["local_curation"]["digest"] == state["digest"]
    assert audit["payload"]["local_curation"]["accepted_sha256"] == state["accepted_sha256"]


def test_recall_new_pin_and_expiry_never_become_local_eligibility(local, catalog, now):
    vendor, target, _store = local
    target.add_local_channel(request_for(target, catalog, now), actor="operator", now=now)
    vendor.change(
        "recall",
        "1.6.0",
        Change(
            revision=vendor.snapshot()["revision"],
            confirmation="1.6.0",
            reason="Withdraw synthetic source Release",
        ),
    )
    raw = vendor.export()[0]
    approve(target, raw, now)
    assert target.catalog(now).channels["local-reviewed"] == frozenset({"1.6.0"})
    target.import_once(actor="operator", now=now)
    state = target.local_channels(now=now)
    assert state["entries"][0]["hold_reason"] == "release_recalled"
    assert target.catalog(now).channels["local-reviewed"] == frozenset()
    with pytest.raises(ValueError, match="expired"):
        target.local_channels(now=now + timedelta(days=2))
    with target.engine.connect() as connection:
        assert connection.execute(select(entries.c.revision)).scalar_one() == 1


def test_local_namespace_collision_and_changed_source_hold(local, catalog, now, monkeypatch):
    _vendor, target, _store = local
    target.add_local_channel(request_for(target, catalog, now), actor="operator", now=now)
    original = target._accepted
    source = original(next_row(target), now)
    monkeypatch.setattr(
        target,
        "_accepted",
        lambda *_: replace(
            source, channels={**source.channels, "local-reviewed": frozenset({"1.5.0"})}
        ),
    )
    with pytest.raises(LocalChannelError, match="collide"):
        target.catalog(now)
    altered = replace(source.releases["1.6.0"], digest="0" * 64)
    monkeypatch.setattr(
        target,
        "_accepted",
        lambda *_: replace(source, releases={**source.releases, "1.6.0": altered}),
    )
    assert target.local_channels(now=now)["entries"][0]["hold_reason"] == "release_digest_changed"
    assert not target.catalog(now).channels["local-reviewed"]
    with pytest.raises(LocalChannelError, match="not eligible"):
        target.add_local_channel(
            request_for(
                target,
                catalog,
                now,
                channel="local-second",
                confirmation="add 1.6.0 to local-second",
            ),
            actor="operator",
            now=now,
        )


def next_row(target):
    with target.engine.connect() as connection:
        return connection.execute(select(trust_state)).mappings().one()


def test_concurrent_curation_uses_one_revision_and_preserves_one_actor(local, catalog, now):
    _vendor, target, _store = local
    request = request_for(target, catalog, now)
    ready = Barrier(2, timeout=10)

    def add(actor):
        ready.wait()
        try:
            target.add_local_channel(request, actor=actor, now=now)
            return "committed"
        except LocalChannelError as error:
            assert error.status == 409
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(add, ("operator-a", "operator-b"))) == ["committed", "conflict"]
    state = target.local_channels(now=now)
    assert state["revision"] == 1
    assert state["entries"][0]["actor"] in {"operator-a", "operator-b"}


def test_explicit_revision_three_upgrade_is_additive_and_required(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'revision3.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE lifecycle_hub_schema_revision (revision INTEGER PRIMARY KEY)"
        )
        connection.exec_driver_sql("INSERT INTO lifecycle_hub_schema_revision VALUES (3)")
        connection.exec_driver_sql("CREATE TABLE retained_marker (value TEXT)")
        connection.exec_driver_sql("INSERT INTO retained_marker VALUES ('preserved')")
    with pytest.raises(ValueError, match="migrate"):
        require_schema(engine, "lifecycle_hub")
    migrate(engine, "lifecycle_hub", lambda _: pytest.fail("Existing schema must not reinitialize"))
    require_schema(engine, "lifecycle_hub")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT value FROM retained_marker")) == "preserved"
        assert connection.scalar(text("SELECT revision FROM lifecycle_hub_schema_revision")) == 4
        assert inspect(connection).has_table(entries.name)
    migrate(engine, "lifecycle_hub", lambda _: pytest.fail("Repeated migration must be idempotent"))


def test_removed_source_membership_and_changed_key_are_not_local_permission(local, catalog, now):
    vendor, target, _store = local
    target.add_local_channel(request_for(target, catalog, now), actor="operator", now=now)
    raw = json.loads(vendor.export()[0])
    raw["revision"] += 1
    raw["channels"]["RELEASE"].remove("1.6.0")
    revised = canonical_bytes(raw)
    target.fetch = lambda _: revised
    approve(target, revised, now)
    target.import_once(actor="operator", now=now)
    assert target.local_channels(now=now)["entries"][0]["hold_reason"] == (
        "release_not_in_source_release_channel"
    )
    assert not target.catalog(now).channels["local-reviewed"]
    with target.engine.begin() as connection:
        connection.execute(trust_state.update().values(key_digest="0" * 64))
    with pytest.raises(ValueError, match="key differs"):
        target.catalog(now)


def test_capacity_and_corrupt_evidence_are_explicit_holds(local, catalog, now, monkeypatch):
    _vendor, target, _store = local
    target.add_local_channel(request_for(target, catalog, now), actor="operator", now=now)
    monkeypatch.setattr(local_channels, "MAX_LOCAL_MEMBERS", 1)
    with pytest.raises(LocalChannelError, match="bound"):
        target.add_local_channel(
            request_for(
                target,
                catalog,
                now,
                channel="local-second",
                confirmation="add 1.6.0 to local-second",
            ),
            actor="operator",
            now=now,
        )
    assert target.local_channels(now=now)["revision"] == 1
    with target.engine.begin() as connection:
        connection.execute(entries.update().values(reason="Unattributed retained mutation"))
    with pytest.raises(LocalChannelError, match="inconsistent"):
        target.catalog(now)


@pytest.mark.parametrize("operation", ["catalog", "local_channels", "add"])
def test_elapsed_lock_time_revalidates_catalog_expiry(local, catalog, now, monkeypatch, operation):
    from types import SimpleNamespace

    _vendor, target, _store = local
    request = request_for(target, catalog, now)
    ticks = iter((0.0, 172800.0))
    monkeypatch.setattr(
        "fdai_lifecycle_hub.remote_catalog.time",
        SimpleNamespace(monotonic=lambda: next(ticks)),
    )
    with pytest.raises(ValueError, match="expired"):
        if operation == "catalog":
            target.catalog(now)
        elif operation == "local_channels":
            target.local_channels(now=now)
        else:
            target.add_local_channel(request, actor="operator", now=now)
    with target.engine.connect() as connection:
        assert connection.execute(select(entries)).first() is None


def test_expiry_during_membership_write_rolls_back_the_new_evidence(
    local, catalog, now, monkeypatch
):
    from types import SimpleNamespace

    _vendor, target, _store = local
    request = request_for(target, catalog, now)
    ticks = iter((0.0, 0.0, 172800.0))
    monkeypatch.setattr(
        "fdai_lifecycle_hub.remote_catalog.time",
        SimpleNamespace(monotonic=lambda: next(ticks)),
    )
    with pytest.raises(ValueError, match="expired"):
        target.add_local_channel(request, actor="operator", now=now)
    with target.engine.connect() as connection:
        assert connection.execute(select(entries)).first() is None


def test_expiry_after_local_planning_rolls_back_plan_and_audit(
    local, catalog, now, installation, enroll, key, monkeypatch
):
    from types import SimpleNamespace

    _vendor, target, store = local
    target.add_local_channel(request_for(target, catalog, now), actor="operator", now=now)
    selected = replace(
        installation,
        settings=replace(
            installation.settings, channel="local-reviewed", plan_duration=timedelta(minutes=25)
        ),
    )
    enroll(store, selected)
    ticks = iter((0.0, 0.0, 172800.0))
    monkeypatch.setattr(
        "fdai_lifecycle_hub.remote_catalog.time",
        SimpleNamespace(monotonic=lambda: next(ticks)),
    )
    with pytest.raises(ValueError, match="expired"):
        target.recompute(store, selected.installation_id, key, now=now)
    with target.engine.connect() as connection:
        assert connection.execute(select(models.Plan)).first() is None
        assert (
            connection.execute(
                select(models.AuditRecord).where(models.AuditRecord.action == "plan.evaluated")
            ).first()
            is None
        )
