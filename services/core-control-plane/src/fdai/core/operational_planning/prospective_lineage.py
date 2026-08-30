"""Content-addressed Forseti envelope and materialization readiness contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal, Protocol, Self

from pydantic import Field, model_validator

from fdai.core.ontology_platform.functions import ontology_function_digest
from fdai.core.operational_planning.coordinator import SpecialistPlanningProjection
from fdai.core.operational_planning.hypothesis_lineage import OperationalProspectiveLineage
from fdai.core.operational_planning.kinetic_proposal import KineticActionProposal
from fdai.shared.contracts.models import ContractBase
from fdai.shared.providers.ontology_instance import normalize_object_record

_DIGEST = r"^sha256:[a-f0-9]{64}$"
_ID = r"^prospective-lineage:[a-f0-9]{64}$"


class ProspectiveLineage(ContractBase):
    """Forseti-owned immutable envelope for one pre-execution ontology subgraph."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    id: Annotated[str, Field(pattern=_ID)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=512)]
    operational_plan_id: Annotated[str, Field(pattern=r"^operational-plan:[a-f0-9]{64}$")]
    proposal_id: Annotated[str, Field(pattern=r"^kinetic-action-proposal:[a-f0-9]{64}$")]
    mutation_plan_digest: Annotated[str, Field(pattern=_DIGEST)]
    decision_case_id: Annotated[str, Field(min_length=1, max_length=512)]
    action_option_id: Annotated[str, Field(min_length=1, max_length=512)]
    expected_effect_ids: tuple[Annotated[str, Field(min_length=1, max_length=512)], ...]
    subgraph_digest: Annotated[str, Field(pattern=_DIGEST)]
    created_at: datetime
    producer_principal: Literal["Forseti"] = "Forseti"
    execution_authority: Literal[False] = False

    @classmethod
    def create(
        cls,
        *,
        lineage: OperationalProspectiveLineage,
        proposal: KineticActionProposal,
    ) -> Self:
        """Create an envelope whose identity covers the exact proposal and subgraph."""

        subgraph_digest = prospective_subgraph_digest(lineage)
        serialized = cls.model_construct(
            id="prospective-lineage:" + "0" * 64,
            schema_version="1.0.0",
            correlation_id=proposal.correlation_id,
            operational_plan_id=proposal.operational_plan_id,
            proposal_id=proposal.proposal_id,
            mutation_plan_digest=proposal.plan.digest,
            decision_case_id=lineage.decision_case.id,
            action_option_id=lineage.action_option.id,
            expected_effect_ids=tuple(item.id for item in lineage.expected_effects),
            subgraph_digest=subgraph_digest,
            created_at=proposal.created_at.astimezone(UTC),
            producer_principal="Forseti",
            execution_authority=False,
        ).model_dump(mode="json", exclude={"id"})
        digest = ontology_function_digest(serialized).removeprefix("sha256:")
        return cls.model_validate({**serialized, "id": f"prospective-lineage:{digest}"})

    @model_validator(mode="after")
    def _identity_matches(self) -> ProspectiveLineage:
        if self.created_at.tzinfo is None:
            raise ValueError("prospective lineage created_at MUST be timezone-aware")
        if (
            not self.expected_effect_ids
            or tuple(dict.fromkeys(self.expected_effect_ids)) != self.expected_effect_ids
        ):
            raise ValueError("prospective lineage expected effects MUST be non-empty and unique")
        material = self.model_dump(mode="json", exclude={"id"})
        expected = ontology_function_digest(material).removeprefix("sha256:")
        if self.id != f"prospective-lineage:{expected}":
            raise ValueError("prospective lineage identity does not match content")
        return self


@dataclass(frozen=True, slots=True)
class FinalizedProspectiveLineage:
    """Exact finalized plan, proposal, records, and publishable envelope."""

    projection: SpecialistPlanningProjection
    proposal: KineticActionProposal
    lineage: OperationalProspectiveLineage
    envelope: ProspectiveLineage


class ProspectiveLineageFinalizer(Protocol):
    async def finalize(
        self,
        projection: SpecialistPlanningProjection,
    ) -> FinalizedProspectiveLineage: ...


class ProspectiveLineageMaterializer(Protocol):
    async def materialize(self, envelope: ProspectiveLineage) -> bool: ...

    async def seal_saga(self, *, lineage_id: str, subgraph_digest: str) -> bool: ...


class ProspectiveLineageReadinessReader(Protocol):
    async def ready(self, proposal_id: str) -> bool: ...


def prospective_subgraph_digest(lineage: OperationalProspectiveLineage) -> str:
    """Digest normalized objects and links in deterministic lineage order."""

    objects = []
    for record in lineage.objects:
        normalized = normalize_object_record(record)
        objects.append(
            {
                "id": normalized.id,
                "object_type": normalized.object_type,
                "properties": dict(normalized.properties),
                "revision": normalized.revision,
            }
        )
    links = [
        {
            "link_type": link.link_type,
            "from_id": link.from_id,
            "to_id": link.to_id,
            "properties": dict(link.properties),
        }
        for link in lineage.links
    ]
    return ontology_function_digest({"objects": objects, "links": links})


__all__ = [
    "FinalizedProspectiveLineage",
    "ProspectiveLineage",
    "ProspectiveLineageFinalizer",
    "ProspectiveLineageMaterializer",
    "ProspectiveLineageReadinessReader",
    "prospective_subgraph_digest",
]
