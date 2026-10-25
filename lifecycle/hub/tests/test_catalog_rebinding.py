from __future__ import annotations

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import create_engine, inspect, select, update

from fdai_lifecycle_hub.catalog_trust import CatalogTrust
from fdai_lifecycle_hub.migrations import migrate
from fdai_lifecycle_hub.remote_catalog import (
    CatalogSource,
    bind_catalog,
    bind_catalog_if_missing,
    trust_events,
    trust_state,
)
from fdai_lifecycle_hub.remote_catalog import metadata as trust_metadata

URL = "https://release.example.com/v1/catalog/export"


def legacy_source() -> CatalogSource:
    pem = (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return CatalogSource(url=URL, access="anonymous", release_public_key=pem)


def tuf_source(seed: str = "1") -> CatalogSource:
    ids = tuple(f"ed25519-{seed * 64}" for _ in range(1))
    pin = CatalogTrust(mode="tuf", root_key_ids=ids, root_threshold=1)
    return CatalogSource(url=URL, access="anonymous", trust=pin)


@pytest.fixture
def engine(tmp_path):
    result = create_engine(f"sqlite:///{tmp_path / 'hub.db'}")
    migrate(result, "lifecycle_hub", trust_metadata.create_all)
    return result


def events(engine) -> list[tuple[str, str, int]]:
    with engine.connect() as connection:
        rows = connection.execute(select(trust_events).order_by(trust_events.c.sequence)).all()
    return [(row.action, row.actor, row.revision) for row in rows]


def seed_accepted(engine, *, floor: int = 9) -> None:
    with engine.begin() as connection:
        connection.execute(
            update(trust_state)
            .where(trust_state.c.id == 1)
            .values(
                floor=floor,
                approval_revision=floor,
                previous_digest="a" * 64,
                approval_digest="a" * 64,
                payload=b"accepted-under-the-previous-trust",
            )
        )


def test_a_different_trust_needs_an_explicit_rebinding(engine):
    bind_catalog(engine, legacy_source(), actor="operator", reason="first binding")
    with pytest.raises(ValueError, match="rebinding"):
        bind_catalog(engine, tuf_source(), actor="operator", reason="no flag")
    assert [action for action, *_ in events(engine)] == ["source.bound"]


def test_rebinding_to_signed_roles_keeps_the_floor_and_drops_unverified_bytes(engine):
    legacy = legacy_source()
    bind_catalog(engine, legacy, actor="operator", reason="first binding")
    seed_accepted(engine)
    tuf = tuf_source()
    bind_catalog(engine, tuf, actor="owner", reason="move to signed roles", rebind=True)
    with engine.connect() as connection:
        row = connection.execute(select(trust_state)).mappings().one()
        assert row["key_digest"] == tuf.key_digest
        assert row["floor"] == 9 and row["approval_revision"] == 9
        assert row["payload"] is None and row["previous_digest"] is None
        assert inspect(connection).has_table("catalog_integrity_state")
    recorded = events(engine)
    assert recorded[-1] == ("source.rebound", "owner", 9)
    with engine.connect() as connection:
        reason = connection.execute(
            select(trust_events.c.reason).where(trust_events.c.action == "source.rebound")
        ).scalar_one()
    assert legacy.key_digest[:16] in reason


def test_rebinding_to_the_same_trust_changes_nothing(engine):
    source = tuf_source()
    bind_catalog(engine, source, actor="operator", reason="first binding")
    seed_accepted(engine)
    bind_catalog(engine, source, actor="owner", reason="repeat", rebind=True)
    with engine.connect() as connection:
        row = connection.execute(select(trust_state)).mappings().one()
    assert row["payload"] == b"accepted-under-the-previous-trust"
    assert [action for action, *_ in events(engine)] == ["source.bound"]


def test_a_new_root_pin_resets_the_role_floors_but_not_the_revision_floor(engine):
    bind_catalog(engine, tuf_source("1"), actor="operator", reason="first binding")
    seed_accepted(engine, floor=4)
    from fdai_lifecycle_hub import catalog_integrity_state as store

    with engine.begin() as connection:
        connection.execute(
            update(store.integrity_state).values(root_version=3, timestamp_version=7)
        )
    bind_catalog(engine, tuf_source("2"), actor="owner", reason="new root pin", rebind=True)
    with engine.connect() as connection:
        floors = connection.execute(select(store.integrity_state)).mappings().one()
        assert floors["root_version"] == 0 and floors["timestamp_version"] == 0
        assert connection.execute(select(trust_state.c.floor)).scalar_one() == 4


def test_signed_roles_cannot_be_rebound_to_a_single_key(engine):
    bind_catalog(engine, tuf_source(), actor="operator", reason="first binding")
    with pytest.raises(ValueError, match="not allowed"):
        bind_catalog(engine, legacy_source(), actor="owner", reason="downgrade", rebind=True)


def test_migration_binds_a_missing_trust_row_and_never_changes_an_existing_one(engine):
    source = tuf_source()
    assert bind_catalog_if_missing(engine, source, actor="system:migration") is True
    assert bind_catalog_if_missing(engine, source, actor="system:migration") is False
    other = tuf_source("2")
    assert bind_catalog_if_missing(engine, other, actor="system:migration") is False
    with engine.connect() as connection:
        assert (
            connection.execute(select(trust_state.c.key_digest)).scalar_one() == source.key_digest
        )
    assert [action for action, *_ in events(engine)] == ["source.bound"]


def test_rebinding_requires_an_attributed_bounded_reason(engine):
    bind_catalog(engine, legacy_source(), actor="operator", reason="first binding")
    for actor, reason in (("", "why"), ("owner", " "), ("x" * 161, "why"), ("owner", "r" * 501)):
        with pytest.raises(ValueError, match="bounded actor"):
            bind_catalog(engine, tuf_source(), actor=actor, reason=reason, rebind=True)
