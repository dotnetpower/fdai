#!/usr/bin/env python3
"""Build the pinned, inert WARA explanation corpus without network or model calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from wara_guidance_critique import apply_specifics, critique_report
from wara_guidance_data import PROFILES as DATA
from wara_guidance_diagrams import build_diagram
from wara_guidance_domains import domain_note
from wara_guidance_images import (
    apply_reference_image,
    image_authoring_inputs,
    image_review_summary,
)
from wara_guidance_localization import (
    LOCALIZATION_SOURCE,
    apply_reader_text,
    assert_korean_reader_text,
    load_reader_text,
)
from wara_guidance_network import PROFILES as NETWORK
from wara_guidance_operations import PROFILES as OPERATIONS
from wara_guidance_pilots import PILOT_IDS, apply_pilot
from wara_guidance_reliability import PROFILES as RELIABILITY
from wara_guidance_reliability import localized as text
from wara_guidance_resolutions import RESOLUTIONS, apply_resolution

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path("rule-catalog/guidance/azure-wara/authoring-manifest.json")
PROFILES = RELIABILITY | OPERATIONS | NETWORK | DATA
MAXIMUM_BYTES = 8 * 1024 * 1024
MAXIMUM_SHARD_BYTES = 512 * 1024
SHARD_SIZE = 32
_PUNCTUATION = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
        "\u00a0": " ",
        "\u202f": " ",
        "\u200b": "",
    }
)


def canonical_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value.translate(_PUNCTUATION)).strip()
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    return value


def load_bindings(path: Path) -> dict[str, dict[str, str]]:
    bindings = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        columns = line.split("|")
        if len(columns) != 4 or any(not part.strip() for part in columns):
            raise ValueError(f"{path}:{number}: expected four nonempty binding columns")
        prefix, family, focus, observation = columns
        if prefix in bindings:
            raise ValueError(f"{path}:{number}: duplicate GUID prefix {prefix}")
        if family not in PROFILES:
            raise ValueError(f"{path}:{number}: unknown mechanism {family}")
        bindings[prefix] = {"family": family, "focus": focus, "observation": observation}
    return bindings


def _sources(control: dict[str, Any], revision: str) -> list[dict[str, Any]]:
    metadata = control["wara"]
    sources = [
        {
            "kind": "aprl",
            "url": "https://github.com/Azure/Azure-Proactive-Resiliency-Library-v2/"
            f"blob/{revision}/{metadata['source_path']}",
            "label": text("Pinned APRL recommendation source (MIT)", "고정된 APRL 권고 원본(MIT)"),
        }
    ]
    original = metadata.get("learn_more_url", "")
    parsed = urlsplit(original)
    if parsed.scheme == "https" and parsed.hostname == "learn.microsoft.com":
        sources.append(
            {
                "kind": "learn",
                "url": parsed._replace(query="").geturl(),
                "label": text(
                    metadata.get("learn_more_name") or "Original Microsoft Learn reference"
                ),
            }
        )
    return sources


def load_korean_bindings(path: Path, bindings: dict[str, dict[str, str]]) -> None:
    localized = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line or line.startswith("#"):
            continue
        columns = line.split("|")
        if len(columns) != 3 or any(not part.strip() for part in columns):
            raise ValueError(f"{path}:{number}: expected three nonempty Korean binding columns")
        prefix, focus, observation = columns
        if prefix in localized:
            raise ValueError(f"{path}:{number}: duplicate Korean binding prefix {prefix}")
        localized[prefix] = {"focus_ko": focus, "observation_ko": observation}
    if set(localized) != set(bindings):
        raise ValueError(
            "Korean guidance bindings must cover every pinned GUID prefix exactly once"
        )
    for prefix, values in localized.items():
        bindings[prefix].update(values)


def _entry(
    control: dict[str, Any],
    binding: dict[str, str],
    revision: str,
    reader_text: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    metadata = control["wara"]
    family = PROFILES[binding["family"]]
    focus, observation = binding["focus"], binding["observation"]
    focus_ko, observation_ko = binding["focus_ko"], binding["observation_ko"]
    note = domain_note(metadata["source_path"])
    description = text(
        "Repository-authored conceptual diagram, not an observed deployment or assessment result. "
        + family["rationale"]["en"],
        "실제 배포나 평가 결과가 아닌 저장소 작성 개념도입니다. " + family["rationale"]["ko"],
    )
    entry = {
        "schema_version": "1.0.0",
        "recommendation_id": control["id"],
        "source_revision": revision,
        "source_digest": metadata["source_digest"],
        "lifecycle": metadata["state"].casefold(),
        "title": text(control["title"]),
        "summary": text(control["description"]),
        "benefits": text(
            metadata["potential_benefits"]
            or "The source does not state a separate benefit; "
            "review its description and intended mechanism."
        ),
        "rationale": family["rationale"],
        "applicability": [
            text(
                f"Source resource or workload: "
                f"{metadata['resource_type'] or metadata['source_path']}. "
                f"Specific focus: {focus}.",
                f"원본의 리소스 또는 워크로드: "
                f"{metadata['resource_type'] or metadata['source_path']}. "
                f"구체적인 초점: {focus_ko}.",
            ),
            family["applies"],
        ],
        "configuration": {
            "before": [
                family["before"],
                text(
                    f"Recommendation-specific baseline to inspect: {observation}. "
                    "This is an inspection question, not a finding about the current environment.",
                    f"권고별 점검 기준: {observation_ko}. "
                    "이는 점검할 질문이며 현재 환경에서 발견한 문제를 뜻하지 않습니다.",
                ),
            ],
            "after": [
                family["after"],
                text(
                    f"Intended source-specific outcome: {control['title']}. "
                    f"Validate using: {observation}.",
                    f"이 권고의 설정 의도를 구현한 뒤 다음을 검증합니다: {observation_ko}.",
                ),
            ],
        },
        "implementation_steps": [
            text(
                f"Identify the actual in-scope {metadata['resource_type'] or 'workload'} objects "
                f"and read their current {focus} configuration. "
                "Record the scope and observation time; "
                "do not infer inventory from this conceptual guide.",
                f"실제 범위에 포함된 {metadata['resource_type'] or '워크로드'} 대상을 식별하고 "
                f"현재 {focus_ko} 구성을 읽습니다. 범위와 관측 시각을 기록하며 "
                "이 개념 설명으로 리소스 목록을 추정하지 않습니다.",
            ),
            family["configure"],
            text(
                f"Review the pinned APRL action '{control['title']}' "
                "against the original description and cited documentation. "
                "Prepare a supported, scoped change proposal and rollback; "
                "this guide itself does not execute or approve changes.",
                "고정된 APRL 권고의 작업을 원문 설명 및 인용 문서와 대조합니다. "
                "지원되는 변경의 범위와 롤백 계획을 준비합니다. "
                "이 설명 자체는 변경을 실행하거나 승인하지 않습니다.",
            ),
            text(
                f"Prepare independent observations for: {observation}. "
                "Resolve unsupported or ambiguous conditions before proposing a change.",
                f"다음 항목의 독립적인 확인 자료를 준비합니다: {observation_ko}. "
                "변경을 제안하기 전에 미지원 조건과 모호한 부분을 해결합니다.",
            ),
        ],
        "verification_steps": [
            text(
                "Inspect and retain source-attributed configuration or workload evidence for: "
                f"{observation}.",
                f"출처가 명시된 구성 또는 워크로드 정보를 확인하고 보존합니다: {observation_ko}.",
            ),
            family["verify"],
            text(
                f"Compare the observed {focus} behavior with this recommendation's "
                "intended mechanism and the original source. Record timestamps, scope, "
                "missing coverage and conflicting observations.",
                f"관측한 {focus_ko} 동작을 이 권고의 의도한 원리 및 원문과 비교합니다. "
                "시각, 범위, 누락된 점검 범위, 상충하는 확인 결과를 기록합니다.",
            ),
            text(
                "Keep the existing automated, manual, blocked or unsupported assessment "
                "disposition separate. Missing evidence stays unknown; a diagram, a setting "
                "write or API acceptance is not operational success.",
                "기존의 자동, 수동, blocked 또는 미지원 평가 상태를 별도로 유지합니다. "
                "정보가 없으면 알 수 없음으로 남깁니다. "
                "그림, 설정 쓰기나 API 수락은 운영 성공이 아닙니다.",
            ),
        ],
        "cautions": [
            family["caution"],
            text(
                "The pinned APRL description and benefits are English-source metadata "
                "with explicit English fallback, not an independently verified Korean translation. "
                "Current product support must be checked before use.",
                "고정된 APRL 설명과 기대 효과는 영어 대체 표시를 사용하는 원본 메타데이터이며 "
                "검증된 한국어 번역이 아닙니다. 사용 전에 현재 제품 지원을 확인해야 합니다.",
            ),
        ],
        "diagram": build_diagram(
            focus,
            observation,
            family["shape"],
            description,
            focus_ko=focus_ko,
            observation_ko=observation_ko,
        ),
        "sources": _sources(control, revision),
    }
    if note:
        entry["applicability"].append(note)
        entry["cautions"].append(note)
    if metadata["resource_type"].casefold() == "microsoft.subscription/subscriptions":
        entry["applicability"].append(
            text(
                "The source classifies this specialized workload under a subscription. "
                f"The actual objects to inspect are the {focus} targets and their dependencies, "
                "not a subscription setting assumed to implement the recommendation.",
                "원본은 이 전문 워크로드를 구독 아래 분류합니다. "
                "실제 점검 대상은 권고에 명시된 리소스와 그 의존성입니다. "
                "구독 설정 하나가 권고를 구현한다고 가정하지 않습니다.",
            )
        )
        entry["implementation_steps"][0] = text(
            f"Identify actual {focus} target objects inside the workload's subscription scope "
            "and read their specific current configuration. Subscription classification is "
            "not a substitute for identifying host pools, shares, clusters or other real targets.",
            f"워크로드의 구독 범위 안에서 실제 {focus_ko} 대상을 식별하고 "
            "그 대상의 현재 구성을 읽습니다. 구독 분류는 호스트 풀, 공유, 클러스터 등 "
            "실제 대상을 식별하는 작업을 대신하지 않습니다.",
        )
    if metadata["state"] == "Disabled":
        entry["cautions"].append(
            text(
                "This recommendation is Disabled in the pinned APRL lifecycle. "
                "It is retained for historical coverage, not presented as an active instruction, "
                "evaluator or automatically applicable remediation.",
                "이 권고는 고정된 APRL 수명 주기에서 Disabled입니다. "
                "이력 범위를 위해 보존하며 활성 지침, 평가기 또는 자동 적용 조치로 "
                "제시하지 않습니다.",
            )
        )
    if control["id"].startswith("e7dbd21f"):
        entry["configuration"]["after"][1] = text(
            "The reviewed fallback-route state preserves intended unmatched-message delivery. "
            "The source title's polarity remains a manual interpretation item, not an instruction "
            "to disable fallback.",
            "검토한 대체 경로 상태가 의도한 미일치 메시지 전달을 유지하도록 합니다. "
            "원본 제목의 활성화 의미는 수동 해석 항목이며 대체 경로를 끄라는 지시가 아닙니다.",
        )
        entry["implementation_steps"][2] = text(
            "Reconcile source polarity before any change: the title says Disabled Fallback Route, "
            "but the description warns that disabling fallback can leave unmatched messages "
            "undelivered. "
            "Review fallback enablement and message delivery, not an unchecked disable action.",
            "변경 전에 원본 의미를 대조합니다. 제목은 Disabled Fallback Route이지만 "
            "설명은 대체 경로를 끄면 일치하지 않는 메시지가 전달되지 않을 수 있다고 경고합니다. "
            "무조건 끄지 말고 활성화 상태와 메시지 전달을 검토합니다.",
        )
    if control["id"].startswith("98bd7098"):
        entry["configuration"]["after"][1] = text(
            "Resource-group metadata continuity and workload resource placement have separate "
            "reviewed requirements. Regional alignment is not imposed as a universal resource "
            "migration action.",
            "리소스 그룹 메타데이터 연속성과 워크로드 배치의 요구를 별도로 검토합니다. "
            "지역 일치를 모든 리소스의 공통 이전 작업으로 강제하지 않습니다.",
        )
        entry["implementation_steps"][2] = text(
            "Review the source's resource-group metadata availability concern "
            "separately from resource placement. Do not move every contained resource "
            "solely to match a group's metadata region; retain workload-specific "
            "zone and regional recovery design and seek manual interpretation of the source.",
            "원본의 리소스 그룹 메타데이터 가용성 우려를 리소스 배치와 구분해 검토합니다. "
            "그룹 메타데이터 지역과 맞추려는 이유만으로 모든 포함 리소스를 이동하지 않습니다. "
            "워크로드별 영역 및 지역 복구 설계를 유지하고 원본의 수동 해석을 요청합니다.",
        )
    apply_specifics(entry)
    apply_pilot(entry)
    apply_resolution(entry)
    apply_reader_text(entry, reader_text)
    apply_reference_image(entry)
    normalized = _normalize(entry)
    normalized["content_digest"] = canonical_digest(normalized)
    return normalized


def build(root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any]]:
    """Reject pin or binding drift instead of silently manufacturing new guides."""
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    source_path = root / manifest["source"]
    digest = file_digest(source_path)
    if digest != manifest["framework_digest"]:
        raise ValueError(
            "Pinned WARA framework bytes changed; review and update authoring pins explicitly"
        )
    framework = json.loads(source_path.read_text(encoding="utf-8"))
    revision = manifest["framework_revision"]
    if (
        next(source["resolved_ref"] for source in framework["sources"] if source["id"] == "aprl")
        != revision
    ):
        raise ValueError("APRL revision does not match the reviewed guidance revision")
    controls = [control for area in framework["areas"] for control in area["controls"]]
    ids = {control["id"] for control in controls}
    if len(ids) != len(controls):
        raise ValueError("Duplicate recommendation identity in pinned source")
    inventory = Counter(control["wara"]["state"].casefold() for control in controls)
    if {"total": len(controls), **dict(inventory)} != manifest["expected_inventory"]:
        raise ValueError("WARA lifecycle inventory changed; explicit review required")
    bindings = load_bindings(root / manifest["binding_source"])
    if len({guid[:8] for guid in ids}) != len(ids) or set(bindings) != {guid[:8] for guid in ids}:
        raise ValueError("Explicit guidance bindings must cover every source GUID exactly once")
    load_korean_bindings(root / manifest["localized_binding_source"], bindings)
    reader_text = load_reader_text(
        root / manifest.get("localization_source", LOCALIZATION_SOURCE),
        framework_revision=revision,
        framework_digest=digest,
    )
    unknown_localizations = set(reader_text) - ids
    if unknown_localizations:
        raise ValueError(
            "Korean reader text contains recommendations outside the pinned source: "
            + ", ".join(sorted(unknown_localizations)[:8])
        )
    if any(
        control["wara"]["source_digest"] != area["source_digest"]
        for area in framework["areas"]
        for control in area["controls"]
    ):
        raise ValueError("Control source digests do not match their pinned source areas")
    entries = [
        _entry(control, bindings[control["id"][:8]], revision, reader_text)
        for control in sorted(controls, key=lambda value: value["id"])
    ]
    assert_korean_reader_text(entries, ids)
    catalog = {
        "schema_version": "1.0.0",
        "framework_revision": revision,
        "framework_digest": digest,
        "entries": entries,
    }
    catalog["catalog_digest"] = canonical_digest(catalog)
    inputs = [
        MANIFEST,
        Path(manifest["binding_source"]),
        Path(manifest["localized_binding_source"]),
        Path(manifest["notice_source"]),
        Path(manifest.get("localization_source", LOCALIZATION_SOURCE)),
    ]
    inputs += [Path(path) for path in manifest["critique_inputs"]]
    crosswalk, semantics = [
        json.loads((root / path).read_text(encoding="utf-8"))
        for path in manifest["critique_inputs"]
    ]
    if any(item["source_revision"] != revision for item in (crosswalk, semantics)):
        raise ValueError("Content critique evidence does not match the pinned APRL revision")
    inputs += sorted(
        path.relative_to(root) for path in (root / "scripts/catalog").glob("wara_guidance_*.py")
    )
    inputs.append(Path("scripts/catalog/build_wara_guidance.py"))
    inputs += [path.relative_to(root) for path in image_authoring_inputs(root)]
    omitted = [
        {
            "recommendation_id": control["id"],
            "original_url": control["wara"]["learn_more_url"],
            "reason": "Original external reference is preserved in pinned APRL, "
            "not rendered as an allowlisted Learn source",
        }
        for control in sorted(controls, key=lambda value: value["id"])
        if len(_sources(control, revision)) == 1
    ]
    critique = critique_report(controls, crosswalk, semantics)
    original_by_id = {control["id"]: control for control in controls}
    critique["structural_review"] = {
        "explicit_guid_bindings": len(bindings),
        "retained_source_description_and_benefit_entries": sum(
            entry["recommendation_id"] not in PILOT_IDS
            and entry["recommendation_id"][:8] not in RESOLUTIONS
            and entry["summary"]["en"]
            == _normalize(original_by_id[entry["recommendation_id"]]["description"])
            and entry["benefits"]["en"]
            == _normalize(original_by_id[entry["recommendation_id"]]["wara"]["potential_benefits"])
            for entry in entries
        ),
        "individually_rewritten_pilots": len(PILOT_IDS),
        "expanded_conditional_document_reviewed_entries": len(RESOLUTIONS),
        "distinct_mechanism_graphs": len({entry["diagram"]["kind"] for entry in entries}),
        "generic_configuration_success_edges": sum(
            edge["label"]["en"]
            in {"source-specific configuration", "intended behavior, not observed success"}
            for entry in entries
            for edge in entry["diagram"]["edges"]
        ),
    }
    report = {
        "schema_version": "1.0.0",
        "framework_revision": revision,
        "framework_digest": digest,
        "catalog_digest": catalog["catalog_digest"],
        "inventory": {"total": len(entries), **dict(sorted(inventory.items()))},
        "mechanism_counts": dict(
            sorted(Counter(binding["family"] for binding in bindings.values()).items())
        ),
        "diagram_counts": dict(
            sorted(Counter(entry["diagram"]["kind"] for entry in entries).items())
        ),
        "authored_binding_count": len(bindings),
        "individually_authored_pilots": sorted(PILOT_IDS),
        "review_scope": manifest["review_scope"],
        "review_accounting": {
            "explicit_guid_bindings": 456,
            "individually_authored_current_document_reviewed_pilots": 3,
            "shared_context_source_grounded_entries": 437,
            "expanded_conditional_document_reviewed_entries": len(RESOLUTIONS),
            "live_azure_or_model_validations": 0,
        },
        "quality_limits": manifest["quality_limits"],
        "image_review": image_review_summary(),
        "content_critique": critique,
        "semantic_review_gaps": manifest["semantic_review_gaps"],
        "non_allowlisted_original_references": omitted,
        "normalized_learn_query_references": [
            {
                "recommendation_id": control["id"],
                "original_url": control["wara"]["learn_more_url"],
                "rendered_url": urlsplit(control["wara"]["learn_more_url"])
                ._replace(query="")
                .geturl(),
                "reason": "Presentation, navigation, version-selection or tracking query "
                "removed for "
                "the public-source allowlist; exact original remains in pinned APRL",
            }
            for control in sorted(controls, key=lambda value: value["id"])
            if urlsplit(control["wara"]["learn_more_url"]).hostname == "learn.microsoft.com"
            and urlsplit(control["wara"]["learn_more_url"]).query
        ],
        "localization": {
            "authored_mechanisms": "English and Korean",
            "pinned_source_metadata": (
                "Original English preserved with source-pinned Korean reader text"
            ),
            "per_guid_observation_bindings": "English and Korean",
            "complete_korean_recommendations": len(entries),
            "missing_korean_reader_fields": 0,
            "source_citation_labels": (
                "Original reference labels retained; excluded from reader translation coverage"
            ),
        },
        "diagram_provenance": manifest["diagram_provenance"],
        "authoring_inputs": {str(path): file_digest(root / path) for path in sorted(inputs)},
    }
    return catalog, report


def encoded(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def artifact_outputs(
    catalog: dict[str, Any], report: dict[str, Any], root: Path = ROOT
) -> dict[Path, bytes]:
    """Keep package files small while retaining the assembled catalog identity."""
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    index_path = root / manifest["output"]
    outputs = {}
    shards = []
    for offset in range(0, len(catalog["entries"]), SHARD_SIZE):
        entries = catalog["entries"][offset : offset + SHARD_SIZE]
        filename = f"wara-guidance-{offset // SHARD_SIZE:02d}.json"
        body = encoded({"entries": entries})
        if len(body) > MAXIMUM_SHARD_BYTES:
            raise ValueError(f"{filename} exceeds the 512 KiB shard limit")
        outputs[index_path.parent / filename] = body
        shards.append(
            {
                "path": filename,
                "digest": "sha256:" + hashlib.sha256(body).hexdigest(),
                "count": len(entries),
            }
        )
    index = {key: value for key, value in catalog.items() if key != "entries"}
    index["shards"] = shards
    outputs[index_path] = encoded(index)
    outputs[root / manifest["coverage_output"]] = encoded(report)
    outputs[root / manifest["notice_output"]] = (root / manifest["notice_source"]).read_bytes()
    return outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Fail if generated corpus or coverage report differs"
    )
    args = parser.parse_args(argv)
    try:
        catalog, report = build()
        body = encoded(catalog)
        if len(body) > MAXIMUM_BYTES:
            raise ValueError("Generated WARA guidance exceeds the 8 MiB packaged catalog limit")
        outputs = artifact_outputs(catalog, report)
        index_parent = next(path.parent for path in outputs if path.name == "wara-guidance.json")
        orphans = sorted(set(index_parent.glob("wara-guidance-*.json")) - set(outputs))
        stale = [
            str(path.relative_to(ROOT))
            for path, content in outputs.items()
            if not path.exists() or path.read_bytes() != content
        ]
        stale.extend(str(path.relative_to(ROOT)) for path in orphans)
        if args.check and stale:
            print("Stale generated WARA guidance: " + ", ".join(stale), file=sys.stderr)
            return 1
        if not args.check:
            for path, content in outputs.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            for path in orphans:
                path.unlink()
        shard_count = (len(catalog["entries"]) + SHARD_SIZE - 1) // SHARD_SIZE
        print(
            f"WARA guidance {'checked' if args.check else 'built'}: "
            f"456 entries (393 active, 63 disabled), {len(PROFILES)} mechanisms, "
            f"{len(body)} assembled bytes, {shard_count} shards"
        )
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"WARA guidance build failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
