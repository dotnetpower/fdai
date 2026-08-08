"""Implementation-free compatibility checks for independently released services."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_SERVICE_IDS = frozenset(
    {
        "core-control-plane",
        "operator-service",
        "document-ingestion-api",
        "document-processing-worker",
        "isolated-executor",
    }
)


class CompatibilityError(ValueError):
    """Report a fail-closed service compatibility contract violation."""


@dataclass(frozen=True, order=True, slots=True)
class SemVer:
    """Comparable semantic version used by service and wire compatibility gates."""

    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, value: object) -> SemVer:
        """Parse a strict three-component semantic version."""

        if not isinstance(value, str) or (match := _SEMVER.fullmatch(value)) is None:
            raise CompatibilityError(f"invalid semantic version: {value!r}")
        return cls(*(int(component) for component in match.groups()))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    """Deterministic outcome of duplicate and reordered delivery attempts."""

    accepted_idempotency_keys: tuple[str, ...]
    duplicate_count: int


def canonical_digest(value: object) -> str:
    """Return a replay-stable SHA-256 digest for one JSON-compatible value."""

    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CompatibilityError("value must be canonical JSON") from exc
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def ensure_supported_version(version: object, supported_major: object) -> SemVer:
    """Reject a wire version outside the explicitly supported major."""

    parsed = SemVer.parse(version)
    if not isinstance(supported_major, int) or isinstance(supported_major, bool):
        raise CompatibilityError("supported major must be an integer")
    if parsed.major != supported_major:
        raise CompatibilityError(
            f"unsupported major {parsed.major}; supported major is {supported_major}"
        )
    return parsed


def project_additive_fields(
    schema: Mapping[str, Any], payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Project a newer payload onto fields understood by an older object schema."""

    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        raise CompatibilityError("object schema must declare properties")
    return {key: payload[key] for key in properties if key in payload}


def assert_additive_schema(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    version_field: str | None = None,
) -> None:
    """Reject field removal, new requirements, narrowing, or nested breaking changes."""

    _assert_additive_node(previous, current, path="$", version_field=version_field)


def _assert_additive_node(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    path: str,
    version_field: str | None,
) -> None:
    previous_types = _type_set(previous.get("type"))
    current_types = _type_set(current.get("type"))
    if previous_types and current_types and not previous_types <= current_types:
        raise CompatibilityError(f"schema narrows type at {path}")
    if previous_types and not current_types:
        pass
    elif not previous_types and current_types:
        raise CompatibilityError(f"schema adds a type constraint at {path}")

    previous_enum = previous.get("enum")
    current_enum = current.get("enum")
    if isinstance(previous_enum, list) and isinstance(current_enum, list):
        if not set(previous_enum) <= set(current_enum):
            raise CompatibilityError(f"schema narrows enum at {path}")
    elif previous_enum is None and current_enum is not None:
        raise CompatibilityError(f"schema adds an enum constraint at {path}")

    _assert_scalar_constraints(previous, current, path=path)
    if path != f"$.{version_field}":
        _assert_exact_constraints(previous, current, path=path)
    _assert_composition_constraints(previous, current, path=path)

    previous_properties = previous.get("properties")
    current_properties = current.get("properties")
    if isinstance(previous_properties, Mapping):
        if not isinstance(current_properties, Mapping):
            raise CompatibilityError(f"schema removes object properties at {path}")
        removed = set(previous_properties) - set(current_properties)
        if removed:
            raise CompatibilityError(f"schema removes fields at {path}: {sorted(removed)}")
        previous_required = _string_set(previous.get("required"))
        current_required = _string_set(current.get("required"))
        added_required = current_required - previous_required
        if added_required:
            raise CompatibilityError(
                f"schema adds required fields at {path}: {sorted(added_required)}"
            )
        for name, previous_child in previous_properties.items():
            current_child = current_properties[name]
            if not isinstance(previous_child, Mapping) or not isinstance(current_child, Mapping):
                raise CompatibilityError(f"schema property at {path}.{name} must be an object")
            _assert_additive_node(
                previous_child,
                current_child,
                path=f"{path}.{name}",
                version_field=version_field,
            )

    previous_items = previous.get("items")
    current_items = current.get("items")
    if isinstance(previous_items, Mapping):
        if not isinstance(current_items, Mapping):
            raise CompatibilityError(f"schema removes array item constraints at {path}")
        _assert_additive_node(
            previous_items,
            current_items,
            path=f"{path}[]",
            version_field=version_field,
        )


def _assert_scalar_constraints(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    path: str,
) -> None:
    for keyword in ("maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties"):
        _assert_bound(previous, current, keyword=keyword, path=path, increase_widens=True)
    for keyword in ("minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties"):
        _assert_bound(previous, current, keyword=keyword, path=path, increase_widens=False)


def _assert_bound(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    keyword: str,
    path: str,
    increase_widens: bool,
) -> None:
    old = previous.get(keyword)
    new = current.get(keyword)
    if old is None and new is not None:
        raise CompatibilityError(f"schema adds {keyword} at {path}")
    if old is None or new is None:
        return
    if (
        not isinstance(old, (int, float))
        or isinstance(old, bool)
        or not isinstance(new, (int, float))
        or isinstance(new, bool)
    ):
        raise CompatibilityError(f"schema {keyword} at {path} must be numeric")
    if (increase_widens and new < old) or (not increase_widens and new > old):
        raise CompatibilityError(f"schema narrows {keyword} at {path}")


def _assert_exact_constraints(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    path: str,
) -> None:
    for keyword in ("pattern", "format", "const"):
        old = previous.get(keyword)
        new = current.get(keyword)
        if old is None and new is not None:
            raise CompatibilityError(f"schema adds {keyword} at {path}")
        if old is not None and new is not None and old != new:
            raise CompatibilityError(f"schema changes {keyword} at {path}")
    old_additional = previous.get("additionalProperties", True)
    new_additional = current.get("additionalProperties", True)
    if old_additional is True and new_additional is not True:
        raise CompatibilityError(f"schema narrows additionalProperties at {path}")
    if isinstance(old_additional, Mapping):
        if new_additional is False:
            raise CompatibilityError(f"schema narrows additionalProperties at {path}")
        if isinstance(new_additional, Mapping):
            _assert_additive_node(
                old_additional,
                new_additional,
                path=f"{path}.*",
                version_field=None,
            )


def _assert_composition_constraints(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    path: str,
) -> None:
    for keyword in ("allOf", "anyOf", "oneOf", "not", "if", "then", "else"):
        old = previous.get(keyword)
        new = current.get(keyword)
        if old is None and new is not None:
            raise CompatibilityError(f"schema adds {keyword} at {path}")
        if old is not None and new is not None and old != new:
            raise CompatibilityError(f"schema changes {keyword} at {path}")


def _type_set(value: object) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return set(value)
    return set()


def _string_set(value: object) -> set[str]:
    if value is None:
        return set()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CompatibilityError("schema required value must be a string array")
    return set(value)


def validate_delivery_trace(attempts: Sequence[Mapping[str, Any]]) -> DeliveryResult:
    """Prove duplicate and reordered attempts converge without duplicate terminal effects."""

    ordered: list[tuple[int, str, str, bool]] = []
    for attempt in attempts:
        sequence = attempt.get("sequence")
        key = attempt.get("idempotency_key")
        digest = attempt.get("payload_digest")
        terminal_effect = attempt.get("terminal_effect")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
            raise CompatibilityError("delivery sequence must be a non-negative integer")
        if not isinstance(key, str) or not key:
            raise CompatibilityError("delivery idempotency key must be non-empty")
        if not isinstance(digest, str) or not digest.startswith("sha256:"):
            raise CompatibilityError("delivery payload digest must use sha256")
        if not isinstance(terminal_effect, bool):
            raise CompatibilityError("delivery terminal_effect must be boolean")
        ordered.append((sequence, key, digest, terminal_effect))

    accepted: dict[str, tuple[str, bool]] = {}
    duplicate_count = 0
    for _sequence, key, digest, terminal_effect in sorted(ordered):
        prior = accepted.get(key)
        if prior is None:
            accepted[key] = (digest, terminal_effect)
            continue
        duplicate_count += 1
        if prior[0] != digest:
            raise CompatibilityError(f"idempotency collision for {key}")
        if terminal_effect and prior[1]:
            raise CompatibilityError(f"duplicate terminal effect for {key}")
        if terminal_effect:
            accepted[key] = (digest, True)
    return DeliveryResult(tuple(accepted), duplicate_count)


def matrix_digest(manifest: Mapping[str, Any]) -> str:
    """Return the digest pinned by independent upgrade and rollback receipts."""

    return canonical_digest(manifest.get("producer_consumer_matrix"))


def validate_peer_upgrade_receipt(
    manifest: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> None:
    """Validate one migration or rollback while every peer remains unchanged."""

    receipt_format = _mapping(manifest.get("upgrade_receipt"), "upgrade_receipt")
    if receipt.get("receipt_version") != receipt_format.get("version"):
        raise CompatibilityError("receipt version does not match the manifest")
    service_id = receipt.get("service_id")
    if service_id not in _SERVICE_IDS:
        raise CompatibilityError("receipt service_id is not one of the five services")
    services = _service_map(manifest)
    service = services[str(service_id)]
    direction = receipt.get("direction")
    if direction not in {"migration", "rollback"}:
        raise CompatibilityError("receipt direction must be migration or rollback")
    transition = _mapping(service.get(str(direction)), f"{service_id}.{direction}")
    if receipt.get("from_version") != transition.get("from_version"):
        raise CompatibilityError("receipt from_version does not match the declared transition")
    if receipt.get("to_version") != transition.get("to_version"):
        raise CompatibilityError("receipt to_version does not match the declared transition")
    ensure_supported_version(receipt.get("from_version"), service.get("supported_major"))
    ensure_supported_version(receipt.get("to_version"), service.get("supported_major"))
    expected_key = (
        f"service-upgrade:{service_id}:{direction}:"
        f"{receipt['from_version']}:{receipt['to_version']}"
    )
    if receipt.get("idempotency_key") != expected_key:
        raise CompatibilityError("receipt idempotency key is not transition-stable")
    if receipt.get("matrix_digest") != matrix_digest(manifest):
        raise CompatibilityError("receipt matrix digest does not match the manifest")

    peers_before = _mapping(receipt.get("peer_versions_before"), "peer_versions_before")
    peers_after = _mapping(receipt.get("peer_versions_after"), "peer_versions_after")
    expected_peers = _SERVICE_IDS - {str(service_id)}
    if set(peers_before) != expected_peers or set(peers_after) != expected_peers:
        raise CompatibilityError("receipt must name every peer and only peers")
    if peers_before != peers_after:
        raise CompatibilityError("peer versions changed during an independent transition")
    for peer_id, version in peers_before.items():
        ensure_supported_version(version, services[peer_id].get("supported_major"))
    required_peers = _mapping(
        transition.get("requires_peer_versions", {}),
        f"{service_id}.{direction}.requires_peer_versions",
    )
    if any(peers_before.get(peer_id) != version for peer_id, version in required_peers.items()):
        raise CompatibilityError("receipt violates the ordered rollout peer requirements")

    checks = _mapping(receipt.get("checks"), "checks")
    required_checks = set(_string_sequence(receipt_format.get("required_checks")))
    if set(checks) != required_checks or any(value is not True for value in checks.values()):
        raise CompatibilityError("every required receipt check must be present and true")
    if receipt.get("peer_restart_count") != 0:
        raise CompatibilityError("independent transition restarted a peer")
    if receipt.get("duplicate_terminal_effects") != 0:
        raise CompatibilityError("independent transition produced duplicate terminal effects")
    if receipt.get("offsets_preserved") is not True:
        raise CompatibilityError("independent transition did not preserve offsets")
    if receipt.get("outcome") != "stable":
        raise CompatibilityError("independent transition outcome is not stable")


def load_json_object(path: Path) -> dict[str, Any]:
    """Load one UTF-8 JSON object for compatibility validation."""

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompatibilityError(f"cannot load JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise CompatibilityError(f"JSON value must be an object: {path}")
    return value


def _service_map(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    services = manifest.get("services")
    if not isinstance(services, list):
        raise CompatibilityError("manifest services must be an array")
    by_id: dict[str, Mapping[str, Any]] = {}
    for item in services:
        service = _mapping(item, "service")
        service_id = service.get("id")
        if not isinstance(service_id, str) or service_id in by_id:
            raise CompatibilityError("manifest service ids must be unique strings")
        by_id[service_id] = service
    if set(by_id) != _SERVICE_IDS:
        raise CompatibilityError("manifest must declare exactly the five FDAI services")
    return by_id


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CompatibilityError(f"{name} must be an object")
    return value


def _string_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CompatibilityError("required_checks must be a string array")
    return tuple(value)


__all__ = [
    "CompatibilityError",
    "DeliveryResult",
    "SemVer",
    "assert_additive_schema",
    "canonical_digest",
    "ensure_supported_version",
    "load_json_object",
    "matrix_digest",
    "project_additive_fields",
    "validate_delivery_trace",
    "validate_peer_upgrade_receipt",
]
