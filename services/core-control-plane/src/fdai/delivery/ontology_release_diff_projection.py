"""Compare retained exact ontology release manifests without reinterpreting schemas."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from fdai.shared.contracts.models import OntologyDeclarationRef, OntologyRelease


def build_ontology_release_diff_projection(
    *,
    base: OntologyRelease,
    candidate: OntologyRelease,
) -> dict[str, object]:
    """Return a deterministic compatibility verdict from retained declaration refs."""

    base_items = {_identity(item): item for item in base.declarations}
    candidate_items = {_identity(item): item for item in candidate.declarations}
    added = [
        _change(None, candidate_items[identity])
        for identity in sorted(candidate_items.keys() - base_items.keys())
    ]
    removed = [
        _change(base_items[identity], None)
        for identity in sorted(base_items.keys() - candidate_items.keys())
    ]
    changed = [
        _change(base_items[identity], candidate_items[identity])
        for identity in sorted(base_items.keys() & candidate_items.keys())
        if base_items[identity] != candidate_items[identity]
    ]
    if removed:
        verdict = "incompatible"
        breaking_change = {
            "path": _change_path(removed[0]),
            "reason": "declaration_removed",
        }
    elif changed:
        verdict = "migration_required"
        breaking_change = {
            "path": _change_path(changed[0]),
            "reason": "declaration_changed_without_retained_field_schema",
        }
    else:
        verdict = "compatible"
        breaking_change = None
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "base_release_digest": base.digest,
        "candidate_release_digest": candidate.digest,
        "mutation_authority": False,
        "added": added,
        "changed": changed,
        "removed": removed,
        "compatibility_verdict": verdict,
        "migration_required": bool(changed or removed),
        "breaking_change": breaking_change,
        "historical_schema_detail": "declaration_refs_only",
        "unbound_historical_evidence": False,
    }
    payload["diff_digest"] = _digest(payload)
    return payload


def build_release_diff_registry(
    *,
    releases: tuple[OntologyRelease, ...],
    truncated: bool = False,
) -> dict[str, object]:
    """Build bounded pairwise diffs for retained releases in deterministic order."""

    ordered = releases
    if len({release.digest for release in ordered}) != len(ordered):
        raise ValueError("retained ontology releases MUST be unique")
    pairs = {
        f"{candidate.digest}|{base.digest}": build_ontology_release_diff_projection(
            base=base,
            candidate=candidate,
        )
        for candidate in ordered
        for base in ordered
        if candidate.digest != base.digest
    }
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "mutation_authority": False,
        "release_digests": [release.digest for release in ordered],
        "active_release_digest": ordered[-1].digest if ordered else None,
        "truncated": truncated,
        "truncation_reason": "release_limit" if truncated else None,
        "diffs": pairs,
    }
    payload["_revision"] = _digest(payload)
    return payload


def _identity(item: OntologyDeclarationRef) -> tuple[str, str]:
    return item.kind.value, item.name


def _change(
    before: OntologyDeclarationRef | None,
    after: OntologyDeclarationRef | None,
) -> dict[str, object]:
    item = after or before
    if item is None:
        raise ValueError("ontology release change requires one declaration identity")
    return {
        "kind": item.kind.value,
        "name": item.name,
        "version_before": None if before is None else str(before.version),
        "version_after": None if after is None else str(after.version),
        "digest_before": None if before is None else before.declaration_digest,
        "digest_after": None if after is None else after.declaration_digest,
    }


def _change_path(change: Mapping[str, object]) -> str:
    return f"declarations.{change['kind']}.{change['name']}"


def _digest(value: Mapping[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = [
    "build_ontology_release_diff_projection",
    "build_release_diff_registry",
]
