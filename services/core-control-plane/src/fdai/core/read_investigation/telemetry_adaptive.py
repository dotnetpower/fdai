"""Production adapters from telemetry recipes to the adaptive investigation loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from fdai_service_contracts.ontology_query import (
    OntologyQueryNode,
    OntologyQueryPlan,
    QueryNodeKind,
    canonical_json,
    content_digest,
)

from fdai.core.ontology_platform.query_execution import OntologyQueryPlanExecutor
from fdai.core.ontology_platform.query_manifest import QueryManifest
from fdai.core.ontology_platform.query_telemetry_handlers import (
    TELEMETRY_RECIPE_ARGUMENT_SCHEMA,
    TelemetryRecipeNodeHandler,
)
from fdai.core.ontology_platform.query_verification import OntologyQueryPlanVerifier
from fdai.core.rca.discrimination import (
    ExpectedObservationOutcome,
    HypothesisDiscriminationFrame,
    HypothesisOutcomePrediction,
    build_discriminating_observation_candidate,
)
from fdai.core.rca.telemetry_evidence import (
    TelemetryEvidenceDisposition,
    TelemetryEvidenceNeed,
    TelemetryEvidenceProvider,
    TelemetryEvidenceReceipt,
    build_telemetry_evidence_need,
)
from fdai.core.rca.telemetry_evidence_codec import telemetry_evidence_need_to_mapping
from fdai.core.rca.telemetry_recipes import (
    DEFAULT_TELEMETRY_RECIPE_CATALOG,
    ReviewedTelemetryRecipeCatalog,
)
from fdai.core.rca.telemetry_tool import TelemetryEvidenceRecipeTool

from .adaptive import (
    AdaptiveHypothesisReviser,
    AdaptiveRoundProposal,
    AdaptiveRoundSource,
    VerifiedObservationGateway,
)
from .adaptive_contract import (
    AdaptiveInvestigationDisposition,
    AdaptiveObservationExecution,
    AdaptiveQueryAuthorityContext,
    HypothesisRevisionSet,
    build_hypothesis_revision_set,
    build_verified_observation_plan_binding,
)
from .telemetry_projection import (
    AdaptiveTelemetryEvidenceResult,
    adaptive_telemetry_evidence_result,
)
from .telemetry_routing import (
    build_initial_telemetry_frame,
    telemetry_hypothesis_id,
    telemetry_mechanisms_for_event,
)

TELEMETRY_ADAPTIVE_SCORER_VERSION: Final[str] = "telemetry-receipt-reviser-v1"
TELEMETRY_ADAPTIVE_PURPOSE: Final[str] = "operations-review"
_RECEIPT_REF_PREFIX = "telemetry-receipt:"


class TelemetryAdaptiveRoundSource(AdaptiveRoundSource):
    """Map each active telemetry hypothesis to one exact verified recipe plan."""

    def __init__(
        self,
        *,
        manifest: QueryManifest,
        principal_scope_digest: str,
        resource_ref: str,
        catalog: ReviewedTelemetryRecipeCatalog = DEFAULT_TELEMETRY_RECIPE_CATALOG,
        maximum_workspace_routes: int = 4,
    ) -> None:
        if not 1 <= maximum_workspace_routes <= 4:
            raise ValueError("maximum_workspace_routes MUST be in [1, 4]")
        self._manifest = manifest
        self._scope_digest = principal_scope_digest
        self._resource_ref = resource_ref
        self._catalog = catalog
        self._maximum_workspace_routes = maximum_workspace_routes
        self._recipes_by_hypothesis = {
            telemetry_hypothesis_id(recipe.mechanism): recipe for recipe in catalog.recipes
        }

    async def propose(
        self,
        frame: HypothesisDiscriminationFrame,
    ) -> AdaptiveRoundProposal:
        candidates = []
        bindings = []
        for hypothesis_id in frame.active_hypothesis_ids:
            recipe = self._recipes_by_hypothesis.get(hypothesis_id)
            if recipe is None:
                raise ValueError("active telemetry hypothesis has no reviewed recipe")
            reserved_cost = recipe.estimated_cost_units * self._maximum_workspace_routes
            need = build_telemetry_evidence_need(
                incident_id=frame.incident_id,
                resource_ref=self._resource_ref,
                evidence_cutoff=frame.evidence_cutoff,
                recipe=recipe,
                max_query_count=self._maximum_workspace_routes,
                max_cost_units=reserved_cost,
                idempotency_key="telemetry-query:"
                + content_digest(
                    {
                        "frame_digest": frame.frame_digest,
                        "recipe_id": recipe.recipe_id,
                        "recipe_version": recipe.version,
                    }
                ).removeprefix("sha256:"),
            )
            plan = _telemetry_plan(frame, need, self._manifest)
            binding = build_verified_observation_plan_binding(
                frame_digest=frame.frame_digest,
                plan=plan,
                manifest=self._manifest,
                principal_scope_digest=self._scope_digest,
                cost_units=reserved_cost,
            )
            candidate = build_discriminating_observation_candidate(
                frame=frame,
                observation_ref=f"telemetry-recipe:{recipe.recipe_id}@{recipe.version}",
                verified_query_receipt_digest=binding.verification_receipt_digest,
                cost_units=reserved_cost,
                predictions=tuple(
                    HypothesisOutcomePrediction(
                        hypothesis_id=active_id,
                        outcome=(
                            ExpectedObservationOutcome.SUPPORTS
                            if active_id == hypothesis_id
                            else ExpectedObservationOutcome.NEUTRAL
                        ),
                    )
                    for active_id in frame.active_hypothesis_ids
                ),
            )
            candidates.append(candidate)
            bindings.append(binding)
        return AdaptiveRoundProposal(
            frame_digest=frame.frame_digest,
            candidates=tuple(candidates),
            bindings=tuple(bindings),
        )


class TelemetryAdaptiveHypothesisReviser(AdaptiveHypothesisReviser):
    """Apply complete telemetry receipts to Forseti's active hypothesis set."""

    def __init__(
        self,
        *,
        tool: TelemetryEvidenceRecipeTool,
        catalog: ReviewedTelemetryRecipeCatalog = DEFAULT_TELEMETRY_RECIPE_CATALOG,
    ) -> None:
        self._tool = tool
        self._catalog = catalog

    async def revise(
        self,
        *,
        frame: HypothesisDiscriminationFrame,
        execution: AdaptiveObservationExecution,
    ) -> HypothesisRevisionSet:
        receipt_ref, receipt = self._receipt(execution)
        active = frame.active_hypothesis_ids
        revised: tuple[str, ...]
        complete = receipt.complete and not receipt.truncated
        if receipt.disposition is TelemetryEvidenceDisposition.COMPLETE:
            recipe = self._catalog.get(receipt.recipe_id, receipt.recipe_version)
            selected = telemetry_hypothesis_id(recipe.mechanism)
            if selected not in active:
                raise ValueError("telemetry receipt mechanism is absent from the active set")
            expected_fact = f"mechanism:{recipe.mechanism.value}"
            mechanism_facts = tuple(
                item for item in receipt.fact_tokens if item.startswith("mechanism:")
            )
            if mechanism_facts != (expected_fact,):
                raise ValueError("telemetry receipt mechanism facts do not match its recipe")
            revised = (selected,)
            disposition = AdaptiveInvestigationDisposition.CONVERGED
        elif receipt.disposition is TelemetryEvidenceDisposition.COMPLETE_NO_DATA:
            recipe = self._catalog.get(receipt.recipe_id, receipt.recipe_version)
            if not recipe.supports_no_data_refutation:
                revised = active
                disposition = AdaptiveInvestigationDisposition.HELD
                complete = False
            else:
                excluded = telemetry_hypothesis_id(recipe.mechanism)
                if excluded not in active:
                    raise ValueError("telemetry no-data receipt is absent from the active set")
                revised = tuple(item for item in active if item != excluded)
                if not revised:
                    disposition = AdaptiveInvestigationDisposition.ALL_REFUTED
                elif len(revised) == 1:
                    disposition = AdaptiveInvestigationDisposition.HELD
                else:
                    disposition = AdaptiveInvestigationDisposition.CONTINUE
        else:
            revised = active
            disposition = AdaptiveInvestigationDisposition.HELD
            complete = False
        active_set_digest = content_digest(
            {
                "prior_active_set_receipt_digest": frame.active_set_receipt_digest,
                "observation_result_digest": execution.result_digest,
                "receipt_digest": receipt.receipt_digest,
                "active_hypothesis_ids": revised,
                "disposition": disposition.value,
                "scorer_version": TELEMETRY_ADAPTIVE_SCORER_VERSION,
            }
        )
        return build_hypothesis_revision_set(
            prior_active_set_receipt_digest=frame.active_set_receipt_digest,
            prior_frame_digest=frame.frame_digest,
            observation_result_digest=execution.result_digest,
            scorer_version=TELEMETRY_ADAPTIVE_SCORER_VERSION,
            graph_revision=frame.graph_revision,
            evidence_cutoff=frame.evidence_cutoff,
            active_hypothesis_ids=revised,
            active_set_receipt_digest=active_set_digest,
            evidence_refs=(receipt_ref,),
            complete=complete,
            truncated=receipt.truncated,
            disposition=disposition,
        )

    def _receipt(
        self,
        execution: AdaptiveObservationExecution,
    ) -> tuple[str, TelemetryEvidenceReceipt]:
        refs = tuple(
            item for item in execution.evidence_refs if item.startswith(_RECEIPT_REF_PREFIX)
        )
        if len(refs) != 1:
            raise ValueError("adaptive telemetry execution requires one receipt reference")
        digest = refs[0].removeprefix(_RECEIPT_REF_PREFIX)
        receipt = self._tool.receipt(digest)
        if receipt is None:
            raise ValueError("adaptive telemetry receipt is not retained")
        return refs[0], receipt


@dataclass(frozen=True, slots=True)
class TelemetryAdaptiveBindings:
    """Concrete adapters consumed by ``AdaptiveInvestigationRuntime``."""

    round_source: TelemetryAdaptiveRoundSource
    reviser: TelemetryAdaptiveHypothesisReviser
    gateway: VerifiedObservationGateway
    tool: TelemetryEvidenceRecipeTool


def build_telemetry_adaptive_bindings(
    *,
    provider: TelemetryEvidenceProvider,
    manifest: QueryManifest,
    principal_scope_digest: str,
    resource_ref: str,
    catalog: ReviewedTelemetryRecipeCatalog = DEFAULT_TELEMETRY_RECIPE_CATALOG,
) -> TelemetryAdaptiveBindings:
    """Compose the verified query path for one exact resource investigation."""

    tool = TelemetryEvidenceRecipeTool(provider=provider, catalog=catalog)
    verifier = OntologyQueryPlanVerifier(
        available_kinds=(QueryNodeKind.TELEMETRY_RECIPE,),
        extension_argument_schemas={
            QueryNodeKind.TELEMETRY_RECIPE: TELEMETRY_RECIPE_ARGUMENT_SCHEMA
        },
    )
    executor = OntologyQueryPlanExecutor(
        handlers={QueryNodeKind.TELEMETRY_RECIPE: TelemetryRecipeNodeHandler(tool)},
        max_concurrency=1,
    )
    authority = AdaptiveQueryAuthorityContext(
        manifest=manifest,
        principal_scope_digest=principal_scope_digest,
        caller_role=manifest.principal_role.value,
        purpose=TELEMETRY_ADAPTIVE_PURPOSE,
    )
    return TelemetryAdaptiveBindings(
        round_source=TelemetryAdaptiveRoundSource(
            manifest=manifest,
            principal_scope_digest=principal_scope_digest,
            resource_ref=resource_ref,
            catalog=catalog,
        ),
        reviser=TelemetryAdaptiveHypothesisReviser(tool=tool, catalog=catalog),
        gateway=VerifiedObservationGateway(
            verifier=verifier,
            executor=executor,
            authority=authority,
        ),
        tool=tool,
    )


def _telemetry_plan(
    frame: HypothesisDiscriminationFrame,
    need: TelemetryEvidenceNeed,
    manifest: QueryManifest,
) -> OntologyQueryPlan:
    arguments = {"need": telemetry_evidence_need_to_mapping(need)}
    node = OntologyQueryNode(
        node_id="telemetry",
        kind=QueryNodeKind.TELEMETRY_RECIPE,
        arguments_json=canonical_json(arguments),
        output_kind="telemetry.evidence",
    )
    material = {
        "schema_version": "1.0.0",
        "ontology_release_digest": manifest.release_digest,
        "semantic_catalog_digest": manifest.manifest_digest,
        "problem_frame_digest": frame.frame_digest,
        "purpose": TELEMETRY_ADAPTIVE_PURPOSE,
        "caller_role": manifest.principal_role.value,
        "nodes": [node.model_dump(mode="json")],
        "output_node_ids": ("telemetry",),
        "execution_authority": False,
    }
    return OntologyQueryPlan(
        ontology_release_digest=manifest.release_digest,
        semantic_catalog_digest=manifest.manifest_digest,
        problem_frame_digest=frame.frame_digest,
        purpose=TELEMETRY_ADAPTIVE_PURPOSE,
        caller_role=manifest.principal_role.value,
        nodes=(node,),
        output_node_ids=("telemetry",),
        plan_digest=content_digest(material),
    )


__all__ = [
    "TELEMETRY_ADAPTIVE_PURPOSE",
    "AdaptiveTelemetryEvidenceResult",
    "adaptive_telemetry_evidence_result",
    "TELEMETRY_ADAPTIVE_SCORER_VERSION",
    "TelemetryAdaptiveBindings",
    "TelemetryAdaptiveHypothesisReviser",
    "TelemetryAdaptiveRoundSource",
    "build_initial_telemetry_frame",
    "build_telemetry_adaptive_bindings",
    "telemetry_hypothesis_id",
    "telemetry_mechanisms_for_event",
]
