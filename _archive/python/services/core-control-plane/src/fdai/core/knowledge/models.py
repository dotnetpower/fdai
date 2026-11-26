"""Knowledge + code-access registration models (SRE-agent slide 8).

Slide 8 is the operator **configuration surface** that registers the two
context inputs the SRE Agent grounds on: free-form Knowledge Sources and
Code Access. FDAI already ships the retrieval seams -
:class:`~fdai.shared.providers.knowledge.KnowledgeSource` and
:class:`~fdai.shared.providers.change_feed.ChangeFeed`. This module is the
missing registration layer that records **what** an operator connected, by
whom, and when - without ever storing a secret inline.

Both records are CSP/VCS-neutral and customer-agnostic: a code repo carries
a ``secret_ref`` handle into the secret store, never a token.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class KnowledgeSourceKind(StrEnum):
    """The kind of a registered knowledge document (mirrors the demo)."""

    UPLOAD = "upload"
    WIKI = "wiki"
    WEB_PAGE = "web_page"
    ARCHITECTURE = "architecture"
    BEST_PRACTICE = "best_practice"
    WORKLOAD_DOC = "workload_doc"
    RUNBOOK = "runbook"


class CodeRepoProvider(StrEnum):
    """A supported code-access provider."""

    GITHUB = "github"
    AZURE_DEVOPS = "azure_devops"


@dataclass(frozen=True, slots=True)
class RegisteredDocument:
    """One knowledge document an operator registered and indexed.

    ``chunk_count`` is how many retrievable chunks the ingest produced -
    ``0`` means the source indexed nothing (empty / unsupported) and the
    console should surface it as a no-op registration, not a success.
    """

    doc_id: str
    source_ref: str
    kind: KnowledgeSourceKind
    title: str
    chunk_count: int
    registered_by: str
    registered_at: datetime
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.doc_id or not self.doc_id.strip():
            raise ValueError("RegisteredDocument.doc_id MUST be non-empty")
        if not self.source_ref or not self.source_ref.strip():
            raise ValueError("RegisteredDocument.source_ref MUST be non-empty")
        if not self.title or not self.title.strip():
            raise ValueError("RegisteredDocument.title MUST be non-empty")
        if not self.registered_by or not self.registered_by.strip():
            raise ValueError("RegisteredDocument.registered_by MUST be non-empty")
        if self.registered_at.utcoffset() is None:
            raise ValueError("RegisteredDocument.registered_at MUST be timezone-aware")
        if isinstance(self.chunk_count, bool) or self.chunk_count < 0:
            raise ValueError("RegisteredDocument.chunk_count MUST be non-negative")


@dataclass(frozen=True, slots=True)
class CodeRepoRegistration:
    """A registered code repository (connection descriptor, no secret).

    ``secret_ref`` is a handle resolved through the secret provider at read
    time - never a raw token. ``repository`` is ``owner/name`` shaped so it
    maps onto the GitHub / Azure DevOps change-feed adapters directly.
    """

    repo_id: str
    provider: CodeRepoProvider
    repository: str
    default_branch: str
    registered_by: str
    registered_at: datetime
    secret_ref: str | None = None
    enabled: bool = True
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.repo_id or not self.repo_id.strip():
            raise ValueError("CodeRepoRegistration.repo_id MUST be non-empty")
        owner, sep, name = self.repository.strip().partition("/")
        if not sep or not owner.strip() or not name.strip() or "/" in name.strip():
            raise ValueError("CodeRepoRegistration.repository MUST be 'owner/name' shaped")
        if not self.default_branch or not self.default_branch.strip():
            raise ValueError("CodeRepoRegistration.default_branch MUST be non-empty")
        if not self.registered_by or not self.registered_by.strip():
            raise ValueError("CodeRepoRegistration.registered_by MUST be non-empty")
        if self.registered_at.utcoffset() is None:
            raise ValueError("CodeRepoRegistration.registered_at MUST be timezone-aware")
        if not isinstance(self.enabled, bool):
            raise ValueError("CodeRepoRegistration.enabled MUST be a boolean")


__all__ = [
    "CodeRepoProvider",
    "CodeRepoRegistration",
    "KnowledgeSourceKind",
    "RegisteredDocument",
]
