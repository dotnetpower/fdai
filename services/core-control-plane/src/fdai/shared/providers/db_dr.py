"""Deep DB-DR provider Protocols - restore + integrity + smoke.

Realizes the wire-level contract the P3 :class:`DbDrVerifier` uses to
run the three-phase Deep DB-DR test described in
[`docs/roadmap/phases/phase-3-integrated-loop.md § Deep DB-DR`]:

    1. Restore a snapshot / PITR into an **isolated environment** - no
       write path back to production.
    2. **Verify integrity deterministically** - row counts, cryptographic
       checksums, referential-constraint consistency; any mismatch fails
       the run.
    3. Run **app-level smoke tests** - representative read + write
       operations against the restored copy.

Each phase sits behind its own Protocol so the orchestrator stays
CSP-neutral: the Azure PITR restore, a pgcompare-style integrity
checker, and a smoke harness are three independent adapters bound at
the composition root.

Design boundaries
-----------------

- ``core/`` MAY reference this module (it lives under
  ``fdai.shared.providers``) but MUST NOT import a concrete
  implementation. Bindings happen at the composition root; the Azure
  adapter under
  :mod:`fdai.delivery.azure.db_dr_restore` and the fakes under
  :mod:`fdai.shared.providers.testing.db_dr` never leak through
  ``core/``.
- Every operation is ``async`` because a real adapter makes HTTP calls
  under a bearer token issued by
  :class:`~fdai.shared.providers.workload_identity.WorkloadIdentity`
  or a psycopg round trip against the restored server.
- Handles are frozen: once the restore returns, the caller can hand
  the same handle to the integrity checker and the smoke runner and
  eventually to :meth:`DbRestoreAdapter.teardown`. Adapters are
  state-free - a shared adapter serves many concurrent verifier runs.

Safety invariants
-----------------

- **Isolation** - the restore contract MUST create a resource in a
  namespace that is not the production one (fresh resource-group /
  fresh cluster / fresh namespace). Concrete adapters enforce this
  before returning the handle.
- **Fail-closed** - every phase raises :class:`DbDrError` on transport
  failure, auth failure, partial restore, or any state the adapter
  cannot classify. Silent success on a partial restore is a defect.
- **Idempotent teardown** - :meth:`DbRestoreAdapter.teardown` MUST NOT
  raise on an already-torn-down handle; the verifier calls it in a
  best-effort ``finally`` clause and cannot mask the primary failure.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable


class IntegrityMismatchKind(StrEnum):
    """Enumerates every reason an :class:`IntegrityChecker` may flag a mismatch.

    Kept small on purpose - adding a new kind is a reviewable
    contract change so downstream audit consumers cannot silently miss
    a novel failure category.
    """

    ROW_COUNT = "row_count"
    """Restored table has a different row count than the source snapshot."""

    CHECKSUM = "checksum"
    """Cryptographic (sha256) content checksum diverged for a table."""

    FOREIGN_KEY = "foreign_key"
    """Referential integrity constraint failed against the restored copy."""


@dataclass(frozen=True, slots=True)
class IntegrityMismatch:
    """One recorded divergence between the restored copy and the source.

    Every field is small, structured, and safe to persist to the audit
    log; a mismatch NEVER embeds a raw row payload or a secret. The
    ``detail`` string is a short, log-safe rendering the operator uses
    to reproduce the failure manually.
    """

    kind: IntegrityMismatchKind
    table: str
    detail: str


@dataclass(frozen=True, slots=True)
class DbRestoreConfig:
    """Input to :meth:`DbRestoreAdapter.restore`.

    ``source_ref`` is a CSP-neutral pointer to the production DB whose
    snapshot / PITR checkpoint is being restored. For Azure PG Flexible
    this is the ARM id of the source server; other adapters resolve
    the value in the same shape.

    ``target_resource_group`` MUST be a fresh, dedicated group - the
    Azure adapter refuses a config whose target group name equals the
    source group name to preserve the isolation invariant.
    """

    experiment_id: str
    source_ref: str
    target_server_name: str
    target_resource_group: str
    target_location: str
    point_in_time_utc: datetime | None = None
    """UTC instant to restore to. ``None`` restores from the most
    recent available backup (the substrate picks the checkpoint)."""


@dataclass(frozen=True, slots=True)
class DbRestoreHandle:
    """Opaque reference to one restored, isolated DB environment.

    Frozen: the caller cannot mutate the pointer to another restore
    mid-run. ``target_ref`` is the substrate-issued resource id (ARM
    id on Azure) of the restored server; ``endpoint`` is the fqdn the
    integrity checker + smoke runner connect to.
    """

    experiment_id: str
    source_ref: str
    target_ref: str
    endpoint: str
    resource_group: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    """Frozen result of one :meth:`IntegrityChecker.check` invocation.

    ``mismatches`` is exhaustive: every divergence the checker observed
    is recorded so the verifier fails the DR test on ANY mismatch, per
    phase-3 § Deep DB-DR (record every mismatch - DO NOT average away).
    """

    table_row_counts: Mapping[str, int]
    checksums: Mapping[str, str]
    mismatches: tuple[IntegrityMismatch, ...] = ()

    @property
    def mismatch_count(self) -> int:
        """Total number of divergences recorded."""
        return len(self.mismatches)

    @property
    def is_clean(self) -> bool:
        """``True`` iff the checker reported zero mismatches."""
        return not self.mismatches


@dataclass(frozen=True, slots=True)
class SmokeCheck:
    """One representative operation exercised against the restored copy.

    ``name`` identifies the operation (e.g. ``read-recent-orders``,
    ``insert-then-select``); ``passed`` is the boolean verdict; the
    ``detail`` string carries a short, log-safe context for a failure.
    """

    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class SmokeReport:
    """Frozen result of one :meth:`SmokeRunner.run` invocation."""

    checks: tuple[SmokeCheck, ...] = ()

    @property
    def passed(self) -> bool:
        """``True`` iff every declared smoke check passed.

        Empty check tuples are treated as ``False`` - a smoke report
        with zero exercised operations is not a passing signal, it is
        a misconfigured runner.
        """
        return bool(self.checks) and all(c.passed for c in self.checks)

    @property
    def failures(self) -> tuple[SmokeCheck, ...]:
        """Tuple of failing checks, in the order the runner produced them."""
        return tuple(c for c in self.checks if not c.passed)


class DbDrError(RuntimeError):
    """Raised on any unrecoverable failure in a DB-DR provider adapter.

    The message is safe to log - implementations MUST NOT embed raw
    tokens, subscription ids, or vendor error bodies larger than a
    short truncated snippet.
    """

    def __init__(
        self,
        message: str,
        *,
        experiment_id: str,
        phase: str,
        status_code: int | None = None,
    ) -> None:
        code = f" (HTTP {status_code})" if status_code is not None else ""
        super().__init__(f"{message}{code} [experiment_id={experiment_id}, phase={phase}]")
        self.message = message
        self.experiment_id = experiment_id
        self.phase = phase
        self.status_code = status_code


@runtime_checkable
class DbRestoreAdapter(Protocol):
    """Create + tear down an isolated restored DB environment.

    Contract:

    - :meth:`restore` MUST create the target in a namespace distinct
      from the source (isolation invariant). Adapters raise
      :class:`DbDrError` before returning a handle on any partial /
      unfinished restore.
    - :meth:`teardown` MUST be idempotent - the verifier invokes it in
      a ``finally`` clause and cannot let a substrate outage mask the
      primary failure.
    """

    async def restore(self, config: DbRestoreConfig) -> DbRestoreHandle:
        """Restore the source snapshot / PITR into a fresh isolated env.

        Raises :class:`DbDrError` on any failure (auth, transport,
        partial restore, isolation-invariant violation) so the caller
        can audit the failure without a half-created environment
        leaking downstream.
        """
        ...

    async def teardown(self, handle: DbRestoreHandle) -> None:
        """Remove the restored environment referenced by ``handle``.

        Idempotent: a teardown on an already-torn-down or never-created
        environment MUST NOT raise. Real substrate outages MAY raise
        :class:`DbDrError` - the caller records the error but keeps
        the primary verdict.
        """
        ...


@runtime_checkable
class IntegrityChecker(Protocol):
    """Deterministic verifier over a restored DB.

    Compares row counts, cryptographic checksums, and referential /
    constraint consistency between the restored copy pointed at by the
    handle and the source snapshot. Implementations MUST record every
    observed mismatch on the returned :class:`IntegrityReport`; the
    verifier fails the run on ANY mismatch - the checker does not
    threshold or average.
    """

    async def check(self, handle: DbRestoreHandle) -> IntegrityReport:
        """Return a full :class:`IntegrityReport` for ``handle``.

        Raises :class:`DbDrError` on transport / auth failure - an
        exception is NOT a "clean" verdict. The verifier treats a
        raised exception as an abort and tears the environment down.
        """
        ...


@runtime_checkable
class SmokeRunner(Protocol):
    """App-level smoke harness against a restored DB.

    Runs representative read and write operations (a bounded suite
    scoped to the tenant) against the restored copy. The suite MUST
    include at least one read and one write; adapters that return an
    empty :class:`SmokeReport` are treated as failing (misconfigured).
    """

    async def run(self, handle: DbRestoreHandle) -> SmokeReport:
        """Exercise the smoke suite and return a :class:`SmokeReport`.

        Raises :class:`DbDrError` on transport / auth failure - an
        exception is NOT a "passing" verdict.
        """
        ...


@dataclass(frozen=True, slots=True)
class DbDrEvidence:
    """Structured summary of the three-phase run - safe to persist.

    Every field is small and log-safe (matches the coding-conventions
    rules on error messages and audit entries). This is what the
    verifier hands back to its caller, and what an operator sees in
    the audit log; a fork MAY extend the audit surface via its own
    :class:`~fdai.shared.providers.state_store.StateStore` binding.
    """

    integrity_row_count_tables: int = 0
    integrity_checksum_tables: int = 0
    integrity_mismatches: tuple[IntegrityMismatch, ...] = ()
    smoke_checks_total: int = 0
    smoke_failures: tuple[SmokeCheck, ...] = field(default_factory=tuple)


__all__ = [
    "DbDrError",
    "DbDrEvidence",
    "DbRestoreAdapter",
    "DbRestoreConfig",
    "DbRestoreHandle",
    "IntegrityChecker",
    "IntegrityMismatch",
    "IntegrityMismatchKind",
    "IntegrityReport",
    "SmokeCheck",
    "SmokeReport",
    "SmokeRunner",
]
