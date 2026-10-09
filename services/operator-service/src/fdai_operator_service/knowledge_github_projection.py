"""Read-only knowledge connection projection; no GitHub identity or scan authorizer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from fdai_service_contracts.knowledge_github import GitHubKnowledgeSource
from pydantic import ValidationError

from fdai_operator_service.code_security_review_projection import (
    GAP_REPOSITORY_MALFORMED,
    GAP_TRUNCATED,
    _MalformedError,
    _repository,
)


def knowledge_github_projection(rows: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    """Render only typed, key-bound observations; malformed rows are explicit gaps."""
    sources: list[dict[str, object]] = []
    gaps: list[dict[str, object]] = []
    if len(rows) > 200:
        gaps.append({"reason_code": GAP_TRUNCATED})
    for row in rows[:200]:
        value = row.get("value")
        try:
            repository = _repository(row.get("key"), value)
            if not isinstance(value, Mapping):
                raise _MalformedError
            revision = value.get("revision")
            if type(revision) is not int or revision < 1:
                raise _MalformedError
            source = (
                GitHubKnowledgeSource.model_validate(value["knowledge_source"])
                if "knowledge_source" in value
                else None
            )
            sources.append(
                {
                    **repository,
                    "revision": revision,
                    "knowledge_source": (
                        source.model_dump(mode="json", exclude={"request_id"}) if source else None
                    ),
                }
            )
        except (_MalformedError, ValidationError):
            gaps.append({"reason_code": GAP_REPOSITORY_MALFORMED})
    sources.sort(key=lambda source: str(source["repository_alias"]))
    return {
        "sources": sources,
        "gaps": gaps,
        "complete": not gaps,
        "source": "postgresql:state_kv:code-security-repository",
        "indexed": False,
    }
