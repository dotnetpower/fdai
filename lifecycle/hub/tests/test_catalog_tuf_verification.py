from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai_deployment_cli.lifecycle_catalog_integrity import (
    ROLE_SIGNATURE_DOMAINS,
    CatalogRootRecord,
    catalog_key_id,
    role_signing_message,
)
from fdai_deployment_cli.lifecycle_catalog_roles import (
    CatalogRootChainError,
    root_from_wire,
    snapshot_from_wire,
    snapshot_to_wire,
    timestamp_from_wire,
    timestamp_to_wire,
    verify_root_chain,
)
from lifecycle.hub.tests.tuf_helpers import Authority, ident, new_key, wire
from pydantic import ValidationError

from fdai_lifecycle_hub.catalog_import import export_signing_message
from fdai_lifecycle_hub.catalog_integrity import (
    IntegrityFloors,
    advanced_floors,
    assess_roles,
    bind_export,
)
from fdai_lifecycle_hub.catalog_trust import (
    CatalogTrust,
    MetadataBundle,
    parse_metadata,
    role_verifier,
    sign_role,
)
from fdai_lifecycle_hub.signing import HubSigningKey

NOW = datetime(2026, 10, 5, 3, tzinfo=UTC)


@pytest.fixture
def export_key() -> HubSigningKey:
    return HubSigningKey(new_key(), 1)


@pytest.fixture
def authority() -> Authority:
    return Authority()


def chain_of(authority, export_key, *extra):
    return [authority.root(1, export_key=export_key, now=NOW), *extra]


def test_a_valid_chain_verifies_and_the_roles_bind_to_the_pin(authority, export_key):
    bundle = authority.bundle(chain_of(authority, export_key), now=NOW)
    result = assess_roles(bundle, trust=authority.pin(), floors=IntegrityFloors(), now=NOW)
    assert result.verified and result.reason_code == "allowed"
    assert not result.expired and not result.root_rotation
    assert result.allowed_plan_types >= {"upgrade", "recall-rolloff", "install"}
    facts = result.policy_facts()
    assert facts["verified"] is True and facts["root_rotation"] is False
    shown = json.dumps(result.to_json())
    assert "signature" not in shown and "public" not in shown


def test_wire_round_trip_is_exact_and_strict(authority, export_key):
    bundle = authority.bundle(chain_of(authority, export_key), now=NOW)
    parsed = parse_metadata(bundle.to_bytes())
    assert parsed.to_bytes() == bundle.to_bytes()
    document = json.loads(bundle.to_bytes())
    document["snapshot"]["unexpected"] = 1
    with pytest.raises(ValueError, match="malformed"):
        parse_metadata(json.dumps(document).encode())
    with pytest.raises(ValueError, match="malformed"):
        parse_metadata(b"{}")
    with pytest.raises(ValueError, match="too large"):
        parse_metadata(b" " * (1024 * 1024 + 1))
    for bad in ({"role": "snapshot"}, {"role": "root"}, []):
        with pytest.raises(ValueError):
            snapshot_from_wire(bad)
    with pytest.raises(ValueError):
        root_from_wire({"role": "root"})
    with pytest.raises(ValueError):
        timestamp_from_wire({"role": "timestamp"})


def test_legacy_root_payload_is_unchanged_by_the_optional_extensions():
    key = new_key()
    legacy = CatalogRootRecord(
        version=1,
        threshold=1,
        root_key_ids=frozenset({"r"}),
        snapshot_key_ids=frozenset({"s"}),
        timestamp_key_ids=frozenset({"t"}),
        signed_at=NOW,
        expires_at=NOW + timedelta(days=1),
    )
    assert set(json.loads(legacy.canonical_payload())) == {
        "role",
        "version",
        "threshold",
        "root_key_ids",
        "snapshot_key_ids",
        "timestamp_key_ids",
        "signed_at",
        "expires_at",
    }
    with pytest.raises(ValueError, match="cover exactly"):
        replace(legacy, public_keys={"x": b"0" * 32})
    with pytest.raises(ValueError, match="self-certifying"):
        replace(
            legacy,
            root_key_ids=frozenset({"x"}),
            snapshot_key_ids=frozenset({"x"}),
            timestamp_key_ids=frozenset({"x"}),
            public_keys={"x": b"0" * 32},
        )
    assert key  # silence unused fixture-style helper


def test_threshold_shortfall_and_wrong_key_are_rejected(authority, export_key):
    one_of_two = authority.root(1, export_key=export_key, now=NOW, signers=authority.root_keys[:1])
    outsider = authority.root(1, export_key=export_key, now=NOW, signers=[new_key(), new_key()])
    mixed = authority.root(
        1,
        export_key=export_key,
        now=NOW,
        signers=authority.root_keys[:1],
        also_signed_by=[new_key()],
    )
    for root in (one_of_two, outsider, mixed):
        bundle = authority.bundle([root], now=NOW)
        result = assess_roles(bundle, trust=authority.pin(), floors=IntegrityFloors(), now=NOW)
        assert not result.verified
        assert result.reason_code == "catalog_root_signature_invalid"


def test_a_duplicate_signature_does_not_count_twice(authority, export_key):
    root = authority.root(1, export_key=export_key, now=NOW, signers=authority.root_keys[:1])
    duplicated = replace(root, signatures={**root.signatures, "ed25519-" + "0" * 64: b"x" * 64})
    bundle = authority.bundle([duplicated], now=NOW)
    result = assess_roles(bundle, trust=authority.pin(), floors=IntegrityFloors(), now=NOW)
    assert result.reason_code == "catalog_root_signature_invalid"


def test_a_root_that_does_not_match_the_pin_is_rejected(authority, export_key):
    other = Authority()
    bundle = other.bundle([other.root(1, export_key=export_key, now=NOW)], now=NOW)
    result = assess_roles(bundle, trust=authority.pin(), floors=IntegrityFloors(), now=NOW)
    assert result.reason_code == "catalog_root_pin_mismatch"
    lowered = CatalogTrust(
        mode="tuf",
        root_key_ids=tuple(ident(key) for key in authority.root_keys),
        root_threshold=1,
    )
    good = authority.bundle(chain_of(authority, export_key), now=NOW)
    assert (
        assess_roles(good, trust=lowered, floors=IntegrityFloors(), now=NOW).reason_code
        == "catalog_root_pin_mismatch"
    )


def test_each_role_rejects_a_rollback(authority, export_key):
    chain = chain_of(authority, export_key)
    first = assess_roles(
        authority.bundle(chain, now=NOW, snapshot_version=5, timestamp_version=7),
        trust=authority.pin(),
        floors=IntegrityFloors(),
        now=NOW,
    )
    floors = advanced_floors(first)
    assert (floors.root_version, floors.snapshot_version, floors.timestamp_version) == (1, 5, 7)
    for kwargs in (
        {"snapshot_version": 4, "timestamp_version": 8},
        {"snapshot_version": 5, "timestamp_version": 6},
    ):
        replayed = authority.bundle(chain, now=NOW, **kwargs)
        result = assess_roles(replayed, trust=authority.pin(), floors=floors, now=NOW)
        assert result.reason_code == "catalog_version_rollback", kwargs
    higher_root = replace(floors, root_version=2)
    result = assess_roles(
        authority.bundle(chain, now=NOW, snapshot_version=5, timestamp_version=7),
        trust=authority.pin(),
        floors=higher_root,
        now=NOW,
    )
    assert result.reason_code == "catalog_version_rollback"


def test_equal_versions_with_different_content_are_equivocation(authority, export_key):
    chain = chain_of(authority, export_key)
    floors = advanced_floors(
        assess_roles(
            authority.bundle(chain, now=NOW),
            trust=authority.pin(),
            floors=IntegrityFloors(),
            now=NOW,
        )
    )
    cases = {
        "catalog_snapshot_equivocation": authority.bundle(chain, now=NOW, export_revision=9),
        "catalog_timestamp_equivocation": authority.bundle(
            chain, now=NOW, timestamp_ttl=timedelta(hours=2)
        ),
    }
    for reason, bundle in cases.items():
        result = assess_roles(bundle, trust=authority.pin(), floors=floors, now=NOW)
        assert result.reason_code == reason
    forked = [authority.root(1, export_key=export_key, now=NOW + timedelta(seconds=1))]
    result = assess_roles(
        authority.bundle(forked, now=NOW), trust=authority.pin(), floors=floors, now=NOW
    )
    assert result.reason_code == "catalog_root_equivocation"


def test_role_signatures_are_domain_separated_and_bound_to_the_named_key(authority, export_key):
    chain = chain_of(authority, export_key)
    bundle = authority.bundle(chain, now=NOW)
    verify = role_verifier(chain[0].public_keys)
    snapshot_payload = bundle.snapshot.canonical_payload()
    timestamp_payload = bundle.timestamp.canonical_payload()
    assert verify(authority.snapshot.key_id, snapshot_payload, bundle.snapshot.signature)
    # A signature over the bare payload, or from the other online key, never verifies.
    bare = authority.snapshot.private_key.sign(snapshot_payload)
    assert not verify(authority.snapshot.key_id, snapshot_payload, bare)
    assert not verify(authority.timestamp.key_id, snapshot_payload, bundle.snapshot.signature)
    assert not verify(authority.snapshot.key_id, timestamp_payload, bundle.snapshot.signature)
    assert not verify("unknown", snapshot_payload, bundle.snapshot.signature)
    assert not verify(authority.snapshot.key_id, b"not json", bundle.snapshot.signature)
    # The export domain is not a role domain, and no two role domains share a prefix.
    domains = list(ROLE_SIGNATURE_DOMAINS.values())
    assert len(set(domains)) == 3
    assert not any(a.startswith(b) for a in domains for b in domains if a is not b)
    export_message = export_signing_message(b"{}")
    assert export_message not in {role_signing_message(r, b"{}") for r in ROLE_SIGNATURE_DOMAINS}
    with pytest.raises(ValueError, match="unknown"):
        role_signing_message("targets", b"{}")
    with pytest.raises(ValueError, match="names no role"):
        sign_role(new_key(), b"[]")


def test_a_snapshot_cannot_be_signed_by_the_timestamp_key(authority, export_key):
    chain = chain_of(authority, export_key)
    bundle = authority.bundle(chain, now=NOW, snapshot_signer=authority.timestamp)
    result = assess_roles(bundle, trust=authority.pin(), floors=IntegrityFloors(), now=NOW)
    assert result.reason_code == "catalog_snapshot_signature_invalid"
    forged = authority.bundle(chain, now=NOW, timestamp_signer=authority.snapshot)
    result = assess_roles(forged, trust=authority.pin(), floors=IntegrityFloors(), now=NOW)
    assert result.reason_code == "catalog_timestamp_signature_invalid"


def test_expired_timestamp_allows_only_recall_rolloff(authority, export_key):
    chain = chain_of(authority, export_key)
    bundle = authority.bundle(chain, now=NOW, timestamp_ttl=timedelta(hours=2))
    later = NOW + timedelta(hours=3)
    result = assess_roles(bundle, trust=authority.pin(), floors=IntegrityFloors(), now=later)
    assert result.verified and result.expired
    assert result.allowed_plan_types == {"recall-rolloff"}
    assert result.demote_operator_overrides_to_shadow
    assert result.policy_facts()["allowed_plan_types"] == ["recall-rolloff"]
    expired_root = authority.bundle(chain, now=NOW)
    gone = assess_roles(
        expired_root, trust=authority.pin(), floors=IntegrityFloors(), now=NOW + timedelta(days=400)
    )
    assert gone.reason_code == "catalog_root_expired" and not gone.verified


def test_rotation_signed_by_the_old_threshold_is_accepted_and_flagged(authority, export_key):
    successor = Authority(root_keys=[new_key() for _ in range(3)], threshold=2)
    successor.snapshot, successor.timestamp = authority.snapshot, authority.timestamp
    second = successor.root(
        2, export_key=export_key, now=NOW, also_signed_by=authority.root_keys[:2]
    )
    chain = [authority.root(1, export_key=export_key, now=NOW), second]
    floors = IntegrityFloors(
        root_version=1,
        root_digest=hashlib.sha256(chain[0].canonical_payload()).hexdigest(),
    )
    result = assess_roles(
        authority.bundle(chain, now=NOW), trust=authority.pin(), floors=floors, now=NOW
    )
    assert result.verified and result.root_rotation and result.previous_root_version == 1
    assert result.policy_facts()["root_rotation"] is True
    fresh = assess_roles(
        authority.bundle(chain, now=NOW), trust=authority.pin(), floors=IntegrityFloors(), now=NOW
    )
    assert fresh.verified and not fresh.root_rotation


def test_rotation_not_signed_by_the_old_threshold_is_rejected(authority, export_key):
    successor = Authority(root_keys=[new_key() for _ in range(3)], threshold=2)
    successor.snapshot, successor.timestamp = authority.snapshot, authority.timestamp
    first = authority.root(1, export_key=export_key, now=NOW)
    cases = {
        "new keys only": successor.root(2, export_key=export_key, now=NOW),
        "one old signer": successor.root(
            2, export_key=export_key, now=NOW, also_signed_by=authority.root_keys[:1]
        ),
    }
    for label, second in cases.items():
        result = assess_roles(
            authority.bundle([first, second], now=NOW),
            trust=authority.pin(),
            floors=IntegrityFloors(),
            now=NOW,
        )
        assert result.reason_code == "catalog_root_rotation_unsigned_by_previous", label
    old_only = successor.root(
        2, export_key=export_key, now=NOW, signers=[], also_signed_by=authority.root_keys[:2]
    )
    result = assess_roles(
        authority.bundle([first, old_only], now=NOW),
        trust=authority.pin(),
        floors=IntegrityFloors(),
        now=NOW,
    )
    assert result.reason_code == "catalog_root_signature_invalid"


def test_root_chain_versions_must_be_consecutive_and_bounded(authority, export_key):
    first = authority.root(1, export_key=export_key, now=NOW)
    skipped = authority.root(3, export_key=export_key, now=NOW)
    pin = {"pinned_root_key_ids": first.root_key_ids, "pinned_threshold": 2}
    for chain in ([], [skipped], [first, first], [first] * 40):
        with pytest.raises(CatalogRootChainError) as raised:
            verify_root_chain(chain, make_verifier=role_verifier, **pin)
        assert raised.value.reason_code == "catalog_root_chain_invalid"
    bare = replace(first, public_keys={})
    with pytest.raises(CatalogRootChainError):
        verify_root_chain([bare], make_verifier=role_verifier, **pin)


def test_recall_sequence_gap_and_withheld_recall_are_rejected(authority, export_key):
    chain = chain_of(authority, export_key)
    gap = authority.bundle(chain, now=NOW, recall_sequences=(1, 2, 4))
    result = assess_roles(gap, trust=authority.pin(), floors=IntegrityFloors(), now=NOW)
    assert result.reason_code == "recall_sequence_gap"
    floors = IntegrityFloors(max_recall_sequence=3)
    withheld = authority.bundle(chain, now=NOW, recall_sequences=(1, 2))
    result = assess_roles(withheld, trust=authority.pin(), floors=floors, now=NOW)
    assert result.reason_code == "recall_sequence_gap"
    kept = authority.bundle(chain, now=NOW, recall_sequences=(1, 2, 3))
    assert assess_roles(kept, trust=authority.pin(), floors=floors, now=NOW).verified


def export_document(**overrides):
    document = {
        "channels": {"DEV": []},
        "expires_at": "2026-10-06T03:00:00+00:00",
        "recalls": [],
        "releases": {},
        "revision": 4,
    }
    return {**document, **overrides}


def bound(authority, export_key, raw, **kwargs):
    bundle = authority.bundle(
        chain_of(authority, export_key),
        now=NOW,
        export_digest=hashlib.sha256(raw).hexdigest(),
        export_revision=4,
        channel_versions={"DEV": 4},
        **kwargs,
    )
    return assess_roles(bundle, trust=authority.pin(), floors=IntegrityFloors(), now=NOW)


def test_the_snapshot_must_describe_exactly_these_export_bytes(authority, export_key):
    raw = json.dumps(export_document(), sort_keys=True).encode()
    assessment = bound(authority, export_key, raw)
    assert bind_export(assessment, raw=raw, floors=IntegrityFloors()) is None
    assert (
        bind_export(assessment, raw=raw + b" ", floors=IntegrityFloors())
        == "export_digest_mismatch"
    )
    other = json.dumps(export_document(revision=5), sort_keys=True).encode()
    mismatched = bound(authority, export_key, other)
    assert (
        bind_export(mismatched, raw=other, floors=IntegrityFloors()) == "snapshot_export_mismatch"
    )
    renamed = json.dumps(export_document(channels={"RELEASE": []}), sort_keys=True).encode()
    assessment = bound(authority, export_key, renamed)
    assert (
        bind_export(assessment, raw=renamed, floors=IntegrityFloors()) == "snapshot_export_mismatch"
    )
    notice = {"scope": "release", "target": "1.0.0", "sequence": 3, "action": "recall"}
    with_recall = json.dumps(export_document(recalls=[notice]), sort_keys=True).encode()
    assessment = bound(authority, export_key, with_recall)
    assert (
        bind_export(assessment, raw=with_recall, floors=IntegrityFloors())
        == "snapshot_export_mismatch"
    )
    honest = bound(authority, export_key, with_recall, recall_sequences=(1,))
    assert bind_export(honest, raw=with_recall, floors=IntegrityFloors()) is None
    floors = IntegrityFloors(channel_versions={"DEV": 9})
    assert bind_export(honest, raw=with_recall, floors=floors) == "catalog_version_rollback"


def test_an_unverified_assessment_cannot_advance_floors_or_bind(authority, export_key):
    failed = assess_roles(
        authority.bundle([authority.root(1, export_key=export_key, now=NOW, signers=[])], now=NOW),
        trust=authority.pin(),
        floors=IntegrityFloors(),
        now=NOW,
    )
    assert not failed.verified
    with pytest.raises(ValueError, match="Only verified"):
        advanced_floors(failed)
    assert bind_export(failed, raw=b"{}", floors=IntegrityFloors()) == "integrity_not_verified"


def test_root_without_an_export_key_is_rejected(authority, export_key):
    root = authority.root(1, export_key=export_key, now=NOW)
    keys = {k: v for k, v in root.public_keys.items() if k not in root.export_key_ids}
    bare = authority.sign(
        replace(root, export_key_ids=frozenset(), public_keys=keys, signatures={}),
        authority.root_keys[:2],
    )
    result = assess_roles(
        authority.bundle([bare], now=NOW), trust=authority.pin(), floors=IntegrityFloors(), now=NOW
    )
    assert result.reason_code == "catalog_root_export_key_missing"


def test_pin_configuration_is_validated_and_has_a_stable_identity(authority):
    pin = authority.pin()
    assert pin.key_digest == authority.pin().key_digest
    reordered = CatalogTrust(
        mode="tuf", root_key_ids=tuple(reversed(pin.root_key_ids)), root_threshold=2
    )
    assert reordered.key_digest == pin.key_digest
    ids = list(pin.root_key_ids)
    bad = [
        {"root_key_ids": ["not-a-key"], "root_threshold": 1},
        {"root_key_ids": [ids[0], ids[0]], "root_threshold": 1},
        {"root_key_ids": ids, "root_threshold": 4},
        {"root_key_ids": ids, "root_threshold": 0},
        {"root_key_ids": [], "root_threshold": 1},
    ]
    for fields in bad:
        with pytest.raises(ValidationError):
            CatalogTrust(mode="tuf", **fields)
    with pytest.raises(ValidationError):
        CatalogTrust(mode="tuf", root_key_ids=ids, root_threshold=2, extra=1)
    assert catalog_key_id(b"x").startswith("ed25519-") and len(catalog_key_id(b"x")) == 72


def test_snapshot_and_timestamp_wire_forms_round_trip(authority, export_key):
    bundle = authority.bundle(chain_of(authority, export_key), now=NOW, recall_sequences=(1, 2))
    assert snapshot_from_wire(snapshot_to_wire(bundle.snapshot)) == bundle.snapshot
    assert timestamp_from_wire(timestamp_to_wire(bundle.timestamp)) == bundle.timestamp
    document = snapshot_to_wire(bundle.snapshot)
    document["signature"] = base64.b64encode(b"short").decode()
    with pytest.raises(ValueError, match="Ed25519 signature"):
        snapshot_from_wire(document)
    assert MetadataBundle  # the bundle type is part of this module's public surface
    assert wire(bundle.root_chain[0])["role"] == "root"
