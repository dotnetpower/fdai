"""Security finding ingestion - CSP-neutral seam feeding the assessment fold.

Design contract: ``docs/roadmap/operations/assurance-twin.md`` (assessment output)
and the Azure SRE Agent parity note in
``docs/internals/sre-agent-gap-analysis.md`` (P3-9).

:func:`~fdai.core.security.assessment.build_security_assessment` is a pure
fold over a bounded ``Sequence[Finding]``; it needs a live feed of those
findings. This Protocol is that seam: a provider that collects security
findings (Microsoft Defender for Cloud assessments, Application Gateway WAF
log signals) and normalizes them into CSP-neutral
:class:`~fdai.shared.providers.projection.Finding` values. ``core/`` sees
only this Protocol; concrete adapters live under ``delivery/`` and are wired
at the composition root.

Async by contract - a real backend query is I/O-bound. The upstream default
binding is :class:`EmptySecurityFindingProvider` (returns no findings), so a
security assessment with no live feed grades ``clear`` on an empty set rather
than fabricating a finding. Fail-closed on a real adapter error means the
scheduled assessment abstains, never auto-blocks on a partial read (and
shadow never blocks regardless).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from fdai.shared.providers.projection import Finding


class SecurityFindingProviderError(RuntimeError):
    """Raised on an unrecoverable provider failure.

    Fail-closed: the caller MUST NOT proceed to auto-block on a partial
    result; the assessment abstains (and shadow never blocks anyway).
    """


@runtime_checkable
class SecurityFindingProvider(Protocol):
    """Collect CSP-neutral security findings for an assessment pass."""

    async def collect(
        self, *, scope: str, since: datetime | None = None, until: datetime | None = None
    ) -> Sequence[Finding]:
        """Return security findings for ``scope`` in the optional window.

        An empty result is a valid answer (nothing flagged), NOT an error.
        """
        ...


class EmptySecurityFindingProvider:
    """Upstream default - reports no findings."""

    async def collect(
        self, *, scope: str, since: datetime | None = None, until: datetime | None = None
    ) -> Sequence[Finding]:  # noqa: ARG002 - Protocol conformance
        return ()


class CompositeSecurityFindingProvider:
    """Merge findings from several providers (e.g. Defender + WAF).

    Fail-closed as a whole: if any child raises
    :class:`SecurityFindingProviderError`, the composite re-raises rather
    than returning a partial merge, so a half-read never grades as a
    complete assessment.
    """

    def __init__(self, providers: Sequence[SecurityFindingProvider]) -> None:
        self._providers = tuple(providers)

    async def collect(
        self, *, scope: str, since: datetime | None = None, until: datetime | None = None
    ) -> Sequence[Finding]:
        merged: list[Finding] = []
        for provider in self._providers:
            merged.extend(await provider.collect(scope=scope, since=since, until=until))
        return tuple(merged)


__all__ = [
    "CompositeSecurityFindingProvider",
    "EmptySecurityFindingProvider",
    "SecurityFindingProvider",
    "SecurityFindingProviderError",
]
