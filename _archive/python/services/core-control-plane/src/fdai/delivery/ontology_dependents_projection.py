"""Project bounded declaration dependents from deterministic catalog topology edges."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import cast


def build_declaration_dependents_projection(
    *,
    topology: Mapping[str, object],
    declaration_kind: str,
    declaration_name: str,
    limit: int = 100,
) -> dict[str, object]:
    """Return only topology-backed references to one exact declaration identity."""

    if declaration_kind != "object-types":
        raise LookupError(f"unsupported dependent declaration kind: {declaration_kind}")
    if not 1 <= limit <= 100:
        raise ValueError("ontology dependents limit MUST be in [1, 100]")
    release_digest = topology.get("ontologyReleaseDigest")
    if not isinstance(release_digest, str) or not release_digest.startswith("sha256:"):
        raise ValueError("ontology dependents require an exact release digest")
    nodes = _mapping_sequence(topology.get("nodes"), field="nodes")
    edges = _mapping_sequence(topology.get("edges"), field="edges")
    nodes_by_id = {str(node.get("id")): node for node in nodes}
    selected_id = f"ot:{declaration_name}"
    if selected_id not in nodes_by_id:
        raise LookupError(f"unknown ObjectType declaration: {declaration_name}")

    dependents = sorted(
        (
            dependent
            for edge in edges
            if selected_id in {edge.get("source"), edge.get("target")}
            for dependent in _dependent_from_edge(
                edge,
                selected_id=selected_id,
                nodes_by_id=nodes_by_id,
            )
        ),
        key=lambda item: (str(item["kind"]), str(item["name"]), str(item["relationship"])),
    )
    unique: list[dict[str, str]] = []
    identities: set[tuple[str, str, str]] = set()
    for dependent in dependents:
        identity = (
            dependent["kind"],
            dependent["name"],
            dependent["relationship"],
        )
        if identity not in identities:
            identities.add(identity)
            unique.append(dependent)
    visible = unique[:limit]
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "ontology_release_digest": release_digest,
        "declaration_kind": "object_type",
        "declaration_name": declaration_name,
        "mutation_authority": False,
        "complete": len(unique) <= limit,
        "truncated": len(unique) > limit,
        "truncation_reason": "result_limit" if len(unique) > limit else None,
        "dependents": visible,
    }
    payload["_revision"] = _digest(payload)
    return payload


def _dependent_from_edge(
    edge: Mapping[str, object],
    *,
    selected_id: str,
    nodes_by_id: Mapping[str, Mapping[str, object]],
) -> tuple[dict[str, str], ...]:
    kind = edge.get("kind")
    label = edge.get("label")
    if not isinstance(label, str) or not label:
        return ()
    if kind == "link_type":
        return (
            {
                "kind": "link_type",
                "name": label,
                "relationship": "references_object_type",
                "evidence_ref": f"LinkType:{label}",
            },
        )
    other_id = str(edge.get("target") if edge.get("source") == selected_id else edge.get("source"))
    other = nodes_by_id.get(other_id)
    if other is None:
        return ()
    other_name = other.get("label")
    other_kind = other.get("kind")
    if not isinstance(other_name, str) or not isinstance(other_kind, str):
        return ()
    relationship_by_kind = {
        ("interface_type", "implements"): "implemented_by_object_type",
        ("agent", "owns_type"): "owns_object_type",
    }
    relationship = relationship_by_kind.get((other_kind, label))
    if relationship is None:
        return ()
    return (
        {
            "kind": other_kind,
            "name": other_name,
            "relationship": relationship,
            "evidence_ref": f"{other_kind}:{other_name}",
        },
    )


def _mapping_sequence(value: object, *, field: str) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"ontology dependents {field} MUST be a sequence")
    if any(not isinstance(item, Mapping) for item in value):
        raise ValueError(f"ontology dependents {field} values MUST be mappings")
    return cast(tuple[Mapping[str, object], ...], tuple(value))


def _digest(value: Mapping[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


__all__ = ["build_declaration_dependents_projection"]
