"""Compose the independent second reader for semantic planning.

The local launcher enables it with ``FDAI_SEMANTIC_SECOND_READER=1``; every other venue
keeps the current single-reader path until the reader is promoted. The primary reader
is the first resolved narrator deployment. The second reader is the first later
narrator deployment outside the completion-token (reasoning) request family, so its
closed choices and constraint quotes do not spend their bounded output on reasoning.
Without such a deployment no second reader exists and nothing binds through it.

The local launcher also sets ``FDAI_SEMANTIC_COMPILED_ANSWERS=1``, which adds the
question-form path that answers a released compilation. Relation directions are then
confirmed by the first later reasoning deployment, because direction turns on syntax. When
that deployment is neither the primary reader's nor the second reader's family, it also
answers the closed ambiguity check that decides whether a released reading may answer a
question the judgment asked to clarify; otherwise the clarification always wins.
``FDAI_SEMANTIC_TYPED_ONLY=1`` makes that path the only way an operational read answers; it
needs both other settings in the local venue, and the composition refuses to start without
them instead of silently answering from the legacy path.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable, Mapping
from pathlib import Path

import httpx
from fdai_service_contracts.venue import (
    ExecutionVenue,
    ExecutionVenueError,
    resolve_execution_venue,
)

from fdai.core.conversation.semantic_compiled_answers import (
    CompiledAnswerPath,
    CompiledAnswerSettings,
)
from fdai.core.conversation.semantic_judgment_coverage import JudgmentCoverageReview
from fdai.core.conversation.semantic_second_reader import SemanticSecondReader
from fdai.core.conversation.semantic_type_grounding import ResourceTypeGrounding
from fdai.core.prompts import FileSystemPromptRegistry, compose_static_selection
from fdai.delivery.azure.llm.completion_body import uses_completion_token_budget
from fdai.delivery.azure.llm.request_target import ModelRequestTarget
from fdai.delivery.azure.llm.semantic_question_form import (
    AzureOpenAIQuestionFormConfig,
    AzureOpenAIQuestionFormModel,
)
from fdai.rule_catalog.schema.llm_resolver import ResolvedModels
from fdai.shared.providers.workload_identity import WorkloadIdentity

from .semantic_query_model_targets import t1_model_targets

SECOND_READER_ENV = "FDAI_SEMANTIC_SECOND_READER"
COMPILED_ANSWERS_ENV = "FDAI_SEMANTIC_COMPILED_ANSWERS"
PRODUCTION_SHADOW_ENV = "FDAI_SEMANTIC_PRODUCTION_SHADOW"
TYPED_ONLY_ENV = "FDAI_SEMANTIC_TYPED_ONLY"
_LOGGER = logging.getLogger(__name__)


def build_second_reader(
    *,
    resolved: ResolvedModels,
    identity: WorkloadIdentity,
    http_client: httpx.AsyncClient,
    endpoint: str | None,
    endpoint_resolver: Callable[[str], str] | None,
    catalog_root: Path,
    owner_loop: asyncio.AbstractEventLoop,
    held_capabilities: frozenset[str] = frozenset(),
) -> SemanticSecondReader | None:
    """Return the second reader when the typed setting enables it, otherwise ``None``."""

    typed_only = typed_only_enabled()
    if os.environ.get(SECOND_READER_ENV) != "1":
        return None
    targets = t1_model_targets(
        resolved,
        endpoint=endpoint,
        endpoint_resolver=endpoint_resolver,
        held_capabilities=held_capabilities,
    )
    second = second_reader_target(targets)
    if second is None:
        if typed_only:
            raise ValueError("typed-only answering requires a second reader deployment")
        _LOGGER.info("semantic_second_reader_disabled", extra={"reason": "second_model_absent"})
        return None
    prompts = FileSystemPromptRegistry(catalog_root)
    form_prompt = compose_static_selection(prompts.resolve("semantic.question_form"))
    concept_prompt = compose_static_selection(prompts.resolve("semantic.concept_selection"))
    extraction_prompt = compose_static_selection(prompts.resolve("semantic.constraint_extraction"))
    compiled = compiled_answers_enabled()
    production_shadow = production_shadow_enabled()
    direction_prompt = (
        compose_static_selection(prompts.resolve("semantic.direction_check"))
        if compiled or production_shadow
        else None
    )
    ambiguity_prompt = (
        compose_static_selection(prompts.resolve("semantic.ambiguity_check"))
        if compiled or production_shadow
        else None
    )
    third = ambiguity_reader_target(targets, second)

    def reader_config(with_direction: bool) -> AzureOpenAIQuestionFormConfig:
        direction = direction_prompt if with_direction else None
        ambiguity = ambiguity_prompt if with_direction and third is not None else None
        return AzureOpenAIQuestionFormConfig(
            candidates=targets[:1],
            form_system_prompt=form_prompt.system_text,
            form_prompt_manifest=form_prompt.replay_manifest(),
            concept_system_prompt=concept_prompt.system_text,
            concept_prompt_manifest=concept_prompt.replay_manifest(),
            extraction_system_prompt=extraction_prompt.system_text,
            extraction_prompt_manifest=extraction_prompt.replay_manifest(),
            extraction_candidates=(second,),
            direction_system_prompt=direction.system_text if direction is not None else None,
            direction_prompt_manifest=direction.replay_manifest()
            if direction is not None
            else None,
            direction_candidates=(direction_reader_target(targets) or second,),
            direction_max_tokens=2_048 if direction is not None else 64,
            ambiguity_system_prompt=ambiguity.system_text if ambiguity is not None else None,
            ambiguity_prompt_manifest=(
                ambiguity.replay_manifest() if ambiguity is not None else None
            ),
            ambiguity_candidates=(third,) if ambiguity is not None and third is not None else (),
            ambiguity_max_tokens=2_048 if ambiguity is not None else 64,
            timeout_seconds=60.0 if direction is not None else 40.0,
        )

    try:
        config = reader_config(compiled or production_shadow)
    except ValueError:
        if typed_only:
            raise
        # An invalid optional path never disables the second reader or the semantic runtime.
        _LOGGER.warning("semantic_compiled_answers_disabled", extra={"reason": "config_invalid"})
        compiled = False
        config = reader_config(False)
    reader = AzureOpenAIQuestionFormModel(
        identity=identity,
        http_client=http_client,
        config=config,
    )
    return SemanticSecondReader(
        type_grounding=ResourceTypeGrounding(chooser=reader, owner_loop=owner_loop),
        coverage_review=JudgmentCoverageReview(extractor=reader, owner_loop=owner_loop),
        compiled_answers=(
            (
                lambda gateway, purpose, clock: CompiledAnswerPath(
                    model=reader,
                    owner_loop=owner_loop,
                    gateway=gateway,
                    purpose=purpose,
                    clock=clock,
                    settings=CompiledAnswerSettings(typed_only=typed_only),
                    ambiguity_reader=reader,
                )
            )
            if compiled
            else None
        ),
    )


def compiled_answers_enabled(environment: Mapping[str, str] | None = None) -> bool:
    """Return whether the local profile enabled compiled answers; other venues never do."""

    source = os.environ if environment is None else environment
    if source.get(COMPILED_ANSWERS_ENV) != "1":
        return False
    try:
        venue = resolve_execution_venue(source)
    except ExecutionVenueError:
        return False
    if venue is not ExecutionVenue.LOCAL:
        _LOGGER.warning("semantic_compiled_answers_ignored", extra={"reason": "venue_not_local"})
        return False
    return True


def typed_only_enabled(environment: Mapping[str, str] | None = None) -> bool:
    """Return whether typed-only answering is on; fail closed when its path cannot exist."""

    source = os.environ if environment is None else environment
    if source.get(TYPED_ONLY_ENV) != "1":
        return False
    if source.get(SECOND_READER_ENV) != "1" or not compiled_answers_enabled(source):
        raise ValueError(
            "typed-only answering requires the second reader and compiled answers in the "
            "local venue"
        )
    return True


def production_shadow_enabled(environment: Mapping[str, str] | None = None) -> bool:
    """Return whether observe-only production shadow wiring should bind reader prompts."""

    source = os.environ if environment is None else environment
    return source.get(PRODUCTION_SHADOW_ENV) == "1"


def direction_reader_target(
    targets: tuple[ModelRequestTarget, ...],
) -> ModelRequestTarget | None:
    """Return the first later reasoning deployment, which confirms relation directions."""

    return next(
        (
            target
            for target in targets[1:]
            if target.deployment != targets[0].deployment
            and uses_completion_token_budget(target.deployment)
        ),
        None,
    )


def ambiguity_reader_target(
    targets: tuple[ModelRequestTarget, ...],
    second: ModelRequestTarget,
) -> ModelRequestTarget | None:
    """Return a third family for the ambiguity check, or ``None`` when none exists.

    The judgment and the question-form proposer read with the primary deployment, and the
    blind review with the second reader, so the ambiguity reader is the direction reader
    only when it is neither of them.
    """

    third = direction_reader_target(targets)
    if third is None or third.deployment in {targets[0].deployment, second.deployment}:
        return None
    return third


def second_reader_target(
    targets: tuple[ModelRequestTarget, ...],
) -> ModelRequestTarget | None:
    """Return the first later deployment whose requests carry an ordinary token bound."""

    return next(
        (
            target
            for target in targets[1:]
            if target.deployment != targets[0].deployment
            and not uses_completion_token_budget(target.deployment)
        ),
        None,
    )


__all__ = [
    "COMPILED_ANSWERS_ENV",
    "PRODUCTION_SHADOW_ENV",
    "SECOND_READER_ENV",
    "ambiguity_reader_target",
    "build_second_reader",
    "compiled_answers_enabled",
    "production_shadow_enabled",
    "typed_only_enabled",
    "direction_reader_target",
    "second_reader_target",
]
