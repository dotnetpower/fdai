#!/usr/bin/env python3
"""Build a governed admission bundle from independently produced proof files."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fdai.core.readiness.decision_evidence import DecisionEvidenceReadinessGate
from fdai.delivery.decision_evidence_policy import (
    DeploymentDecisionEvidencePolicy,
    deployment_freshness_policy_digest,
    load_deployment_decision_evidence_policy,
)
from fdai.delivery.persistence.state_store_decision_evidence import (
    RetainedDecisionEvidence,
    decision_evidence_record_mapping,
)
from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceVerifierBinding,
    DecisionEvidenceVerifierRegistry,
)
from fdai_service_contracts.decision_evidence import (
    DecisionCriticalEvidenceReceipt,
    LiveEvidenceClaimRequirement,
)
from fdai_service_contracts.decision_evidence_verification import (
    DecisionEvidenceVerificationBundle,
    DecisionEvidenceVerificationProof,
)

_MAX_INPUT_BYTES = 1024 * 1024


class DecisionEvidenceBundleError(ValueError):
    """The candidate proof files cannot produce a trusted admission record."""


class _ProofBundleVerifier:
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


async def build_decision_evidence_artifacts(
    *,
    receipt: DecisionCriticalEvidenceReceipt,
    requirement: LiveEvidenceClaimRequirement,
    authentication_proof: DecisionEvidenceVerificationProof,
    readback_proofs: tuple[DecisionEvidenceVerificationProof, ...],
    evaluated_at: datetime,
    policy: DeploymentDecisionEvidencePolicy,
) -> tuple[DecisionEvidenceVerificationBundle, dict[str, object]]:
    """Validate five proofs and return their bundle plus immutable admission record."""

    proofs = (authentication_proof, *readback_proofs)
    if len(proofs) != 5:
        raise DecisionEvidenceBundleError(
            "decision evidence bundle requires one authentication and four readback proofs"
        )
    verifier_ids = {proof.verifier_id for proof in proofs}
    verifier_versions = {proof.verifier_version for proof in proofs}
    trust_anchor_ids = {proof.trust_anchor_id for proof in proofs}
    if len(verifier_ids) != 1 or len(verifier_versions) != 1 or len(trust_anchor_ids) != 1:
        raise DecisionEvidenceBundleError(
            "decision evidence proofs require one verifier and trust binding"
        )
    verifier_id = next(iter(verifier_ids))
    verifier_version = next(iter(verifier_versions))
    trust_anchor_id = next(iter(trust_anchor_ids))
    _validate_trusted_policy(
        receipt=receipt,
        requirement=requirement,
        verifier_id=verifier_id,
        verifier_version=verifier_version,
        trust_anchor_id=trust_anchor_id,
        policy=policy,
    )
    bundle = DecisionEvidenceVerificationBundle.create(
        receipt_digest=receipt.receipt_digest,
        verifier_id=verifier_id,
        verifier_version=verifier_version,
        trust_anchor_id=trust_anchor_id,
        verified_at=max(proof.issued_at for proof in proofs),
        valid_until=min(proof.valid_until for proof in proofs),
        proofs=proofs,
    )
    gate = DecisionEvidenceReadinessGate(
        registry=DecisionEvidenceVerifierRegistry(
            (
                DecisionEvidenceVerifierBinding(
                    authority_class=receipt.authority_class,
                    method_id=receipt.method_id,
                    verifier_id=verifier_id,
                    verifier_version=verifier_version,
                    trust_anchor_id=trust_anchor_id,
                    verifier=_ProofBundleVerifier(bundle),
                    valid_from=bundle.verified_at,
                    valid_until=bundle.valid_until,
                ),
            )
        )
    )
    result = await gate.evaluate(
        receipt,
        requirement,
        evaluated_at=evaluated_at,
    )
    if not result.eligible or result.admission is None or result.verification_bundle is None:
        details = ",".join(result.rejection_details)
        suffix = f":{details}" if details else ""
        raise DecisionEvidenceBundleError(
            f"decision evidence bundle rejected:{result.reason.value}{suffix}"
        )
    record = decision_evidence_record_mapping(
        RetainedDecisionEvidence(
            receipt=receipt,
            verification_bundle=result.verification_bundle,
            admission=result.admission,
        )
    )
    return result.verification_bundle, record


def _validate_trusted_policy(
    *,
    receipt: DecisionCriticalEvidenceReceipt,
    requirement: LiveEvidenceClaimRequirement,
    verifier_id: str,
    verifier_version: str,
    trust_anchor_id: str,
    policy: DeploymentDecisionEvidencePolicy,
) -> None:
    static_receipt = (
        receipt.authority_class,
        receipt.purpose_id,
        receipt.producer_id,
        receipt.producer_version,
        receipt.method_id,
        receipt.method_version,
        receipt.freshness_policy_id,
        receipt.freshness_policy_version,
        receipt.freshness_ceiling_seconds,
        receipt.freshness_policy_digest,
    )
    static_policy = (
        policy.authority_class,
        policy.purpose_id,
        policy.producer_id,
        policy.producer_version,
        policy.method_id,
        policy.method_version,
        policy.freshness_policy_id,
        policy.freshness_policy_version,
        policy.freshness_ceiling_seconds,
        deployment_freshness_policy_digest(policy),
    )
    if static_receipt != static_policy:
        raise DecisionEvidenceBundleError(
            "decision evidence receipt does not match the trusted policy"
        )
    if (
        requirement.allowed_authority_classes != (policy.authority_class,)
        or requirement.allowed_source_identities != (receipt.source_identity,)
        or requirement.scope_digest != receipt.scope_digest
        or requirement.purpose_id != policy.purpose_id
        or requirement.producer_id != policy.producer_id
        or requirement.producer_version != policy.producer_version
        or requirement.method_id != policy.method_id
        or requirement.method_version != policy.method_version
        or requirement.source_revision != receipt.source_revision
        or requirement.freshness_policy_digest != deployment_freshness_policy_digest(policy)
        or requirement.freshness_ceiling_seconds != policy.freshness_ceiling_seconds
        or not receipt.source_identity.startswith(policy.source_identity_prefix + ":")
    ):
        raise DecisionEvidenceBundleError(
            "decision evidence requirement does not match the trusted policy"
        )
    if (
        verifier_id != policy.verifier_id
        or verifier_version != policy.verifier_version
        or trust_anchor_id != policy.trust_anchor_id
    ):
        raise DecisionEvidenceBundleError(
            "decision evidence verifier does not match the trusted policy"
        )


def _load(path: Path) -> Any:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_INPUT_BYTES:
        raise DecisionEvidenceBundleError("decision evidence input MUST be a bounded regular file")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DecisionEvidenceBundleError("decision evidence input is invalid JSON") from exc


def _write(path: Path, payload: object) -> None:
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError as exc:
        raise DecisionEvidenceBundleError(
            "decision evidence output MUST be a new regular file"
        ) from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")


async def _run(args: argparse.Namespace) -> None:
    try:
        receipt = DecisionCriticalEvidenceReceipt.model_validate(_load(args.receipt))
        requirement = LiveEvidenceClaimRequirement.model_validate(_load(args.requirement))
        policy = load_deployment_decision_evidence_policy(args.policy)
        authentication = DecisionEvidenceVerificationProof.model_validate(
            _load(args.authentication_proof)
        )
        readback = _load(args.readback_proofs)
        if not isinstance(readback, dict) or set(readback) != {"proofs"}:
            raise DecisionEvidenceBundleError(
                "decision evidence readback proof record shape is invalid"
            )
        proof_rows = readback["proofs"]
        if not isinstance(proof_rows, list):
            raise DecisionEvidenceBundleError("decision evidence readback proofs MUST be an array")
        readback_proofs = tuple(
            DecisionEvidenceVerificationProof.model_validate(row) for row in proof_rows
        )
        evaluated_at = datetime.fromisoformat(args.evaluated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        if isinstance(exc, DecisionEvidenceBundleError):
            raise
        raise DecisionEvidenceBundleError(
            "decision evidence input does not match its contract"
        ) from exc
    bundle, record = await build_decision_evidence_artifacts(
        receipt=receipt,
        requirement=requirement,
        authentication_proof=authentication,
        readback_proofs=readback_proofs,
        evaluated_at=evaluated_at,
        policy=policy,
    )
    _write(args.output_bundle, bundle.model_dump(mode="json"))
    _write(args.output_record, record)


def main() -> int:
    """Parse fixed proof files and emit only validated content-addressed records."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--requirement", type=Path, required=True)
    parser.add_argument("--authentication-proof", type=Path, required=True)
    parser.add_argument("--readback-proofs", type=Path, required=True)
    parser.add_argument("--evaluated-at", required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output-bundle", type=Path, required=True)
    parser.add_argument("--output-record", type=Path, required=True)
    args = parser.parse_args()
    try:
        asyncio.run(_run(args))
    except DecisionEvidenceBundleError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DecisionEvidenceBundleError",
    "build_decision_evidence_artifacts",
]
