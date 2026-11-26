"""Preflight PR-check publisher Protocol - Wave P.3.

Ships the seam a delivery adapter (GitHub Checks API, Azure DevOps
status hook, or a fork's equivalent) implements to post a
:class:`~fdai.core.deploy_preflight.report.DeploymentReadinessReport`
onto an infrastructure PR. The upstream ships the Protocol + fake; the
real Checks-API adapter is fork territory (see
[deployment-preflight.md](../../../../docs/roadmap/deployment/deployment-preflight.md)
under Delivery Increments).

Design invariants
-----------------

- **Publish, not mutate**: the adapter writes an annotation onto an
  existing PR; it does NOT open / merge / close.
- **Idempotent by ``check_key``**: a second call with the same key
  returns ``already_existed=True`` and MUST NOT post a duplicate Check.
- **Shadow reviews are advisory**: when the source report ran in
  shadow mode, the adapter MUST label the Check as advisory so a CI
  provider does not gate a merge on it.
- **No privileged identity in ``core/``**: real adapters live under
  ``delivery/`` and carry their own auth (GitHub App token,
  Azure DevOps PAT, etc.); the core preflight subsystem consumes only
  this Protocol.
- **Fail-closed**: adapter transport / auth failures raise
  :class:`PreflightCheckPublishError`; the caller treats a raise as
  "abstain" (do not retry blindly).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from fdai.core.deploy_preflight.report import DeploymentReadinessReport


@dataclass(frozen=True, slots=True)
class PreflightCheck:
    """One Preflight report post + metadata for the audit chain."""

    pr_ref: str
    """Opaque handle of the infrastructure pull request being annotated.

    Format depends on the adapter (``owner/repo#123`` for GitHub, a
    numeric id for Azure DevOps). ``core/`` never parses this string.
    """

    check_key: str
    """Idempotency key. Same key on redelivery MUST NOT post a duplicate.

    Callers derive it from ``(pr_ref, report hash, preflight-run id)``
    so a re-run of the same preflight over the same PR is a no-op.
    """

    report: DeploymentReadinessReport
    """The report to render on the PR. The adapter is free to
    summarize; it MUST NOT drop the ``blocks_deploy`` verdict."""

    metadata: Mapping[str, str] = field(default_factory=dict)
    """Optional adapter-neutral k/v pairs (correlation id, deployer
    email, ...). Never carries secrets."""


@dataclass(frozen=True, slots=True)
class PreflightCheckReceipt:
    """Adapter-issued receipt for one publish attempt."""

    check_ref: str
    """Opaque handle for the posted Check / annotation."""

    url: str | None = None
    """Optional deep link a reviewer can open."""

    already_existed: bool = False
    """``True`` when the adapter detected a prior post with the same
    ``check_key`` and returned it unchanged. The caller MUST audit
    that path distinctly so redelivery is traceable."""


class PreflightCheckPublishError(RuntimeError):
    """Raised when an adapter refuses to post the Check.

    The upstream caller catches this and abstains rather than retrying
    blindly - a Check that cannot be posted is treated as "preflight
    has no opinion" for the CI-gate contract.
    """


@runtime_checkable
class PreflightCheckPublisher(Protocol):
    """Post a Preflight report onto an infrastructure PR."""

    async def publish(self, check: PreflightCheck) -> PreflightCheckReceipt:
        """Return a receipt for the publish attempt.

        Implementations MUST:

        - be **idempotent by ``check.check_key``** - a second call
          with the same key returns ``already_existed=True`` and MUST
          NOT post a duplicate Check;
        - label a Check derived from a ``shadow``-mode report as
          advisory so the CI provider does not gate a merge on it;
        - raise :class:`PreflightCheckPublishError` on any transport or
          policy failure; the caller treats a raise as "abstain".
        """
        ...


__all__ = [
    "PreflightCheck",
    "PreflightCheckPublishError",
    "PreflightCheckPublisher",
    "PreflightCheckReceipt",
]
