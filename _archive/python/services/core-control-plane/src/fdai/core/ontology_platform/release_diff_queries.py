"""Read-only compatibility queries over retained exact ontology releases."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyDeclarationKind,
    OntologyDeclarationRef,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
)

from .functions import ContextualOntologyFunction, FunctionInvocationContext

ONTOLOGY_RELEASE_DIFF_FUNCTION_NAME = "query.ontology_release_diff"
ONTOLOGY_RELEASE_DIFF_PURPOSE = "operations-review"
_MAX_ROWS = 1_000


def ontology_release_diff_function_type() -> OntologyFunctionType:
    """Return the declaration-ref-only retained-release diff FunctionType."""

    digest_schema = {"type": "string", "pattern": "^sha256:[a-f0-9]{64}$"}
    return OntologyFunctionType(
        name=ONTOLOGY_RELEASE_DIFF_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}",
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["base_release_digest", "candidate_release_digest", "limit"],
            "properties": {
                "base_release_digest": digest_schema,
                "candidate_release_digest": digest_schema,
                "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_ROWS},
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["rows", "complete", "truncation_reason"],
            "properties": {
                "rows": {
                    "type": "array",
                    "maxItems": _MAX_ROWS,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["row_id", "values"],
                        "properties": {
                            "row_id": {"type": "string", "minLength": 1, "maxLength": 512},
                            "values": {
                                "type": "object",
                                "required": [
                                    "base_release_digest",
                                    "candidate_release_digest",
                                    "change_kind",
                                    "compatibility_verdict",
                                    "historical_schema_detail",
                                    "execution_authority",
                                    "mutation_authority",
                                ],
                                "properties": {
                                    "base_release_digest": digest_schema,
                                    "candidate_release_digest": digest_schema,
                                    "change_kind": {
                                        "enum": ["added", "changed", "removed", "summary"]
                                    },
                                    "compatibility_verdict": {
                                        "enum": [
                                            "compatible",
                                            "migration_required",
                                            "incompatible",
                                        ]
                                    },
                                    "historical_schema_detail": {"const": "declaration_refs_only"},
                                    "execution_authority": {"const": False},
                                    "mutation_authority": {"const": False},
                                },
                            },
                        },
                    },
                },
                "complete": {"type": "boolean"},
                "truncation_reason": {
                    "type": ["string", "null"],
                    "enum": ["result_limit", "release_limit", None],
                },
            },
        },
        read_sets=[],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=[ONTOLOGY_RELEASE_DIFF_PURPOSE],
        timeout_seconds=1,
        cpu_millis=100,
        memory_bytes=33_554_432,
        max_output_bytes=1_048_576,
        network_allowed=False,
        credentials_allowed=False,
    )


def ontology_release_diff_function(
    active_release: OntologyRelease,
    *,
    retained_releases: Sequence[OntologyRelease],
    registry_truncated: bool = False,
) -> ContextualOntologyFunction:
    """Bind retained exact releases without reconstructing declaration schemas."""

    active_release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        ONTOLOGY_RELEASE_DIFF_FUNCTION_NAME,
    )
    releases = {item.digest: item for item in retained_releases}
    if len(releases) != len(retained_releases):
        raise ValueError("retained ontology releases MUST be unique")
    if active_release.digest not in releases:
        raise ValueError("retained ontology releases MUST include the active release")

    async def evaluate(
        arguments: Mapping[str, Any],
        invocation_context: FunctionInvocationContext,
    ) -> object:
        if invocation_context.purposes != (ONTOLOGY_RELEASE_DIFF_PURPOSE,):
            raise PermissionError("ontology release diff purpose does not match invocation context")
        base_digest = str(arguments["base_release_digest"])
        candidate_digest = str(arguments["candidate_release_digest"])
        if base_digest == candidate_digest:
            raise ValueError("ontology release diff requires two distinct releases")
        try:
            base = releases[base_digest]
            candidate = releases[candidate_digest]
        except KeyError as error:
            raise LookupError("ontology release diff requires retained exact releases") from error
        rows, verdict = _diff_rows(base, candidate)
        limit = int(arguments["limit"])
        selected = rows[:limit]
        result_limited = len(selected) != len(rows)
        complete = not result_limited and not registry_truncated
        reason = (
            "result_limit" if result_limited else "release_limit" if registry_truncated else None
        )
        if not selected:
            selected = (
                {
                    "row_id": "summary:no-change",
                    "values": _values(
                        base,
                        candidate,
                        change_kind="summary",
                        verdict=verdict,
                        declaration=None,
                    ),
                },
            )
        return {
            "rows": list(selected),
            "complete": complete,
            "truncation_reason": reason,
        }

    return evaluate


def _diff_rows(
    base: OntologyRelease,
    candidate: OntologyRelease,
) -> tuple[tuple[dict[str, object], ...], str]:
    before = {_identity(item): item for item in base.declarations}
    after = {_identity(item): item for item in candidate.declarations}
    added = [("added", None, after[key]) for key in sorted(after.keys() - before.keys())]
    removed = [("removed", before[key], None) for key in sorted(before.keys() - after.keys())]
    changed = [
        ("changed", before[key], after[key])
        for key in sorted(before.keys() & after.keys())
        if before[key] != after[key]
    ]
    verdict = "incompatible" if removed else "migration_required" if changed else "compatible"
    rows: list[dict[str, object]] = []
    for change_kind, before_item, after_item in (*added, *changed, *removed):
        item = after_item or before_item
        if item is None:  # pragma: no cover - each change has one declaration side
            raise RuntimeError("ontology release change lost its declaration identity")
        rows.append(
            {
                "row_id": f"{change_kind}:{item.kind.value}:{item.name}",
                "values": _values(
                    base,
                    candidate,
                    change_kind=change_kind,
                    verdict=verdict,
                    declaration=(before_item, after_item),
                ),
            }
        )
    return tuple(rows), verdict


def _values(
    base: OntologyRelease,
    candidate: OntologyRelease,
    *,
    change_kind: str,
    verdict: str,
    declaration: tuple[OntologyDeclarationRef | None, OntologyDeclarationRef | None] | None,
) -> dict[str, object]:
    before, after = declaration or (None, None)
    item = after or before
    return {
        "base_release_digest": base.digest,
        "candidate_release_digest": candidate.digest,
        "change_kind": change_kind,
        "declaration_kind": None if item is None else item.kind.value,
        "declaration_name": None if item is None else item.name,
        "version_before": None if before is None else str(before.version),
        "version_after": None if after is None else str(after.version),
        "digest_before": None if before is None else before.declaration_digest,
        "digest_after": None if after is None else after.declaration_digest,
        "compatibility_verdict": verdict,
        "migration_required": verdict != "compatible",
        "historical_schema_detail": "declaration_refs_only",
        "execution_authority": False,
        "mutation_authority": False,
    }


def _identity(item: OntologyDeclarationRef) -> tuple[str, str]:
    return item.kind.value, item.name


__all__ = [
    "ONTOLOGY_RELEASE_DIFF_FUNCTION_NAME",
    "ONTOLOGY_RELEASE_DIFF_PURPOSE",
    "ontology_release_diff_function",
    "ontology_release_diff_function_type",
]
