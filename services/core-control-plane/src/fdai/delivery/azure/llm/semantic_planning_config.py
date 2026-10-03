"""Immutable semantic-planning configuration and diagnostic request identity."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from fdai_service_contracts.ontology_query import content_digest
from pydantic import BaseModel

from fdai.core.prompts import PromptAssembler, PromptReplayManifest
from fdai.delivery.catalog_search.ontology_candidate_proposal import (
    OntologyCandidateModelBinding,
    OntologyCandidateProposal,
)

from .completion_body import completion_body_params
from .request_target import ModelRequestTarget
from .semantic_planning_manifest import (
    transmitted_prompt_manifest,
    validate_output_reserve,
    validate_prompt_manifest,
)

_MAX_CANDIDATES = 8
MAX_SYSTEM_PROMPT_CHARS = 65_536


@dataclass(frozen=True, slots=True)
class AzureOpenAISemanticPlanningModelConfig:
    """Bounded request targets and catalog-owned semantic planning prompts."""

    candidates: tuple[ModelRequestTarget, ...]
    frame_system_prompt: str
    plan_system_prompt: str
    operational_frame_system_prompt: str | None = None
    recovery_frame_system_prompt: str | None = None
    frame_prompt_manifest: PromptReplayManifest | None = None
    plan_prompt_manifest: PromptReplayManifest | None = None
    operational_frame_prompt_manifest: PromptReplayManifest | None = None
    recovery_frame_prompt_manifest: PromptReplayManifest | None = None
    timeout_seconds: float = 90.0
    max_tokens: int = 2_048
    frame_prompt_assembler: PromptAssembler | None = None
    plan_prompt_assembler: PromptAssembler | None = None

    def __post_init__(self) -> None:
        if not 1 <= len(self.candidates) <= _MAX_CANDIDATES:
            raise ValueError(f"semantic planning candidates MUST contain 1 to {_MAX_CANDIDATES}")
        for assembler, prompt, manifest in (
            (self.frame_prompt_assembler, self.frame_system_prompt, self.frame_prompt_manifest),
            (self.plan_prompt_assembler, self.plan_system_prompt, self.plan_prompt_manifest),
        ):
            if assembler is not None and (
                assembler.complete.system_text != prompt
                or assembler.complete.replay_manifest() != manifest
            ):
                raise ValueError("semantic planning assembler MUST match its complete prompt")
        identities = tuple(
            (candidate.endpoint, candidate.deployment, candidate.api_version)
            for candidate in self.candidates
        )
        if len(identities) != len(set(identities)):
            raise ValueError("semantic planning candidates MUST be unique")
        for prompt in (self.frame_system_prompt, self.plan_system_prompt):
            if not prompt or len(prompt) > MAX_SYSTEM_PROMPT_CHARS:
                raise ValueError("semantic planning system prompts MUST be non-empty and bounded")
        if self.operational_frame_system_prompt is not None and (
            not self.operational_frame_system_prompt
            or len(self.operational_frame_system_prompt) > MAX_SYSTEM_PROMPT_CHARS
        ):
            raise ValueError("operational frame system prompt MUST be non-empty and bounded")
        if self.recovery_frame_system_prompt is not None and (
            not self.recovery_frame_system_prompt
            or len(self.recovery_frame_system_prompt) > MAX_SYSTEM_PROMPT_CHARS
        ):
            raise ValueError("recovery frame system prompt MUST be non-empty and bounded")
        validate_prompt_manifest(self.frame_system_prompt, self.frame_prompt_manifest)
        validate_prompt_manifest(self.plan_system_prompt, self.plan_prompt_manifest)
        validate_prompt_manifest(
            self.operational_frame_system_prompt,
            self.operational_frame_prompt_manifest,
        )
        validate_prompt_manifest(
            self.recovery_frame_system_prompt,
            self.recovery_frame_prompt_manifest,
        )
        if not 0 < self.timeout_seconds <= 120:
            raise ValueError("semantic planning timeout_seconds MUST be in (0, 120]")
        if not 1 <= self.max_tokens <= 4_096:
            raise ValueError("semantic planning max_tokens MUST be in [1, 4096]")
        for name, manifest in (
            ("frame", self.frame_prompt_manifest),
            ("plan", self.plan_prompt_manifest),
            ("operational frame", self.operational_frame_prompt_manifest),
            ("recovery frame", self.recovery_frame_prompt_manifest),
        ):
            validate_output_reserve(name, manifest, self.max_tokens)


def candidate_proposal_binding(
    config: AzureOpenAISemanticPlanningModelConfig,
) -> OntologyCandidateModelBinding:
    if len(config.candidates) != 1 or config.plan_prompt_manifest is None:
        raise ValueError("candidate proposal binding requires one target and a prompt")
    schema = proposal_schema(OntologyCandidateProposal)
    prompt = transmitted_prompt_manifest(
        config.plan_prompt_manifest,
        system_content=f"{config.plan_system_prompt}\nRequired JSON Schema:\n{schema}",
        schema=schema,
    )
    if prompt is None:
        raise ValueError("candidate proposal prompt binding is unavailable")
    target = config.candidates[0]
    return OntologyCandidateModelBinding(
        content_digest(asdict(target)),
        content_digest({"deployment": target.deployment}),
        content_digest(
            {
                "completion": completion_body_params(
                    target.deployment, temperature=0.0, max_tokens=config.max_tokens
                ),
                "response_format": {"type": "json_object"},
                "timeout_seconds": config.timeout_seconds,
                "max_attempts": 1,
            }
        ),
        prompt,
    )


def proposal_schema(proposal_type: type[BaseModel]) -> str:
    return json.dumps(
        proposal_type.model_json_schema(),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
