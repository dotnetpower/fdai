"""Compose a current-model read stage; only independent registry admission enables calls."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
from .resolved_models import _capability
from .resolved_models_revision import resolved_models_for_binding
from .semantic_query_model_targets import model_target_for_capability

READ_DATA_POLICY = {
    "purpose": "typed-selection-read",
    "candidate_only": True,
    "evidence_storage": "installation-local",
    "requires_qualification": True,
    "max_model_calls": 2,
    "execution_authority": False,
}
GOVERNED_READ_CONFIG_RELATIVE_PATH = Path("config/governed-typed-selection-read.json")


@dataclass(frozen=True, slots=True)
class GovernedTypedSelectionModelPin:
    model_capability: str
    model_family: str
    model_version: str
    prompt_profile_id: str
    prompt_profile_digest: str
    system_text_sha256: str
    reasoning_effort: str
    timeout_seconds: float
    max_tokens: int

    @classmethod
    def load(cls, path: Path) -> GovernedTypedSelectionModelPin:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(raw, dict)
            or raw.get("schema_version") != "1.0.0"
            or raw.get("qualification_protocol_id") != "governed-typed-selection-answer-window.v2"
        ):
            raise ValueError("governed typed-selection model pin is not reviewed")
        return cls(
            model_capability=str(raw["model_capability"]),
            model_family=str(raw["model_family"]),
            model_version=str(raw["model_version"]),
            prompt_profile_id=str(raw["prompt_profile_id"]),
            prompt_profile_digest=str(raw["prompt_profile_digest"]),
            system_text_sha256=str(raw["system_text_sha256"]),
            reasoning_effort=str(raw["reasoning_effort"]),
            timeout_seconds=float(raw["timeout_seconds"]),
            max_tokens=int(raw["max_tokens"]),
        )


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
    config_path: Path,
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
        pin = GovernedTypedSelectionModelPin.load(config_path)
        resolved = resolved_models_for_binding(container)
        capability = _capability(
            resolved,
            pin.model_capability,
            held_capabilities=container.held_model_capabilities,
        )
        target = model_target_for_capability(
            resolved,
            pin.model_capability,
            endpoint=endpoint,
            endpoint_resolver=endpoint_resolver,
            held_capabilities=container.held_model_capabilities,
        )
        if (
            capability is None
            or target is None
            or capability.family != pin.model_family
            or capability.version != pin.model_version
            or target.model_family != pin.model_family
        ):
            return unavailable
        prompts = FileSystemPromptRegistry(catalog_root)
        plan = PromptAssembler(
            prompts.resolve("semantic.query.plan", profile_id=pin.prompt_profile_id)
        ).complete
        frame = PromptAssembler(prompts.resolve("semantic.query.frame")).complete
        profile = prompts.resolve("semantic.query.plan", profile_id=pin.prompt_profile_id).profile
        manifest = plan.replay_manifest()
        if (
            profile is None
            or profile.reasoning_effort != pin.reasoning_effort
            or profile.reserved_output_tokens != pin.max_tokens
            or manifest.profile_id != pin.prompt_profile_id
            or manifest.profile_digest != pin.prompt_profile_digest
            or manifest.system_text_sha256 != pin.system_text_sha256
        ):
            return unavailable
        proposer = AzureOpenAISemanticPlanningModel(
            identity=identity,
            http_client=http_client,
            owner_loop=owner_loop,
            config=AzureOpenAISemanticPlanningModelConfig(
                candidates=(target,),
                frame_system_prompt=frame.system_text,
                plan_system_prompt=plan.system_text,
                plan_prompt_manifest=manifest,
                timeout_seconds=pin.timeout_seconds,
                max_tokens=pin.max_tokens,
                reasoning_effort=pin.reasoning_effort,
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
