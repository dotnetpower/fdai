"""Handover-bootstrap consumer and draft-result storage."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from fdai.core.stewardship.handover_bootstrap import (
    DocumentKind,
    DraftOutcome,
    ExtractedMapping,
    HandoverBootstrapper,
    HandoverDocument,
    MappingSource,
    PersonRef,
    SourceSpan,
    StewardMapDraft,
    render_draft_yaml,
)
from fdai.core.stewardship.model import Responsibility, StewardKind
from fdai.shared.contracts import DocumentEnvelope, DocumentPurpose, UploadSession
from fdai.shared.providers import DocumentNotFoundError
from fdai.shared.providers.state_store import StateStore

if TYPE_CHECKING:
    from fdai.delivery.stewardship.governance import HandoverDraftGovernance

_KEY_PREFIX = "handover_draft:"


@dataclass(frozen=True, slots=True)
class HandoverDraftArtifact:
    upload_id: UUID
    document_id: UUID
    version_id: UUID
    draft: StewardMapDraft
    yaml: str

    def to_dict(self) -> dict[str, object]:
        return {
            "upload_id": str(self.upload_id),
            "document_id": str(self.document_id),
            "version_id": str(self.version_id),
            "draft": self.draft.to_dict(),
            "yaml": self.yaml,
        }


class HandoverDraftReader(Protocol):
    async def get(self, upload_id: UUID) -> HandoverDraftArtifact: ...


class HandoverDraftStore(HandoverDraftReader, Protocol):
    async def put(self, artifact: HandoverDraftArtifact) -> None: ...


class InMemoryHandoverDraftStore:
    def __init__(self) -> None:
        self._items: dict[UUID, HandoverDraftArtifact] = {}

    async def put(self, artifact: HandoverDraftArtifact) -> None:
        self._items[artifact.upload_id] = artifact

    async def get(self, upload_id: UUID) -> HandoverDraftArtifact:
        try:
            return self._items[upload_id]
        except KeyError as exc:
            raise DocumentNotFoundError("handover draft was not found") from exc


class StateStoreHandoverDraftStore:
    """Durable handover draft projection over the injected StateStore."""

    def __init__(self, *, state_store: StateStore) -> None:
        self._state_store = state_store

    async def put(self, artifact: HandoverDraftArtifact) -> None:
        await self._state_store.write_state(
            f"{_KEY_PREFIX}{artifact.upload_id}",
            artifact.to_dict(),
        )

    async def get(self, upload_id: UUID) -> HandoverDraftArtifact:
        raw = await self._state_store.read_state(f"{_KEY_PREFIX}{upload_id}")
        if raw is None:
            raise DocumentNotFoundError("handover draft was not found")
        try:
            return _artifact_from_mapping(raw)
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("durable handover draft is malformed") from exc


class HandoverBootstrapConsumer:
    purpose = DocumentPurpose.HANDOVER_BOOTSTRAP

    def __init__(
        self,
        *,
        bootstrapper: HandoverBootstrapper,
        store: HandoverDraftStore,
        governance: HandoverDraftGovernance | None = None,
    ) -> None:
        self._bootstrapper = bootstrapper
        self._store = store
        self._governance = governance

    async def consume(
        self, *, session: UploadSession, envelope: DocumentEnvelope
    ) -> tuple[str, ...]:
        document = HandoverDocument(
            doc_id=str(envelope.document_id),
            kind=_document_kind(session.source_name),
            title=session.source_name,
            text="\n".join(unit.text for unit in envelope.units),
        )
        draft = await self._bootstrapper.bootstrap((document,))
        artifact = HandoverDraftArtifact(
            upload_id=session.upload_id,
            document_id=envelope.document_id,
            version_id=envelope.version_id,
            draft=draft,
            yaml=render_draft_yaml(draft),
        )
        await self._store.put(artifact)
        if self._governance is not None:
            await self._governance.propose(artifact=artifact, actor_oid=session.actor_id)
        return draft.warnings


def _document_kind(source_name: str) -> DocumentKind:
    lowered = source_name.casefold()
    if "raci" in lowered:
        return DocumentKind.RACI
    if "on-call" in lowered or "on_call" in lowered:
        return DocumentKind.ON_CALL
    if "org" in lowered:
        return DocumentKind.ORG_CHART
    if "runbook" in lowered:
        return DocumentKind.RUNBOOK
    if "handover" in lowered:
        return DocumentKind.HANDOVER_MEMO
    return DocumentKind.OTHER


def _artifact_from_mapping(raw: Mapping[str, object]) -> HandoverDraftArtifact:
    draft_raw = _mapping(raw["draft"])
    return HandoverDraftArtifact(
        upload_id=UUID(str(raw["upload_id"])),
        document_id=UUID(str(raw["document_id"])),
        version_id=UUID(str(raw["version_id"])),
        draft=StewardMapDraft(
            version=_int(draft_raw["version"]),
            outcome=DraftOutcome(str(draft_raw["outcome"])),
            mappings=_mappings(draft_raw.get("mappings")),
            abstained=_mappings(draft_raw.get("abstained")),
            unresolved_people=_people(draft_raw.get("unresolved_people")),
            unmapped_agents=_strings(draft_raw.get("unmapped_agents")),
            warnings=_strings(draft_raw.get("warnings")),
        ),
        yaml=str(raw["yaml"]),
    )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("expected mapping")
    return value


def _mappings(value: object) -> tuple[ExtractedMapping, ...]:
    if not isinstance(value, list):
        raise TypeError("expected mapping list")
    out: list[ExtractedMapping] = []
    for item in value:
        raw = _mapping(item)
        citations_raw = raw.get("citations")
        if not isinstance(citations_raw, list):
            raise TypeError("expected citation list")
        citations = tuple(
            SourceSpan(
                doc_id=str(_mapping(citation)["doc_id"]),
                line=_int(_mapping(citation)["line"]),
                quote=str(_mapping(citation)["quote"]),
            )
            for citation in citations_raw
        )
        out.append(
            ExtractedMapping(
                agent_name=str(raw["agent_name"]),
                person=_person(raw["person"]),
                responsibility=Responsibility(str(raw["responsibility"])),
                confidence=_float(raw["confidence"]),
                source=MappingSource(str(raw["source"])),
                citations=citations,
                rationale=str(raw.get("rationale") or ""),
            )
        )
    return tuple(out)


def _people(value: object) -> tuple[PersonRef, ...]:
    if not isinstance(value, list):
        raise TypeError("expected person list")
    return tuple(_person(item) for item in value)


def _person(value: object) -> PersonRef:
    raw = _mapping(value)
    oid = raw.get("oid")
    return PersonRef(
        display_name=str(raw["display_name"]),
        kind=StewardKind(str(raw["kind"])),
        oid=str(oid) if oid is not None else None,
    )


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise TypeError("expected string list")
    return tuple(value)


def _int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("expected integer")
    return value


def _float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("expected number")
    return float(value)


__all__ = [
    "HandoverBootstrapConsumer",
    "HandoverDraftArtifact",
    "HandoverDraftReader",
    "HandoverDraftStore",
    "InMemoryHandoverDraftStore",
    "StateStoreHandoverDraftStore",
]
