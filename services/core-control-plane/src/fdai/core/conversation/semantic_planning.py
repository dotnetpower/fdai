"""Schema-constrained semantic planning for ordinary-language read questions.

The model proposes meaning and typed nodes from the whole bounded turn. Core
rebuilds every identity, verifies the exact principal manifest, and grants no
execution authority. No phrase, regex, or keyword selects a query capability.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from fdai_service_contracts.ontology_query import (
    OntologyQueryPlan,
    QueryNodeKind,
    SemanticOperation,
    SemanticProblemFrame,
)
from pydantic import ValidationError

from fdai.core.ontology_platform import (
    OntologyQueryPlanVerifier,
    QueryManifest,
)
from fdai.core.ontology_platform.incident_queries import (
    INCIDENT_EVIDENCE_FUNCTION_NAME,
    INCIDENT_EVIDENCE_MAX_RECORDS,
)

from .intent_graph import build_intent_graph
from .semantic_activity_planning import compile_target_activity_plan
from .semantic_current_state_planning import compile_target_current_state_plan
from .semantic_error_activity_planning import compile_target_error_activity_plan
from .semantic_health_planning import compile_target_health_plan
from .semantic_impact_planning import compile_target_impact_plan
from .semantic_investigation_planning import (
    InvestigationClarificationRequiredError,
    compile_investigation_plan,
)
from .semantic_planning_cascade import ProposalRejectedError, SemanticPlanningCascade
from .semantic_planning_frame import (
    build_semantic_frame as _build_frame,
)
from .semantic_planning_frame import (
    resolve_incident_reference as _resolve_incident_reference,
)
from .semantic_planning_frame import (
    resolve_principal_scope_evidence_subject as _resolve_principal_scope_evidence_subject,
)
from .semantic_planning_models import (
    BoundIncident,
    CompleteManifestSelector,
    QueryManifestProvider,
    QueryNodeProposal,
    QueryPlanProposal,
    SemanticDescriptorSelector,
    SemanticFrameProposal,
    SemanticOutputShape,
    SemanticPlanningDisposition,
    SemanticPlanningModel,
    SemanticPlanningOutcome,
)
from .semantic_planning_support import (
    _MAX_DESCRIPTORS,
    _bounded_context,
    _build_plan,
    _clarification,
    _investigation_clarification,
    _investigation_windows,
    _outcome,
    _plan_node_summary,
    _refresh_object_set_cutoffs,
    _validated_descriptors,
    _validated_metric_concepts,
)
from .semantic_planning_value_filters import ground_stated_value_filters
from .session import Principal, Turn

_LOGGER = logging.getLogger(__name__)

_SAFE_VALIDATION_REASONS = frozenset(
    {
        "investigation declaration is absent or ambiguous",
        "investigation target has no readable properties",
        "investigation relationship direction is invalid",
        "investigation relationship path endpoint does not compose",
        "investigation relationship path is empty",
        "investigation query side is absent or ambiguous",
        "query plan output_node_ids MUST reference declared nodes",
        "query extension arguments violate their registered schema",
        "metric concept is absent from the reviewed registry",
        "metric_scope_series MUST read one scoped query.table",
        "metric_scope_series dependency MUST be a scoped query.table",
        "relationship traversal requires one entity dependency",
        "relationship traversal source MUST be an object_set table",
        "relationship traversal target is absent from the manifest",
        "relationship traversal LinkType is absent from the manifest",
        "relationship traversal source endpoint type does not match",
        "relationship traversal target endpoint type is invalid",
        "relationship traversal target endpoint type does not match",
        "function dependencies MUST all have argument bindings",
        "function node omits required arguments",
        "function node supplies unknown arguments",
        "query node arguments do not match the closed schema",
    }
)

_INCIDENT_EVIDENCE_FUNCTION = INCIDENT_EVIDENCE_FUNCTION_NAME
_INCIDENT_EVIDENCE_NODE_ID = "bound_incident_evidence"


def _safe_validation_reason(exc: ValidationError | TypeError | ValueError) -> str:
    reason = str(exc)
    if reason in _SAFE_VALIDATION_REASONS:
        return reason
    if reason.startswith("query node kind "):
        return "query node kind is unavailable or has no verifier schema"
    return "validation_reason_not_allowlisted"


class SemanticPlanningService:
    """Build a T1 proposal and escalate only a failed proposal to T2 verification."""

    def __init__(
        self,
        *,
        model: SemanticPlanningModel,
        escalation_model: SemanticPlanningModel | None = None,
        manifests: QueryManifestProvider,
        verifier: OntologyQueryPlanVerifier,
        descriptor_selector: SemanticDescriptorSelector | None = None,
        metric_concepts: Sequence[str] = (),
        investigation_window_seconds: int = 900,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._manifests = manifests
        self._verifier = verifier
        self._selector = descriptor_selector or CompleteManifestSelector()
        self._metric_concepts = _validated_metric_concepts(metric_concepts)
        if not 60 <= investigation_window_seconds <= 86_400:
            raise ValueError("investigation_window_seconds MUST be in [60, 86400]")
        self._investigation_window = timedelta(seconds=investigation_window_seconds)
        self._now = now or (lambda: datetime.now(UTC))
        self._cascade = SemanticPlanningCascade(
            model=model,
            escalation_model=escalation_model,
            verifier=verifier,
            frame_builder=_build_frame,
            plan_builder=_build_plan,
        )

    def plan(
        self,
        *,
        utterance: str,
        prior_turns: Sequence[Turn],
        principal: Principal,
        purpose: str,
        bound_incident: BoundIncident | None = None,
    ) -> SemanticPlanningOutcome:
        """Return a verified plan, one clarification, or a typed safe hold."""

        if not utterance.strip() or len(utterance) > 32_000:
            return _outcome(SemanticPlanningDisposition.UNSUPPORTED, "utterance_out_of_bounds")
        stage = "manifest"
        try:
            manifest = self._manifests.manifest_for(principal=principal, purpose=purpose)
            scope_mismatch = manifest.principal_role.value != principal.role.value
            if scope_mismatch or purpose not in manifest.purposes:
                raise PermissionError("principal manifest scope does not match planning request")
            selected = self._selector.select(
                utterance=utterance,
                manifest=manifest,
                limit=_MAX_DESCRIPTORS,
            )
            descriptors = _validated_descriptors(selected, manifest=manifest)
            context = _bounded_context(prior_turns)
            _LOGGER.info("semantic_planning_stage_completed", extra={"stage": stage})
            stage = "frame_proposal"
            frame_result = self._cascade.propose_frame(
                utterance=utterance,
                context=context,
                descriptors=descriptors,
                metric_concepts=self._metric_concepts,
                principal=principal,
                purpose=purpose,
            )
            if frame_result is None:
                return _outcome(
                    SemanticPlanningDisposition.UNAVAILABLE,
                    "semantic_frame_unavailable",
                    manifest_digest=manifest.manifest_digest,
                )
            proposal, frame, investigation_intent = frame_result
            _LOGGER.info("semantic_planning_stage_completed", extra={"stage": stage})
            _LOGGER.info("semantic_planning_stage_completed", extra={"stage": "frame_build"})
            if bound_incident is not None:
                proposal, frame = _resolve_incident_reference(
                    proposal,
                    frame,
                    utterance=utterance,
                    context=context,
                )
            proposal, frame = _resolve_principal_scope_evidence_subject(
                proposal,
                frame,
                utterance=utterance,
                context=context,
            )
            if frame.unresolved_terms:
                clarification = proposal.clarification or _clarification(frame.unresolved_terms)
                return _outcome(
                    SemanticPlanningDisposition.CLARIFICATION,
                    "semantic_clarification_required",
                    manifest_digest=manifest.manifest_digest,
                    frame=frame,
                    clarification=clarification,
                )
            if frame.operation is SemanticOperation.ACTION_DRAFT:
                return _outcome(
                    SemanticPlanningDisposition.ACTION_DRAFT,
                    "governed_action_draft_required",
                    manifest_digest=manifest.manifest_digest,
                    frame=frame,
                )
            stage = "plan_proposal"
            evaluation_time = self._now()
            if evaluation_time.tzinfo is None:
                raise ValueError("semantic planning evaluation time MUST be timezone-aware")
            plan = self._anchored_incident_plan(
                bound_incident=bound_incident,
                frame=frame,
                descriptors=descriptors,
                manifest=manifest,
                principal=principal,
                purpose=purpose,
                evaluation_time=evaluation_time,
            )
            plan_source = "bound_incident" if plan is not None else "proposed"
            if plan is None:
                plan = compile_target_error_activity_plan(
                    frame=frame,
                    utterance=utterance,
                    manifest=manifest,
                    verifier=self._verifier,
                    evaluation_time=evaluation_time,
                    purpose=purpose,
                )
                if plan is not None:
                    plan_source = "server_target_error_activity"
            if plan is None:
                plan = compile_target_health_plan(
                    frame=frame,
                    utterance=utterance,
                    manifest=manifest,
                    verifier=self._verifier,
                    evaluation_time=evaluation_time,
                    purpose=purpose,
                )
                if plan is not None:
                    plan_source = "server_target_health"
            if plan is None:
                plan = compile_target_current_state_plan(
                    frame=frame,
                    utterance=utterance,
                    manifest=manifest,
                    verifier=self._verifier,
                    evaluation_time=evaluation_time,
                    purpose=purpose,
                )
                if plan is not None:
                    plan_source = "server_target_current_state"
            if plan is None:
                plan = compile_target_activity_plan(
                    frame=frame,
                    utterance=utterance,
                    manifest=manifest,
                    verifier=self._verifier,
                    evaluation_time=evaluation_time,
                    purpose=purpose,
                )
                if plan is not None:
                    plan_source = "server_target_activity"
            if plan is None:
                plan = compile_target_impact_plan(
                    frame=frame,
                    utterance=utterance,
                    manifest=manifest,
                    verifier=self._verifier,
                    evaluation_time=evaluation_time,
                    purpose=purpose,
                )
                if plan is not None:
                    plan_source = "server_target_impact"
            if plan is None and investigation_intent is not None:
                try:
                    plan = compile_investigation_plan(
                        investigation_intent,
                        manifest=manifest,
                        verifier=self._verifier,
                        windows=_investigation_windows(
                            evaluation_time,
                            duration=self._investigation_window,
                        ),
                        purpose=purpose,
                        problem_frame_digest=frame.frame_digest,
                    )
                except InvestigationClarificationRequiredError as exc:
                    return _outcome(
                        SemanticPlanningDisposition.CLARIFICATION,
                        exc.reason,
                        manifest_digest=manifest.manifest_digest,
                        frame=frame,
                        clarification=_investigation_clarification(exc.reason),
                    )
                plan_source = "server_investigation"
            if plan is None:
                plan = self._principal_scope_evidence_plan(
                    frame=frame,
                    descriptors=descriptors,
                    manifest=manifest,
                    principal=principal,
                    purpose=purpose,
                    evaluation_time=evaluation_time,
                )
                if plan is not None:
                    plan_source = "principal_scope_evidence"
            if plan is None:
                plan = self._cascade.propose_plan(
                    frame=frame,
                    descriptors=descriptors,
                    metric_concepts=self._metric_concepts,
                    principal=principal,
                    purpose=purpose,
                    manifest=manifest,
                    evaluation_time=evaluation_time,
                )
            if plan is None:
                return _outcome(
                    SemanticPlanningDisposition.UNSUPPORTED,
                    "semantic_plan_unavailable",
                    manifest_digest=manifest.manifest_digest,
                    frame=frame,
                )
            if any(node.kind.value == "object_set" for node in plan.nodes):
                execution_time = self._now()
                if execution_time.tzinfo is None:
                    raise ValueError("semantic execution cutoff MUST be timezone-aware")
                plan = _refresh_object_set_cutoffs(plan, execution_time=execution_time)
                plan, grounded = ground_stated_value_filters(
                    plan,
                    utterance=utterance,
                    descriptors=descriptors,
                    subject_constraints=frame.subject_constraints,
                )
                if grounded:
                    _LOGGER.info(
                        "semantic_plan_filter_grounded",
                        extra={"grounded_properties": ",".join(grounded)},
                    )
                self._verifier.verify(plan, manifest=manifest)
            _LOGGER.info("semantic_planning_stage_completed", extra={"stage": stage})
            _LOGGER.info(
                "semantic_planning_stage_completed",
                extra={
                    "stage": "plan_verify",
                    "plan_nodes": _plan_node_summary(plan),
                    "plan_source": plan_source,
                    "output_shape": frame.output_shape,
                },
            )
            graph = build_intent_graph(
                frame=frame,
                plan=plan,
                confidence=proposal.confidence,
            )
            return _outcome(
                SemanticPlanningDisposition.PLANNED,
                "semantic_plan_verified",
                manifest_digest=manifest.manifest_digest,
                frame=frame,
                plan=plan,
                intent_graph=graph,
                investigation_intent=investigation_intent,
            )
        except PermissionError:
            return _outcome(SemanticPlanningDisposition.UNSUPPORTED, "semantic_scope_denied")
        except ProposalRejectedError as exc:
            _LOGGER.warning(
                "semantic_plan_rejected",
                extra={"stage": exc.stage, "failure_type": exc.failure_type},
            )
            return _outcome(SemanticPlanningDisposition.UNSUPPORTED, "semantic_plan_invalid")
        except (ValidationError, TypeError, ValueError) as exc:
            _LOGGER.warning(
                "semantic_plan_rejected",
                extra={
                    "stage": stage,
                    "failure_type": type(exc).__name__,
                    "validation_reason": _safe_validation_reason(exc),
                },
            )
            return _outcome(SemanticPlanningDisposition.UNSUPPORTED, "semantic_plan_invalid")
        except Exception:  # noqa: BLE001 - model/provider details never cross the boundary
            _LOGGER.exception(
                "semantic_planning_failed",
                extra={"principal_role": principal.role.value, "purpose": purpose},
            )
            return _outcome(SemanticPlanningDisposition.UNAVAILABLE, "semantic_planning_failed")

    def _anchored_incident_plan(
        self,
        *,
        bound_incident: BoundIncident | None,
        frame: SemanticProblemFrame,
        descriptors: tuple[dict[str, Any], ...],
        manifest: QueryManifest,
        principal: Principal,
        purpose: str,
        evaluation_time: datetime,
    ) -> OntologyQueryPlan | None:
        """Build the anchored incident read from the binding, never from a proposal.

        The frame still decides that this turn wants incident evidence. Reading it
        then needs only the two identities the conversation already holds, so no
        model selects the capability or transcribes an identifier. The node runs
        through the same builder and verifier as any proposed plan.
        """
        if bound_incident is None or frame.output_shape != SemanticOutputShape.INCIDENT_EVIDENCE:
            return None
        if not any(
            item.get("kind") == "function" and item.get("name") == _INCIDENT_EVIDENCE_FUNCTION
            for item in descriptors
        ):
            return None
        proposal = QueryPlanProposal(
            nodes=(
                QueryNodeProposal(
                    node_id=_INCIDENT_EVIDENCE_NODE_ID,
                    kind=QueryNodeKind.FUNCTION,
                    depends_on=(),
                    arguments={
                        "function_name": _INCIDENT_EVIDENCE_FUNCTION,
                        "arguments": {
                            "incident_id": bound_incident.incident_id,
                            "correlation_id": bound_incident.correlation_id,
                            "limit": INCIDENT_EVIDENCE_MAX_RECORDS,
                        },
                        "dependency_arguments": {},
                    },
                    output_kind="query.value",
                ),
            ),
            output_node_ids=(_INCIDENT_EVIDENCE_NODE_ID,),
        )
        plan = _build_plan(
            proposal,
            frame=frame,
            manifest=manifest,
            principal=principal,
            purpose=purpose,
            evaluation_time=evaluation_time,
        )
        self._verifier.verify(plan, manifest=manifest)
        return plan

    def _principal_scope_evidence_plan(
        self,
        *,
        frame: SemanticProblemFrame,
        descriptors: tuple[dict[str, Any], ...],
        manifest: QueryManifest,
        principal: Principal,
        purpose: str,
        evaluation_time: datetime,
    ) -> OntologyQueryPlan | None:
        if frame.output_shape != SemanticOutputShape.EVIDENCE_VALIDATION:
            return None
        if not any(
            item.get("kind") == "object" and item.get("name") == "Resource" for item in descriptors
        ):
            return None
        proposal = QueryPlanProposal(
            nodes=(
                QueryNodeProposal(
                    node_id="evidence-scope",
                    kind=QueryNodeKind.OBJECT_SET,
                    arguments={
                        "definition": {
                            "selector": {"kind": "object_type", "name": "Resource"},
                            "as_of": evaluation_time.astimezone(UTC).isoformat(),
                            "purpose": purpose,
                            "limit": 1000,
                        }
                    },
                    output_kind="query.table",
                ),
            ),
            output_node_ids=("evidence-scope",),
        )
        plan = _build_plan(
            proposal,
            frame=frame,
            manifest=manifest,
            principal=principal,
            purpose=purpose,
            evaluation_time=evaluation_time,
        )
        self._verifier.verify(plan, manifest=manifest)
        return plan


__all__ = [
    "CompleteManifestSelector",
    "QueryManifestProvider",
    "QueryNodeProposal",
    "QueryPlanProposal",
    "SemanticDescriptorSelector",
    "SemanticFrameProposal",
    "SemanticPlanningDisposition",
    "SemanticPlanningModel",
    "SemanticPlanningOutcome",
    "SemanticPlanningService",
]
