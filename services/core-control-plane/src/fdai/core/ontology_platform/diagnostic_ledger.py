"""Validate the complete diagnostic absorption ledger before ontology projection."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

VALIDATION_AXES = (
    "benchmark_measured",
    "semantic_generalized",
    "operationalized",
    "provider_validated",
    "action_validated",
    "outcome_validated",
    "azure_validated",
)
_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MECHANISM_ID = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_ALLOWED_STATUSES = frozenset({"semantic_generalized", "operationalized", "rejected"})
_MAX_MECHANISM_COMMITS = 32
_MAX_TEXT_CHARS = 8_192
_EXPECTED_SOURCE_SET_SHA256 = "5c547ea475ab0bd5c3403f696017d78e55d2d2cd3c415463430bc1b8091c188c"
_EXPECTED_SOURCE_HEAD = "386fed856292d68a15bf0a1861580a2b8a286aa6"
_EXPECTED_ARCHIVE_SHA256 = "d3fb9974b4c8368d362a2a2c0b0eb0bff56b1c1cf16facd4acdf0ec1f69cd041"


@dataclass(frozen=True, slots=True)
class DiagnosticLedger:
    """Validated frozen source identity and mechanism records."""

    source_set_sha256: str
    mechanisms: tuple[Mapping[str, Any], ...]


def validate_diagnostic_ledger(payload: Mapping[str, Any]) -> DiagnosticLedger:
    """Return validated records or reject any incomplete or contradictory ledger."""

    if payload.get("schema_version") != "1.0.0":
        raise ValueError("diagnostic ledger schema_version is unsupported")
    if tuple(payload.get("validation_axes") or ()) != VALIDATION_AXES:
        raise ValueError("diagnostic ledger validation_axes are incompatible")
    groups = payload.get("groups")
    if not isinstance(groups, list):
        raise ValueError("diagnostic ledger groups MUST be an array")
    source_commits: list[str] = []
    for group in groups:
        if not isinstance(group, Mapping) or not isinstance(group.get("commits"), list):
            raise ValueError("diagnostic ledger group commits MUST be arrays")
        source_commits.extend(_commit_list(group["commits"], field="group commits"))
    if len(source_commits) != 124 or payload.get("source_commit_count") != len(source_commits):
        raise ValueError("diagnostic ledger source commit count is incomplete")
    if len(set(source_commits)) != len(source_commits):
        raise ValueError("diagnostic ledger source commits MUST be unique")
    source_digest = hashlib.sha256(
        "".join(f"{commit}\n" for commit in sorted(source_commits)).encode("ascii")
    ).hexdigest()
    if payload.get("source_set_sha256") != source_digest:
        raise ValueError("diagnostic ledger source_set_sha256 mismatch")
    if source_digest != _EXPECTED_SOURCE_SET_SHA256:
        raise ValueError("diagnostic ledger source set is not the frozen source set")
    source_head = payload.get("source_head")
    if not isinstance(source_head, str) or not _SHA1.fullmatch(source_head):
        raise ValueError("diagnostic ledger source_head MUST be a full revision")
    if source_head not in set(source_commits):
        raise ValueError("diagnostic ledger source_head is outside the source set")
    if source_head != _EXPECTED_SOURCE_HEAD:
        raise ValueError("diagnostic ledger source_head is not the frozen source head")
    archive_digest = payload.get("archive_bundle_sha256")
    if not isinstance(archive_digest, str) or not _SHA256.fullmatch(archive_digest):
        raise ValueError("diagnostic ledger archive digest MUST be SHA-256")
    if archive_digest != _EXPECTED_ARCHIVE_SHA256:
        raise ValueError("diagnostic ledger archive digest is not the frozen archive")

    mechanisms = payload.get("absorbed_mechanisms")
    if not isinstance(mechanisms, list):
        raise ValueError("diagnostic ledger mechanisms MUST be an array")
    if payload.get("absorbed_mechanism_count") != 61 or len(mechanisms) != 61:
        raise ValueError("diagnostic ledger mechanism count is incomplete")
    validated: list[Mapping[str, Any]] = []
    mechanism_ids: set[str] = set()
    source_set = set(source_commits)
    for mechanism in mechanisms:
        if not isinstance(mechanism, Mapping):
            raise ValueError("diagnostic ledger mechanism MUST be an object")
        mechanism_id = mechanism.get("id")
        if not isinstance(mechanism_id, str) or not _MECHANISM_ID.fullmatch(mechanism_id):
            raise ValueError("diagnostic ledger mechanism id is invalid")
        if mechanism_id in mechanism_ids:
            raise ValueError(f"duplicate diagnostic mechanism {mechanism_id!r}")
        mechanism_ids.add(mechanism_id)
        revisions = _commit_list(mechanism.get("source_commits"), field="mechanism commits")
        if not revisions or len(revisions) > _MAX_MECHANISM_COMMITS:
            raise ValueError("diagnostic mechanism commit count is outside limits")
        if len(set(revisions)) != len(revisions):
            raise ValueError("diagnostic mechanism source commits MUST be unique")
        if not set(revisions) <= source_set:
            raise ValueError("diagnostic mechanism references a revision outside the source set")
        axes = {axis: mechanism.get(axis) for axis in VALIDATION_AXES}
        if any(not isinstance(value, bool) for value in axes.values()):
            raise ValueError("diagnostic mechanism validation axes MUST be boolean")
        _validate_status(mechanism, axes)
        for field in (
            "source_hardening",
            "provider_validation_evidence",
            "azure_validation_evidence",
        ):
            value = mechanism.get(field)
            if value is not None and (
                not isinstance(value, str) or not value.strip() or len(value) > _MAX_TEXT_CHARS
            ):
                raise ValueError(f"diagnostic mechanism {field} is invalid")
        validated.append(mechanism)
    return DiagnosticLedger(
        source_set_sha256=source_digest,
        mechanisms=tuple(validated),
    )


def _commit_list(value: object, *, field: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or _SHA1.fullmatch(item) is None for item in value
    ):
        raise ValueError(f"diagnostic ledger {field} MUST contain full lowercase revisions")
    return list(value)


def _validate_status(mechanism: Mapping[str, Any], axes: Mapping[str, object]) -> None:
    status = mechanism.get("status")
    if status not in _ALLOWED_STATUSES:
        raise ValueError("diagnostic mechanism status is unsupported")
    semantic = axes["semantic_generalized"] is True
    operational = axes["operationalized"] is True
    if status == "rejected":
        if semantic or operational or not mechanism.get("source_hardening"):
            raise ValueError("rejected diagnostic mechanism has contradictory authority axes")
    elif status == "semantic_generalized" and not semantic:
        raise ValueError("semantic diagnostic mechanism has contradictory authority axes")
    elif status == "operationalized" and (not semantic or not operational):
        raise ValueError("operational diagnostic mechanism has contradictory authority axes")


__all__ = ["DiagnosticLedger", "VALIDATION_AXES", "validate_diagnostic_ledger"]
