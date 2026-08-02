"""Remediation-PR publisher - CSP-neutral contract for the delivery layer.

The executor emits a rendered :class:`RemediationPr` and hands it to a
:class:`RemediationPrPublisher`. Concrete adapters live under
``delivery/gitops_pr/`` and MAY talk to GitHub / Azure DevOps / GitLab.
``core/`` only knows this Protocol - the same DI pattern the other five
provider Protocols use.

Why a dedicated contract (vs re-using ``EventBus``)
---------------------------------------------------

- PR opening is **not idempotent by delivery mechanics**; the adapter has
  to consult its remote to decide whether a PR for a given
  ``(idempotency_key, action_id)`` already exists. Modeling this via a
  Kafka topic would put non-idempotency inside the wire, not the adapter.
- ``ShadowExecutor`` writes an audit record whether or not a PR was
  opened (a rejected safety precondition still generates an audit entry).
  Splitting the publisher from the audit sink keeps that separation
  explicit: audit goes to ``StateStore``, PR intent goes here.

Shadow-mode invariant
---------------------

Every PR opened in P1 MUST be a **draft** and MUST carry the ``shadow``
label so it is reviewable but not mergeable through the normal flow
(see ``docs/roadmap/phases/phase-1-rule-catalog-t0.md § Remediation PR``).
The publisher enforces this by rejecting a :class:`RemediationPr` whose
``mode`` is anything but :attr:`~fdai.shared.contracts.models.Mode.SHADOW`
until Phase 2 promotes the ActionType to enforce.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable
from uuid import UUID

from fdai.shared.contracts.models import Mode


@dataclass(frozen=True, slots=True)
class RemediationPr:
    """Renderable remediation intent handed to a publisher adapter.

    Frozen so a caller cannot rewrite the intent between publish and
    audit; the adapter's :class:`PublishReceipt` is the only place a
    remote-assigned id (PR number, URL) surfaces.
    """

    action_id: UUID
    """Correlates back to :class:`~fdai.shared.contracts.models.Action`."""

    idempotency_key: str
    """Stable key from the source event; the adapter uses it to detect a
    prior open PR before creating a new one."""

    rule_ids: tuple[str, ...]
    """Citing rules that authored the action; embedded in the PR body."""

    title: str
    body: str
    """Rendered PR title + body. It carries the seven safeguards, including
    the content-addressed dry-run receipt, per the phase-1 contract."""

    patch: str
    """Rendered Terraform / IaC patch content the PR proposes."""

    patch_path: str
    """Repo-relative file the patch targets (e.g.
    ``infra/envs/dev/storage.tf``); adapters map this into a branch commit."""

    labels: tuple[str, ...] = ("shadow",)
    """Every P1 PR carries at least ``shadow``; the publisher fails
    closed on a `Mode.ENFORCE` intent that omits ``enforce``."""

    mode: Mode = Mode.SHADOW
    """New actions ship shadow-first; ``Mode.ENFORCE`` is a Phase 2
    promotion."""

    metadata: Mapping[str, str] = field(default_factory=dict)
    """Optional adapter-neutral k/v pairs (correlation id, tenant label,
    ...). Never carries secrets."""


@dataclass(frozen=True, slots=True)
class PublishReceipt:
    """Adapter-issued receipt for one publish attempt.

    ``pr_ref`` is opaque to ``core/`` - an adapter that talks to GitHub
    might use ``"owner/repo#123"``, an in-memory fake might use a
    monotonically increasing counter. Consumers MUST treat it as a
    correlation string only.
    """

    pr_ref: str
    url: str | None = None
    already_existed: bool = False
    """``True`` when the adapter detected a prior open PR for the same
    ``idempotency_key`` and returned it unchanged; the executor MUST
    audit that path distinctly so re-delivery is auditable."""


@runtime_checkable
class RemediationPrPublisher(Protocol):
    """Publish a rendered remediation intent as a draft, shadow-labeled PR."""

    async def publish(self, pr: RemediationPr) -> PublishReceipt:
        """Return a receipt for the publish attempt.

        Implementations MUST:

        - be **idempotent by ``pr.idempotency_key``** - a second call
          with the same key returns ``already_existed=True`` and MUST
          NOT open a duplicate PR;
        - reject an intent whose ``mode`` is enforce and whose ``labels``
          do not include ``enforce`` (P1 promotion contract);
        - never merge, never remove the ``shadow`` label, never bypass
          human review; the publisher is a **write-once** contract.
        """
        ...


__all__ = [
    "PublishReceipt",
    "RemediationPr",
    "RemediationPrPublisher",
]
