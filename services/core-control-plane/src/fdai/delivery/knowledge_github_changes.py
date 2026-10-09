"""Governed knowledge read connections using the existing repository identity ledger."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime

import httpx
from fdai_github_app_auth.repository_reader import (
    GitHubApiRepositoryReader,
    GitHubRepositoryReader,
    GitHubRepositoryReadError,
)
from fdai_service_contracts.knowledge_github import GitHubKnowledgeChangeBody, GitHubKnowledgeSource

from fdai.delivery.persistence.state_store_code_security_repository import (
    CodeSecurityRepository,
    CodeSecurityRepositoryError,
    _audit,
    read_repository,
    repository_state_key,
    validate_ref,
)
from fdai.shared.providers.state_store import StateStore


async def apply_knowledge_change(
    store: StateStore,
    body: GitHubKnowledgeChangeBody,
    *,
    principal: str,
    request_id: str,
    reader: GitHubRepositoryReader | None = None,
) -> tuple[dict[str, object] | None, str | None]:
    """Validate before CAS; new read connections always start with scans disabled.

    The caller rechecks Owner authority. Existing scan permission is independent and preserved.
    Provider failures never replace prior evidence. Replay of the exact applied request is inert.
    """
    existing = await read_repository(store, body.repository_alias)
    if existing and existing.knowledge_source:
        if existing.knowledge_source.request_id == request_id:
            return _result(existing, body.action), None
    if (existing.revision if existing else 0) != body.expected_revision:
        return None, "repository_conflict"
    if body.action == "disconnect":
        if existing is None or existing.knowledge_source is None:
            return None, "repository_not_registered"
        updated = replace(
            existing,
            revision=existing.revision + 1,
            knowledge_source=existing.knowledge_source.model_copy(
                update={"knowledge_read_enabled": False, "request_id": request_id}
            ),
        )
    else:
        if body.location is None or body.credential_reference is None:
            return None, "request_malformed"
        if existing and (
            existing.location != body.location
            or (
                existing.knowledge_source is not None
                and existing.knowledge_source.credential_reference != body.credential_reference
            )
        ):
            return None, "repository_conflict"
        try:
            if reader is None:
                async with httpx.AsyncClient(trust_env=False) as client:
                    observation = await GitHubApiRepositoryReader(os.environ, client).verify(
                        body.location, body.credential_reference
                    )
            else:
                observation = await reader.verify(body.location, body.credential_reference)
            validate_ref(observation.default_branch)
            if (
                existing
                and existing.knowledge_source
                and existing.knowledge_source.repository_id != observation.repository_id
            ):
                return None, "repository_conflict"
            source = GitHubKnowledgeSource(
                credential_reference=body.credential_reference,
                knowledge_read_enabled=True,
                repository_id=observation.repository_id,
                private=observation.private,
                observed_commit=observation.commit,
                readme_digest=observation.readme_digest,
                observed_at=datetime.now(UTC).isoformat(),
                request_id=request_id,
            )
        except (GitHubRepositoryReadError, CodeSecurityRepositoryError, ValueError):
            return None, "source_unavailable"
        updated = (
            replace(existing, revision=existing.revision + 1, knowledge_source=source)
            if existing
            else CodeSecurityRepository(
                repository_alias=body.repository_alias,
                provider="github",
                location=body.location,
                default_ref=observation.default_branch,
                exposure="unknown",
                enabled=False,
                registered_at=source.observed_at,
                registered_by=principal,
                revision=1,
                knowledge_source=source,
            )
        )
    audit = {
        **_audit(
            updated, "knowledge_connected" if body.action == "connect" else "knowledge_disconnected"
        ),
        "actor": principal,
    }
    applied = (
        await store.compare_and_set_state_with_audit(
            repository_state_key(updated.repository_alias),
            updated.as_record(),
            expected_revision=body.expected_revision,
            audit_entry=audit,
        )
        if existing
        else await store.write_state_with_audit_if_absent(
            repository_state_key(updated.repository_alias), updated.as_record(), audit
        )
    )
    return (_result(updated, body.action), None) if applied else (None, "repository_conflict")


def _result(repository: CodeSecurityRepository, action: str) -> dict[str, object]:
    return {
        "action": action,
        "repository_alias": repository.repository_alias,
        "enabled": repository.enabled,
        "created": repository.revision == 1,
    }
