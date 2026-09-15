"""Compile explicitly typed handover Rule candidates without activation.

The exact fdai.rule.candidate.v1 marker is a machine contract, not a keyword classifier.
Prose extraction alone proves no source fidelity and is never admitted by this compiler.
Full Rule shape, existing ActionTypes, resources, policy files, and source lineage are verified.
Human review, shadow replay, regression, and promotion remain independent required later gates.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import (
    Path,
    PurePosixPath,
)
from typing import Any

from fdai.rule_catalog.schema.rule import load_rule_from_mapping
from fdai.shared.contracts.registry import SchemaRegistry
from fdai.shared.providers.distiller import (
    CandidateKind,
    DistilledCandidate,
    ManualDocument,
)


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("typed handover Rule contains duplicate JSON keys")
        result[key] = value
    return result


def explicit_rule_candidates(document: ManualDocument) -> tuple[DistilledCandidate, ...]:
    """Parse complete machine-marked JSON structural units only; prose has no deterministic route.

    Source and provenance fields belong to the compiler and cannot be supplied by the artifact.
    A malformed marked artifact fails closed; unrelated non-JSON document units are not Rules.
    """
    candidates: list[DistilledCandidate] = []
    for number, line in enumerate(document.text.splitlines(), start=1):
        if not line.lstrip().startswith("{"):
            continue
        try:
            raw = json.loads(line, object_pairs_hook=_unique_pairs)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict) or raw.get("kind") != "fdai.rule.candidate.v1":
            continue
        if set(raw) != {"kind", "rule"} or not isinstance(raw["rule"], dict):
            raise ValueError("typed handover Rule requires only kind and rule")
        body = raw["rule"]
        if {"source", "provenance"} & body.keys():
            raise ValueError("typed handover Rule cannot supply compiler-owned provenance")
        identity = body.get("id")
        if not isinstance(identity, str):
            raise ValueError("typed handover Rule requires a canonical Rule id")
        candidates.append(
            DistilledCandidate(
                kind=CandidateKind.RULE,
                candidate_id=identity,
                source_ref=document.source_ref,
                source_section="typed-artifact",
                source_lines=(number, number),
                content_sha=document.content_sha,
                body=body,
            )
        )
        if len(candidates) > 20:
            raise ValueError("typed handover Rules exceed the candidate bound")
    return tuple(candidates)


def _artifact_digest(root: Path, reference: str, prefix: str) -> str:
    """Hash one bounded catalog file without following links or accepting opaque file references."""
    relative = reference.removeprefix(prefix)
    path = PurePosixPath(relative)
    if (
        not reference.startswith(prefix)
        or not relative
        or path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != relative
        or "\\" in relative
    ):
        raise ValueError("handover Rule dependency requires a canonical catalog-relative file")
    handles: list[int] = []
    try:
        handles.append(os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))
        for part in path.parts[:-1]:
            handles.append(
                os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=handles[-1],
                )
            )
        file = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=handles[-1],
        )
        handles.append(file)
        before = os.fstat(file)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= 1_048_576:
            raise ValueError("handover Rule dependency must be a bounded regular file")
        with os.fdopen(os.dup(file), "rb") as stream:
            content = stream.read(1_048_577)
        after = os.fstat(file)
        if len(content) != before.st_size or (
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("handover Rule dependency changed during its read")
        return hashlib.sha256(content).hexdigest()
    except OSError:
        raise ValueError("handover Rule dependency is unavailable") from None
    finally:
        for handle in reversed(handles):
            os.close(handle)


@dataclass(frozen=True, slots=True)
class HandoverRuleCompiler:
    """Validate source-bound Rules against the real catalog, not a permissive surrogate schema."""

    schema_registry: SchemaRegistry
    action_type_names: frozenset[str]
    resource_type_ids: frozenset[str]
    policies_root: Path
    remediation_root: Path

    def compile(
        self,
        document: ManualDocument,
        candidates: tuple[DistilledCandidate, ...],
    ) -> tuple[dict[str, Any], ...]:
        """Return actual Rule bodies and immutable attribution without writing the catalog."""
        if (
            len(candidates) > 20
            or document.content_sha != hashlib.sha256(document.text.encode()).hexdigest()
            or not document.metadata.get("revision")
        ):
            raise ValueError("handover Rule compiler requires bounded immutable source content")
        retrieved = document.metadata.get("recorded_at", "")
        timestamp = datetime.fromisoformat(retrieved)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("handover Rule source timestamp must be explicit")
        explicit = explicit_rule_candidates(document)
        provenance = {item.line_number: item for item in document.line_provenance}
        lines = document.text.splitlines()
        result: list[dict[str, Any]] = []
        identities: set[str] = set()
        for candidate in candidates:
            if candidate.kind is not CandidateKind.RULE:
                continue
            if (
                candidate.source_ref != document.source_ref
                or candidate.content_sha != document.content_sha
                or not 1 <= candidate.source_lines[0] <= candidate.source_lines[1] <= len(lines)
                or not isinstance(candidate.body, Mapping)
                or candidate.candidate_id in identities
            ):
                raise ValueError("handover Rule candidate source, span, or identity is invalid")
            if not any(
                json.dumps(asdict(candidate), sort_keys=True, allow_nan=False)
                == json.dumps(asdict(original), sort_keys=True, allow_nan=False)
                for original in explicit
            ):
                raise ValueError("handover Rule source fidelity requires an exact typed artifact")
            identities.add(candidate.candidate_id)
            raw = dict(candidate.body)
            if raw.get("id") != candidate.candidate_id:
                raise ValueError("handover Rule candidate id differs from its compiled Rule")
            raw["source"] = "custom"
            raw["provenance"] = {
                "source_url": document.source_ref,
                "resolved_ref": document.metadata["revision"],
                "content_hash": "sha256:" + document.content_sha,
                "license": "LicenseRef-reference-only",
                "redistribution": "reference-only",
                "retrieved_at": timestamp.isoformat(),
            }
            rule = load_rule_from_mapping(
                raw,
                schema_registry=self.schema_registry,
                action_type_names=set(self.action_type_names),
                resource_type_ids=set(self.resource_type_ids),
                policies_root=self.policies_root,
                remediation_root=self.remediation_root,
                origin="handover-candidate",
            )
            dependencies = {
                "policy_sha256": _artifact_digest(
                    self.policies_root,
                    rule.check_logic.reference,
                    "policies/",
                ),
                "remediation_sha256": _artifact_digest(
                    self.remediation_root,
                    rule.remediation.template_ref,
                    "remediation/",
                ),
                "rule_schema_sha256": hashlib.sha256(
                    json.dumps(
                        dict(self.schema_registry.get("rule")),
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ).encode()
                ).hexdigest(),
            }
            result.append(
                {
                    "kind": "rule",
                    "rule": rule.model_dump(mode="json"),
                    "dependencies": dependencies,
                    "source_ref": document.source_ref,
                    "source_lines": list(candidate.source_lines),
                    "source_units": [
                        asdict(provenance[number])
                        for number in range(
                            candidate.source_lines[0], candidate.source_lines[1] + 1
                        )
                    ],
                    "source_sha256": document.metadata["source_sha256"],
                    "normalized_sha256": document.content_sha,
                    "required_gates": [
                        "source_fidelity_review",
                        "regression",
                        "shadow",
                        "promotion",
                    ],
                    "review_required": True,
                    "execution_authority": False,
                }
            )
        return tuple(result)


__all__ = ["HandoverRuleCompiler", "explicit_rule_candidates"]
