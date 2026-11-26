"""Bound current source authorization around a complete read, without granting write authority."""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Protocol

from fdai.shared.ontology.acl import ProjectionRequest

_DIGEST = re.compile(r"sha256:[a-f0-9]{64}")


class SourceReadAdmissionError(RuntimeError):
    """Current source authorization could not be established for this read."""


@dataclass(frozen=True, slots=True)
class SourceReadAdmission:
    """One current principal/purpose admission over the complete derived-source universe.

    ``source_state_digest`` binds the complete source set, current versions, ACL generations,
    authority, retention, and effective-time admission. It is not a projection approval.
    """

    principal_scope_digest: str
    purpose: str
    source_state_digest: str

    def __post_init__(self) -> None:
        if any(
            _DIGEST.fullmatch(value) is None
            for value in (self.principal_scope_digest, self.source_state_digest)
        ):
            raise ValueError("source read admission requires canonical SHA-256 digests")
        if (
            not self.purpose.strip()
            or self.purpose != self.purpose.strip()
            or len(self.purpose) > 128
        ):
            raise ValueError("source read admission requires a bounded purpose")


class SourceReadAdmissionReader(Protocol):
    """Independently authorize every active derived source, including an empty source set.

    Denial raises ``PermissionError``. Missing, partial, stale, or unavailable evidence raises
    ``SourceReadAdmissionError``. The reader must not accept a cached receipt as current
    authority. This deliberately conservative first seam admits the complete source universe,
    not a filtered subset whose hidden predicates or counts could disclose private facts.
    """

    async def authorize(
        self, *, principal_scope_digest: str, purpose: str
    ) -> SourceReadAdmission: ...


@asynccontextmanager
async def admitted_source_read(
    reader: SourceReadAdmissionReader | None,
    *,
    request: ProjectionRequest,
    purpose: str,
) -> AsyncIterator[None]:
    """Reauthorize before graph I/O and before releasing any graph, count, or index result."""
    if reader is None:
        yield
        return
    scope = request.principal_scope_digest
    if (
        scope is None
        or _DIGEST.fullmatch(scope) is None
        or not purpose.strip()
        or purpose not in request.declared_purposes
    ):
        raise PermissionError("source read admission requires authenticated scope and purpose")

    async def current() -> SourceReadAdmission:
        try:
            async with asyncio.timeout(5):
                result = await reader.authorize(principal_scope_digest=scope, purpose=purpose)
        except PermissionError:
            raise PermissionError("current source access is denied") from None
        except Exception:  # noqa: BLE001 - provider failures never disclose source content.
            raise SourceReadAdmissionError("current source admission is unavailable") from None
        if not isinstance(result, SourceReadAdmission) or (
            result.principal_scope_digest != scope or result.purpose != purpose
        ):
            raise SourceReadAdmissionError("current source admission does not match read")
        return result

    before = await current()
    yield
    if await current() != before:
        raise SourceReadAdmissionError("source authorization changed during graph read")
