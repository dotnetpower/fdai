"""The complete bilingual presentation corpus cannot become evidence or authority."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from fdai_service_contracts.catalog_canonical import canonical_bytes, canonical_digest
from fdai_service_contracts.framework_guidance import (
    EXPECTED_COUNTS,
    MAXIMUM_CATALOG_BYTES,
    FrameworkGuidance,
    FrameworkGuidanceMismatch,
    FrameworkGuidanceUnavailable,
    assert_framework_guidance_catalog,
    framework_guidance_detail,
    load_framework_guidance,
    packaged_framework_guidance,
    resolve_framework_guidance,
)

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "packages/service-contracts/src/fdai_service_contracts/data"


def _seal(material: dict, key: str = "content_digest") -> dict:
    material[key] = "sha256:" + canonical_digest(
        {name: value for name, value in material.items() if name != key}
    )
    return material


@pytest.fixture(scope="module")
def catalog():
    return packaged_framework_guidance()


@pytest.fixture
def entry(catalog):
    return catalog.entries[0].model_dump(mode="json", by_alias=True)


def _texts(value):
    if isinstance(value, dict):
        if "en" in value:
            yield value
        for item in value.values():
            yield from _texts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _texts(item)


def test_complete_counts_and_authoritative_identity(catalog):
    assert Counter(entry.framework_id for entry in catalog.entries) == EXPECTED_COUNTS
    for framework_id, count in EXPECTED_COUNTS.items():
        body = (
            ROOT / f"rule-catalog/framework-assessments/generated/{framework_id}.json"
        ).read_bytes()
        source = json.loads(body)
        assert_framework_guidance_catalog(catalog, framework_id, body)
        controls = {control["control_id"]: control for control in source["controls"]}
        assert len(controls) == count
        for guide in (entry for entry in catalog.entries if entry.framework_id == framework_id):
            control = controls[guide.control_id]
            assert guide.title.en == control["title"]
            assert guide.source_revision == source["source_revision_digest"]
            assert guide.source_digest == control["specification_digest"]
            assert (
                resolve_framework_guidance(
                    framework_id=framework_id,
                    control_id=guide.control_id,
                    source_revision=guide.source_revision,
                    source_digest=guide.source_digest,
                )
                is guide
            )


def test_every_reader_text_is_complete_readable_korean(catalog):
    for guide in catalog.entries:
        for text in _texts(guide.model_dump(mode="json", by_alias=True)):
            assert text["en"].strip() and text["ko"].strip()
            assert re.search("[가-힣]", text["ko"])
            assert text["ko"] == unicodedata.normalize("NFC", text["ko"])
            assert not text["ko"].startswith(("예시: ", "설명: "))
            assert not re.search("[ぁ-ヿ]", text["ko"])
            assert not any(token in text["ko"] for token in ("\u2014", "\u2013", "\u00a0"))


def test_each_control_has_original_specific_mechanism_and_practice(catalog):
    for field in ("summary", "benefits"):
        assert len({getattr(entry, field).en for entry in catalog.entries}) == 160
        assert len({getattr(entry, field).ko for entry in catalog.entries}) == 160
    for guide in catalog.entries:
        assert len(guide.summary.en.split()) >= 7
        assert guide.summary.en != guide.title.en
        assert guide.configuration.before[0] != guide.configuration.after[0]
        assert guide.implementation_steps[1] == guide.configuration.after[0]
        assert guide.verification_steps[0].en not in {
            "Check the configuration.",
            "Review the evidence.",
            "Verify the control.",
        }
        source = json.loads(
            (
                ROOT / f"rule-catalog/framework-assessments/generated/{guide.framework_id}.json"
            ).read_bytes()
        )
        control = next(
            item for item in source["controls"] if item["control_id"] == guide.control_id
        )
        rendered = " ".join(text["en"] for text in _texts(guide.model_dump(mode="json")))
        for requirement in control["evidence"]:
            assert requirement["requirement_id"] in rendered
            assert requirement["authoritative_producer"] in rendered
            assert str(requirement["freshness_ceiling_seconds"]) in rendered
            for role in requirement["approval_roles"]:
                assert role in rendered
            assert requirement["failure_behavior"] in rendered
            assert requirement["generation_contract"] in rendered
        assert "unknown" in guide.cautions[1].en
        assert "no execution authority" in guide.cautions[1].en


def test_catalog_digest_uses_the_shared_ascii_canonical_format(catalog):
    material = catalog.model_dump(mode="json", by_alias=True)
    assert b"\\u" in canonical_bytes(material)
    assert catalog.catalog_digest == _seal(material, "catalog_digest")["catalog_digest"]
    for guide in catalog.entries:
        assert (
            guide.content_digest
            == _seal(guide.model_dump(mode="json", by_alias=True))["content_digest"]
        )


def test_detail_attachment_is_pure_and_preserves_evidence_authority_and_legacy_source(catalog):
    for guide in catalog.entries:
        detail = {
            "control_id": guide.control_id,
            "benchmark_version": "v1",
            "source_revision": "a" * 40,
            "guidance_source_revision": guide.source_revision,
            "guidance_source_digest": guide.source_digest,
            "evaluation": {"status": "unknown", "missing": ["required-evidence"]},
            "execution_authority": False,
            "remediation_candidates": [],
        }
        before = copy.deepcopy(detail)
        attached = framework_guidance_detail(
            MappingProxyType(detail), framework_id=guide.framework_id
        )
        assert detail == before
        assert {key: value for key, value in attached.items() if key != "guidance"} == before
        assert attached["guidance"] == guide.model_dump(mode="json", by_alias=True)


@pytest.mark.parametrize(
    "legacy",
    [
        {"id": "CO:01", "title": "Source title", "provenance": {"resolved_ref": "a" * 40}},
        {"control_id": "strategy", "source_revision": "a" * 40, "source_version": "2026-01-01"},
        {
            "control_id": "NS-1",
            "benchmark_version": "v1",
            "source": {
                "resolved_ref": "a" * 40,
                "content_hash": "sha256:" + "0" * 64,
            },
        },
        {"control_id": "RE:01", "source_revision": "synthetic", "source_digest": "fake"},
    ],
)
def test_legacy_or_fabricated_source_never_implies_current_guidance(legacy):
    framework_id = (
        "azure-caf"
        if legacy.get("control_id") == "strategy"
        else "azure-mcsb"
        if "benchmark_version" in legacy
        else "azure-waf"
    )
    detail = {**legacy, "guidance": {"injected": True}}
    attached = framework_guidance_detail(detail, framework_id=framework_id)
    assert attached["guidance"] is None
    assert attached["guidance_unavailable_reason"] == "missing_source_pins"
    assert detail["guidance"] == {"injected": True}


@pytest.mark.parametrize("version", ["v2-preview", "v2", None, ""])
def test_mcsb_other_or_missing_version_never_receives_v1_guidance(catalog, version):
    guide = next(item for item in catalog.entries if item.framework_id == "azure-mcsb")
    attached = framework_guidance_detail(
        {
            "control_id": guide.control_id,
            "benchmark_version": version,
            "guidance_source_revision": guide.source_revision,
            "guidance_source_digest": guide.source_digest,
        },
        framework_id="azure-mcsb",
    )
    assert attached["guidance"] is None
    assert attached["guidance_unavailable_reason"] == "unsupported_benchmark_version"


@pytest.mark.parametrize("wrong", ["fake-legacy-pin", "", 7])
def test_present_invalid_detail_pins_raise_bounded_value_error(catalog, wrong):
    guide = catalog.entries[0]
    with pytest.raises(ValueError) as error:
        framework_guidance_detail(
            {
                "control_id": guide.control_id,
                "guidance_source_revision": guide.source_revision,
                "guidance_source_digest": wrong,
            },
            framework_id=guide.framework_id,
        )
    assert len(str(error.value)) < 200
    assert "fake-legacy-pin" not in str(error.value)


def test_missing_detail_identity_and_unavailable_package_are_explicit(catalog):
    assert framework_guidance_detail({}, framework_id="azure-waf") == {
        "guidance": None,
        "guidance_unavailable_reason": "missing_control_identity",
    }
    guide = catalog.entries[0]
    with patch(
        "fdai_service_contracts.framework_guidance.packaged_framework_guidance",
        side_effect=FrameworkGuidanceUnavailable("Unavailable"),
    ):
        attached = framework_guidance_detail(
            {
                "control_id": guide.control_id,
                "guidance_source_revision": guide.source_revision,
                "guidance_source_digest": guide.source_digest,
            },
            framework_id=guide.framework_id,
        )
    assert attached["guidance"] is None
    assert attached["guidance_unavailable_reason"] == "guidance_unavailable"


@pytest.mark.parametrize("field", ["source_revision", "source_digest"])
def test_lookup_rejects_mismatched_pin(catalog, field):
    guide = catalog.entries[0]
    request = {
        "framework_id": guide.framework_id,
        "control_id": guide.control_id,
        "source_revision": guide.source_revision,
        "source_digest": guide.source_digest,
    }
    request[field] = "sha256:" + "0" * 64
    with pytest.raises(FrameworkGuidanceMismatch, match="source pins"):
        resolve_framework_guidance(**request)


@pytest.mark.parametrize(
    "framework_id,control_id",
    [
        ("azure-wara", "RE:01"),
        ("azure-caf", "RE:01"),
        ("azure-waf", "not-a-control"),
        ("azure-mcsb", "00000000-0000-0000-0000-000000000000"),
    ],
)
def test_lookup_rejects_unknown_or_cross_framework_identity(framework_id, control_id):
    with pytest.raises(FrameworkGuidanceUnavailable, match="unavailable"):
        resolve_framework_guidance(
            framework_id=framework_id,
            control_id=control_id,
            source_revision="sha256:" + "0" * 64,
            source_digest="sha256:" + "0" * 64,
        )


def test_tampered_reader_text_fails_digest(entry):
    entry["benefits"]["en"] = "Tampered content."
    with pytest.raises(ValidationError, match="content digest"):
        FrameworkGuidance.model_validate(entry)


@pytest.mark.parametrize(
    "change", ["missing-ko", "blank-ko", "markup", "wrong-identity", "authority"]
)
def test_strict_presentation_validation(entry, change):
    if change == "missing-ko":
        entry["diagram"]["nodes"][0]["detail"].pop("ko")
    elif change == "blank-ko":
        entry["summary"]["ko"] = " "
    elif change == "markup":
        entry["title"]["en"] = "<script>alert(1)</script>"
    elif change == "wrong-identity":
        entry["framework_id"] = "azure-caf"
    else:
        entry["execution_authority"] = True
    with pytest.raises(ValidationError):
        FrameworkGuidance.model_validate(_seal(entry))


@pytest.mark.parametrize(
    "change",
    [
        "duplicate-node",
        "self-edge",
        "unknown-end",
        "isolated-node",
        "duplicate-edge",
        "wrong-direction",
        "missing-evidence-role",
    ],
)
def test_malformed_directed_diagrams_are_rejected(entry, change):
    diagram = entry["diagram"]
    if change == "duplicate-node":
        diagram["nodes"][1]["id"] = diagram["nodes"][0]["id"]
    elif change == "self-edge":
        diagram["edges"][0]["to"] = diagram["edges"][0]["from"]
    elif change == "unknown-end":
        diagram["edges"][0]["to"] = "missing"
    elif change == "isolated-node":
        diagram["nodes"].append(
            {
                "id": "isolated",
                "label": {"en": "Unused", "ko": "미사용"},
                "detail": {"en": "No relation", "ko": "관계 없음"},
                "role": "dependency",
            }
        )
    elif change == "duplicate-edge":
        diagram["edges"].append(copy.deepcopy(diagram["edges"][0]))
    elif change == "wrong-direction":
        for edge in diagram["edges"]:
            edge["from"], edge["to"] = edge["to"], edge["from"]
    else:
        diagram["nodes"][2]["role"] = "dependency"
    with pytest.raises(ValidationError, match="diagram"):
        FrameworkGuidance.model_validate(_seal(entry))


@pytest.mark.parametrize(
    "url",
    [
        "http://learn.microsoft.com/en-us/example",
        "https://example.com/control",
        "https://learn.microsoft.com@evil.example/control",
        "https://learn.microsoft.com/en-us/../private",
        "https://learn.microsoft.com/en-us/%2e%2e/private",
        "https://learn.microsoft.com/en-us/control?token=redacted",
    ],
)
def test_sources_reject_unreviewed_or_unsafe_urls(entry, url):
    entry["sources"][0]["url"] = url
    with pytest.raises(ValidationError):
        FrameworkGuidance.model_validate(_seal(entry))


def test_catalog_tampering_and_duplicate_accounting_fail(catalog):
    material = catalog.model_dump(mode="json", by_alias=True)
    material["entries"][0] = copy.deepcopy(material["entries"][1])
    with pytest.raises(ValidationError, match="duplicated"):
        load_framework_guidance(json.dumps(_seal(material, "catalog_digest")).encode())
    material = catalog.model_dump(mode="json", by_alias=True)
    material["pins"][0]["expected_control_count"] = 58
    with pytest.raises(ValidationError, match="accounting"):
        load_framework_guidance(json.dumps(_seal(material, "catalog_digest")).encode())
    material = catalog.model_dump(mode="json", by_alias=True)
    material["catalog_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValidationError, match="catalog digest"):
        load_framework_guidance(json.dumps(material).encode())


@pytest.mark.parametrize(
    "field",
    [
        "catalog_digest",
        "source_revision_digest",
        "framework_definition_digest",
        "control",
        "duplicate-control",
        "missing-control",
    ],
)
def test_authoritative_catalog_drift_is_rejected(catalog, field):
    body = (ROOT / "rule-catalog/framework-assessments/generated/azure-waf.json").read_bytes()
    material = json.loads(body)
    if field == "control":
        material["controls"][0]["specification_digest"] = "sha256:" + "0" * 64
    elif field == "duplicate-control":
        material["controls"][0] = material["controls"][1]
    elif field == "missing-control":
        material["controls"].pop()
    else:
        material[field] = "sha256:" + "0" * 64
    with pytest.raises(FrameworkGuidanceMismatch):
        assert_framework_guidance_catalog(catalog, "azure-waf", json.dumps(material).encode())


def test_catalog_and_shard_byte_limits(catalog):
    with pytest.raises(ValueError, match="byte limit"):
        load_framework_guidance(b" " * (MAXIMUM_CATALOG_BYTES + 1))
    with pytest.raises(FrameworkGuidanceMismatch, match="byte limit"):
        assert_framework_guidance_catalog(catalog, "azure-waf", b" " * (MAXIMUM_CATALOG_BYTES + 1))
    manifest = json.loads((DATA / "framework-guidance.json").read_bytes())
    assert len(manifest["official_sources"]) == 21
    assert len(manifest["shards"]) == 10
    for shard in manifest["shards"]:
        body = (DATA / shard["file"]).read_bytes()
        assert len(body) <= 524_288
        assert shard["digest"] == "sha256:" + hashlib.sha256(body).hexdigest()


@pytest.mark.parametrize("target", ["shard", "manifest-source", "manifest-shard-path"])
def test_packaged_load_reports_missing_and_tampered_files(target):
    original = Path.read_bytes

    def tampered(path):
        body = original(path)
        if target == "shard" and path.name == "framework-guidance-00.json":
            return body + b" "
        if target.startswith("manifest-") and path.name == "framework-guidance.json":
            material = json.loads(body)
            if target == "manifest-source":
                material["official_sources"][0]["resolved_ref"] = "0" * 40
            else:
                material["shards"][0]["file"] = "../framework-guidance-00.json"
            return json.dumps(material).encode()
        return body

    packaged_framework_guidance.cache_clear()
    try:
        with patch.object(Path, "read_bytes", tampered):
            with pytest.raises(FrameworkGuidanceUnavailable, match="missing or invalid"):
                packaged_framework_guidance()
        with patch.object(Path, "read_bytes", side_effect=FileNotFoundError):
            with pytest.raises(FrameworkGuidanceUnavailable, match="missing or invalid"):
                packaged_framework_guidance()
    finally:
        packaged_framework_guidance.cache_clear()
