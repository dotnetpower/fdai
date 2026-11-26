"""Protected decision-evidence bundle builder tests."""

from __future__ import annotations

import importlib.util
import stat
import sys
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import ModuleType

import pytest
from fdai.delivery.decision_evidence_policy import (
    DeploymentDecisionEvidencePolicy,
    deployment_freshness_policy_digest,
)
from fdai_service_contracts.decision_evidence_verification import (
    EvidenceVerificationProofKind,
)

from tests.core.readiness.test_decision_evidence import (
    _NOW,
    _bundle,
    _receipt,
    _requirement,
)

_SCRIPT = (
    Path(__file__).resolve().parents[4]
    / "scripts"
    / "deployment"
    / "azure"
    / "decision_evidence_bundle.py"
)


def _policy():
    return DeploymentDecisionEvidencePolicy(
        source_workflow_path=".github/workflows/test.yml",
        source_identity_prefix="principal",
        authority_class="provider_observation",
        purpose_id="readiness",
        producer_id="inventory-observer",
        producer_version="1.0.0",
        method_id="resource-health-query",
        method_version="1.0.0",
        freshness_policy_id="readiness-eight-minute",
        freshness_policy_version="1.0.0",
        freshness_ceiling_seconds=540,
        verifier_id="azure.readback",
        verifier_version="1.0.0",
        trust_anchor_id="azure:managed-identity",
    )


def _trusted_inputs():
    policy = _policy()
    freshness_digest = deployment_freshness_policy_digest(policy)
    receipt = _receipt(freshness_policy_digest=freshness_digest)
    requirement = _requirement().model_copy(update={"freshness_policy_digest": freshness_digest})
    return policy, receipt, requirement


@pytest.fixture(scope="module")
def builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("decision_evidence_bundle_script", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


async def test_builds_bundle_and_content_addressed_admission_record(
    builder: ModuleType,
) -> None:
    policy, receipt, requirement = _trusted_inputs()
    candidate = _bundle(receipt)
    authentication = next(
        proof
        for proof in candidate.proofs
        if proof.kind is EvidenceVerificationProofKind.AUTHENTICATION
    )
    readback = tuple(
        proof
        for proof in candidate.proofs
        if proof.kind is not EvidenceVerificationProofKind.AUTHENTICATION
    )

    bundle, record = await builder.build_decision_evidence_artifacts(
        receipt=receipt,
        requirement=requirement,
        authentication_proof=authentication,
        readback_proofs=readback,
        evaluated_at=_NOW + timedelta(minutes=3),
        policy=policy,
    )

    assert bundle == candidate
    assert record["receipt"]["receipt_digest"] == receipt.receipt_digest
    assert record["admission"]["execution_authority"] is False
    assert record["admission"]["promotion_authority"] is False


async def test_rejects_a_missing_readback_proof(builder: ModuleType) -> None:
    policy, receipt, requirement = _trusted_inputs()
    candidate = _bundle(receipt)
    authentication = next(
        proof
        for proof in candidate.proofs
        if proof.kind is EvidenceVerificationProofKind.AUTHENTICATION
    )
    readback = tuple(
        proof
        for proof in candidate.proofs
        if proof.kind is not EvidenceVerificationProofKind.AUTHENTICATION
    )

    with pytest.raises(builder.DecisionEvidenceBundleError, match="requires one"):
        await builder.build_decision_evidence_artifacts(
            receipt=receipt,
            requirement=requirement,
            authentication_proof=authentication,
            readback_proofs=readback[:-1],
            evaluated_at=_NOW + timedelta(minutes=3),
            policy=policy,
        )


async def test_rejects_expired_proof_window(builder: ModuleType) -> None:
    policy, receipt, requirement = _trusted_inputs()
    candidate = _bundle(receipt)
    authentication = next(
        proof
        for proof in candidate.proofs
        if proof.kind is EvidenceVerificationProofKind.AUTHENTICATION
    )
    readback = tuple(
        proof
        for proof in candidate.proofs
        if proof.kind is not EvidenceVerificationProofKind.AUTHENTICATION
    )

    with pytest.raises(builder.DecisionEvidenceBundleError, match="untrusted_verifier"):
        await builder.build_decision_evidence_artifacts(
            receipt=receipt,
            requirement=requirement,
            authentication_proof=authentication,
            readback_proofs=readback,
            evaluated_at=_NOW + timedelta(minutes=9),
            policy=policy,
        )


async def test_rejects_verifier_not_pinned_by_trusted_policy(
    builder: ModuleType,
) -> None:
    policy, receipt, requirement = _trusted_inputs()
    candidate = _bundle(receipt)
    authentication = next(
        proof
        for proof in candidate.proofs
        if proof.kind is EvidenceVerificationProofKind.AUTHENTICATION
    )
    readback = tuple(
        proof
        for proof in candidate.proofs
        if proof.kind is not EvidenceVerificationProofKind.AUTHENTICATION
    )

    with pytest.raises(builder.DecisionEvidenceBundleError, match="trusted policy"):
        await builder.build_decision_evidence_artifacts(
            receipt=receipt,
            requirement=requirement,
            authentication_proof=authentication,
            readback_proofs=readback,
            evaluated_at=_NOW + timedelta(minutes=3),
            policy=replace(policy, verifier_id="other.verifier"),
        )


def test_output_writer_refuses_symlink_and_uses_owner_only_mode(
    builder: ModuleType,
    tmp_path: Path,
) -> None:
    output = tmp_path / "bundle.json"
    builder._write(output, {"safe": True})

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    target = tmp_path / "target.json"
    target.write_text("{}\n", encoding="utf-8")
    link = tmp_path / "linked.json"
    link.symlink_to(target)
    with pytest.raises(builder.DecisionEvidenceBundleError, match="new regular file"):
        builder._write(link, {"unsafe": True})
    assert target.read_text(encoding="utf-8") == "{}\n"
