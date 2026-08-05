"""Project diagnostic mechanism provenance into the ontology read model."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from fdai.shared.providers.ontology_instance import OntologyLinkRecord, OntologyObjectRecord

from .catalog_projection import CatalogOntologyProjection
from .diagnostic_ledger import VALIDATION_AXES

_SHA1 = re.compile(r"^[0-9a-f]{40}$")


def build_diagnostic_catalog_projection(
    mechanisms: Sequence[Mapping[str, Any]],
    *,
    benchmark_id: str,
) -> CatalogOntologyProjection:
    """Build bounded catalog-owned objects from validated mechanism records.

    The projection records semantic and validation provenance only. It never
    creates an ActionType, approval, promotion, or execution authority.
    """

    if not benchmark_id.strip():
        raise ValueError("diagnostic benchmark_id MUST be non-empty")
    objects: list[OntologyObjectRecord] = []
    links: list[OntologyLinkRecord] = []
    seen_ids: set[str] = set()
    for mechanism in sorted(mechanisms, key=lambda item: str(item.get("id") or "")):
        mechanism_id = _required_text(mechanism, "id")
        if mechanism_id in seen_ids:
            raise ValueError(f"duplicate diagnostic mechanism {mechanism_id!r}")
        seen_ids.add(mechanism_id)
        source_commits = mechanism.get("source_commits")
        if (
            not isinstance(source_commits, list)
            or not source_commits
            or any(
                not isinstance(item, str) or _SHA1.fullmatch(item) is None
                for item in source_commits
            )
            or len(set(source_commits)) != len(source_commits)
        ):
            raise ValueError("diagnostic mechanism source_commits MUST be unique full revisions")
        axes = {axis: _required_bool(mechanism, axis) for axis in VALIDATION_AXES}
        mechanism_ref = f"diagnostic-mechanism:{mechanism_id}"
        mechanism_properties: dict[str, Any] = {
            "id": mechanism_ref,
            "mechanism_id": mechanism_id,
            "status": _required_text(mechanism, "status"),
            "source_commits": sorted(source_commits),
            **axes,
        }
        source_hardening = mechanism.get("source_hardening")
        if source_hardening is not None:
            if not isinstance(source_hardening, str) or not source_hardening.strip():
                raise ValueError("diagnostic mechanism source_hardening MUST be non-empty")
            mechanism_properties["source_hardening"] = source_hardening
        objects.append(
            OntologyObjectRecord(
                id=mechanism_ref,
                object_type="DiagnosticMechanism",
                properties=mechanism_properties,
            )
        )
        for axis in VALIDATION_AXES:
            receipt_properties = _validation_receipt(
                mechanism=mechanism,
                mechanism_id=mechanism_id,
                benchmark_id=benchmark_id,
                axis=axis,
                passed=axes[axis],
            )
            validation_ref = receipt_properties["id"]
            objects.append(
                OntologyObjectRecord(
                    id=validation_ref,
                    object_type="BenchmarkValidation",
                    properties=receipt_properties,
                )
            )
            links.append(
                OntologyLinkRecord(
                    link_type="mechanism_validated_by",
                    from_id=mechanism_ref,
                    to_id=validation_ref,
                )
            )
    return CatalogOntologyProjection(objects=tuple(objects), links=tuple(links))


def _required_text(record: Mapping[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"diagnostic mechanism {key} MUST be non-empty")
    return value


def _required_bool(record: Mapping[str, Any], key: str) -> bool:
    value = record.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"diagnostic mechanism {key} MUST be boolean")
    return value


def _validation_receipt(
    *,
    mechanism: Mapping[str, Any],
    mechanism_id: str,
    benchmark_id: str,
    axis: str,
    passed: bool,
) -> dict[str, Any]:
    source_revisions = sorted(mechanism["source_commits"])
    content: dict[str, Any] = {
        "benchmark_id": benchmark_id,
        "mechanism_id": mechanism_id,
        "validation_axis": axis,
        "passed": passed,
        "source_revisions": source_revisions,
        "validation_kind": (
            mechanism.get("provider_validation_kind", "source-review")
            if axis in {"provider_validated", "azure_validated"}
            else "source-review"
        ),
    }
    evidence_field = {
        "provider_validated": "provider_validation_evidence",
        "azure_validated": "azure_validation_evidence",
    }.get(axis)
    if evidence_field is not None and mechanism.get(evidence_field):
        content["evidence_summary"] = mechanism[evidence_field]
    encoded = json.dumps(
        content,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return {
        "id": f"benchmark-validation:{digest}",
        **content,
        "evidence_digest": f"sha256:{digest}",
    }


__all__ = ["build_diagnostic_catalog_projection"]
