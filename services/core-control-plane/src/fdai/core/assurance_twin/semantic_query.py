"""Strict Assurance Twin semantic compilation and inert discovery handoff."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from fdai.core.assurance_twin.query import (
    AbstainCode,
    AbstainResult,
    CompiledQuery,
    NlQueryCompiler,
    QueryVerificationError,
    QueryVerifier,
)


class DiscoveryHandoffStatus(StrEnum):
    """Outcome of an authority-free query-gap handoff."""

    NOT_REQUIRED = "not_required"
    EMITTED = "emitted"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class AssuranceTwinQueryGap:
    """Content-free candidate for the governed discovery loop."""

    schema_version: str
    question_digest: str
    compiler_revision: str
    code: AbstainCode
    grants_authority: bool = False


@runtime_checkable
class AssuranceTwinDiscoverySink(Protocol):
    """Publish an inert query gap for Norns/Mimir review."""

    async def publish(self, gap: AssuranceTwinQueryGap) -> None: ...


@dataclass(frozen=True, slots=True)
class AssuranceTwinCompilation:
    """Verified read plan or explicit abstention plus discovery disposition."""

    compiled: CompiledQuery
    discovery_status: DiscoveryHandoffStatus


class AssuranceTwinSemanticQueryCoordinator:
    """Compile one question without lexical fallback or mutation authority."""

    def __init__(
        self,
        *,
        compiler: NlQueryCompiler,
        verifier: QueryVerifier,
        compiler_revision: str,
        discovery_sink: AssuranceTwinDiscoverySink | None,
    ) -> None:
        if not compiler_revision.strip() or len(compiler_revision) > 128:
            raise ValueError("compiler_revision MUST be bounded and non-empty")
        self._compiler = compiler
        self._verifier = verifier
        self._compiler_revision = compiler_revision
        self._discovery_sink = discovery_sink

    async def compile(self, question: str) -> AssuranceTwinCompilation:
        """Return only a strict verified read plan or an explicit abstention."""

        digest = question_digest(question)
        proposed = self._compiler.compile(question)
        if isinstance(proposed, AbstainResult):
            status = await self._handoff(proposed.code, digest=digest)
            return AssuranceTwinCompilation(proposed, status)
        try:
            verified = self._verifier.verify(
                proposed,
                expected_input_digest=digest,
            )
        except QueryVerificationError as error:
            abstain = AbstainResult(
                code=AbstainCode.AMBIGUOUS,
                reason=f"semantic query verification failed:{error.kind}",
                hint=error.field,
            )
            status = await self._handoff(abstain.code, digest=digest)
            return AssuranceTwinCompilation(abstain, status)
        return AssuranceTwinCompilation(verified, DiscoveryHandoffStatus.NOT_REQUIRED)

    async def _handoff(self, code: AbstainCode, *, digest: str) -> DiscoveryHandoffStatus:
        if self._discovery_sink is None:
            return DiscoveryHandoffStatus.UNAVAILABLE
        await self._discovery_sink.publish(
            AssuranceTwinQueryGap(
                schema_version="1.0.0",
                question_digest=digest,
                compiler_revision=self._compiler_revision,
                code=code,
            )
        )
        return DiscoveryHandoffStatus.EMITTED


def question_digest(question: str) -> str:
    """Return a replay identity without retaining operator text."""

    return f"sha256:{hashlib.sha256(question.encode()).hexdigest()}"


__all__ = [
    "AssuranceTwinCompilation",
    "AssuranceTwinDiscoverySink",
    "AssuranceTwinQueryGap",
    "AssuranceTwinSemanticQueryCoordinator",
    "DiscoveryHandoffStatus",
    "question_digest",
]
