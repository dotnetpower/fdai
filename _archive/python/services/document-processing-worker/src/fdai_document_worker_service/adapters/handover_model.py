"""Bounded independently reviewed Azure OpenAI handover interpretation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from azure.core.credentials_async import AsyncTokenCredential
from fdai_service_contracts import DocumentEnvelope, HandoverMapping
from fdai_service_contracts.handover import HandoverModelReview

from ..handover_interpretation import (
    ReviewedHandoverInterpretation,
    handover_proposal_digest,
    validate_interpretation,
)

_HANDOVER_ROLES = {
    "Odin": "Cross-team coordination and escalation; never execute or approve.",
    "Thor": "Execute authorized changes; never judge or approve.",
    "Forseti": "Judge proposed changes; never execute or approve.",
    "Huginn": "Normalize and route events; never judge or execute.",
    "Heimdall": "Observe current state and independent effects; never execute.",
    "Vidar": "Authorized rollback and recovery; never approve.",
    "Var": "Human approval coordination; never execute or replace human authority.",
    "Bragi": "Operator explanation and translation; presentation only.",
    "Saga": "Durable audit and handoff recordkeeping; never judge or approve.",
    "Mimir": "Governed rule and policy lifecycle; never self-promote.",
    "Muninn": "Institutional knowledge and memory; never grant authority.",
    "Norns": "Inert improvement candidates; never activate or execute.",
    "Njord": "Cost governance evidence and advice; never execute.",
    "Freyr": "Capacity evidence and sizing advice; never execute.",
    "Loki": "Bounded chaos proposals and resilience evidence; never auto-execute.",
}


class ModelCallReservation(Protocol):
    async def reserve_model_calls(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        source_sha256: str,
    ) -> bool: ...

    async def record_model_usage(
        self,
        *,
        document_id: UUID,
        version_id: UUID,
        stage: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_micros: int,
        pricing_sha256: str,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class HandoverModelTarget:
    endpoint: str
    deployment: str
    publisher: str
    family: str
    input_micros_per_million: int = 0
    output_micros_per_million: int = 0
    api_version: str = "2025-01-01-preview"

    def __post_init__(self) -> None:
        parsed = urlsplit(self.endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or any(
                not value.strip() or len(value) > 128
                for value in (
                    self.deployment,
                    self.publisher,
                    self.family,
                    self.api_version,
                )
            )
        ):
            raise ValueError("handover model target is invalid")
        if (
            type(self.input_micros_per_million) is not int
            or type(self.output_micros_per_million) is not int
            or self.input_micros_per_million < 0
            or self.output_micros_per_million < 0
        ):
            raise ValueError("handover model prices MUST be non-negative integer micros")

    @property
    def identity(self) -> str:
        return f"{self.publisher}:{self.family}:{self.deployment}"


class AzureReviewedHandoverInterpreter:
    """Two reserved model calls; source checks, independent review and no hidden retry."""

    def __init__(
        self,
        *,
        author: HandoverModelTarget,
        reviewer: HandoverModelTarget,
        credential: AsyncTokenCredential,
        client: httpx.AsyncClient,
        reservations: ModelCallReservation,
        author_prompt: str,
        reviewer_prompt: str,
        max_input_bytes: int = 64_000,
        timeout_seconds: float = 20,
    ) -> None:
        if (author.endpoint.rstrip("/").casefold(), author.deployment.casefold()) == (
            reviewer.endpoint.rstrip("/").casefold(),
            reviewer.deployment.casefold(),
        ) or (author.publisher.casefold(), author.family.casefold()) == (
            reviewer.publisher.casefold(),
            reviewer.family.casefold(),
        ):
            raise ValueError("handover author and reviewer targets MUST be independent")
        if (
            not author_prompt.strip()
            or not reviewer_prompt.strip()
            or isinstance(max_input_bytes, bool)
            or not isinstance(max_input_bytes, int)
            or max_input_bytes < 1
        ):
            raise ValueError("handover model prompts and input budget are required")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 30
        ):
            raise ValueError("handover model deadline MUST be in (0, 30]")
        self._author, self._reviewer = author, reviewer
        self._credential, self._client, self._reservations = credential, client, reservations
        self._author_prompt, self._reviewer_prompt = author_prompt, reviewer_prompt
        self._max_input_bytes, self._timeout = max_input_bytes, timeout_seconds

    async def interpret(self, envelope: DocumentEnvelope) -> ReviewedHandoverInterpretation:
        lines = [line for unit in envelope.units for line in unit.text.splitlines()]
        payload = {
            "document_id": str(envelope.document_id),
            "version_id": str(envelope.version_id),
            "source_sha256": envelope.source_sha256,
            "lines": [{"line": index + 1, "text": text} for index, text in enumerate(lines)],
            "execution_authority": False,
            "agent_roles": _HANDOVER_ROLES,
            "role_binding_authority": False,
        }
        if len(json.dumps(payload, ensure_ascii=False).encode()) > self._max_input_bytes:
            return ReviewedHandoverInterpretation(unavailable_reason="input_budget_exceeded")
        async with asyncio.timeout(self._timeout):
            if not await self._reservations.reserve_model_calls(
                document_id=envelope.document_id,
                version_id=envelope.version_id,
                source_sha256=envelope.source_sha256,
            ):
                return ReviewedHandoverInterpretation(unavailable_reason="model_budget_denied")
            model_schema = HandoverMapping.model_json_schema()
            definitions = model_schema.pop("$defs", {})
            schema = {
                "type": "object",
                "additionalProperties": False,
                "required": ["mappings"],
                "properties": {
                    "mappings": {"type": "array", "maxItems": 64, "items": model_schema}
                },
                "$defs": definitions,
            }
            _strict_schema(schema)
            author_response = await self._complete(
                self._author, self._author_prompt, payload, schema
            )
            if author_response is not None:
                await self._record_usage(envelope, "author", self._author, author_response)
            authored = author_response.proposal if author_response is not None else None
            if not isinstance(authored, dict) or set(authored) != {"mappings"}:
                return ReviewedHandoverInterpretation(unavailable_reason="author_unavailable")
            raw = authored["mappings"]
            if not isinstance(raw, list) or not 1 <= len(raw) <= 64:
                return ReviewedHandoverInterpretation(unavailable_reason="author_abstained")
            mappings = tuple(HandoverMapping.model_validate(item) for item in raw)
            digest = handover_proposal_digest(mappings)
            provisional = HandoverModelReview(
                author_identity=self._author.identity,
                reviewer_identity=self._reviewer.identity,
                source_sha256=envelope.source_sha256,
                proposal_sha256=digest,
                reviewed_mapping_count=len(mappings),
            )
            candidate = ReviewedHandoverInterpretation(mappings=mappings, review=provisional)
            if not validate_interpretation(candidate, envelope, max_candidates=64):
                return ReviewedHandoverInterpretation(
                    unavailable_reason="source_grounding_rejected"
                )
            review_schema = {
                "type": "object",
                "additionalProperties": False,
                "required": ["proposal_sha256", "accepted", "reviewed_mapping_count"],
                "properties": {
                    "proposal_sha256": {"type": "string"},
                    "accepted": {"type": "boolean"},
                    "reviewed_mapping_count": {"type": "integer"},
                },
            }
            review_response = await self._complete(
                self._reviewer,
                self._reviewer_prompt,
                {
                    **payload,
                    "proposal_sha256": digest,
                    "mappings": [
                        mapping.model_dump(mode="json", exclude_computed_fields=True)
                        for mapping in mappings
                    ],
                },
                review_schema,
            )
            if review_response is not None:
                await self._record_usage(envelope, "reviewer", self._reviewer, review_response)
            reviewed = review_response.proposal if review_response is not None else None
            if (
                not isinstance(reviewed, dict)
                or set(reviewed) != {"proposal_sha256", "accepted", "reviewed_mapping_count"}
                or reviewed["accepted"] is not True
                or reviewed["proposal_sha256"] != digest
                or type(reviewed["reviewed_mapping_count"]) is not int
                or reviewed["reviewed_mapping_count"] != len(mappings)
            ):
                return ReviewedHandoverInterpretation(
                    unavailable_reason="independent_review_rejected"
                )
            if author_response is None or review_response is None:
                return ReviewedHandoverInterpretation(unavailable_reason="usage_unavailable")
            prices = [
                [target.identity, target.input_micros_per_million, target.output_micros_per_million]
                for target in (self._author, self._reviewer)
            ]
            cost = sum(
                (
                    result.prompt_tokens * target.input_micros_per_million
                    + result.completion_tokens * target.output_micros_per_million
                    + 999_999
                )
                // 1_000_000
                for result, target in (
                    (author_response, self._author),
                    (review_response, self._reviewer),
                )
            )
            return ReviewedHandoverInterpretation(
                mappings=mappings,
                review=provisional.model_copy(
                    update={
                        "prompt_tokens": author_response.prompt_tokens
                        + review_response.prompt_tokens,
                        "completion_tokens": author_response.completion_tokens
                        + review_response.completion_tokens,
                        "cost_micros": cost,
                        "pricing_sha256": hashlib.sha256(
                            json.dumps(prices, separators=(",", ":")).encode()
                        ).hexdigest(),
                    }
                ),
            )

    async def _complete(
        self,
        target: HandoverModelTarget,
        prompt: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
    ) -> HandoverStructuredResponse | None:
        token = await self._credential.get_token("https://cognitiveservices.azure.com/.default")
        response = await self._client.post(
            f"{target.endpoint.rstrip('/')}/openai/deployments/{target.deployment}/chat/completions",
            params={"api-version": target.api_version},
            headers={"Authorization": f"Bearer {token.token}"},
            json={
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "handover_grounded_output",
                        "strict": True,
                        "schema": schema,
                    },
                },
                "max_completion_tokens": 2_048,
            },
        )
        response.raise_for_status()
        body = response.json()
        usage = body.get("usage")
        choices = body.get("choices")
        if not isinstance(usage, dict) or any(
            type(usage.get(key)) is not int or usage[key] < 0
            for key in ("prompt_tokens", "completion_tokens")
        ):
            return None
        proposal: object = None
        if isinstance(choices, list) and len(choices) == 1 and isinstance(choices[0], dict):
            choice = choices[0]
            message = choice.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if (
                choice.get("finish_reason") == "stop"
                and isinstance(content, str)
                and len(content.encode()) <= 128_000
            ):
                try:
                    proposal = json.loads(content)
                except ValueError:
                    proposal = None
        return HandoverStructuredResponse(
            proposal=proposal,
            prompt_tokens=usage["prompt_tokens"],
            completion_tokens=usage["completion_tokens"],
        )

    async def _record_usage(
        self,
        envelope: DocumentEnvelope,
        stage: str,
        target: HandoverModelTarget,
        response: HandoverStructuredResponse,
    ) -> None:
        pricing = [
            target.identity,
            target.input_micros_per_million,
            target.output_micros_per_million,
        ]
        cost = (
            response.prompt_tokens * target.input_micros_per_million
            + response.completion_tokens * target.output_micros_per_million
            + 999_999
        ) // 1_000_000
        await self._reservations.record_model_usage(
            document_id=envelope.document_id,
            version_id=envelope.version_id,
            stage=stage,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            cost_micros=cost,
            pricing_sha256=hashlib.sha256(
                json.dumps(pricing, separators=(",", ":")).encode()
            ).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class HandoverStructuredResponse:
    proposal: object
    prompt_tokens: int
    completion_tokens: int

    def __post_init__(self) -> None:
        if any(
            type(value) is not int or value < 0
            for value in (self.prompt_tokens, self.completion_tokens)
        ):
            raise ValueError("handover measured usage MUST be non-negative integer tokens")


def _strict_schema(value: object) -> None:
    if isinstance(value, dict):
        value.pop("default", None)
        if value.get("type") == "object":
            properties = value.get("properties", {})
            value["additionalProperties"] = False
            value["required"] = list(properties)
        if "const" in value:
            value["enum"] = [value.pop("const")]
        for child in value.values():
            _strict_schema(child)
    elif isinstance(value, list):
        for child in value:
            _strict_schema(child)
