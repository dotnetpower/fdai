"""Azure OpenAI semantic planning and diagnostic candidate proposals."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from functools import partial
from typing import Any

import httpx
from fdai_service_contracts.ontology_query import SemanticProblemFrame
from pydantic import BaseModel, ValidationError

from fdai.core.conversation.adaptive_call_scope import (
    call_scoped_provider,
    run_scoped_model,
    stop_scoped_provider_retry,
)
from fdai.core.conversation.semantic_judgment import SemanticJudgmentObservation
from fdai.core.conversation.semantic_planning_assembly import (
    frame_assembly_keys,
    frame_result_keys,
    plan_assembly_keys,
)
from fdai.core.conversation.semantic_planning_assembly import (
    plan_descriptors as _plan_descriptors,
)
from fdai.core.conversation.semantic_planning_models import (
    QueryPlanProposal,
    SemanticFrameProposal,
    SemanticPlanningModelResponse,
)
from fdai.core.conversation.turn_reservations import TurnReservationHeldError
from fdai.core.ontology_platform import QueryManifest
from fdai.core.prompts import estimate_chat_request_tokens, estimate_prompt_tokens
from fdai.core.prompts.types import (
    LayerRef,
    PromptAssemblyReceipt,
    PromptLayer,
    PromptReplayManifest,
)
from fdai.delivery.azure.llm.completion_body import completion_body_params
from fdai.delivery.azure.llm.model_trace import (
    bounded_usage,
    complete_model_trace,
    prepare_model_messages,
    start_model_trace,
)
from fdai.delivery.azure.llm.semantic_planning_bounds import bounded_input
from fdai.delivery.azure.llm.semantic_planning_config import (
    MAX_SYSTEM_PROMPT_CHARS as _MAX_SYSTEM_PROMPT_CHARS,
)
from fdai.delivery.azure.llm.semantic_planning_config import (
    AzureOpenAISemanticPlanningModelConfig as AzureOpenAISemanticPlanningModelConfig,
)
from fdai.delivery.azure.llm.semantic_planning_config import (
    candidate_proposal_binding,
    candidate_proposal_request_target,
    candidate_proposal_response_format,
    candidate_proposal_system_content,
    reasoning_effort_for_target,
)
from fdai.delivery.azure.llm.semantic_planning_config import (
    proposal_schema as _proposal_schema,
)
from fdai.delivery.azure.llm.semantic_planning_manifest import (
    sha256_hex as _sha256,
)
from fdai.delivery.azure.llm.semantic_planning_manifest import (
    transmitted_prompt_manifest as _transmitted_prompt_manifest,
)
from fdai.delivery.azure.llm.semantic_planning_response import (
    SemanticPlanningResponseValidationError,
    provider_error_code,
    validated_content,
)
from fdai.delivery.catalog_search.generation import SemanticGenerationBuild
from fdai.delivery.catalog_search.ontology_candidate_proposal import (
    OntologyCandidateModelBinding,
    OntologyCandidateProposal,
    OntologyCandidateProposalResult,
    candidate_proposal_payload,
    filter_candidate_proposal_quotes,
)
from fdai.delivery.catalog_search.ontology_candidate_selection import OntologyCandidateSelection
from fdai.delivery.catalog_search.ontology_snapshot_store import OntologyStagedProjection
from fdai.shared.providers.workload_identity import WorkloadIdentity

# Bounded with OntologySemanticEvaluationBudget: one typed-selection call never exceeds 10 s.
_CANDIDATE_PROPOSAL_MAX_TIMEOUT_SECONDS = 10

_LOGGER = logging.getLogger(__name__)
_MAX_DESCRIPTORS = 512
_MAX_RESPONSE_BYTES = 65_536
_MAX_OPERATIONAL_REQUEST_BYTES = 65_536
_MAX_RECOVERY_CONTEXT_CHARS = 1_024
_MAX_ATTEMPTS_PER_CANDIDATE = 3
_COMPACT_OPERATIONAL_INTENTS = frozenset(
    {
        "create.document",
        "query.gateway_diagnostic_evidence",
        "query.resource_configuration_changes",
        "query.resource_current_state",
        "query.resource_state_inventory",
        "query.contextual_resources",
    }
)
_RECOVERY_PROMPT = """
This is one bounded T2 recovery attempt after a typed T1 planning failure.
Re-evaluate the complete operator utterance against the supplied descriptors. Preserve the
requested answer family, especially causal intent. Prefer a verified read plan over clarification
only when the exact target, relationships, and evidence requirements are grounded in supplied
input. Never invent identity, scope, evidence, or authority. If ambiguity remains, return the
schema-valid clarification.
""".strip()


class AzureOpenAISemanticPlanningModel:
    """Propose validated planning records over async Azure I/O.

    Synchronous frame/plan calls must run outside ``owner_loop``. ``SemanticConversationRuntime``
    provides that boundary with ``asyncio.to_thread``. The adapter schedules
    workload-identity and HTTP work back onto the owning runtime loop, tries
    candidates in configured order, and returns ``None`` after any bounded
    all-candidate failure without exposing provider details. The async candidate
    diagnostic runs on the owner loop and raises on its single-attempt failure.
    """

    def __init__(
        self,
        *,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        config: AzureOpenAISemanticPlanningModelConfig,
        owner_loop: asyncio.AbstractEventLoop,
    ) -> None:
        if not owner_loop.is_running():
            raise ValueError("semantic planning owner_loop MUST be running")
        self._identity = identity
        self._http = http_client
        self._config = config
        self._owner_loop = owner_loop

    def candidate_proposal_binding(self) -> OntologyCandidateModelBinding:
        return candidate_proposal_binding(self._config)

    def candidate_proposal_binding_for_manifest(
        self, manifest: QueryManifest, build: SemanticGenerationBuild | None = None
    ) -> OntologyCandidateModelBinding:
        return candidate_proposal_binding(self._config, manifest=manifest, build=build)

    async def propose_candidate_selection(
        self,
        *,
        query: str,
        manifest: QueryManifest,
        build: SemanticGenerationBuild,
        staged: OntologyStagedProjection,
    ) -> OntologyCandidateProposalResult:
        """One diagnostic proposal, without fallback, repair or activation authority."""
        if asyncio.get_running_loop() is not self._owner_loop:
            raise ValueError("candidate proposal must run on the model owner loop")
        if (
            len(self._config.candidates) != 1
            or self._config.timeout_seconds > _CANDIDATE_PROPOSAL_MAX_TIMEOUT_SECONDS
            or self._config.plan_prompt_manifest is None
            or self._config.plan_prompt_manifest.profile_id
            != "diagnostic.ontology-candidate-selection"
        ):
            raise ValueError("candidate proposal requires one bounded target and diagnostic prompt")
        deadline = asyncio.get_running_loop().time() + self._config.timeout_seconds
        async with asyncio.timeout(self._config.timeout_seconds):
            payload = candidate_proposal_payload(
                query=query, manifest=manifest, build=build, staged=staged
            )
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("candidate proposal deadline exceeded before dispatch")
            response = await self._complete_async(
                payload=payload,
                prompt=self._config.plan_system_prompt,
                proposal_type=OntologyCandidateProposal,
                operation="candidate_selection",
                manifest=self._config.plan_prompt_manifest,
                query_manifest=manifest,
                build=build,
                max_attempts=1,
            )
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("candidate proposal deadline exceeded after return")
            if not isinstance(response, SemanticPlanningModelResponse):
                raise ValueError("candidate proposal model unavailable")
            proposal, quote_invalid_clauses = filter_candidate_proposal_quotes(
                query,
                OntologyCandidateProposal.model_validate(response.proposal),
            )
            result = OntologyCandidateProposalResult(
                proposal=proposal,
                selection=(
                    OntologyCandidateSelection.bind(
                        query=query, manifest=manifest, staged=staged, clauses=proposal.clauses
                    )
                    if proposal.status == "select"
                    else None
                ),
                input_digest=str(payload["input_digest"]),
                observation=response.observation,
                quote_invalid_clauses=quote_invalid_clauses,
            )
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("candidate proposal deadline exceeded before publication")
            return result

    def propose_frame(
        self,
        *,
        utterance: str,
        context: tuple[str, ...],
        descriptors: tuple[dict[str, Any], ...],
        principal_role: str,
        purpose: str,
        metric_concepts: tuple[str, ...] = (),
        semantic_judgment: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any] | None:
        """Return one validated frame proposal or ``None`` on bounded failure."""

        payload = {
            "utterance": utterance,
            "context": context,
            "descriptors": _frame_descriptor_candidates(descriptors),
            "metric_concepts": metric_concepts,
            "principal_role": principal_role,
            "purpose": purpose,
            "semantic_judgment": semantic_judgment,
        }
        if not bounded_input(payload, context=context, descriptors=descriptors):
            return None
        prompt, manifest, receipt = self._frame_selection(semantic_judgment)
        response = self._complete(
            payload=payload,
            prompt=prompt,
            proposal_type=SemanticFrameProposal,
            operation="frame",
            manifest=manifest,
        )
        if (
            receipt is None
            or not isinstance(response, SemanticPlanningModelResponse)
            or not receipt.uncovered(frame_result_keys(response.proposal))
        ):
            return response
        _LOGGER.info("semantic_planning_frame_assembly_fallback")
        complete = self._config.frame_system_prompt
        retry = self._complete(
            payload=payload,
            prompt=complete,
            proposal_type=SemanticFrameProposal,
            operation="frame",
            manifest=self._config.frame_prompt_manifest,
        )
        if not isinstance(retry, SemanticPlanningModelResponse):
            return retry
        return replace(
            retry, prior_observations=(*response.observations, *retry.prior_observations)
        )

    def propose_plan(
        self,
        *,
        frame: SemanticProblemFrame,
        descriptors: tuple[dict[str, Any], ...],
        metric_concepts: tuple[str, ...],
        principal_role: str,
        purpose: str,
        evaluation_time: datetime,
    ) -> Mapping[str, Any] | None:
        """Return one validated query-plan proposal or ``None`` on bounded failure."""

        assembler = self._config.plan_prompt_assembler
        assembled = assembler.assemble(plan_assembly_keys(frame)) if assembler else None
        guidance = (
            assembled.system_text
            if assembled is not None
            and assembled.assembly is not None
            and assembled.assembly.mode.value == "selected"
            else None
        )
        payload = {
            "frame": frame.model_dump(mode="json"),
            "descriptors": _plan_descriptors(descriptors, frame, guidance),
            "metric_concepts": metric_concepts,
            "principal_role": principal_role,
            "purpose": purpose,
            "evaluation_time": evaluation_time.isoformat(),
        }
        if not bounded_input(payload, context=(), descriptors=descriptors):
            return None
        return self._complete(
            payload=payload,
            prompt=assembled.system_text if assembled else self._config.plan_system_prompt,
            proposal_type=QueryPlanProposal,
            operation="plan",
            manifest=assembled.replay_manifest() if assembled else None,
        )

    def propose_escalated_frame(
        self,
        *,
        utterance: str,
        context: tuple[str, ...],
        descriptors: tuple[dict[str, Any], ...],
        principal_role: str,
        purpose: str,
        metric_concepts: tuple[str, ...] = (),
        semantic_judgment: Mapping[str, Any] | None = None,
        recovery_context: Mapping[str, str],
    ) -> Mapping[str, Any] | None:
        """Retry frame planning with compact typed failure context."""

        payload = {
            "utterance": utterance,
            "context": context,
            "descriptors": _frame_descriptor_candidates(descriptors),
            "metric_concepts": metric_concepts,
            "principal_role": principal_role,
            "purpose": purpose,
            "semantic_judgment": semantic_judgment,
            "recovery_context": _bounded_recovery_context(recovery_context),
        }
        if not bounded_input(payload, context=context, descriptors=descriptors):
            return None
        prompt = _recovery_prompt(
            self._config.recovery_frame_system_prompt or self._frame_prompt(semantic_judgment)
        )
        if prompt is None:
            return None
        return self._complete(
            payload=payload,
            prompt=prompt,
            proposal_type=SemanticFrameProposal,
            operation="frame_recovery",
        )

    def propose_escalated_plan(
        self,
        *,
        frame: SemanticProblemFrame,
        descriptors: tuple[dict[str, Any], ...],
        metric_concepts: tuple[str, ...],
        principal_role: str,
        purpose: str,
        evaluation_time: datetime,
        recovery_context: Mapping[str, str],
    ) -> Mapping[str, Any] | None:
        """Retry plan construction with compact typed failure context."""

        payload = {
            "frame": frame.model_dump(mode="json"),
            "descriptors": descriptors,
            "metric_concepts": metric_concepts,
            "principal_role": principal_role,
            "purpose": purpose,
            "evaluation_time": evaluation_time.isoformat(),
            "recovery_context": _bounded_recovery_context(recovery_context),
        }
        if not bounded_input(payload, context=(), descriptors=descriptors):
            return None
        prompt = _recovery_prompt(self._config.plan_system_prompt)
        if prompt is None:
            return None
        return self._complete(
            payload=payload,
            prompt=prompt,
            proposal_type=QueryPlanProposal,
            operation="plan_recovery",
        )

    def _frame_prompt(self, semantic_judgment: Mapping[str, Any] | None) -> str:
        if (
            self._config.operational_frame_system_prompt is not None
            and semantic_judgment is not None
            and semantic_judgment.get("primary_intent") in _COMPACT_OPERATIONAL_INTENTS
        ):
            return self._config.operational_frame_system_prompt
        return self._config.frame_system_prompt

    def _frame_selection(
        self, semantic_judgment: Mapping[str, Any] | None
    ) -> tuple[str, PromptReplayManifest | None, PromptAssemblyReceipt | None]:
        prompt = self._frame_prompt(semantic_judgment)
        assembler = self._config.frame_prompt_assembler
        if prompt != self._config.frame_system_prompt or assembler is None:
            return prompt, None, None
        assembled = assembler.assemble(frame_assembly_keys(semantic_judgment))
        return assembled.system_text, assembled.replay_manifest(), assembled.assembly

    def _complete(
        self,
        *,
        payload: Mapping[str, Any],
        prompt: str,
        proposal_type: type[BaseModel],
        operation: str,
        manifest: PromptReplayManifest | None = None,
    ) -> Mapping[str, Any] | None:
        future = asyncio.run_coroutine_threadsafe(
            self._complete_async(
                payload=payload,
                prompt=prompt,
                proposal_type=proposal_type,
                operation=operation,
                manifest=manifest,
            ),
            self._owner_loop,
        )
        try:
            return future.result(timeout=self._config.timeout_seconds + 1)
        except Exception as exc:  # noqa: BLE001 - provider details remain inside the adapter
            future.cancel()
            _LOGGER.warning(
                "semantic_planning_model_unavailable",
                extra={"operation": operation, "failure_type": type(exc).__name__},
            )
            return None

    async def _complete_async(
        self,
        *,
        payload: Mapping[str, Any],
        prompt: str,
        proposal_type: type[BaseModel],
        operation: str,
        manifest: PromptReplayManifest | None = None,
        query_manifest: QueryManifest | None = None,
        build: SemanticGenerationBuild | None = None,
        max_attempts: int = _MAX_ATTEMPTS_PER_CANDIDATE,
    ) -> Mapping[str, Any] | None:
        return await run_scoped_model(
            lambda: self._complete_attempts(
                payload=payload,
                prompt=prompt,
                proposal_type=proposal_type,
                operation=operation,
                manifest=manifest,
                query_manifest=query_manifest,
                build=build,
                max_attempts=max_attempts,
            )
        )

    async def _complete_attempts(
        self,
        *,
        payload: Mapping[str, Any],
        prompt: str,
        proposal_type: type[BaseModel],
        operation: str,
        manifest: PromptReplayManifest | None = None,
        query_manifest: QueryManifest | None = None,
        build: SemanticGenerationBuild | None = None,
        max_attempts: int = _MAX_ATTEMPTS_PER_CANDIDATE,
    ) -> Mapping[str, Any] | None:
        user_content = json.dumps(
            {"untrusted_input": payload},
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        schema = _proposal_schema(
            proposal_type,
            manifest=query_manifest if proposal_type is OntologyCandidateProposal else None,
            query=str(payload.get("query")) if proposal_type is OntologyCandidateProposal else None,
            build=build if proposal_type is OntologyCandidateProposal else None,
        )
        system_content = (
            candidate_proposal_system_content(prompt)
            if proposal_type is OntologyCandidateProposal
            else f"{prompt}\nRequired JSON Schema:\n{schema}"
        )
        messages = list(
            prepare_model_messages(
                (
                    {"role": "system", "content": system_content},
                    {"role": "user", "content": user_content},
                )
            ).messages
        )
        transmitted_system = messages[0]["content"]
        transmitted_user = messages[1]["content"]
        if not isinstance(transmitted_system, str) or not isinstance(transmitted_user, str):
            return None
        if proposal_type is OntologyCandidateProposal and (
            transmitted_system != system_content or transmitted_user != user_content
        ):
            _LOGGER.warning("ontology_candidate_proposal_input_changed")
            return None
        prompt_profile = (
            "operational" if prompt == self._config.operational_frame_system_prompt else "general"
        )
        response_format: dict[str, Any] = (
            candidate_proposal_response_format()
            if proposal_type is OntologyCandidateProposal and query_manifest is None
            else candidate_proposal_response_format(
                manifest=query_manifest,
                query=(
                    str(payload.get("query"))
                    if proposal_type is OntologyCandidateProposal
                    else None
                ),
                build=build if proposal_type is OntologyCandidateProposal else None,
            )
            if proposal_type is OntologyCandidateProposal
            else {"type": "json_object"}
        )
        request_bytes = len(
            json.dumps(
                {"messages": messages, "response_format": response_format},
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        )
        if prompt_profile == "operational" and request_bytes > _MAX_OPERATIONAL_REQUEST_BYTES:
            _LOGGER.warning(
                "semantic_planning_operational_request_over_budget",
                extra={"request_bytes": request_bytes},
            )
            return None
        prompt_manifest = _transmitted_prompt_manifest(
            manifest if manifest is not None else self._prompt_manifest(prompt),
            system_content=transmitted_system,
            schema=schema,
        )
        if (
            prompt_manifest is not None
            and prompt_manifest.system_token_budget is not None
            and prompt_manifest.token_estimate > prompt_manifest.system_token_budget
        ):
            _LOGGER.warning(
                "semantic_planning_system_token_budget_exceeded",
                extra={
                    "operation": operation,
                    "profile_id": prompt_manifest.profile_id,
                    "system_token_estimate": prompt_manifest.token_estimate,
                    "system_token_budget": prompt_manifest.system_token_budget,
                },
            )
            return None
        request_token_estimate = estimate_chat_request_tokens(
            messages=messages,
            response_format=response_format,
            reserved_output_tokens=self._config.max_tokens,
        )
        if (
            prompt_manifest is not None
            and prompt_manifest.request_token_budget is not None
            and request_token_estimate > prompt_manifest.request_token_budget
        ):
            _LOGGER.warning(
                "semantic_planning_request_token_budget_exceeded",
                extra={
                    "operation": operation,
                    "profile_id": prompt_manifest.profile_id,
                    "request_token_estimate": request_token_estimate,
                    "request_token_budget": prompt_manifest.request_token_budget,
                },
            )
            return None
        _LOGGER.info(
            "semantic_planning_request_prepared",
            extra={
                "operation": operation,
                "prompt_profile": prompt_profile,
                "system_chars": len(transmitted_system),
                "user_chars": len(transmitted_user),
                "request_bytes": request_bytes,
                "candidate_count": len(self._config.candidates),
            },
        )
        candidate_timeout = self._config.timeout_seconds / len(self._config.candidates)
        request_targets = tuple(
            candidate_proposal_request_target(target)
            if proposal_type is OntologyCandidateProposal
            else target
            for target in self._config.candidates
        )
        for index, target in enumerate(request_targets):
            try:
                async with asyncio.timeout(candidate_timeout):
                    token = await self._identity.get_token(target.auth_audience)
                    request = target.operation("chat/completions")
                    body: dict[str, Any] = {
                        "messages": messages,
                        "response_format": response_format,
                        **completion_body_params(
                            target.model_family or target.deployment,
                            temperature=0.0,
                            max_tokens=self._config.max_tokens,
                        ),
                    }
                    if request.model_body_field is not None:
                        body["model"] = request.model_body_field
                    reasoning_effort = reasoning_effort_for_target(self._config, target)
                    if reasoning_effort is not None:
                        body["reasoning_effort"] = reasoning_effort
                    for attempt in range(max_attempts):
                        trace_start = start_model_trace(body["messages"])
                        response, reservation = await call_scoped_provider(
                            partial(
                                self._http.post,
                                request.url,
                                params=request.params,
                                headers={
                                    "Authorization": f"Bearer {token.token}",
                                    "Content-Type": "application/json",
                                },
                                json=body,
                                timeout=candidate_timeout,
                            ),
                            request=body,
                            output_tokens=self._config.max_tokens,
                            stage=operation,
                        )
                        if response.status_code == 429:
                            response.raise_for_status()
                        response.raise_for_status()
                        try:
                            proposal, response_content, usage = validated_content(
                                response,
                                proposal_type,
                            )
                            trace_call = complete_model_trace(
                                trace_start,
                                call_id=f"semantic-planning-{operation}-{index + 1}",
                                kind=f"semantic-planning-{operation}",
                                model=target.deployment,
                                response_content=response_content,
                                usage=usage,
                            )
                            observation = SemanticJudgmentObservation(
                                model=target.deployment,
                                usage=bounded_usage(usage),
                                trace_call=trace_call,
                                prompt_replay_manifest=prompt_manifest,
                            )
                            if reservation is not None:
                                reservation.record(observation)
                            return SemanticPlanningModelResponse(
                                proposal=proposal,
                                observation=observation,
                            )
                        except (ValidationError, ValueError) as exc:
                            if attempt + 1 >= max_attempts:
                                raise
                            _LOGGER.info(
                                "semantic_planning_candidate_retry",
                                extra={
                                    "operation": operation,
                                    "candidate_index": index,
                                    "attempt": attempt + 1,
                                    "failure_type": type(exc).__name__,
                                },
                            )
                    raise RuntimeError("semantic planning retry loop exhausted")
            except Exception as exc:  # noqa: BLE001 - bounded fallback hides provider details
                if isinstance(exc, TurnReservationHeldError):
                    return None  # Every candidate would hold; the ledger names the stage.
                if stop_scoped_provider_retry():
                    _LOGGER.warning(
                        "adaptive_query_provider_attempt_ended",
                        extra={"operation": operation, "failure_type": type(exc).__name__},
                    )
                    return None
                failure: dict[str, Any] = {
                    "operation": operation,
                    "candidate_index": index,
                    "failure_type": type(exc).__name__,
                }
                if isinstance(exc, httpx.HTTPStatusError):
                    failure["status_code"] = exc.response.status_code
                    error_code = await provider_error_code(exc.response)
                    if error_code is not None:
                        failure["provider_error_code"] = error_code
                if isinstance(exc, ValidationError):
                    failure["validation_stage"] = "schema_validation"
                    failure["validation_errors"] = json.dumps(
                        [
                            {
                                "location": ".".join(str(part) for part in error["loc"]),
                                "type": error["type"],
                            }
                            for error in exc.errors(include_input=False, include_url=False)
                        ],
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                elif isinstance(exc, SemanticPlanningResponseValidationError):
                    failure["validation_stage"] = exc.stage
                _LOGGER.warning(
                    "semantic_planning_candidate_failed",
                    extra=failure,
                )
        return None

    def _prompt_manifest(self, prompt: str) -> PromptReplayManifest | None:
        candidates = (
            (self._config.frame_system_prompt, self._config.frame_prompt_manifest),
            (self._config.plan_system_prompt, self._config.plan_prompt_manifest),
            (
                self._config.operational_frame_system_prompt,
                self._config.operational_frame_prompt_manifest,
            ),
            (
                self._config.recovery_frame_system_prompt,
                self._config.recovery_frame_prompt_manifest,
            ),
        )
        for configured_prompt, manifest in candidates:
            if configured_prompt is None or manifest is None:
                continue
            if prompt == configured_prompt:
                return manifest
            if prompt.startswith(f"{configured_prompt}\n\n"):
                recovery_text = prompt[len(configured_prompt) + 2 :]
                return replace(
                    manifest,
                    system_text_sha256=_sha256(prompt),
                    layer_manifest=(
                        *manifest.layer_manifest,
                        LayerRef(
                            id="semantic-recovery-directive",
                            version=1,
                            layer=PromptLayer.RECOVERY,
                            token_estimate=estimate_prompt_tokens(recovery_text),
                        ),
                    ),
                    token_estimate=estimate_prompt_tokens(prompt),
                )
        return None


def _bounded_recovery_context(context: Mapping[str, str]) -> dict[str, str]:
    normalized = {
        key: value
        for key, value in context.items()
        if key in {"stage", "trigger", "reason"} and isinstance(value, str) and value
    }
    encoded = json.dumps(normalized, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    if len(encoded) > _MAX_RECOVERY_CONTEXT_CHARS:
        raise ValueError("semantic planning recovery context is too large")
    return normalized


def _recovery_prompt(base_prompt: str) -> str | None:
    prompt = f"{base_prompt}\n\n{_RECOVERY_PROMPT}"
    if len(prompt) > _MAX_SYSTEM_PROMPT_CHARS:
        _LOGGER.warning(
            "semantic_planning_recovery_prompt_unavailable",
            extra={"failure_type": "PromptBudgetExceeded"},
        )
        return None
    return prompt


def _frame_descriptor_candidates(
    descriptors: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    """Project exact manifest declarations into bounded frame-selection candidates."""

    candidates: list[dict[str, Any]] = []
    for descriptor in descriptors:
        kind = descriptor.get("kind")
        if kind == "action":
            continue
        candidate = {key: descriptor[key] for key in ("kind", "name") if key in descriptor}
        if kind == "link":
            for key in ("from_type", "to_type"):
                if key in descriptor:
                    candidate[key] = descriptor[key]
        elif kind == "function":
            if "read_sets" in descriptor:
                candidate["read_sets"] = descriptor["read_sets"]
            output_schema = descriptor.get("output_schema")
            if isinstance(output_schema, Mapping):
                measure_concepts = output_schema.get("x-fdai-measure-concepts")
                if measure_concepts is not None:
                    candidate["measure_concepts"] = measure_concepts
        candidates.append(candidate)
    return tuple(candidates)


__all__ = [
    "AzureOpenAISemanticPlanningModel",
    "AzureOpenAISemanticPlanningModelConfig",
]
