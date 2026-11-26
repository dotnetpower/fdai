"""One in-process verifier venue: engine, proof store, owners, and programmable sources."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from fdai.core.operational_context.test_context import TestContextClaim
from fdai.core.operational_context.test_context_commands import TestContextCommandHandler
from fdai.core.operational_context.test_context_lifecycle import (
    GovernedTestContextStore,
    context_history_key,
    parse_test_context_history,
)
from fdai.core.operational_evidence.issuance import (
    OperationalEvidenceVerifierEngine,
    VerifierIdentity,
)
from fdai.core.operational_evidence.owner_outcome import OperationalEvidenceRequester
from fdai.core.operational_evidence.readback.test_context_command import (
    OperatorTestContextCommandReadback,
)
from fdai.core.operational_evidence.readback.test_context_lifecycle import (
    ContextTransitionReadback,
    OperationalTestContextReadback,
)
from fdai.core.operational_evidence.readback.test_context_sources import AuditRow
from fdai.core.operational_evidence.revision_history import RegistryHistory
from fdai.core.operational_evidence.trust_registry import DeploymentAnchors
from fdai.delivery.operational_evidence_admission import OperationalEvidenceAdmissionProvider
from fdai.delivery.operational_evidence_transport import (
    BoundedOperationalEvidenceIssuer,
    InProcessOperationalEvidenceTransport,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.operational_evidence import (
    OperationalEvidenceIssuanceRequest,
    OperationalEvidenceIssuanceResponse,
    OperationalEvidenceLocator,
    OperationalEvidenceLookup,
    OperationalEvidenceRejectionRecord,
)
from tests.core.operational_evidence.support import (
    NOW,
    POLICY,
    REQUESTER,
    REQUESTER_GROUP,
    REVIEWER,
    REVIEWER_GROUP,
    SCOPE,
    TARGET,
    MemoryProofStore,
    MimirSources,
    OperatorOutbox,
    anchors,
    command_from_row,
    history,
)


class ProgrammableSources(MimirSources):
    """Real Mimir history and audit rows, with optional tampering for negative tests."""

    def __init__(self, store: InMemoryStateStore) -> None:
        super().__init__(store)
        self.audit_tamper: Callable[[AuditRow], AuditRow] | None = None
        self.bump_after_reads: int | None = None
        self._reads = 0

    def change_revision_after(self, reads: int) -> None:
        """Report a newer store revision on every history read after the next ``reads``."""

        self._reads = 0
        self.bump_after_reads = reads

    async def history(
        self, *, access_scope_digest: str, target_ref: str
    ) -> Mapping[str, Any] | None:
        value = await super().history(
            access_scope_digest=access_scope_digest, target_ref=target_ref
        )
        self._reads += 1
        if value is not None and self.bump_after_reads is not None:
            if self._reads > self.bump_after_reads:
                return {**value, "revision": int(value["revision"]) + 1}
        return value

    async def transition_entries(self, *, context_digests: tuple[str, ...]) -> tuple[AuditRow, ...]:
        rows = await super().transition_entries(context_digests=context_digests)
        tamper = self.audit_tamper
        return tuple(tamper(row) for row in rows) if tamper is not None else rows


class VerifierVenue:
    """One verifier, one proof store, and the owners that consume its records."""

    def __init__(
        self,
        *,
        registry: RegistryHistory | None = None,
        bound: DeploymentAnchors | None = None,
        consumer_anchors: DeploymentAnchors | None = None,
        consumer_registry: RegistryHistory | None = None,
        verifier_version: str = "1.0.0",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.outbox = OperatorOutbox()
        self.state = InMemoryStateStore()
        self.proofs = MemoryProofStore()
        self.history = registry or history()
        self.consumer_history = consumer_registry or self.history
        self.anchors = bound or anchors()
        self.sources = ProgrammableSources(self.state)
        self.engine = OperationalEvidenceVerifierEngine(
            identity=VerifierIdentity("operational-evidence-verifier", verifier_version),
            history=lambda: self.history,
            anchors=self.anchors,
            readbacks=(
                OperatorTestContextCommandReadback(commands=self.outbox),
                ContextTransitionReadback(
                    commands=self.outbox, history=self.sources, audit=self.sources
                ),
                OperationalTestContextReadback(
                    commands=self.outbox, history=self.sources, audit=self.sources
                ),
            ),
            writer=self.proofs,
            lineage=self.proofs,
            clock=clock or (lambda: NOW),
        )
        self.provider = OperationalEvidenceAdmissionProvider(
            reader=self.proofs,
            history=lambda: self.consumer_history,
            anchors=consumer_anchors or self.anchors,
            verifier_id="operational-evidence-verifier",
            clock=lambda: NOW,
        )
        self.requester = OperationalEvidenceRequester(
            issuer=BoundedOperationalEvidenceIssuer(
                InProcessOperationalEvidenceTransport(self.engine, caller_principal="fdai_core")
            ),
            outcomes=self.provider,
            producer_id="core-control-plane",
            producer_version="1.0.0",
        )
        self.handler = TestContextCommandHandler(
            contexts=GovernedTestContextStore(
                store=self.state,
                admission=self.provider,
                evidence=self.requester,
                clock=lambda: NOW,
            ),
            admission=self.provider,
            evidence=self.requester,
            clock=lambda: NOW,
        )

    def propose(self, **overrides: Any) -> dict[str, Any]:
        values: dict[str, Any] = {
            "principal": REQUESTER,
            "group": REQUESTER_GROUP,
            "roles": ("Contributor",),
            "accepted_at": NOW - timedelta(minutes=1),
            "expected_revision": 0,
        }
        values.update(overrides)
        return command_from_row(self.outbox.add("propose", **values)).model_dump(mode="json")

    def review(self, **overrides: Any) -> dict[str, Any]:
        values: dict[str, Any] = {
            "principal": REVIEWER,
            "group": REVIEWER_GROUP,
            "roles": ("Approver",),
            "accepted_at": NOW - timedelta(seconds=30),
            "expected_revision": 1,
        }
        values.update(overrides)
        return command_from_row(self.outbox.add("review", **values)).model_dump(mode="json")

    async def reviewed_chain(self) -> TestContextClaim:
        """Admit a proposal and an independent review through the real verifier."""

        await self.handler.transition(self.propose(), reviewed_by_var=False)
        await self.handler.transition(self.review(), reviewed_by_var=True)
        return (await self.context_history())["context-test"][-1]

    async def context_history(self) -> dict[str, tuple[TestContextClaim, ...]]:
        _, histories = parse_test_context_history(
            await self.state.read_state(context_history_key(SCOPE, TARGET))
        )
        return histories

    async def issue(
        self, purpose_id: str, evidence_digest: str, **coordinates: str
    ) -> tuple[OperationalEvidenceIssuanceResponse, OperationalEvidenceRejectionRecord | None]:
        """Ask the engine directly and return the rejection it recorded, if any."""

        request = OperationalEvidenceIssuanceRequest(
            attempt_id=uuid4().hex,
            lookup=OperationalEvidenceLookup(
                evidence_digest=evidence_digest,
                scope_digest="sha256:" + SCOPE,
                purpose_id=purpose_id,
                source_revision=POLICY,
            ),
            locator=OperationalEvidenceLocator(purpose_id=purpose_id, coordinates=coordinates),
            producer_id="core-control-plane",
            producer_version="1.0.0",
            requested_at=NOW,
        )
        response = await self.engine.issue(request, caller_principal="fdai_core")
        rejection = next(
            (item for item in self.proofs.rejections if item.attempt_id == request.attempt_id),
            None,
        )
        return response, rejection

    async def issue_current(
        self, claim: TestContextClaim
    ) -> tuple[OperationalEvidenceIssuanceResponse, OperationalEvidenceRejectionRecord | None]:
        return await self.issue(
            "operational-test-context",
            claim.digest,
            context_id=claim.context_id,
            target_ref=claim.target_ref,
            signal_code=claim.signal_code,
        )


__all__ = ["ProgrammableSources", "VerifierVenue"]
