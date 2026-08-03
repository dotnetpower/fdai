"""Provider-neutral contracts for blind ontology model council voting."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from fdai.shared.providers.ontology_council_receipt import CouncilOutcome
from fdai.shared.providers.ontology_council_validation import (
    require_bounded,
    require_digest,
    require_identifier,
    require_property_names,
    require_unique,
)

type CouncilScalar = str | int | float | bool | None

_PROPERTY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_MAX_TEXT = 16_384
_MAX_CONTEXT_ITEMS = 10_000


class CouncilDisposition(StrEnum):
    PROPOSE = "propose"
    UNSUPPORTED = "unsupported"
    ABSTAIN = "abstain"


class CouncilTargetKind(StrEnum):
    OBJECT = "object"
    LINK = "link"


class CouncilOperation(StrEnum):
    ADD = "add"
    UPDATE = "update"
    REMOVE = "remove"
    SUPERSEDE = "supersede"


@dataclass(frozen=True, slots=True)
class CouncilModelIdentity:
    publisher: str
    family: str
    version: str
    deployment: str
    binding: str
    fault_domain: str

    def __post_init__(self) -> None:
        require_bounded(self.publisher, "model publisher")
        require_bounded(self.family, "model family")
        require_bounded(self.version, "model version")
        require_bounded(self.deployment, "model deployment", maximum=200)
        require_bounded(self.binding, "model binding", maximum=200)
        require_bounded(self.fault_domain, "model fault domain")

    @property
    def digest(self) -> str:
        return _stable_digest(
            {
                "publisher": self.publisher,
                "family": self.family,
                "version": self.version,
                "deployment": self.deployment,
                "binding": self.binding,
                "fault_domain": self.fault_domain,
            }
        )


@dataclass(frozen=True, slots=True)
class CouncilProperty:
    name: str
    value: CouncilScalar

    def __post_init__(self) -> None:
        if _PROPERTY.fullmatch(self.name) is None:
            raise ValueError("council property name MUST use the bounded property syntax")
        if isinstance(self.value, str) and len(self.value) > 4096:
            raise ValueError("council property string MUST be bounded")
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError("council property float MUST be finite")
        if (
            isinstance(self.value, int)
            and not isinstance(self.value, bool)
            and abs(self.value) > 10**18
        ):
            raise ValueError("council property integer MUST fit the signed 64-bit envelope")


@dataclass(frozen=True, slots=True)
class CouncilSemanticFields:
    numbers: tuple[str, ...] = ()
    units: tuple[str, ...] = ()
    comparators: tuple[str, ...] = ()
    negated: bool = False
    effective_from: str | None = None
    effective_to: str | None = None

    def __post_init__(self) -> None:
        for label, values in (
            ("numbers", self.numbers),
            ("units", self.units),
            ("comparators", self.comparators),
        ):
            if len(values) > 64 or any(not value or len(value) > 64 for value in values):
                raise ValueError(f"council semantic {label} MUST be bounded")
        if type(self.negated) is not bool:
            raise ValueError("council semantic negated MUST be a boolean")
        for value in (self.effective_from, self.effective_to):
            if value is not None and (not value or len(value) > 64):
                raise ValueError("council semantic effective time MUST be bounded")


@dataclass(frozen=True, slots=True)
class CouncilObjectDeclaration:
    name: str
    properties: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.name, "object type")
        require_property_names(self.properties)


@dataclass(frozen=True, slots=True)
class CouncilLinkDeclaration:
    name: str
    from_type: str
    to_type: str
    properties: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.name, "link type")
        require_identifier(self.from_type, "link from type")
        require_identifier(self.to_type, "link to type")
        require_property_names(self.properties)


@dataclass(frozen=True, slots=True)
class CouncilEntity:
    identity: str
    object_type: str

    def __post_init__(self) -> None:
        require_identifier(self.identity, "entity identity")
        require_identifier(self.object_type, "entity object type")


@dataclass(frozen=True, slots=True)
class CouncilAlias:
    alias: str
    identity: str

    def __post_init__(self) -> None:
        require_bounded(self.alias, "entity alias", maximum=200)
        require_identifier(self.identity, "alias identity")


@dataclass(frozen=True, slots=True)
class CouncilClaimPacket:
    claim_id: str
    source_assertion: str
    source_ref: str
    source_lines: tuple[int, int]
    content_sha256: str
    citation_digest: str
    authority: str
    ontology_release: str
    graph_revision: str
    object_types: tuple[CouncilObjectDeclaration, ...]
    links: tuple[CouncilLinkDeclaration, ...]
    entities: tuple[CouncilEntity, ...]
    aliases: tuple[CouncilAlias, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.claim_id, "claim id")
        if not self.source_assertion or len(self.source_assertion) > _MAX_TEXT:
            raise ValueError("council source assertion MUST be bounded and non-empty")
        require_bounded(self.source_ref, "source ref", maximum=2048)
        start, end = self.source_lines
        if start < 1 or end < start:
            raise ValueError("council source lines MUST be a 1-based inclusive range")
        require_digest(self.content_sha256, "content digest")
        require_digest(self.citation_digest, "citation digest")
        if (
            hashlib.sha256(self.source_assertion.encode("utf-8")).hexdigest()
            != self.citation_digest
        ):
            raise ValueError("council citation digest MUST match the exact source assertion")
        require_bounded(self.authority, "authority")
        require_digest(self.ontology_release, "ontology release")
        require_bounded(self.graph_revision, "graph revision", maximum=200)
        for values in (self.object_types, self.links, self.entities, self.aliases):
            if len(values) > _MAX_CONTEXT_ITEMS:
                raise ValueError("council claim packet context exceeds the bounded limit")
        require_unique((item.name for item in self.object_types), "object declarations")
        require_unique((item.name for item in self.links), "link declarations")
        require_unique((item.identity for item in self.entities), "entities")
        object_names = {item.name for item in self.object_types}
        if any(
            item.from_type not in object_names or item.to_type not in object_names
            for item in self.links
        ):
            raise ValueError("council link declarations MUST reference packet object types")
        if any(item.object_type not in object_names for item in self.entities):
            raise ValueError("council entities MUST reference packet object types")
        entity_ids = {item.identity for item in self.entities}
        if any(item.identity not in entity_ids for item in self.aliases):
            raise ValueError("council aliases MUST reference packet entities")

    @property
    def digest(self) -> str:
        return _stable_digest(self)


@dataclass(frozen=True, slots=True)
class CouncilVote:
    model_identity: CouncilModelIdentity
    claim_id: str
    citation_digest: str
    disposition: CouncilDisposition
    operation: CouncilOperation | None = None
    target_kind: CouncilTargetKind | None = None
    target_type: str | None = None
    target_identity: str | None = None
    authority: str | None = None
    properties: tuple[CouncilProperty, ...] = ()
    from_identity: str | None = None
    to_identity: str | None = None
    semantics: CouncilSemanticFields = field(default_factory=CouncilSemanticFields)

    def __post_init__(self) -> None:
        require_identifier(self.claim_id, "vote claim id")
        require_digest(self.citation_digest, "vote citation digest")
        proposal_values = (
            self.operation,
            self.target_kind,
            self.target_type,
            self.target_identity,
            self.authority,
        )
        if self.disposition is CouncilDisposition.PROPOSE:
            if (
                self.operation is None
                or self.target_kind is None
                or self.target_type is None
                or self.target_identity is None
                or self.authority is None
            ):
                raise ValueError("propose vote MUST include the complete target shape")
            require_identifier(self.target_type, "vote target type")
            require_identifier(self.target_identity, "vote target identity")
            require_bounded(self.authority, "vote authority")
            names = tuple(item.name for item in self.properties)
            if len(names) > 64 or names != tuple(sorted(names)) or len(names) != len(set(names)):
                raise ValueError("vote properties MUST be unique and sorted")
            if self.target_kind is CouncilTargetKind.LINK:
                if self.from_identity is None or self.to_identity is None:
                    raise ValueError("link vote MUST include both endpoint identities")
                require_identifier(self.from_identity, "vote from identity")
                require_identifier(self.to_identity, "vote to identity")
            elif self.from_identity is not None or self.to_identity is not None:
                raise ValueError("object vote MUST NOT include link endpoint identities")
        elif (
            any(value is not None for value in proposal_values)
            or self.properties
            or self.from_identity
            or self.to_identity
            or self.semantics != CouncilSemanticFields()
        ):
            raise ValueError("non-proposal vote MUST NOT include proposal fields")

    @property
    def digest(self) -> str:
        return _stable_digest(self)

    @property
    def semantic_fingerprint(self) -> str | None:
        if self.disposition is not CouncilDisposition.PROPOSE:
            return None
        return _stable_digest(
            {
                "claim_id": self.claim_id,
                "citation_digest": self.citation_digest,
                "operation": self.operation,
                "target_kind": self.target_kind,
                "target_type": self.target_type,
                "target_identity": self.target_identity,
                "authority": self.authority,
                "properties": self.properties,
                "from_identity": self.from_identity,
                "to_identity": self.to_identity,
                "semantics": self.semantics,
            }
        )


@dataclass(frozen=True, slots=True)
class CouncilFieldDifference:
    field_name: str
    value_digests: tuple[str, ...]

    def __post_init__(self) -> None:
        if _PROPERTY.fullmatch(self.field_name) is None:
            raise ValueError("disputed field name MUST use the bounded property syntax")
        if not 2 <= len(self.value_digests) <= 3:
            raise ValueError("disputed field MUST contain two or three value digests")
        require_unique(self.value_digests, "disputed field value digests")
        for digest in self.value_digests:
            require_digest(digest, "disputed field value digest")


@dataclass(frozen=True, slots=True)
class CouncilDispute:
    claim_id: str
    packet_digest: str
    initial_vote_digests: tuple[str, str, str]
    differences: tuple[CouncilFieldDifference, ...]

    def __post_init__(self) -> None:
        require_identifier(self.claim_id, "dispute claim id")
        require_digest(self.packet_digest, "dispute packet digest")
        if len(self.initial_vote_digests) != 3:
            raise ValueError("council dispute MUST contain three initial vote digests")
        for digest in self.initial_vote_digests:
            require_digest(digest, "initial vote digest")
        if not self.differences or len(self.differences) > 32:
            raise ValueError("council dispute MUST contain bounded field differences")
        require_unique((item.field_name for item in self.differences), "disputed fields")


@runtime_checkable
class OntologyCouncilModel(Protocol):
    identity: CouncilModelIdentity

    async def blind_vote(self, packet: CouncilClaimPacket) -> CouncilVote: ...

    async def revise_vote(
        self,
        packet: CouncilClaimPacket,
        dispute: CouncilDispute,
    ) -> CouncilVote: ...


def _stable_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            default=lambda item: (
                item.value if isinstance(item, StrEnum) else _dataclass_payload(item)
            ),
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _dataclass_payload(value: object) -> dict[str, object]:
    fields = getattr(value, "__dataclass_fields__", None)
    if fields is None:
        raise TypeError(f"unsupported council digest value: {type(value).__name__}")
    return {name: getattr(value, name) for name in fields}


__all__ = [
    "CouncilAlias",
    "CouncilClaimPacket",
    "CouncilDisposition",
    "CouncilDispute",
    "CouncilFieldDifference",
    "CouncilLinkDeclaration",
    "CouncilModelIdentity",
    "CouncilObjectDeclaration",
    "CouncilOperation",
    "CouncilOutcome",
    "CouncilProperty",
    "CouncilScalar",
    "CouncilSemanticFields",
    "CouncilTargetKind",
    "CouncilVote",
    "OntologyCouncilModel",
]
