"""Compose a current-model read stage; only independent registry admission enables calls."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Mapping
from pathlib import Path

import httpx
from fdai_service_contracts.ontology_query import content_digest

from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.prompts import PromptAssembler
from fdai.core.prompts.registry import FileSystemPromptRegistry
from fdai.delivery.azure.llm.semantic_planning import (
    AzureOpenAISemanticPlanningModel,
    AzureOpenAISemanticPlanningModelConfig,
)
from fdai.delivery.catalog_search.ontology_governed_selection_read import (
    GovernedTypedSelectionRead,
    ReadSelectionSource,
    typed_read_source,
)
from fdai.delivery.persistence.state_store_typed_selection_read import StateStoreTypedSelectionRead
from fdai.runtime.ontology_index_runtime import OntologyIndexRuntime
from fdai.runtime.typed_selection_read_lifecycle import FinalizedTypedReadApproval
from fdai.shared.providers.state_store import StateStore
from fdai.shared.providers.workload_identity import WorkloadIdentity

from ._helpers import Container
from .resolved_models_revision import resolved_models_for_binding
from .semantic_query_model_targets import t1_model_targets

READ_DATA_POLICY = {
    "purpose": "typed-selection-read",
    "candidate_only": True,
    "evidence_storage": "installation-local",
    "requires_qualification": True,
    "max_model_calls": 2,
    "execution_authority": False,
}


def compose_typed_selection_read(
    *,
    container: Container,
    environment: Mapping[str, str],
    state_store: StateStore,
    index: OntologyIndexRuntime | None,
    identity: WorkloadIdentity | None,
    http_client: httpx.AsyncClient | None,
    endpoint: str | None,
    endpoint_resolver: Callable[[str], str] | None,
    catalog_root: Path,
    owner_loop: asyncio.AbstractEventLoop,
) -> GovernedTypedSelectionRead:
    registry = StateStoreTypedSelectionRead(
        state_store,
        admission=container.decision_evidence_admission_provider,
        approvals=FinalizedTypedReadApproval(state_store),
    )
    unavailable = GovernedTypedSelectionRead(registry=registry, source=None, proposer=None)
    revision = environment.get("FDAI_SOURCE_REVISION", "")
    if (
        index is None
        or index.workers is None
        or identity is None
        or http_client is None
        or re.fullmatch(r"[a-f0-9]{40}", revision) is None
    ):
        return unavailable
    try:
        targets = t1_model_targets(
            resolved_models_for_binding(container),
            endpoint=endpoint,
            endpoint_resolver=endpoint_resolver,
            held_capabilities=container.held_model_capabilities,
        )
        if not targets:
            return unavailable
        prompts = FileSystemPromptRegistry(catalog_root)
        plan = PromptAssembler(
            prompts.resolve(
                "semantic.query.plan", profile_id="diagnostic.ontology-candidate-selection"
            )
        ).complete
        frame = PromptAssembler(prompts.resolve("semantic.query.frame")).complete
        profile = prompts.resolve(
            "semantic.query.plan", profile_id="diagnostic.ontology-candidate-selection"
        ).profile
        if profile is None:
            return unavailable
        proposer = AzureOpenAISemanticPlanningModel(
            identity=identity,
            http_client=http_client,
            owner_loop=owner_loop,
            config=AzureOpenAISemanticPlanningModelConfig(
                candidates=(targets[0],),
                frame_system_prompt=frame.system_text,
                plan_system_prompt=plan.system_text,
                plan_prompt_manifest=plan.replay_manifest(),
                timeout_seconds=20,
                max_tokens=profile.reserved_output_tokens,
                reasoning_effort=profile.reasoning_effort,
            ),
        )
    except (OSError, ValueError, RuntimeError):
        return unavailable

    async def source(context: FunctionInvocationContext) -> ReadSelectionSource:
        scope = await index.enroll_context(context)
        if index.workers is None:
            raise PermissionError("typed selection source workers are unavailable")
        return await typed_read_source(
            index.workers,
            scope,
            proposer=proposer,
            source_revision=revision,
            data_policy_digest=content_digest(READ_DATA_POLICY),
        )

    return GovernedTypedSelectionRead(registry=registry, source=source, proposer=proposer)
