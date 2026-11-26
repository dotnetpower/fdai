"""Actual Rule and ontology compilation, source fencing, and independent review."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from dataclasses import replace
from datetime import (
    UTC,
    datetime,
    timedelta,
)
from pathlib import Path
from uuid import UUID

import pytest
import yaml
from fdai.rule_catalog.pipeline.distill.handover_rules import HandoverRuleCompiler
from fdai.rule_catalog.pipeline.distill.handover_semantics import (
    HandoverSemanticCompilation,
    HandoverSemanticReview,
    HandoverSemanticVerification,
)
from fdai.rule_catalog.pipeline.distill.ontology_models import AuthorityClass
from fdai.rule_catalog.pipeline.distill.ontology_verify import (
    EntityRecord,
    SourceAuthorityPolicy,
    VerificationContext,
)
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.providers.distiller import (
    CandidateKind,
    DistillationResult,
    DistilledCandidate,
    DistillerAvailability,
    DistillerCapabilityDescriptor,
)
from fdai_service_contracts import (
    AccessDescriptor,
    ArtifactManifestEntry,
    DocumentArtifactManifest,
    DocumentEnvelope,
    DocumentPurpose,
    ProtectionState,
    RetentionPolicy,
    StructuralUnit,
)
from fdai_service_contracts.handover_knowledge import HandoverKnowledgeNotice

ROOT = Path(__file__).resolve().parents[6]
AT = datetime(2026, 9, 14, 12, tzinfo=UTC)


class Packages:
    def __init__(self):
        self.rows = {}

    async def claim(self, key, identity):
        if key in self.rows:
            assert self.rows[key]["identity"] == identity
            return False
        self.rows[key] = {"identity": dict(identity), "package": None}
        return True

    async def read(self, key):
        return copy.deepcopy(self.rows.get(key))

    async def complete(self, key, identity, package):
        assert self.rows[key]["identity"] == identity
        assert self.rows[key]["package"] is None
        self.rows[key]["package"] = json.loads(json.dumps(package))

    async def reconcile(self, notice, *, withdrawn):
        return 0


class Sources:
    def __init__(self, envelope):
        self.envelope = envelope
        self.calls = 0
        self.available = True

    async def read(self, notice):
        self.calls += 1
        if not self.available:
            raise ValueError("synthetic source withdrawn")
        return (self.envelope,)


class Extractor:
    def __init__(self):
        self.calls = 0
        self.alter = lambda result: result

    def distiller_capability(self):
        return DistillerCapabilityDescriptor(
            "synthetic",
            "1",
            "ontology-distiller-conformance.v1",
            DistillerAvailability.AVAILABLE,
        )

    async def distill(self, document):
        self.calls += 1
        result = DistillationResult(
            candidates=(
                DistilledCandidate(
                    kind=CandidateKind.ONTOLOGY_OBJECT,
                    candidate_id="service-owner",
                    source_ref=document.source_ref,
                    source_section="ownership",
                    source_lines=(1, 1),
                    content_sha=document.content_sha,
                    body={
                        "operation": "update",
                        "target_type": "BusinessService",
                        "target_identity": "service:example",
                        "authority": "declared_intent",
                        "source_assertion": document.text.splitlines()[0],
                        "properties": {"owner_ref": "team:example"},
                    },
                ),
            )
        )
        return self.alter(result)


def fixture(*, typed=True):
    rule = yaml.safe_load(
        (ROOT / "rule-catalog/catalog/object-storage.public-access.deny.yaml").read_text()
    )
    rule.pop("source")
    rule.pop("provenance")
    text = "Example service is owned by Example team."
    units = [
        StructuralUnit(unit_id="unit:1", kind="paragraph", locator="docx/paragraph:1", text=text)
    ]
    if typed:
        units.append(
            StructuralUnit(
                unit_id="unit:2",
                kind="paragraph",
                locator="docx/paragraph:2",
                text=json.dumps(
                    {"kind": "fdai.rule.candidate.v1", "rule": rule}, separators=(",", ":")
                ),
            )
        )
    envelope = DocumentEnvelope(
        document_id=UUID(int=1),
        version_id=UUID(int=2),
        source_sha256="a" * 64,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        observed_format="docx",
        size_bytes=100,
        collection_id="manuals",
        purposes=(DocumentPurpose.MANUAL_DISTILLATION,),
        protection_state=ProtectionState.NONE,
        access_descriptor_ref="access:manuals",
        units=tuple(units),
        extractor_name="synthetic",
        extractor_version="1",
        artifact_manifest=DocumentArtifactManifest(
            document_id=UUID(int=1),
            version_id=UUID(int=2),
            source_sha256="a" * 64,
            access=AccessDescriptor(reference="access:manuals", collection_id="manuals"),
            retention=RetentionPolicy(policy_version="synthetic:1"),
            entries=(
                ArtifactManifestEntry(
                    artifact_id="source:example",
                    kind="source",
                    content_sha256="a" * 64,
                    retained=False,
                ),
            ),
            extractor_name="synthetic",
            extractor_version="1",
            created_at=AT,
            updated_at=AT,
        ),
    )

    def context(source):
        return VerificationContext(
            ontology_release="b" * 64,
            current_graph_revision="graph:1",
            object_types=frozenset({"BusinessService"}),
            links=(),
            entities=(EntityRecord("service:example", "BusinessService"),),
            source_policies=(
                SourceAuthorityPolicy(
                    f"document://{source.document_id}/versions/{source.version_id}",
                    frozenset({AuthorityClass.DECLARED_INTENT}),
                    10,
                ),
            ),
            claim_text=(),
        )

    verifier = HandoverSemanticVerification(
        HandoverRuleCompiler(
            PackageResourceSchemaRegistry(),
            frozenset({rule["remediates"]}),
            frozenset({"object-storage"}),
            ROOT / "policies",
            ROOT / "rule-catalog/remediation",
        ),
        context,
        "c" * 64,
    )
    sources, packages, extractor = Sources(envelope), Packages(), Extractor()
    compiler = HandoverSemanticCompilation(sources, packages, extractor, verifier, lambda: AT)
    reviewer = HandoverSemanticReview(sources, packages, verifier, lambda: AT)
    notice = HandoverKnowledgeNotice(
        source="core",
        goal_id="goal:example",
        goal_revision=1,
        source_digest="d" * 64,
        check_epoch=int(AT.timestamp()) // 300,
    )
    return compiler, reviewer, notice


async def test_actual_rule_and_ontology_bodies_are_compiled_and_independently_reviewed():
    compiler, reviewer, notice = fixture()
    receipt = await compiler.compile(notice)
    assert receipt.rule_count == 1 and receipt.ontology_count == 1
    package = compiler.packages.rows[receipt.package_ref]["package"]
    document = package["documents"][0]
    assert document["rules"][0]["rule"]["schema_version"] == "2.0.0"
    assert document["rules"][0]["source_units"] == [
        {
            "line_number": 2,
            "source_format": "docx",
            "unit_id": "unit:2",
            "locator": "docx/paragraph:2",
        }
    ]
    assert document["ontology"]["proposals"][0]["proposal"]["target_identity"] == "service:example"
    assert document["source_coverage_complete"] is False
    assert await reviewer.review(notice, receipt) == receipt
    assert compiler.distiller.calls == 1
    assert await compiler.compile(notice) == receipt
    assert compiler.distiller.calls == 1
    assert (
        not receipt.execution_authority
        and not receipt.projection_authority
        and not receipt.promotion_authority
    )
    assert "Example service" not in receipt.model_dump_json()


@pytest.mark.parametrize("change", ["source", "compiler", "package", "candidate", "withdrawal"])
async def test_independent_semantic_review_cannot_reuse_changed_inputs(change):
    compiler, reviewer, notice = fixture()
    receipt = await compiler.compile(notice)
    if change == "source":
        compiler.sources.envelope = compiler.sources.envelope.model_copy(
            update={"source_sha256": "e" * 64}
        )
    elif change == "compiler":
        reviewer = replace(reviewer, verifier=replace(reviewer.verifier, compiler_digest="e" * 64))
    elif change == "package":
        receipt = receipt.model_copy(update={"package_digest": "e" * 64})
    elif change == "candidate":
        package = compiler.packages.rows[receipt.package_ref]["package"]
        package["documents"][0]["rules"][0]["rule"]["severity"] = "low"
    else:
        compiler.sources.available = False
    with pytest.raises(ValueError):
        await reviewer.review(notice, receipt)
    assert compiler.distiller.calls == 1


async def test_interrupted_claim_does_not_repeat_provider_work():
    compiler, _, notice = fixture()

    def fail(_):
        raise RuntimeError("synthetic model failure")

    compiler.distiller.alter = fail
    with pytest.raises(RuntimeError):
        await compiler.compile(notice)
    receipt = await compiler.compile(notice)
    assert receipt.disposition == "held" and receipt.reason == "attempt_interrupted"
    assert compiler.distiller.calls == 1


async def test_unbound_prose_is_not_a_successful_semantic_candidate():
    from fdai.shared.providers.distiller import AbstainingDistiller

    compiler, _, notice = fixture(typed=False)
    compiler = replace(compiler, distiller=AbstainingDistiller())
    receipt = await compiler.compile(notice)
    assert receipt.disposition == "held" and receipt.reason == "no_supported_candidates"
    assert receipt.rule_count == receipt.ontology_count == 0


@pytest.mark.parametrize(
    "change", ["unknown_action", "missing_policy", "candidate_digest", "duplicate_id"]
)
async def test_actual_rule_and_ontology_compilation_fail_closed(change):
    compiler, _, notice = fixture()
    if change in {"unknown_action", "missing_policy"}:
        envelope = compiler.sources.envelope
        marker = json.loads(envelope.units[1].text)
        if change == "unknown_action":
            marker["rule"]["remediates"] = "remediate.unknown"
        else:
            marker["rule"]["check_logic"]["reference"] = "policies/missing.rego"
        compiler.sources.envelope = envelope.model_copy(
            update={
                "units": (
                    envelope.units[0],
                    envelope.units[1].model_copy(update={"text": json.dumps(marker)}),
                )
            }
        )
    elif change == "duplicate_id":
        compiler.distiller.alter = lambda result: replace(result, candidates=result.candidates * 2)
    else:
        compiler.distiller.alter = lambda result: replace(
            result, candidates=(replace(result.candidates[0], content_sha="f" * 64),)
        )
    if change == "candidate_digest":
        receipt = await compiler.compile(notice)
        assert receipt.ontology_count == 0
    else:
        with pytest.raises(ValueError):
            await compiler.compile(notice)


async def test_single_extractor_rule_proposal_has_no_fidelity_authority():
    compiler, _, notice = fixture(typed=False)
    raw = yaml.safe_load(
        (ROOT / "rule-catalog/catalog/object-storage.public-access.deny.yaml").read_text()
    )
    raw.pop("source")
    raw.pop("provenance")

    def add_rule(result):
        original = result.candidates[0]
        return replace(
            result,
            candidates=(
                *result.candidates,
                replace(
                    original,
                    kind=CandidateKind.RULE,
                    candidate_id=raw["id"],
                    body=raw,
                ),
            ),
        )

    compiler.distiller.alter = add_rule
    with pytest.raises(ValueError, match="fidelity"):
        await compiler.compile(notice)


@pytest.mark.parametrize("change", ["claim", "package", "reference"])
async def test_independent_review_binds_the_claim_and_content_address(change):
    compiler, reviewer, notice = fixture()
    receipt = await compiler.compile(notice)
    retained = compiler.packages.rows[receipt.package_ref]
    package = retained["package"]
    if change == "claim":
        retained["identity"]["source_revision"] = 2
    elif change == "package":
        package["identity"]["source_revision"] = 2
        body = {key: value for key, value in package.items() if key != "receipt"}
        digest = hashlib.sha256(
            json.dumps(
                body,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        receipt = receipt.model_copy(update={"package_digest": digest})
    else:
        reference = "human_assignment:semantic-package:" + "f" * 64
        compiler.packages.rows[reference] = compiler.packages.rows.pop(receipt.package_ref)
        receipt = receipt.model_copy(update={"package_ref": reference})
    package["receipt"] = receipt.model_dump(mode="json")
    with pytest.raises(ValueError):
        await reviewer.review(notice, receipt)


async def test_expiry_during_claim_prevents_model_work():
    compiler, _, notice = fixture()
    clock = {"at": AT}
    original_claim = compiler.packages.claim

    async def slow_claim(key, identity):
        claimed = await original_claim(key, identity)
        clock["at"] += timedelta(minutes=5)
        return claimed

    compiler.packages.claim = slow_claim
    compiler = replace(compiler, clock=lambda: clock["at"])
    with pytest.raises(ValueError):
        await compiler.compile(notice)
    assert compiler.distiller.calls == 0


async def test_review_rechecks_source_after_deterministic_compilation():
    compiler, reviewer, notice = fixture()
    receipt = await compiler.compile(notice)
    original_context = reviewer.verifier.context

    def changed_source(envelope):
        compiler.sources.available = False
        return original_context(envelope)

    reviewer = replace(reviewer, verifier=replace(reviewer.verifier, context=changed_source))
    with pytest.raises(ValueError):
        await reviewer.review(notice, receipt)


async def test_cancelled_extraction_preserves_claim_without_retrying_model():
    compiler, _, notice = fixture()

    def cancel(_):
        raise asyncio.CancelledError

    compiler.distiller.alter = cancel
    with pytest.raises(asyncio.CancelledError):
        await compiler.compile(notice)
    receipt = await compiler.compile(notice)
    assert receipt.disposition == "held" and receipt.reason == "attempt_interrupted"
    assert compiler.distiller.calls == 1


async def test_typed_rule_preserves_significant_whitespace_in_json_values():
    compiler, _, notice = fixture()
    envelope = compiler.sources.envelope
    marker = json.loads(envelope.units[1].text)
    marker["rule"]["parameters"] = {"review_label": "Preserve  two spaces"}
    compiler.sources.envelope = envelope.model_copy(
        update={
            "units": (
                envelope.units[0],
                envelope.units[1].model_copy(update={"text": json.dumps(marker)}),
            )
        }
    )
    receipt = await compiler.compile(notice)
    package = compiler.packages.rows[receipt.package_ref]["package"]
    rule = package["documents"][0]["rules"][0]["rule"]
    assert rule["parameters"]["review_label"] == "Preserve  two spaces"


@pytest.mark.parametrize("dependency", ["policy", "remediation"])
async def test_independent_review_rejects_changed_rule_dependency_bytes(tmp_path, dependency):
    compiler, reviewer, notice = fixture()
    marker = json.loads(compiler.sources.envelope.units[1].text)["rule"]
    references = {
        "policy": ("policies", marker["check_logic"]["reference"], ROOT),
        "remediation": (
            "remediation",
            marker["remediation"]["template_ref"],
            ROOT / "rule-catalog",
        ),
    }
    copied = {}
    for name, (_prefix, reference, source_root) in references.items():
        copied[name] = tmp_path / reference
        copied[name].parent.mkdir(parents=True, exist_ok=True)
        copied[name].write_bytes((source_root / reference).read_bytes())
    rules = replace(
        compiler.verifier.rules,
        policies_root=tmp_path / "policies",
        remediation_root=tmp_path / "remediation",
    )
    verifier = replace(compiler.verifier, rules=rules)
    compiler = replace(compiler, verifier=verifier)
    reviewer = replace(reviewer, verifier=verifier)
    receipt = await compiler.compile(notice)
    copied[dependency].write_bytes(
        copied[dependency].read_bytes() + b"\n# Changed synthetic dependency.\n"
    )
    with pytest.raises(ValueError):
        await reviewer.review(notice, receipt)


@pytest.mark.parametrize("field,value", [("rule_count", 2), ("reason", "source_withdrawn")])
async def test_independent_review_derives_receipt_counts_and_outcome(field, value):
    compiler, reviewer, notice = fixture()
    receipt = await compiler.compile(notice)
    receipt = receipt.model_copy(update={field: value})
    compiler.packages.rows[receipt.package_ref]["package"]["receipt"] = receipt.model_dump(
        mode="json"
    )
    with pytest.raises(ValueError):
        await reviewer.review(notice, receipt)


async def test_withdrawn_source_is_checked_before_private_package_content():
    compiler, reviewer, notice = fixture()
    receipt = await compiler.compile(notice)
    compiler.sources.available = False
    reads = []
    original = compiler.packages.read

    async def read(key):
        reads.append(key)
        return await original(key)

    compiler.packages.read = read
    with pytest.raises(ValueError):
        await reviewer.review(notice, receipt)
    assert not reads
