"""Immutable bounded HTML and SARIF artifacts for one accepted code-security review."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime

from fdai.shared.providers.state_store import StateStore

CODE_SECURITY_ARTIFACT_STATE_PREFIX = "runtime:code-security-issues:"
_ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_REVISION = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_MAX_ARTIFACT_BYTES = 900_000


class CodeSecurityArtifactConflictError(RuntimeError):
    """A different artifact set already exists for the accepted review."""


class CodeSecurityArtifactTooLargeError(ValueError):
    """The generated artifacts exceed the bounded state-store contract."""


def code_security_artifact_state_key(repository_alias: str, revision: str) -> str:
    if _ALIAS.fullmatch(repository_alias) is None or _REVISION.fullmatch(revision) is None:
        raise ValueError("code-security artifact identity is invalid")
    return f"{CODE_SECURITY_ARTIFACT_STATE_PREFIX}{repository_alias}:{revision}:artifacts"


def validate_code_security_artifacts(raw: Mapping[str, object]) -> dict[str, str]:
    if set(raw) != {"html", "sarif"}:
        raise ValueError("code-security artifacts must contain html and sarif")
    html = raw.get("html")
    sarif = raw.get("sarif")
    if not isinstance(html, str) or not html.startswith("<!doctype html>"):
        raise ValueError("code-security HTML artifact is invalid")
    if not isinstance(sarif, str):
        raise ValueError("code-security SARIF artifact is invalid")
    try:
        parsed = json.loads(sarif)
    except json.JSONDecodeError as exc:
        raise ValueError("code-security SARIF artifact is invalid") from exc
    if not isinstance(parsed, dict) or parsed.get("version") != "2.1.0":
        raise ValueError("code-security SARIF artifact is invalid")
    encoded = json.dumps({"html": html, "sarif": sarif}, ensure_ascii=False).encode()
    if len(encoded) > _MAX_ARTIFACT_BYTES:
        raise CodeSecurityArtifactTooLargeError(
            "code-security artifacts exceed the persistence bound"
        )
    return {"html": html, "sarif": sarif}


async def record_code_security_artifacts(
    store: StateStore,
    *,
    repository_alias: str,
    revision: str,
    review_digest: str,
    artifacts: Mapping[str, object],
    recorded_at: datetime | None = None,
) -> bool:
    if _DIGEST.fullmatch(review_digest) is None:
        raise ValueError("review_digest is invalid")
    validated = validate_code_security_artifacts(artifacts)
    key = code_security_artifact_state_key(repository_alias, revision)
    row = {
        "kind": "code-security-review-artifacts",
        "schema_version": "1.0.0",
        "repository_alias": repository_alias,
        "revision": revision,
        "review_digest": review_digest,
        "recorded_at": (recorded_at or datetime.now(UTC)).isoformat(),
        **validated,
    }
    created = await store.write_state_if_absent(key, row)
    if not created:
        existing = await store.read_state(key)
        comparable = {key: value for key, value in row.items() if key != "recorded_at"}
        stored = (
            {key: value for key, value in existing.items() if key != "recorded_at"}
            if existing is not None
            else None
        )
        if stored != comparable:
            raise CodeSecurityArtifactConflictError(
                f"different code-security artifacts already exist for {repository_alias}@{revision}"
            )
    return created


async def record_code_security_artifact_gap(
    store: StateStore,
    *,
    repository_alias: str,
    revision: str,
    review_digest: str,
    reason_code: str,
    recorded_at: datetime | None = None,
) -> bool:
    if _DIGEST.fullmatch(review_digest) is None or reason_code != "artifact_size_exceeded":
        raise ValueError("code-security artifact gap is invalid")
    key = code_security_artifact_state_key(repository_alias, revision)
    row = {
        "kind": "code-security-review-artifacts-unavailable",
        "schema_version": "1.0.0",
        "repository_alias": repository_alias,
        "revision": revision,
        "review_digest": review_digest,
        "recorded_at": (recorded_at or datetime.now(UTC)).isoformat(),
        "reason_code": reason_code,
    }
    created = await store.write_state_if_absent(key, row)
    if not created:
        existing = await store.read_state(key)
        comparable = {key: value for key, value in row.items() if key != "recorded_at"}
        stored = (
            {key: value for key, value in existing.items() if key != "recorded_at"}
            if existing is not None
            else None
        )
        if stored != comparable:
            raise CodeSecurityArtifactConflictError(
                f"different code-security artifacts already exist for {repository_alias}@{revision}"
            )
    return created


__all__ = [
    "CODE_SECURITY_ARTIFACT_STATE_PREFIX",
    "CodeSecurityArtifactConflictError",
    "CodeSecurityArtifactTooLargeError",
    "code_security_artifact_state_key",
    "record_code_security_artifacts",
    "record_code_security_artifact_gap",
    "validate_code_security_artifacts",
]
