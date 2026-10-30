"""Illustrated reference content never becomes evidence or an execution contract."""

from __future__ import annotations

import copy
import hashlib
import json
import struct
import zlib
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest

from fdai_service_contracts.catalog_canonical import canonical_digest
from fdai_service_contracts.reference_image_assets import (
    load_packaged_reference_image,
    verify_reference_image_bytes,
)
from fdai_service_contracts.wara_guidance import (
    ReferenceImage,
    WaraGuidance,
    assert_wara_guidance_framework,
    load_wara_guidance,
    packaged_wara_guidance,
    wara_guidance_detail,
)

ROOT = Path(__file__).resolve().parents[3]
FRAMEWORK = ROOT / "rule-catalog/collected/wara-aprl/azure-wara.json"


def _text(value: str) -> dict[str, str]:
    return {"en": value, "ko": f"예시: {value}"}


def _seal(value: dict[str, object], key: str) -> dict[str, object]:
    value[key] = "sha256:" + canonical_digest(
        {name: item for name, item in value.items() if name != key}
    )
    return value


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def _png(width: int = 1, height: int = 1) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    pixels = b"\x00" + b"\x00\x00\x00" * width * height
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(pixels))
        + _png_chunk(b"IEND", b"")
    )


def _reference_image(content: bytes) -> dict[str, object]:
    digest = hashlib.sha256(content).hexdigest()
    return {
        "asset_id": f"sha256-{digest}",
        "digest": f"sha256:{digest}",
        "source_document_url": (
            "https://learn.microsoft.com/en-us/azure/backup/backup-azure-vms-introduction"
        ),
        "image_url": (
            "https://learn.microsoft.com/en-us/azure/backup/media/"
            "backup-azure-vms-introduction/vmbackup-architecture.png"
        ),
        "source_revision": "a" * 40,
        "attribution": "Microsoft, About Azure VM backup - Azure Backup",
        "license": "CC-BY-4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "alt": {"en": "A reference image.", "ko": "참고 이미지."},
        "caption": {"en": "Backup flow.", "ko": "백업 흐름."},
        "english_in_image_notice": {
            "en": "Text in the image is in English.",
            "ko": "이미지 내 텍스트는 영어입니다.",
        },
    }


@pytest.fixture(scope="module")
def catalog_material() -> dict[str, object]:
    framework = json.loads(FRAMEWORK.read_text(encoding="utf-8"))
    revision = next(
        source["resolved_ref"] for source in framework["sources"] if source["id"] == "aprl"
    )
    entries = []
    for area in framework["areas"]:
        for control in area["controls"]:
            metadata = control["wara"]
            material = {
                "schema_version": "1.0.0",
                "recommendation_id": control["id"],
                "source_revision": revision,
                "source_digest": metadata["source_digest"],
                "lifecycle": metadata["state"].casefold(),
                "title": _text(control["title"]),
                "summary": _text(control["description"]),
                "benefits": _text(metadata["potential_benefits"]),
                "rationale": _text("A test-only explanation of the configuration relationship."),
                "applicability": [_text("Exact resource scope."), _text("Reviewed prerequisites.")],
                "configuration": {
                    "before": [_text("Unverified configuration."), _text("Unproven coverage.")],
                    "after": [_text("Reviewed configuration."), _text("Verified coverage.")],
                },
                "implementation_steps": [_text(f"Implementation step {i}.") for i in range(3)],
                "verification_steps": [_text(f"Verification step {i}.") for i in range(3)],
                "cautions": [
                    _text("No execution authority."),
                    _text("An example is not evidence."),
                ],
                "diagram": {
                    "id": "test-configuration",
                    "kind": "test-relationship",
                    "title": _text("Test diagram"),
                    "description": _text("Test-only relationship."),
                    "nodes": [
                        {
                            "id": "resource",
                            "label": _text("Resource"),
                            "detail": _text("Exact scope."),
                            "role": "subject",
                        },
                        {
                            "id": "configuration",
                            "label": _text("Configuration"),
                            "detail": _text("Reviewed settings."),
                            "role": "configuration",
                        },
                        {
                            "id": "observation",
                            "label": _text("Observation"),
                            "detail": _text("Independent verification."),
                            "role": "evidence",
                        },
                    ],
                    "edges": [
                        {
                            "from": "resource",
                            "to": "configuration",
                            "label": _text("uses"),
                            "style": "solid",
                        },
                        {
                            "from": "configuration",
                            "to": "observation",
                            "label": _text("verified by"),
                            "style": "dashed",
                        },
                    ],
                },
                "sources": [
                    {
                        "label": _text("Pinned APRL source"),
                        "url": area["source_url"],
                        "kind": "aprl",
                    }
                ],
            }
            entries.append(_seal(material, "content_digest"))
    return _seal(
        {
            "schema_version": "1.0.0",
            "framework_revision": revision,
            "framework_digest": "sha256:" + hashlib.sha256(FRAMEWORK.read_bytes()).hexdigest(),
            "entries": entries,
        },
        "catalog_digest",
    )


def test_complete_lifecycle_corpus_is_immutable_and_source_bound(catalog_material) -> None:
    catalog = load_wara_guidance(json.dumps(catalog_material).encode())
    assert len(catalog.entries) == 456
    assert sum(entry.lifecycle == "active" for entry in catalog.entries) == 393
    assert_wara_guidance_framework(catalog, FRAMEWORK.read_bytes())
    with pytest.raises(ValueError, match="framework digest"):
        assert_wara_guidance_framework(catalog, b"tampered")
    with pytest.raises(ValueError):
        catalog.entries[0].lifecycle = "disabled"


def test_optional_reference_image_is_typed_and_legacy_digest_shape_is_unchanged(
    catalog_material,
) -> None:
    legacy = WaraGuidance.model_validate(catalog_material["entries"][0])
    assert legacy.reference_image is None
    assert "reference_image" not in legacy.model_dump(mode="json", by_alias=True, exclude_none=True)

    raw = copy.deepcopy(catalog_material["entries"][0])
    raw["reference_image"] = _reference_image(_png())
    _seal(raw, "content_digest")
    guide = WaraGuidance.model_validate(raw)
    serialized = guide.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert serialized["reference_image"] == raw["reference_image"]
    assert "reference_image" not in serialized["diagram"]
    assert guide.content_digest == raw["content_digest"]


@pytest.mark.parametrize(
    "change",
    ["asset_id", "digest", "source_document_url", "image_url", "license_url", "markup"],
)
def test_reference_image_provenance_and_local_origin_are_strict(catalog_material, change) -> None:
    raw = copy.deepcopy(catalog_material["entries"][0])
    image = _reference_image(_png())
    if change == "asset_id":
        image["asset_id"] = "sha256-" + "0" * 64
    elif change == "digest":
        image["digest"] = "sha256:" + "0" * 64
    elif change == "source_document_url":
        image["source_document_url"] = "https://learn.microsoft.com@evil.example/doc"
    elif change == "image_url":
        image["image_url"] = "https://learn.microsoft.com/azure/backup/image.png?token=x"
    elif change == "license_url":
        image["license_url"] = "https://example.com/license"
    else:
        image["alt"] = {"en": "<img src=x>", "ko": "참고 이미지."}
    raw["reference_image"] = image
    _seal(raw, "content_digest")
    with pytest.raises(ValueError):
        WaraGuidance.model_validate(raw)


def test_packaged_reference_image_is_content_addressed_and_bounded(monkeypatch) -> None:
    content = _png(898, 400)
    image = ReferenceImage.model_validate(_reference_image(content))
    joined_paths: list[tuple[str, ...]] = []

    class MemoryResource:
        def joinpath(self, *parts: str) -> MemoryResource:
            joined_paths.append(parts)
            return self

        def open(self, mode: str) -> BytesIO:
            assert mode == "rb"
            return BytesIO(content)

    monkeypatch.setattr(
        "fdai_service_contracts.reference_image_assets.resources.files",
        lambda _: MemoryResource(),
    )
    asset = load_packaged_reference_image(image)
    assert (asset.width, asset.height) == (898, 400)
    assert asset.content == content
    assert joined_paths == [
        ("data", "wara-guidance-assets"),
        (f"{image.asset_id}.png",),
    ]
    assert verify_reference_image_bytes(image, content).content == content
    with pytest.raises(ValueError, match="digest"):
        verify_reference_image_bytes(image, content + b"tampered")
    oversized_content = content + b"\x00" * (2_097_153 - len(content))
    oversized_image = ReferenceImage.model_validate(_reference_image(oversized_content))
    with pytest.raises(ValueError, match="byte limit"):
        verify_reference_image_bytes(oversized_image, oversized_content)
    oversized = _png(4_097, 1)
    oversized_image = ReferenceImage.model_validate(_reference_image(oversized))
    with pytest.raises(ValueError, match="dimensions"):
        verify_reference_image_bytes(oversized_image, oversized)


@pytest.mark.parametrize("change", ["duplicate", "omission", "source", "lifecycle", "digest"])
def test_corpus_coverage_and_source_drift_are_explicit_errors(catalog_material, change) -> None:
    raw = copy.deepcopy(catalog_material)
    if change == "duplicate":
        raw["entries"][1] = raw["entries"][0]
    elif change == "omission":
        raw["entries"].pop()
    elif change == "source":
        raw["framework_revision"] = "0" * 40
    elif change == "lifecycle":
        raw["entries"][0]["lifecycle"] = (
            "disabled" if raw["entries"][0]["lifecycle"] == "active" else "active"
        )
        _seal(raw["entries"][0], "content_digest")
    else:
        raw["entries"][0]["summary"]["en"] = "tampered"
    _seal(raw, "catalog_digest")
    with pytest.raises(ValueError):
        load_wara_guidance(json.dumps(raw).encode())


@pytest.mark.parametrize("change", ["authority", "bad_edge", "isolated", "html", "empty_english"])
def test_invalid_presentation_structures_are_not_silently_rendered(
    catalog_material, change
) -> None:
    raw = copy.deepcopy(catalog_material["entries"][0])
    if change == "authority":
        raw["execution_authority"] = True
    elif change == "bad_edge":
        raw["diagram"]["edges"][0]["to"] = "unknown"
    elif change == "isolated":
        raw["diagram"]["edges"].pop()
    elif change == "html":
        raw["diagram"]["html"] = "<script>forbidden</script>"
    else:
        raw["summary"]["en"] = " "
    _seal(raw, "content_digest")
    with pytest.raises(ValueError):
        WaraGuidance.model_validate_json(json.dumps(raw))


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/guide",
        "https://learn.microsoft.com@evil.example/guide",
        "http://learn.microsoft.com/guide",
        "https://learn.microsoft.com:8443/guide",
        "https://learn.microsoft.com/guide?token=forbidden",
        "javascript:alert(1)",
    ],
)
def test_reference_links_cannot_become_provider_or_untrusted_endpoints(
    catalog_material, url
) -> None:
    raw = copy.deepcopy(catalog_material["entries"][0])
    raw["sources"].append({"label": _text("Documentation"), "url": url, "kind": "learn"})
    _seal(raw, "content_digest")
    with pytest.raises(ValueError):
        WaraGuidance.model_validate_json(json.dumps(raw))


@pytest.mark.parametrize(
    "suffix",
    [
        "../another-repository/guide",
        "%2e%2e/another-repository/guide",
        "guide%0d%0a",
        "folder%5c..%5cprivate",
    ],
)
def test_public_repository_reference_cannot_escape_its_reviewed_path(
    catalog_material, suffix
) -> None:
    raw = copy.deepcopy(catalog_material["entries"][0])
    raw["sources"][0]["url"] = (
        "https://github.com/Azure/Azure-Proactive-Resiliency-Library-v2/" + suffix
    )
    _seal(raw, "content_digest")
    with pytest.raises(ValueError):
        WaraGuidance.model_validate_json(json.dumps(raw))


def test_exact_vendor_citation_is_not_a_wildcard_document_origin(catalog_material) -> None:
    raw = copy.deepcopy(catalog_material["entries"][0])
    raw["sources"].append(
        {
            "label": _text("Product-specific public limit"),
            "kind": "vendor",
            "url": "https://docs.citrix.com/us/en/citrix-daas-azure/limits.html",
        }
    )
    _seal(raw, "content_digest")
    assert WaraGuidance.model_validate_json(json.dumps(raw)).sources[-1].kind == "vendor"
    raw["sources"][-1]["url"] = "https://docs.citrix.com/us/en/private-document.html"
    _seal(raw, "content_digest")
    with pytest.raises(ValueError):
        WaraGuidance.model_validate_json(json.dumps(raw))


def test_detail_attachment_preserves_actual_evaluation_and_authority(catalog_material) -> None:
    catalog = load_wara_guidance(json.dumps(catalog_material).encode())
    guide = catalog.entries[0]
    control = {
        "id": guide.recommendation_id,
        "source_revision": guide.source_revision,
        "source_digest": guide.source_digest,
        "lifecycle": guide.lifecycle,
        "satisfaction": "unknown",
        "evaluation_status": "blocked",
        "execution_authority": False,
    }
    with patch("fdai_service_contracts.wara_guidance.packaged_wara_guidance", return_value=catalog):
        value = wara_guidance_detail(control)
        assert all(value[key] == expected for key, expected in control.items())
        assert value["guidance"]["recommendation_id"] == control["id"]
        assert value["description"] == guide.summary.en
        assert value["potential_benefits"] == guide.benefits.en
        with pytest.raises(ValueError, match="selected recommendation source"):
            wara_guidance_detail({**control, "source_digest": "sha256:" + "0" * 64})


def test_unknown_legacy_record_is_explicitly_without_guide(catalog_material) -> None:
    catalog = load_wara_guidance(json.dumps(catalog_material).encode())
    with patch("fdai_service_contracts.wara_guidance.packaged_wara_guidance", return_value=catalog):
        result = wara_guidance_detail({"id": "legacy-example", "satisfaction": "unknown"})
    assert result == {"id": "legacy-example", "satisfaction": "unknown", "guidance": None}


def test_oversized_corpus_is_rejected_before_parsing() -> None:
    with pytest.raises(ValueError, match="byte limit"):
        load_wara_guidance(b" " * 8_388_609)


@pytest.fixture
def packaged_directory(catalog_material, tmp_path, monkeypatch):
    directory = tmp_path / "data"
    directory.mkdir()
    references = []
    for offset in range(0, 456, 32):
        entries = catalog_material["entries"][offset : offset + 32]
        body = json.dumps({"entries": entries}, ensure_ascii=False).encode()
        name = f"wara-guidance-{offset // 32:02d}.json"
        (directory / name).write_bytes(body)
        references.append(
            {
                "path": name,
                "digest": "sha256:" + hashlib.sha256(body).hexdigest(),
                "count": len(entries),
            }
        )
    manifest = {key: value for key, value in catalog_material.items() if key != "entries"}
    manifest["shards"] = references
    (directory / "wara-guidance.json").write_text(json.dumps(manifest))
    monkeypatch.setattr("fdai_service_contracts.wara_guidance.resources.files", lambda _: tmp_path)
    packaged_wara_guidance.cache_clear()
    yield directory, manifest
    packaged_wara_guidance.cache_clear()


def test_packaged_manifest_keeps_every_entry_bounded_and_content_addressed(
    packaged_directory,
) -> None:
    directory, _ = packaged_directory
    catalog = packaged_wara_guidance()
    assert len(catalog.entries) == 456
    assert all(path.stat().st_size <= 524_288 for path in directory.iterdir())
    assert packaged_wara_guidance() is catalog


@pytest.mark.parametrize("change", ["path", "bytes", "count", "missing", "duplicate"])
def test_packaged_shards_fail_explicitly_on_substitution_or_missing_content(
    packaged_directory, change
) -> None:
    directory, manifest = packaged_directory
    reference = manifest["shards"][0]
    target = directory / reference["path"]
    if change == "path":
        reference["path"] = "../outside.json"
    elif change == "bytes":
        target.write_bytes(target.read_bytes() + b" ")
    elif change == "count":
        reference["count"] += 1
    elif change == "missing":
        target.unlink()
    else:
        manifest["shards"][1]["path"] = reference["path"]
    (directory / "wara-guidance.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        packaged_wara_guidance()
