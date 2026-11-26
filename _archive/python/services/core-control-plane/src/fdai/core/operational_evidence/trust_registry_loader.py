"""Strict loaders for the pinned trust registry and the deployment anchor binding."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from fdai_service_contracts.operational_evidence import OPERATIONAL_EVIDENCE_PURPOSES

from .registry_json import (
    RegistryUnavailableError,
    bounded_text,
    exact_fields,
    has_duplicates,
    load_pinned_json,
    load_strict_json_text,
    positive_int,
    strict_bool,
    text_tuple,
    validity,
)
from .trust_registry import (
    TRUST_REGISTRY_ID,
    AnchorBinding,
    AnchorEvidenceClass,
    DeploymentAnchors,
    FreshnessPolicy,
    ProducerEntry,
    PurposeTrust,
    SourceEntry,
    TrustRegistry,
    Venue,
    VerifierEntry,
)

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
_TOP_FIELDS = frozenset({"schema_version", "registry_id", "revision", "purposes"})
_PURPOSE_FIELDS = frozenset(
    {
        "purpose_id",
        "authority_class",
        "method_id",
        "method_version",
        "evidence_class",
        "producers",
        "sources",
        "freshness_policy",
        "verifiers",
        "separation",
        "revoked",
    }
)
_PRODUCER_FIELDS = frozenset({"producer_id", "producer_version", "anchor_id"})
_SOURCE_FIELDS = frozenset({"source_id", "role", "anchor_id"})
_FRESHNESS_FIELDS = frozenset({"policy_id", "policy_version", "ceiling_seconds"})
_VERIFIER_FIELDS = frozenset(
    {"verifier_id", "verifier_version", "trust_anchor_id", "valid_from", "valid_until", "revoked"}
)
_ANCHOR_FIELDS = frozenset({"anchor_id", "principal_id", "evidence_class"})


def load_trust_registry(data: bytes, *, expected_pin: str) -> TrustRegistry:
    """Load one pinned revision; a defective purpose is unavailable, never repaired."""

    raw = load_pinned_json(data, expected_pin=expected_pin, label="trust registry")
    try:
        top = exact_fields(raw, _TOP_FIELDS, label="trust registry")
        if top["schema_version"] != "1.0.0" or top["registry_id"] != TRUST_REGISTRY_ID:
            raise ValueError("trust registry schema or identity is unsupported")
        revision = positive_int(top["revision"], label="trust registry revision", maximum=10**9)
        entries = top["purposes"]
        if not isinstance(entries, list) or not 1 <= len(entries) <= 64:
            raise ValueError("trust registry purposes MUST be a bounded non-empty array")
    except ValueError as exc:
        raise RegistryUnavailableError(str(exc)) from exc
    counts: dict[str, int] = {}
    for entry in entries:
        purpose_id = entry.get("purpose_id") if isinstance(entry, Mapping) else None
        if isinstance(purpose_id, str):
            counts[purpose_id] = counts.get(purpose_id, 0) + 1
    purposes: dict[str, PurposeTrust] = {}
    defects: dict[str, tuple[str, ...]] = {}
    for entry in entries:
        purpose_id = entry.get("purpose_id") if isinstance(entry, Mapping) else None
        if not isinstance(purpose_id, str) or purpose_id not in OPERATIONAL_EVIDENCE_PURPOSES:
            continue
        if counts[purpose_id] > 1:
            defects[purpose_id] = ("duplicate_purpose",)
            continue
        if has_duplicates(entry):
            defects[purpose_id] = ("duplicate_key",)
            continue
        try:
            purpose = _purpose(entry)
        except (KeyError, TypeError, ValueError):
            defects[purpose_id] = ("invalid_entry",)
            continue
        if purpose.shared_verifier_anchors():
            # A shared anchor would let separation checks skip an independent identity.
            defects[purpose_id] = ("verifier_anchor_not_exclusive",)
            continue
        purposes[purpose_id] = purpose
    return TrustRegistry(pin=expected_pin, revision=revision, purposes=purposes, defects=defects)


def load_deployment_anchors(raw_json: str, *, execution_venue: Venue) -> DeploymentAnchors:
    """Parse the deployment binding strictly against the authoritative execution venue.

    The venue comes from ``resolve_execution_venue``, never from the document: a document
    whose ``venue`` disagrees, or that repeats any key, leaves every purpose unbound.
    """

    raw = load_strict_json_text(raw_json, label="deployment anchor binding")
    try:
        top = exact_fields(raw, frozenset({"schema_version", "venue", "anchors"}), label="anchors")
        if top["schema_version"] != "1.0.0":
            raise ValueError("deployment anchor schema is unsupported")
        if Venue(top["venue"]) is not execution_venue:
            raise ValueError("deployment anchor venue disagrees with the execution venue")
        items = top["anchors"]
        if not isinstance(items, list) or not 1 <= len(items) <= 64:
            raise ValueError("deployment anchors MUST be a bounded non-empty array")
        bindings: dict[str, AnchorBinding] = {}
        for item in items:
            value = exact_fields(item, _ANCHOR_FIELDS, label="anchor")
            binding = AnchorBinding(
                anchor_id=bounded_text(value["anchor_id"], label="anchor_id"),
                principal_id=bounded_text(value["principal_id"], label="principal_id"),
                evidence_class=AnchorEvidenceClass(value["evidence_class"]),
            )
            if binding.anchor_id in bindings:
                raise ValueError("deployment anchor is duplicated")
            bindings[binding.anchor_id] = binding
    except (TypeError, ValueError) as exc:
        raise RegistryUnavailableError("deployment anchor binding is invalid") from exc
    return DeploymentAnchors(venue=execution_venue, bindings=bindings)


def _purpose(raw: Mapping[str, Any]) -> PurposeTrust:
    value = exact_fields(raw, _PURPOSE_FIELDS, label="purpose")
    purpose_id = _identifier(value["purpose_id"], "purpose_id")
    producers = tuple(
        ProducerEntry(
            producer_id=_identifier(item["producer_id"], "producer_id"),
            producer_version=_semver(item["producer_version"], "producer_version"),
            anchor_id=bounded_text(item["anchor_id"], label="producer anchor"),
        )
        for item in (
            exact_fields(entry, _PRODUCER_FIELDS, label="producer")
            for entry in _bounded_list(value["producers"], "producers")
        )
    )
    sources = tuple(
        SourceEntry(
            source_id=bounded_text(item["source_id"], label="source_id"),
            role=_role(item["role"]),
            anchor_id=bounded_text(item["anchor_id"], label="source anchor"),
        )
        for item in (
            exact_fields(entry, _SOURCE_FIELDS, label="source")
            for entry in _bounded_list(value["sources"], "sources")
        )
    )
    if not any(item.role == "authoritative" for item in sources):
        raise ValueError("purpose requires an authoritative source")
    fresh = exact_fields(value["freshness_policy"], _FRESHNESS_FIELDS, label="freshness_policy")
    verifiers = tuple(
        VerifierEntry(
            verifier_id=_identifier(item["verifier_id"], "verifier_id"),
            verifier_version=_semver(item["verifier_version"], "verifier_version"),
            trust_anchor_id=bounded_text(item["trust_anchor_id"], label="trust_anchor_id"),
            window=validity(item, label="verifier"),
        )
        for item in (
            exact_fields(entry, _VERIFIER_FIELDS, label="verifier")
            for entry in _bounded_list(value["verifiers"], "verifiers")
        )
    )
    if len({item.key for item in verifiers}) != len(verifiers):
        raise ValueError("purpose verifier bindings MUST be unique")
    if value["evidence_class"] != "live":
        raise ValueError("upstream purposes MUST declare live evidence")
    return PurposeTrust(
        purpose_id=purpose_id,
        authority_class=_identifier(value["authority_class"], "authority_class"),
        method_id=_identifier(value["method_id"], "method_id"),
        method_version=_semver(value["method_version"], "method_version"),
        evidence_class="live",
        producers=producers,
        sources=sources,
        freshness=FreshnessPolicy(
            policy_id=_identifier(fresh["policy_id"], "freshness policy_id"),
            policy_version=_semver(fresh["policy_version"], "freshness policy_version"),
            ceiling_seconds=positive_int(
                fresh["ceiling_seconds"], label="ceiling_seconds", maximum=86_400
            ),
        ),
        verifiers=verifiers,
        separation=text_tuple(value["separation"], label="separation"),
        revoked=strict_bool(value["revoked"], label="purpose revoked"),
    )


def _bounded_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list) or not 1 <= len(value) <= 16:
        raise ValueError(f"{label} MUST be a bounded non-empty array")
    return value


def _identifier(value: object, label: str) -> str:
    text = bounded_text(value, label=label, maximum=128)
    if _IDENTIFIER.fullmatch(text) is None:
        raise ValueError(f"{label} MUST be a canonical identifier")
    return text


def _semver(value: object, label: str) -> str:
    text = bounded_text(value, label=label, maximum=32)
    if _SEMVER.fullmatch(text) is None:
        raise ValueError(f"{label} MUST be a semantic version")
    return text


def _role(value: object) -> str:
    if value not in {"authoritative", "corroborating"}:
        raise ValueError("source role MUST be authoritative or corroborating")
    return str(value)


__all__ = ["load_deployment_anchors", "load_trust_registry"]
