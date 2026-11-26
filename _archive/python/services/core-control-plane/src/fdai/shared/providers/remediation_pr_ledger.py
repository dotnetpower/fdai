"""RemediationPrLedger - correlation lookup from event correlation_id to PR ref.

Realizes the second half of the out-of-band attribution rule in
``docs/roadmap/phases/phase-1-rule-catalog-t0.md § Out-of-Band Detection``:
a change is *authorized* when its ``correlation_id`` links back to a
merged remediation PR, even if the raw actor identity on the wire
looks unfamiliar to the pipeline-principal registry (a bot commit
merged by an operator, a manual re-run of a pipeline that lost its
service-principal handle, ...).

Design boundaries
-----------------

- ``core/`` depends only on the Protocol. A production adapter under
  ``delivery/gitops_pr/`` reads the git remote (or a mirror table) to
  answer :meth:`RemediationPrLedger.find_correlation`; the in-memory
  fake is fine for unit tests + shadow-mode dev.
- Lookup returns an opaque PR ref (matching the ``pr_ref`` produced
  by :class:`~fdai.shared.providers.remediation_pr.PublishReceipt`).
  Absence returns :data:`None` - never raise for "no match", so the
  detector can fold the check into a straight-line decision.
- No mutation surface exists on the Protocol: the ledger observes
  merges, it never records them. Writes to the ledger are the
  responsibility of the delivery layer / a git-webhook consumer.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable


@runtime_checkable
class RemediationPrLedger(Protocol):
    """Map a ``correlation_id`` to a merged remediation PR reference.

    Callers (the change-safety detector) treat a non-``None`` return
    as evidence the change was authored by a merged remediation PR
    and MAY classify the event as *authorized*. The ledger itself
    does not read the PR body - that is the executor / GitOps
    publisher's job.
    """

    def find_correlation(self, correlation_id: str) -> str | None:
        """Return the merged PR ref for ``correlation_id`` or ``None``.

        Implementations MUST be pure lookups (no side effects) and MUST
        NOT block on a network call - the detector runs on the
        event-loop hot path. A real adapter caches / preloads the
        merged-PR index and refreshes it out of band.
        """
        ...


class InMemoryRemediationPrLedger(RemediationPrLedger):
    """Dict-backed :class:`RemediationPrLedger` - upstream default + test fake.

    A fork replaces this with a git-adapter that hydrates from PR
    events (webhook or REST poll). Ships in ``shared/providers/`` (not
    ``testing/``) because ``core/`` needs a working default for the
    control-loop e2e path in dev, matching the pattern used by
    :class:`~fdai.shared.providers.exemption.InMemoryExemptionRegistry`
    and :class:`~fdai.shared.providers.pipeline_principal.InMemoryPipelinePrincipalRegistry`.
    """

    __slots__ = ("_index",)

    def __init__(self, correlations: Mapping[str, str] | None = None) -> None:
        # Copy the mapping so a caller cannot mutate the ledger via the
        # dict handed to the constructor.
        self._index: dict[str, str] = dict(correlations or {})

    def find_correlation(self, correlation_id: str) -> str | None:
        return self._index.get(correlation_id)

    # ------------------------------------------------------------------
    # Test / fork helper - NOT part of the Protocol.
    # ------------------------------------------------------------------

    def record(self, correlation_id: str, pr_ref: str) -> None:
        """Register a ``correlation_id -> pr_ref`` mapping.

        Intended for tests and a lightweight local dev harness that
        wants to simulate merged PRs without a real git backend. The
        Protocol has no mutation surface on purpose - production
        adapters observe merges, they do not synthesize them.
        """
        if not correlation_id:
            raise ValueError("correlation_id MUST be non-empty")
        if not pr_ref:
            raise ValueError("pr_ref MUST be non-empty")
        self._index[correlation_id] = pr_ref


__all__ = [
    "InMemoryRemediationPrLedger",
    "RemediationPrLedger",
]
