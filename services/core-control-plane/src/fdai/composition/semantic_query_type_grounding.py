"""Compose the independent second reader for semantic planning.

The local launcher enables it with ``FDAI_SEMANTIC_SECOND_READER=1``; every other venue
keeps the current single-reader path until the reader is promoted. The primary reader
is the first resolved narrator deployment. The second reader is the first later
narrator deployment outside the completion-token (reasoning) request family, so its
closed choices and constraint quotes do not spend their bounded output on reasoning.
Without such a deployment no second reader exists and nothing binds through it.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from pathlib import Path

import httpx

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
        _LOGGER.info("semantic_second_reader_disabled", extra={"reason": "second_model_absent"})
        return None
    prompts = FileSystemPromptRegistry(catalog_root)
    form_prompt = compose_static_selection(prompts.resolve("semantic.question_form"))
    concept_prompt = compose_static_selection(prompts.resolve("semantic.concept_selection"))
    extraction_prompt = compose_static_selection(prompts.resolve("semantic.constraint_extraction"))
    reader = AzureOpenAIQuestionFormModel(
        identity=identity,
        http_client=http_client,
        config=AzureOpenAIQuestionFormConfig(
            candidates=targets[:1],
            form_system_prompt=form_prompt.system_text,
            form_prompt_manifest=form_prompt.replay_manifest(),
            concept_system_prompt=concept_prompt.system_text,
            concept_prompt_manifest=concept_prompt.replay_manifest(),
            extraction_system_prompt=extraction_prompt.system_text,
            extraction_prompt_manifest=extraction_prompt.replay_manifest(),
            extraction_candidates=(second,),
            timeout_seconds=40.0,
        ),
    )
    return SemanticSecondReader(
        type_grounding=ResourceTypeGrounding(chooser=reader, owner_loop=owner_loop),
        coverage_review=JudgmentCoverageReview(extractor=reader, owner_loop=owner_loop),
    )


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


__all__ = ["SECOND_READER_ENV", "build_second_reader", "second_reader_target"]
