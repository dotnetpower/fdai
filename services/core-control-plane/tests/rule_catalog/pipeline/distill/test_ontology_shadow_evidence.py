"""Tests for governed ontology live-shadow evidence collection."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fdai.rule_catalog.pipeline.distill.ontology_evaluation import (
    ChangeRiskClass,
    PromotionPolicy,
    ShadowReviewEvidenceBatch,
    ShadowReviewOutcome,
    assess_low_risk_promotion,
)
from fdai.rule_catalog.pipeline.distill.ontology_shadow_evidence import (
    GovernedShadowReviewBatchProducer,
    ImmutableFileShadowReviewEvidenceSource,
    ManifestShadowReviewEvidenceVerifier,
    ShadowReviewEvidenceManifest,
)

_REVISION = "a" * 40
_RELEASE = "b" * 64
_BINDING = "c" * 64
_SOURCE_RECEIPT = "d" * 64
_POLICY = PromotionPolicy()
_SEALED_AT = datetime(2026, 9, 16, 12, tzinfo=UTC)


def _outcome(index: int = 1) -> ShadowReviewOutcome:
    return ShadowReviewOutcome(
        outcome_id=f"{index + 100:064x}",
        proposal_digest=f"{index:064x}",
        observed_at=datetime(2026, 9, 1, index, tzinfo=UTC),
        audit_sequence=1,
        review_receipt_digest=f"{index + 200:064x}",
        reviewer_id="reviewer:independent",
        requester_id="requester:source",
        fdai_revision=_REVISION,
        ontology_release=_RELEASE,
        binding_digest=_BINDING,
        reviewed=True,
        risk_class=ChangeRiskClass.LOW_RISK_MAPPING,
        correct=True,
    )


class StaticOutcomeSource:
    def __init__(self, outcomes: tuple[ShadowReviewOutcome, ...]) -> None:
        self._outcomes = outcomes
        self.calls: list[tuple[str, str, str, str]] = []

    async def load_outcomes(
        self,
        *,
        fdai_revision: str,
        ontology_release: str,
        binding_digest: str,
        policy_digest: str,
    ) -> tuple[ShadowReviewOutcome, ...]:
        self.calls.append((fdai_revision, ontology_release, binding_digest, policy_digest))
        return self._outcomes


async def _produce(tmp_path: Path, outcomes: tuple[ShadowReviewOutcome, ...] | None = None):
    source = StaticOutcomeSource(outcomes or (_outcome(1), _outcome(2)))
    artifact = await GovernedShadowReviewBatchProducer(
        source=source,
        output_dir=tmp_path,
        clock=lambda: _SEALED_AT,
    ).produce(
        fdai_revision=_REVISION,
        ontology_release=_RELEASE,
        binding_digest=_BINDING,
        policy=_POLICY,
        source_receipt_digest=_SOURCE_RECEIPT,
    )
    return artifact, source


async def test_producer_round_trip_binds_governed_source_and_review_receipts(
    tmp_path: Path,
) -> None:
    artifact, source = await _produce(tmp_path)
    loaded = await ImmutableFileShadowReviewEvidenceSource(artifact.manifest).load_batch(
        fdai_revision=_REVISION,
        ontology_release=_RELEASE,
        binding_digest=_BINDING,
        policy_digest=_POLICY.policy_digest,
    )
    verifier = ManifestShadowReviewEvidenceVerifier(artifact.manifest)

    assert loaded == artifact.batch
    assert verifier.verify(loaded) is True
    assert source.calls == [(_REVISION, _RELEASE, _BINDING, _POLICY.policy_digest)]
    assessment = assess_low_risk_promotion(
        loaded,
        as_of=date(2026, 9, 16),
        verifier=verifier,
    )
    assert assessment.eligible is False
    assert assessment.reason_codes == (
        "insufficient_reviewed_samples",
        "insufficient_distinct_days",
        "precision_lower_bound_not_met",
    )


async def test_content_addressed_retry_is_idempotent(tmp_path: Path) -> None:
    first, _ = await _produce(tmp_path)
    second, _ = await _produce(tmp_path, (_outcome(2), _outcome(1)))

    assert second.batch_path == first.batch_path
    assert second.manifest_path == first.manifest_path
    assert second.batch_path.read_bytes() == first.batch_path.read_bytes()
    assert second.manifest_path.read_bytes() == first.manifest_path.read_bytes()


async def test_empty_or_cross_identity_source_fails_before_publication(tmp_path: Path) -> None:
    source = StaticOutcomeSource(())
    producer = GovernedShadowReviewBatchProducer(
        source=source,
        output_dir=tmp_path,
        clock=lambda: _SEALED_AT,
    )
    with pytest.raises(ValueError, match="MUST contain outcomes"):
        await producer.produce(
            fdai_revision=_REVISION,
            ontology_release=_RELEASE,
            binding_digest=_BINDING,
            policy=_POLICY,
            source_receipt_digest=_SOURCE_RECEIPT,
        )

    with pytest.raises(ValueError, match="sealed evidence identity"):
        await _produce(tmp_path, (replace(_outcome(), binding_digest="e" * 64),))
    assert not tuple(tmp_path.glob("*.json"))


async def test_loader_rejects_tampered_batch_and_requested_identity(tmp_path: Path) -> None:
    artifact, _ = await _produce(tmp_path)
    source = ImmutableFileShadowReviewEvidenceSource(artifact.manifest)
    with pytest.raises(ValueError, match="requested identity mismatch"):
        await source.load_batch(
            fdai_revision="f" * 40,
            ontology_release=_RELEASE,
            binding_digest=_BINDING,
            policy_digest=_POLICY.policy_digest,
        )

    payload = json.loads(artifact.batch_path.read_text(encoding="utf-8"))
    payload["outcomes"][0]["correct"] = False
    artifact.batch_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="batch digest mismatch"):
        await source.load_batch(
            fdai_revision=_REVISION,
            ontology_release=_RELEASE,
            binding_digest=_BINDING,
            policy_digest=_POLICY.policy_digest,
        )


def test_manifest_verifier_rejects_missing_review_or_source_receipt(tmp_path: Path) -> None:
    batch_path = tmp_path / "batch.json"
    batch_path.write_text("{}", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "batch": {
                    "path": batch_path.name,
                    "content_digest": "1" * 64,
                    "fdai_revision": _REVISION,
                    "ontology_release": _RELEASE,
                    "binding_digest": _BINDING,
                    "policy_digest": _POLICY.policy_digest,
                },
                "source_receipt_digest": _SOURCE_RECEIPT,
                "review_receipt_digests": ["9" * 64],
            }
        ),
        encoding="utf-8",
    )
    manifest = ShadowReviewEvidenceManifest.load(manifest_path)
    batch = replace(
        ShadowReviewEvidenceBatch(
            fdai_revision=_REVISION,
            ontology_release=_RELEASE,
            binding_digest=_BINDING,
            policy_digest=_POLICY.policy_digest,
            sealed_at=_SEALED_AT,
            source_receipt_digest=_SOURCE_RECEIPT,
            outcomes=(_outcome(),),
        ),
        source_receipt_digest="8" * 64,
    )

    assert ManifestShadowReviewEvidenceVerifier(manifest).verify(batch) is False


def test_manifest_rejects_symlink_and_unknown_fields(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    symlink = tmp_path / "manifest.json"
    symlink.symlink_to(target)
    with pytest.raises(ValueError, match="MUST be a regular file"):
        ShadowReviewEvidenceManifest.load(symlink)

    strict = tmp_path / "strict.json"
    strict.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "batch": {},
                "source_receipt_digest": _SOURCE_RECEIPT,
                "review_receipt_digests": [],
                "unexpected": True,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="fields do not match schema"):
        ShadowReviewEvidenceManifest.load(strict)
