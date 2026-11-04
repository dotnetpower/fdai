"""Real row-level coherent leases for the isolated LOCAL PostgreSQL owner backend."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import psycopg
from fdai_service_contracts.decision_evidence import (
    DecisionCriticalEvidenceReceipt,
    EvidenceConflictStatus,
    LiveEvidenceClaimRequirement,
    decision_critical_evidence_receipt_digest,
)
from fdai_service_contracts.decision_evidence_verification import (
    DecisionEvidenceVerificationBundle,
    DecisionEvidenceVerificationProof,
    expected_verification_subjects,
)
from fdai_service_contracts.ontology_query import content_digest
from fdai_service_contracts.operator_authentication import OperatorAuthenticationReceipt
from psycopg.rows import dict_row

from fdai.core.readiness.decision_evidence import DecisionEvidenceReadinessGate
from fdai.core.tiers.t1_lightweight.retained_pattern_bindings import (
    FINAL_QUALIFICATION_PURPOSE,
    RetainedPatternQualification,
)
from fdai.core.tiers.t1_lightweight.retained_pattern_lease import RetainedPatternLeaseEvidence
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    DecisionEvidenceVerifierBinding,
    DecisionEvidenceVerifierRegistry,
)

from .local_pattern_owner import local_dsn, owner_key
from .local_pattern_validation import artifact_key, base_keys, validate_locked


class LocalPostgresPatternQualifier:
    """Lock the closed dependency set, including negative members and authorization.

    Only the LOCAL owner sources in this module's sibling adapter are supported.
    A real database row lock, not an epoch convention, blocks every UPDATE/DELETE
    and conflicting upsert through the normal StateStore or another connection.
    No new permission is minted: the lease carries the two independently retained
    readiness admissions. It is valid only inside ``lease`` and is never persisted.
    """

    def __init__(
        self,
        *,
        dsn: str,
        venue: str,
        clock: Callable[[], datetime] | None = None,
        statement_timeout_ms: int = 1500,
    ) -> None:
        pinned = local_dsn(dsn, venue=venue)
        if not 1 <= statement_timeout_ms <= 3000:
            raise ValueError("local Pattern lease timeout is out of bounds")
        self._dsn, self._timeout = pinned, statement_timeout_ms
        self._clock = clock or (lambda: datetime.now(UTC))

    async def qualify(
        self, request: RetainedPatternQualification
    ) -> DecisionEvidenceAdmission | None:
        """An unleased call cannot safely qualify; never replace it with a new permission."""
        return None

    @asynccontextmanager
    async def lease(
        self, request: RetainedPatternQualification
    ) -> AsyncIterator[RetainedPatternLeaseEvidence | None]:
        value = request.descriptor
        if not 1 <= len(value["cohort"]["cases"]) <= 100:
            raise ValueError("local Pattern lease cohort is out of bounds")
        keys = set(base_keys(value))
        async with await psycopg.AsyncConnection.connect(
            self._dsn, row_factory=dict_row, connect_timeout=2
        ) as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)", (str(self._timeout),)
                )
                # Discover storage coordinates only; no eligibility is inferred here.
                metadata_keys = [key for key in keys if key.startswith("case-history:latest:")]
                cursor = await connection.execute(
                    "SELECT value FROM state_kv WHERE key = ANY(%s)", (metadata_keys,)
                )
                for row in await cursor.fetchall():
                    storage = row["value"].get("storage_ref")
                    if isinstance(storage, str):
                        keys.add(artifact_key(storage))
                if len(keys) > 256:
                    raise ValueError("local Pattern lease dependency set is out of bounds")
                cursor = await connection.execute(
                    "SELECT key, value FROM state_kv WHERE key = ANY(%s) ORDER BY key FOR SHARE",
                    (sorted(keys),),
                )
                rows: dict[str, dict[str, Any]] = {
                    row["key"]: row["value"] for row in await cursor.fetchall()
                }
                if rows.keys() != keys:
                    yield None
                    return
                # A changed metadata coordinate references an unlocked/missing artifact
                # and fails closed. There is no expanding read/lock retry loop.
                try:
                    qualified = validate_locked(request, rows, now=self._clock())
                except (KeyError, TypeError, ValueError):
                    qualified = None
                if qualified is None:
                    yield None
                    return
                qualified.guard.active = True
                try:
                    yield qualified
                finally:
                    qualified.guard.active = False


class _CoherentBundleVerifier:
    def __init__(self, bundle: DecisionEvidenceVerificationBundle) -> None:
        self._bundle = bundle

    async def verify(
        self,
        receipt: DecisionCriticalEvidenceReceipt,
        *,
        trust_anchor_id: str,
    ) -> DecisionEvidenceVerificationBundle:
        del receipt, trust_anchor_id
        return self._bundle


class PostgresCoherentPatternFinalQualifier:
    """Issue a gate-verified final admission over a row-locked dependency tuple.

    Locks the complete cohort, positive and negative case metadata/artifacts,
    principal/authenticated-request records, measured reuse statistics, registered
    ActionType schema, current-reuse verification, and both independent read/reuse
    admissions in one ``FOR SHARE`` snapshot, then evaluates the coherent tuple
    through ``DecisionEvidenceReadinessGate`` under a separated verifier identity.
    """

    def __init__(
        self,
        *,
        dsn: str,
        venue: str,
        clock: Callable[[], datetime] | None = None,
        statement_timeout_ms: int = 1500,
        require_authenticated_request: bool = True,
        verifier_id: str = "operational-evidence-verifier",
        trust_anchor_id: str = "anchor:operational-evidence-verifier",
        source_identity: str = "postgres:local-pattern-owner",
        producer_id: str = "core-control-plane",
    ) -> None:
        pinned = local_dsn(dsn, venue=venue)
        if not 1 <= statement_timeout_ms <= 3000:
            raise ValueError("local Pattern final qualifier timeout is out of bounds")
        if (
            not verifier_id.strip()
            or not trust_anchor_id.strip()
            or not source_identity.strip()
            or not producer_id.strip()
            or verifier_id in {source_identity, producer_id}
            or source_identity == producer_id
        ):
            raise ValueError(
                "final qualifier identities MUST separate source, producer, and verifier"
            )
        self._dsn = pinned
        self._timeout = statement_timeout_ms
        self._clock = clock or (lambda: datetime.now(UTC))
        self._require_authenticated_request = require_authenticated_request
        self._verifier_id = verifier_id
        self._trust_anchor_id = trust_anchor_id
        self._source_identity = source_identity
        self._producer_id = producer_id

    async def qualify(
        self, request: RetainedPatternQualification
    ) -> DecisionEvidenceAdmission | None:
        value = request.descriptor
        if not 1 <= len(value["cohort"]["cases"]) <= 100:
            raise ValueError("local Pattern final qualification cohort is out of bounds")
        core_keys = set(base_keys(value))
        extra_keys: set[str] = set()
        if self._require_authenticated_request:
            event_id = str(value["event"]["event_id"])
            pattern_id = str(value["cohort"]["pattern_id"])
            extra_keys.add(owner_key("authenticated_request", event_id))
            extra_keys.add(owner_key("candidate", event_id, pattern_id))
        async with await psycopg.AsyncConnection.connect(
            self._dsn, row_factory=dict_row, connect_timeout=2
        ) as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT set_config('statement_timeout', %s, true)", (str(self._timeout),)
                )
                metadata_keys = [key for key in core_keys if key.startswith("case-history:latest:")]
                cursor = await connection.execute(
                    "SELECT value FROM state_kv WHERE key = ANY(%s)", (metadata_keys,)
                )
                for row in await cursor.fetchall():
                    storage = row["value"].get("storage_ref")
                    if isinstance(storage, str):
                        core_keys.add(artifact_key(storage))
                all_keys = core_keys | extra_keys
                if len(all_keys) > 256:
                    raise ValueError(
                        "local Pattern final qualification dependency set is out of bounds"
                    )
                cursor = await connection.execute(
                    "SELECT key, value FROM state_kv WHERE key = ANY(%s) ORDER BY key FOR SHARE",
                    (sorted(all_keys),),
                )
                rows: dict[str, dict[str, Any]] = {
                    row["key"]: row["value"] for row in await cursor.fetchall()
                }
                if rows.keys() != all_keys:
                    return None
                now = self._clock()
                if self._require_authenticated_request and not _validate_server_owned_bindings(
                    value, rows, now=now
                ):
                    return None
                base_rows = {key: rows[key] for key in core_keys}
                try:
                    qualified = validate_locked(request, base_rows, now=now)
                except (KeyError, TypeError, ValueError):
                    qualified = None
                if qualified is None or now >= qualified.valid_until:
                    return None
                admission = await self._evaluate_gate(request, qualified, now=now)
                if admission is None:
                    return None
                recheck_cursor = await connection.execute(
                    "SELECT key, value FROM state_kv WHERE key = ANY(%s) ORDER BY key",
                    (sorted(core_keys),),
                )
                rechecked = {row["key"]: row["value"] for row in await recheck_cursor.fetchall()}
                current_deps_digest = content_digest(
                    {content_digest(k): content_digest(v) for k, v in rechecked.items()}
                )
                if current_deps_digest != qualified.dependencies_digest:
                    return None
                return admission

    async def _evaluate_gate(
        self,
        request: RetainedPatternQualification,
        qualified: RetainedPatternLeaseEvidence,
        *,
        now: datetime,
    ) -> DecisionEvidenceAdmission | None:
        ceiling_seconds = max(1, int((qualified.valid_until - now).total_seconds()))
        policy_digest = content_digest(
            {
                "policy_id": "retained-pattern-coherent-fence-freshness",
                "policy_version": "1.0.0",
            }
        )
        provenance_digest = content_digest(
            {
                "dependencies_digest": qualified.dependencies_digest,
                "read_admission": qualified.read_admission.receipt_digest,
                "reuse_admission": qualified.reuse_admission.receipt_digest,
            }
        )
        values: dict[str, object] = {
            "schema_version": "1.0.0",
            "authority_class": "retained_pattern_tuple_readback",
            "source_identity": self._source_identity,
            "authentication_evidence_digest": qualified.read_admission.receipt_digest,
            "scope_digest": request.scope_digest,
            "purpose_id": FINAL_QUALIFICATION_PURPOSE,
            "producer_id": self._producer_id,
            "producer_version": "1.0.0",
            "method_id": "retained-pattern-coherent-fence",
            "method_version": "1.0.0",
            "source_revision": request.evidence_digest,
            "evidence_digest": request.evidence_digest,
            "provenance_digest": provenance_digest,
            "event_at": now,
            "evidence_cutoff": now,
            "recorded_at": now,
            "fresh_until": qualified.valid_until,
            "freshness_policy_id": "retained-pattern-coherent-fence-freshness",
            "freshness_policy_version": "1.0.0",
            "freshness_policy_digest": policy_digest,
            "freshness_ceiling_seconds": ceiling_seconds,
            "completeness_basis_points": 10_000,
            "completeness_evidence_digest": qualified.dependencies_digest,
            "conflict_status": EvidenceConflictStatus.CLEAR,
            "conflict_evidence_digest": qualified.reuse_admission.receipt_digest,
            "conflict_evidence_digests": (),
            "synthetic": False,
            "execution_authority": False,
        }
        receipt = DecisionCriticalEvidenceReceipt.model_validate(
            {
                **values,
                "receipt_digest": decision_critical_evidence_receipt_digest(**values),
            }
        )
        subjects = expected_verification_subjects(
            authentication_evidence_digest=receipt.authentication_evidence_digest,
            evidence_digest=receipt.evidence_digest,
            completeness_evidence_digest=receipt.completeness_evidence_digest,
            conflict_evidence_digest=receipt.conflict_evidence_digest,
            freshness_policy_digest=receipt.freshness_policy_digest,
        )
        proofs = tuple(
            DecisionEvidenceVerificationProof(
                kind=kind,
                receipt_digest=receipt.receipt_digest,
                subject_digest=subject,
                proof_digest=content_digest(
                    {
                        "kind": str(kind),
                        "receipt": receipt.receipt_digest,
                        "subject": subject,
                        "dependencies": qualified.dependencies_digest,
                    }
                ),
                verifier_id=self._verifier_id,
                verifier_version="1.0.0",
                trust_anchor_id=self._trust_anchor_id,
                issued_at=now,
                valid_until=qualified.valid_until,
            )
            for kind, subject in subjects.items()
        )
        bundle = DecisionEvidenceVerificationBundle.create(
            receipt_digest=receipt.receipt_digest,
            verifier_id=self._verifier_id,
            verifier_version="1.0.0",
            trust_anchor_id=self._trust_anchor_id,
            verified_at=now,
            valid_until=qualified.valid_until,
            proofs=proofs,
        )
        binding = DecisionEvidenceVerifierBinding(
            authority_class=receipt.authority_class,
            method_id=receipt.method_id,
            verifier_id=self._verifier_id,
            verifier_version="1.0.0",
            trust_anchor_id=self._trust_anchor_id,
            verifier=_CoherentBundleVerifier(bundle),
        )
        gate = DecisionEvidenceReadinessGate(registry=DecisionEvidenceVerifierRegistry((binding,)))
        requirement = LiveEvidenceClaimRequirement(
            allowed_authority_classes=(receipt.authority_class,),
            allowed_source_identities=(self._source_identity,),
            scope_digest=request.scope_digest,
            purpose_id=FINAL_QUALIFICATION_PURPOSE,
            producer_id=self._producer_id,
            producer_version="1.0.0",
            method_id=receipt.method_id,
            method_version="1.0.0",
            source_revision=request.evidence_digest,
            freshness_policy_digest=policy_digest,
            freshness_ceiling_seconds=ceiling_seconds,
            minimum_completeness_basis_points=10_000,
        )
        result = await gate.evaluate(receipt, requirement, evaluated_at=now)
        if not result.eligible:
            return None
        return DecisionEvidenceAdmission(
            receipt_digest=receipt.receipt_digest,
            verification_bundle_digest=bundle.bundle_digest,
            evidence_digest=request.evidence_digest,
            scope_digest=request.scope_digest,
            purpose_id=FINAL_QUALIFICATION_PURPOSE,
            source_revision=request.evidence_digest,
            verified_at=now,
            valid_until=qualified.valid_until,
        )


def _validate_server_owned_bindings(
    value: dict[str, Any], rows: dict[str, dict[str, Any]], *, now: datetime
) -> bool:
    event_id = str(value["event"]["event_id"])
    pattern_id = str(value["cohort"]["pattern_id"])
    principal = value["read"]["principal"]
    args = value["read"]["arguments"]
    match = value["match"]
    req_row = rows.get(owner_key("authenticated_request", event_id))
    cand_row = rows.get(owner_key("candidate", event_id, pattern_id))
    if req_row is None or cand_row is None:
        return False
    try:
        receipt = OperatorAuthenticationReceipt.model_validate(req_row["receipt"])
    except (KeyError, TypeError, ValueError):
        return False
    if (
        req_row.get("event_id") != event_id
        or req_row.get("context") != principal
        or req_row.get("access_scope_digest") != args.get("access_scope_digest")
        or req_row.get("purpose") != args.get("purpose")
        or req_row.get("failure_fingerprint") != args.get("failure_fingerprint")
        or req_row.get("request_id") != principal.get("authentication_request_ref")
        or not receipt.valid_at(now)
        or receipt.receipt_digest != principal.get("authentication_receipt_ref")
        or receipt.subject_id != principal.get("principal_ref")
        or list(receipt.groups) != list(principal.get("principal_groups", ()))
    ):
        return False
    cand_action = cand_row.get("action")
    return bool(
        isinstance(cand_action, dict)
        and cand_row.get("event_id") == event_id
        and cand_row.get("pattern_id") == pattern_id
        and cand_row.get("statistics_ref") == value["measurement"].get("evidence_ref")
        and cand_row.get("score") == match.get("score")
        and all(
            cand_action.get(k) == match.get(k)
            for k in ("signature", "rule_id", "action_type", "params", "incident_id", "context")
        )
    )
