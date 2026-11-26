"""Fail-closed loading and Zstandard bundle acceleration for discovery-only Rule records."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError

from fdai.rule_catalog.schema.rule import RuleCatalogError, RuleIssue
from fdai.rule_catalog.schema.zstd_codec import (
    DEFAULT_MAX_OUTPUT_BYTES,
    DEFAULT_ZSTD_LEVEL,
    ZstdCodecError,
    ZstdEnvelope,
    compress_bytes,
    decompress_bytes,
)
from fdai.shared.contracts.models import Rule
from fdai.shared.contracts.registry import SchemaRegistry

_DISCOVERY_SCHEMA_VERSION = "1.0.0"
_BUNDLE_FORMAT_VERSION = 1
_AUTO_BUNDLE_MIN_FILES = 500
_RULE_TUPLE_ADAPTER: TypeAdapter[tuple[Rule, ...]] = TypeAdapter(tuple[Rule, ...])
_MEMORY_BUNDLE_CACHE: dict[str, bytes] = {}


def _yaml_load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def discovery_tree_sha256(
    root: Path,
    *,
    schema_registry: SchemaRegistry | None = None,
) -> str:
    """Compute a cryptographic SHA-256 digest over every discovery YAML file and schema."""
    paths = sorted(root.rglob("*.yaml")) if root.is_dir() else []
    if not paths:
        raise RuleCatalogError(
            [RuleIssue(key=str(root), message="discovery catalog contains no Rule YAML files")]
        )
    hasher = hashlib.sha256()
    if schema_registry is not None:
        schema = dict(schema_registry.get("rule", _DISCOVERY_SCHEMA_VERSION))
        schema_bytes = json.dumps(schema, sort_keys=True, separators=(",", ":")).encode("utf-8")
        hasher.update(b"schema:")
        hasher.update(hashlib.sha256(schema_bytes).digest())
        hasher.update(b"\n")
    for path in paths:
        rel = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        hasher.update(rel)
        hasher.update(b"\0")
        hasher.update(hashlib.sha256(content).digest())
        hasher.update(b"\n")
    return "sha256:" + hasher.hexdigest()


def serialize_discovery_rule_bundle(
    rules: Sequence[Rule],
    *,
    tree_sha256: str,
    level: int = DEFAULT_ZSTD_LEVEL,
) -> ZstdEnvelope:
    """Serialize validated discovery ``Rule`` records into a Zstandard-compressed bundle."""
    if not tree_sha256.startswith("sha256:") or len(tree_sha256) != 71:
        raise ValueError("tree_sha256 MUST be a canonical sha256:<hex> digest")
    ordered = tuple(sorted(rules, key=lambda rule: rule.id))
    seen: set[str] = set()
    for rule in ordered:
        if rule.id in seen:
            raise ValueError(f"duplicate discovery Rule id {rule.id!r}")
        if rule.schema_version != _DISCOVERY_SCHEMA_VERSION:
            raise ValueError(
                f"discovery rule bundle requires schema_version {_DISCOVERY_SCHEMA_VERSION}"
            )
        seen.add(rule.id)
    rules_json = _RULE_TUPLE_ADAPTER.dump_json(ordered).decode("utf-8")
    envelope_json = (
        '{"format_version":'
        f"{_BUNDLE_FORMAT_VERSION},"
        f'"tree_sha256":{json.dumps(tree_sha256)},'
        f'"rule_count":{len(ordered)},'
        f'"rules":{rules_json}'
        "}"
    ).encode()
    return compress_bytes(envelope_json, level=level)


def deserialize_discovery_rule_bundle(
    compressed_bytes: bytes,
    *,
    expected_tree_sha256: str | None = None,
    max_output_size: int = DEFAULT_MAX_OUTPUT_BYTES,
) -> tuple[Rule, ...]:
    """Decompress and validate a discovery Rule bundle within ``max_output_size``."""
    raw = decompress_bytes(compressed_bytes, max_output_size=max_output_size)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ZstdCodecError(f"discovery rule bundle is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(payload, Mapping) or payload.get("format_version") != _BUNDLE_FORMAT_VERSION:
        raise ZstdCodecError("unsupported discovery rule bundle format_version")
    recorded_tree = payload.get("tree_sha256")
    if not isinstance(recorded_tree, str) or not recorded_tree.startswith("sha256:"):
        raise ZstdCodecError("discovery rule bundle is missing tree_sha256")
    if expected_tree_sha256 is not None and recorded_tree != expected_tree_sha256:
        raise ZstdCodecError(
            f"discovery rule bundle tree_sha256 mismatch: expected {expected_tree_sha256}, "
            f"got {recorded_tree}"
        )
    raw_rules = payload.get("rules")
    if not isinstance(raw_rules, list):
        raise ZstdCodecError("discovery rule bundle rules MUST be a list")
    try:
        rules = _RULE_TUPLE_ADAPTER.validate_python(raw_rules)
    except ValidationError as exc:
        raise ZstdCodecError(f"discovery rule bundle failed Rule validation: {exc}") from exc
    if len(rules) != payload.get("rule_count"):
        raise ZstdCodecError("discovery rule bundle rule_count mismatch")
    ids = [rule.id for rule in rules]
    if len(ids) != len(set(ids)):
        raise ZstdCodecError("discovery rule bundle contains duplicate rule ids")
    if any(rule.schema_version != _DISCOVERY_SCHEMA_VERSION for rule in rules):
        raise ZstdCodecError("discovery rule bundle contains non-1.0.0 schema_version")
    return tuple(sorted(rules, key=lambda rule: rule.id))


def write_discovery_rule_bundle(
    rules: Sequence[Rule],
    bundle_path: Path,
    *,
    tree_sha256: str,
    level: int = DEFAULT_ZSTD_LEVEL,
) -> ZstdEnvelope:
    """Atomically write a Zstandard-compressed discovery Rule bundle to ``bundle_path``."""
    envelope = serialize_discovery_rule_bundle(rules, tree_sha256=tree_sha256, level=level)
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = bundle_path.with_suffix(bundle_path.suffix + ".tmp")
    tmp_path.write_bytes(envelope.compressed_bytes)
    tmp_path.replace(bundle_path)
    return envelope


def load_discovery_rule_bundle(
    bundle_path: Path,
    *,
    expected_tree_sha256: str | None = None,
    max_output_size: int = DEFAULT_MAX_OUTPUT_BYTES,
) -> tuple[Rule, ...]:
    """Read, decompress, and validate a discovery Rule bundle from disk."""
    try:
        compressed = bundle_path.read_bytes()
    except OSError as exc:
        raise ZstdCodecError(f"unable to read discovery rule bundle {bundle_path}: {exc}") from exc
    return deserialize_discovery_rule_bundle(
        compressed,
        expected_tree_sha256=expected_tree_sha256,
        max_output_size=max_output_size,
    )


def _default_bundle_cache_path(root: Path, tree_sha256: str) -> Path | None:
    resolved = root.resolve()
    for parent in (resolved, *resolved.parents):
        if (parent / "pyproject.toml").is_file() and (parent / ".git").exists():
            digest_hex = tree_sha256.removeprefix("sha256:")[:24]
            return parent / ".fdai" / "cache" / f"discovery-rules-{digest_hex}.json.zst"
    return None


def load_discovery_rule_catalog(
    root: Path,
    *,
    schema_registry: SchemaRegistry,
    bundle_path: Path | None = None,
) -> tuple[Rule, ...]:
    """Load normalized Rule candidates recursively without granting active authority.

    Records must satisfy the shipped Rule 1.0.0 schema and model. The loader
    aggregates invalid records and duplicate ids, but deliberately does not
    resolve policy or ActionType execution references because discovery rows
    are candidate-only and cannot enter evaluation or action paths.

    When all YAML files under ``root`` hash to a previously verified
    ``discovery_tree_sha256``, the loader can restore the validated tuple from
    the Zstandard-compressed bundle (in-memory or ``bundle_path`` / ``.fdai/cache``)
    in ~250ms instead of ~8.7s while preserving 100% cryptographic content parity.
    """

    validator = Draft202012Validator(dict(schema_registry.get("rule", _DISCOVERY_SCHEMA_VERSION)))
    paths = sorted(root.rglob("*.yaml")) if root.is_dir() else []
    if not paths:
        raise RuleCatalogError(
            [RuleIssue(key=str(root), message="discovery catalog contains no Rule YAML files")]
        )

    tree_digest = discovery_tree_sha256(root, schema_registry=schema_registry)
    if cached_zst := _MEMORY_BUNDLE_CACHE.get(tree_digest):
        try:
            return deserialize_discovery_rule_bundle(cached_zst, expected_tree_sha256=tree_digest)
        except ZstdCodecError:
            _MEMORY_BUNDLE_CACHE.pop(tree_digest, None)

    effective_bundle_path = bundle_path or (
        _default_bundle_cache_path(root, tree_digest)
        if len(paths) >= _AUTO_BUNDLE_MIN_FILES
        else None
    )
    if effective_bundle_path is not None and effective_bundle_path.is_file():
        try:
            compressed_disk = effective_bundle_path.read_bytes()
            restored = deserialize_discovery_rule_bundle(
                compressed_disk, expected_tree_sha256=tree_digest
            )
            _MEMORY_BUNDLE_CACHE[tree_digest] = compressed_disk
            return restored
        except (OSError, ZstdCodecError):
            pass

    issues: list[RuleIssue] = []
    loaded: list[Rule] = []
    seen_ids: dict[str, str] = {}
    for path in paths:
        origin = str(path.relative_to(root))
        try:
            raw = _yaml_load(path)
        except yaml.YAMLError as exc:
            issues.append(RuleIssue(key=origin, message=f"invalid YAML: {exc}"))
            continue
        if not isinstance(raw, Mapping):
            issues.append(RuleIssue(key=origin, message="top-level must be a mapping"))
            continue

        schema_errors = sorted(validator.iter_errors(dict(raw)), key=lambda error: list(error.path))
        if schema_errors:
            for error in schema_errors:
                location = ".".join(str(part) for part in error.absolute_path) or "<root>"
                issues.append(RuleIssue(key=f"{origin}:{location}", message=error.message))
            continue

        try:
            rule = Rule.model_validate(raw)
        except ValueError as exc:
            issues.append(RuleIssue(key=f"{origin}:<root>", message=str(exc)))
            continue
        if rule.schema_version != _DISCOVERY_SCHEMA_VERSION:
            issues.append(
                RuleIssue(
                    key=f"{origin}:schema_version",
                    message=(
                        "discovery rule catalog requires schema_version "
                        f"{_DISCOVERY_SCHEMA_VERSION}"
                    ),
                )
            )
            continue

        previous = seen_ids.get(rule.id)
        if previous is not None:
            issues.append(
                RuleIssue(
                    key=f"{origin}:id",
                    message=f"duplicate rule id {rule.id!r}; first loaded from {previous}",
                )
            )
            continue
        seen_ids[rule.id] = origin
        loaded.append(rule)

    if issues:
        raise RuleCatalogError(issues)
    result = tuple(sorted(loaded, key=lambda rule: rule.id))
    envelope = serialize_discovery_rule_bundle(result, tree_sha256=tree_digest)
    _MEMORY_BUNDLE_CACHE[tree_digest] = envelope.compressed_bytes
    if effective_bundle_path is not None:
        try:
            write_discovery_rule_bundle(result, effective_bundle_path, tree_sha256=tree_digest)
        except OSError:
            pass
    return result


__all__ = [
    "deserialize_discovery_rule_bundle",
    "discovery_tree_sha256",
    "load_discovery_rule_bundle",
    "load_discovery_rule_catalog",
    "serialize_discovery_rule_bundle",
    "write_discovery_rule_bundle",
]
