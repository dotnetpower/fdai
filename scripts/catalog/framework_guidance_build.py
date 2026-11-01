#!/usr/bin/env python3
"""Build the complete public guidance corpus offline from pinned source catalogs.

Run ``uv run python scripts/catalog/framework_guidance_build.py --check`` to
verify exact reproducibility. Edit the adjacent bilingual authoring files,
never packaged JSON. Examples and original diagrams are FDAI-authored teaching
material, not quotations, installation observations or new assessment rules.

The pipe-delimited authoring rows have 16 columns: control identity, Korean title,
then English/Korean pairs for mechanism, benefit, before, after, verification,
exclusion and caution. Use readable NFC UTF-8 and retain official product names.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml
from fdai_service_contracts.catalog_canonical import canonical_digest
from fdai_service_contracts.framework_guidance import (
    EXPECTED_COUNTS,
    MAXIMUM_SHARD_BYTES,
    assert_framework_guidance_catalog,
    load_framework_guidance,
)

WAF_ROWS = Path(__file__).with_name("framework_guidance_waf.tsv").read_text(encoding="utf-8")
MCSB_ROWS = Path(__file__).with_name("framework_guidance_mcsb.tsv").read_text(encoding="utf-8")
CAF_ROWS = Path(__file__).with_name("framework_guidance_caf.tsv").read_text(encoding="utf-8")

DATA = Path("packages/service-contracts/src/fdai_service_contracts/data")
AUTHORING = (
    "framework_guidance_build.py",
    "framework_guidance_waf.tsv",
    "framework_guidance_mcsb.tsv",
    "framework_guidance_caf.tsv",
)


def _text(english: str, korean: str) -> dict[str, str]:
    return {"en": english, "ko": korean}


def _seal(material: dict[str, Any], key: str) -> dict[str, Any]:
    material[key] = "sha256:" + canonical_digest(material)
    return material


def _bytes(material: object) -> bytes:
    return (json.dumps(material, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _parse(rows: str) -> dict[str, dict[str, Any]]:
    entries = {}
    for row in rows.strip().splitlines():
        if not row.strip():
            continue
        columns = row.split("|")
        if len(columns) != 16:
            raise ValueError(f"Authored guidance row must have 16 columns: {columns[0]}")
        identity, korean_title, *prose = columns
        if identity in entries:
            raise ValueError(f"Duplicate authored control: {identity}")
        text = [_text(prose[index], prose[index + 1]) for index in range(0, 14, 2)]
        entries[identity] = dict(
            zip(
                ("mechanism", "benefit", "before", "after", "verify", "exclude", "caution"),
                text,
                strict=True,
            ),
            title_ko=korean_title,
        )
    return entries


def _sources(
    root: Path,
    source_files: set[Path],
) -> tuple[dict[tuple[str, str], str], list[dict[str, str]]]:
    urls: dict[tuple[str, str], str] = {}
    official: list[dict[str, str]] = []
    waf_path = Path("rule-catalog/frameworks/azure-waf.yaml")
    caf_path = Path("rule-catalog/frameworks/azure-caf.yaml")
    mcsb_path = Path("rule-catalog/compliance/mcsb/v1/controls.yaml")
    source_files.update((waf_path, caf_path, mcsb_path))
    for area in yaml.safe_load((root / waf_path).read_text())["areas"]:
        official.append(
            {
                "framework_id": "azure-waf",
                "source_url": area["source_url"],
                "resolved_ref": area["resolved_ref"],
                "content_hash": "git:" + area["resolved_ref"],
                "license": "CC-BY-4.0",
            }
        )
        for control in area["controls"]:
            urls["azure-waf", control["id"]] = area["source_url"]
            ref = control["best_practice_ref"].split("@")[0]
            practice_path = Path("rule-catalog/best-practices") / (ref + ".yaml")
            source_files.add(practice_path)
            practice = yaml.safe_load((root / practice_path).read_text())
            if practice["control_id"] != control["id"]:
                raise ValueError("WAF best-practice identity does not match the framework")
            if practice["provenance"]["resolved_ref"] != area["resolved_ref"]:
                raise ValueError("WAF best-practice source revision does not match the framework")
    for control in yaml.safe_load((root / caf_path).read_text())["controls"]:
        urls["azure-caf", control["id"]] = control["source_url"]
        official.append(
            {
                "framework_id": "azure-caf",
                "source_url": control["source_url"],
                "resolved_ref": control["resolved_ref"],
                "content_hash": "git:" + control["resolved_ref"],
                "license": "CC-BY-4.0",
            }
        )
    mcsb = yaml.safe_load((root / mcsb_path).read_text())
    if mcsb["benchmark_version"] != "v1" or mcsb["status"] != "stable":
        raise ValueError("Framework guidance requires the stable MCSB v1 catalog")
    official.append(
        {
            "framework_id": "azure-mcsb",
            "source_url": mcsb["source"]["source_url"],
            "resolved_ref": mcsb["source"]["resolved_ref"],
            "content_hash": mcsb["source"]["content_hash"],
            "license": mcsb["source"]["license"],
        }
    )
    for control in mcsb["controls"]:
        urls["azure-mcsb", control["id"]] = mcsb["source"]["source_url"]
    return urls, official


def _requirement(requirement: dict[str, Any]) -> dict[str, str]:
    kinds = {"artifact": "산출물", "approval": "승인", "rule": "규칙", "procedure": "절차"}
    scopes = {
        "exact-workload": "정확한 워크로드 범위",
        "exact-estate": "정확한 전체 환경 범위",
        "exact-resource": "정확한 리소스 범위",
    }
    kind = requirement["kind"]
    freshness = requirement["freshness_ceiling_seconds"]
    approvals = ", ".join(requirement["approval_roles"])
    completeness_en = (
        "complete" if requirement["completeness_required"] else "declared completeness"
    )
    completeness_ko = "완전한 범위" if requirement["completeness_required"] else "선언한 완전성"
    return _text(
        f"Retain {requirement['requirement_id']} from {requirement['authoritative_producer']} "
        f"for {requirement['scope_contract']}; freshness limit {freshness} seconds, "
        f"owner {requirement['owner_slot']}, role {requirement['evidence_role']}. "
        f"Verify {completeness_en} coverage and approval roles {approvals}; "
        f"failure disposition {requirement['failure_behavior']}, "
        f"phase {requirement['process_phase']}, generation {requirement['generation_contract']}.",
        f"{scopes.get(requirement['scope_contract'], '선언된 범위')}의 "
        f"{kinds.get(kind, '평가 항목')} {requirement['requirement_id']}을 "
        f"{requirement['authoritative_producer']}에서 확보합니다. 최신성 한도는 {freshness}초이며 "
        f"담당 역할은 {requirement['owner_slot']}, "
        f"근거 역할은 {requirement['evidence_role']}입니다. "
        f"{completeness_ko}와 승인 역할 {approvals}을 확인합니다. "
        f"실패 시 처리 상태는 {requirement['failure_behavior']}, "
        f"절차 단계는 {requirement['process_phase']}, "
        f"세대 일치 규약은 {requirement['generation_contract']}입니다.",
    )


_WAF_DOMAINS: dict[str, tuple[str, dict[str, str], dict[str, str], dict[str, str]]] = {
    "RE": (
        "waf-reliability-topology",
        _text("Resilience and isolation design", "복원력 및 장애 격리 설계"),
        _text("Failure domain and recovery boundary", "장애 범위 및 복구 경계"),
        _text("Health and recovery verification", "상태 및 복구 검증"),
    ),
    "SE": (
        "waf-security-boundary",
        _text("Defense-in-depth and least privilege", "심층 방어 및 최소 권한 설계"),
        _text("Identity, network and encryption boundary", "신원·네트워크·암호화 경계"),
        _text("Security posture and audit check", "보안 태세 및 감사 검증"),
    ),
    "CO": (
        "waf-cost-guardrail",
        _text("Cost model and budget guardrail", "비용 모델 및 예산 가드레일 설계"),
        _text("Billing unit and capacity boundary", "과금 단위 및 용량 배분 경계"),
        _text("Usage and rate reconciliation", "사용량 및 실효 요금 대조 검증"),
    ),
    "OE": (
        "waf-operational-loop",
        _text("Safe deployment and runbook design", "안전 배포 및 런북 자동화 설계"),
        _text("Observability and release gate boundary", "관측성 및 릴리스 게이트 경계"),
        _text("Telemetry and change verification", "원격 분석 및 변경 추적 검증"),
    ),
    "PE": (
        "waf-performance-scaling",
        _text("Performance target and scaling design", "성능 목표 및 탄력적 확장 설계"),
        _text("Load distribution and capacity boundary", "부하 분산 및 용량 병목 경계"),
        _text("Load test and saturation check", "부하 시험 및 포화도 검증"),
    ),
}

_MCSB_DOMAINS: dict[str, tuple[str, dict[str, str], dict[str, str], dict[str, str]]] = {
    "NS": (
        "mcsb-network-security",
        _text("Network segmentation and edge control", "네트워크 분할 및 경계 통제 설계"),
        _text("Zero-trust perimeter and private link", "제로 트러스트 경계 및 사설 연결"),
        _text("Traffic flow and rule verification", "트래픽 흐름 및 방화벽 규칙 검증"),
    ),
    "IM": (
        "mcsb-identity-management",
        _text("Centralized identity and strong auth", "중앙 신원 및 강력한 인증 설계"),
        _text("Federation, SSO and conditional access", "연합 인증·SSO·조건부 접근 경계"),
        _text("Authentication and token audit", "인증 정책 및 토큰 감사 검증"),
    ),
    "PA": (
        "mcsb-privileged-access",
        _text("Least privilege and JIT elevation", "최소 권한 및 JIT 권한 승격 설계"),
        _text("PIM lifecycle and break-glass boundary", "권한 수명주기 및 비상 계정 경계"),
        _text("Role assignment and access review", "역할 배정 및 정기 접근 검토"),
    ),
    "DP": (
        "mcsb-data-protection",
        _text("Classification and encryption policy", "데이터 분류 및 암호화 정책 설계"),
        _text("In-transit TLS, at-rest CMK and vault", "전송·저장 암호화 및 키 보관소 경계"),
        _text("Key rotation and cipher verification", "키 회전 및 암호화 상태 검증"),
    ),
    "AM": (
        "mcsb-asset-management",
        _text("Approved service and inventory policy", "승인 서비스 및 자산 목록 설계"),
        _text("Resource graph and lifecycle tracking", "리소스 그래프 및 수명주기 경계"),
        _text("Inventory reconciliation check", "자산 인벤토리 및 승인 상태 검증"),
    ),
    "LT": (
        "mcsb-logging-threat-detection",
        _text("Diagnostic collection and alert rules", "진단 수집 및 위협 탐지 규칙 설계"),
        _text("Central SIEM and Log Analytics pipeline", "중앙 로그 분석 및 보존 파이프라인"),
        _text("Log completeness and alert verification", "로그 완전성 및 경보 전달 검증"),
    ),
    "IR": (
        "mcsb-incident-response",
        _text("Incident response plan and routing", "인시던트 대응 계획 및 라우팅 설계"),
        _text("Triage, containment and recovery loop", "분류·격리·복구 실행 경계"),
        _text("Response drill and postmortem check", "대응 훈련 및 사후 검토 검증"),
    ),
    "PV": (
        "mcsb-posture-vulnerability",
        _text("Secure baseline and patch automation", "보안 기준선 및 패치 자동화 설계"),
        _text("Configuration drift and CVE scanner", "구성 드리프트 및 취약점 스캔 경계"),
        _text("Baseline compliance and fix check", "기준선 준수 및 조치 결과 검증"),
    ),
    "ES": (
        "mcsb-endpoint-security",
        _text("EDR and anti-malware enforcement", "EDR 및 맬웨어 방지 강제 설계"),
        _text("Host agent and signature update loop", "호스트 에이전트 및 서명 갱신 경계"),
        _text("Endpoint health and telemetry check", "엔드포인트 상태 및 원격 분석 검증"),
    ),
    "BR": (
        "mcsb-backup-recovery",
        _text("Automated backup and immutability", "자동 백업 및 불변성 보호 설계"),
        _text("Isolated vault and RPO/RTO boundary", "격리 자격 증명 모음 및 복구 경계"),
        _text("Restore drill and vault verification", "복원 훈련 및 보존 상태 검증"),
    ),
    "DS": (
        "mcsb-devops-security",
        _text("Supply chain and pipeline security", "공급망 및 파이프라인 보안 설계"),
        _text("SAST/DAST gate and artifact signing", "정적·동적 분석 게이트 및 서명 경계"),
        _text("Pipeline audit and dependency check", "파이프라인 감사 및 의존성 검증"),
    ),
    "GS": (
        "mcsb-governance-strategy",
        _text("Security governance and duty separation", "보안 거버넌스 및 직무 분리 설계"),
        _text("Accountable owner and policy hierarchy", "책임 역할 및 전사 정책 계층 경계"),
        _text("Governance review and exception check", "거버넌스 검토 및 예외 추적 검증"),
    ),
}


def _domain_profile(
    framework_id: str, control_id: str
) -> tuple[str, dict[str, str], dict[str, str], dict[str, str]]:
    if framework_id == "azure-waf":
        prefix = control_id.split(":", 1)[0]
        return _WAF_DOMAINS[prefix]
    if framework_id == "azure-mcsb":
        prefix = control_id.split("-", 1)[0]
        return _MCSB_DOMAINS[prefix]
    if control_id.startswith("landing-zone."):
        return (
            "caf-landing-zone-architecture",
            _text("Landing-zone platform governance", "랜딩 존 플랫폼 거버넌스 설계"),
            _text("Shared subscription and policy boundary", "공통 구독·네트워크·정책 경계"),
            _text("Platform and workload readiness check", "플랫폼 및 워크로드 준비도 검증"),
        )
    return (
        "caf-estate-methodology",
        _text("Estate operating procedure and ownership", "클라우드 자산 운영 절차 및 책임 설계"),
        _text("Cross-subscription governance boundary", "구독 간 거버넌스 및 인수인계 경계"),
        _text("Procedure and execution evidence check", "절차 및 실행 근거 대조 검증"),
    )


def _diagram(
    framework_id: str,
    control_id: str,
    title: dict[str, str],
    authored: dict[str, Any],
) -> dict[str, Any]:
    identity = control_id.lower().replace(":", "-")
    kind, config_label, mech_label, ev_label = _domain_profile(framework_id, control_id)
    return {
        "id": f"{framework_id}.{identity}",
        "kind": kind,
        "title": title,
        "description": _text(
            "Illustrative directed relationship, not an observed installation "
            "or compliance result.",
            "관측한 설치 환경이나 준수 결과가 아닌, 방향이 있는 관계의 예시입니다.",
        ),
        "nodes": [
            {"id": "subject", "label": title, "detail": authored["before"], "role": "subject"},
            {
                "id": "configuration",
                "label": config_label,
                "detail": authored["after"],
                "role": "configuration",
            },
            {
                "id": "evidence",
                "label": ev_label,
                "detail": authored["verify"],
                "role": "evidence",
            },
            {
                "id": "mechanism",
                "label": mech_label,
                "detail": authored["mechanism"],
                "role": "dependency",
            },
            {
                "id": "outcome",
                "label": _text("Expected benefit", "기대 효과"),
                "detail": authored["benefit"],
                "role": "outcome",
            },
        ],
        "edges": [
            {
                "from": "subject",
                "to": "configuration",
                "label": _text("Apply scoped practice", "범위 내 관행 적용"),
                "style": "solid",
            },
            {
                "from": "subject",
                "to": "mechanism",
                "label": _text("Bind architectural boundary", "아키텍처 경계 결합"),
                "style": "solid",
            },
            {
                "from": "configuration",
                "to": "evidence",
                "label": _text("Verify independently", "독립적으로 검증"),
                "style": "solid",
            },
            {
                "from": "mechanism",
                "to": "evidence",
                "label": _text("Inspect boundary telemetry", "경계 상태 및 근거 확인"),
                "style": "dashed",
            },
            {
                "from": "evidence",
                "to": "outcome",
                "label": _text("Assess, do not assume", "가정하지 않고 평가"),
                "style": "dashed",
            },
        ],
    }


def _entry(
    framework: dict[str, Any],
    control: dict[str, Any],
    authored: dict[str, Any],
    url: str,
) -> dict[str, Any]:
    framework_id, control_id = framework["framework_id"], control["control_id"]
    estate = framework_id == "azure-caf"
    scope_en, scope_ko = (
        ("cloud estate", "전체 클라우드 환경") if estate else ("workload", "워크로드")
    )
    title = _text(control["title"], authored["title_ko"])
    refs = ", ".join(item["requirement_id"] for item in control["evidence"])
    phases = (
        ", ".join(
            sorted(
                {
                    item["process_phase"]
                    for item in control["evidence"]
                    if item["process_phase"] != "none"
                }
            )
        )
        or "none"
    )
    generation = ", ".join(sorted({item["generation_contract"] for item in control["evidence"]}))
    blocked = sorted(
        {item["blocked_dependency"] for item in control["evidence"] if item["blocked_dependency"]}
    )
    cautions = [
        authored["caution"],
        _text(
            "These before/after examples are instructional only. Missing, stale, incomplete or "
            "conflicting required evidence remains unknown; "
            "this guide grants no execution authority.",
            "변경 전후 예시는 설명용입니다. 필수 근거가 누락되거나 오래되었거나 불완전하거나 "
            "충돌하면 알 수 없음 상태를 유지합니다. 이 안내는 실행 권한을 부여하지 않습니다.",
        ),
    ]
    if blocked:
        cautions.append(
            _text(
                "Blocked dependencies remain explicit: " + ", ".join(blocked) + ".",
                "차단된 의존성을 명시적으로 유지합니다: " + ", ".join(blocked) + ".",
            )
        )
    return _seal(
        {
            "schema_version": "1.0.0",
            "framework_id": framework_id,
            "control_id": control_id,
            "source_revision": framework["source_revision_digest"],
            "source_digest": control["specification_digest"],
            "title": title,
            "summary": authored["mechanism"],
            "benefits": authored["benefit"],
            "rationale": _text(
                f"{authored['mechanism']['en']} In FDAI, {control_id} is assessed through {refs}. "
                f"Process phases: {phases}; generation contract: {generation}. "
                "The original example explains the control, not a new official requirement.",
                f"{authored['mechanism']['ko']} "
                f"FDAI는 {control_id}을 {refs} 항목으로 평가합니다. "
                f"절차 단계는 {phases}, 세대 일치 규약은 {generation}입니다. "
                "직접 작성한 예시는 통제의 설명이며 새로운 공식 요구사항이 아닙니다.",
            ),
            "applicability": [
                _text(
                    f"Apply {control_id} only to the reviewed {scope_en} scope with accountable "
                    f"owner role {control['owner_slot']}; "
                    f"review cadence {control['cadence_days']} days.",
                    f"{control_id}은 책임 역할 {control['owner_slot']}이 있는 검토된 {scope_ko} "
                    f"범위에만 적용합니다. 검토 주기는 {control['cadence_days']}일입니다.",
                ),
                authored["exclude"],
            ],
            "configuration": {
                "before": [
                    authored["before"],
                    _text(
                        f"Illustrative gap: {control_id} has no current, "
                        "source-bound evidence bundle.",
                        f"예시 공백: {control_id}에 최신이며 출처와 연결된 근거 묶음이 없습니다.",
                    ),
                ],
                "after": [
                    authored["after"],
                    _text(
                        f"Illustrative target: retain {refs} for the exact reviewed scope.",
                        f"예시 목표: 검토한 정확한 범위에 대해 {refs} 항목을 보존합니다.",
                    ),
                ],
            },
            "implementation_steps": [
                _text(
                    f"Confirm {control_id} scope, owner {control['owner_slot']} and the exclusion "
                    "above before proposing a change.",
                    f"변경을 제안하기 전에 {control_id}의 범위, 담당 역할 {control['owner_slot']}, "
                    "앞서 설명한 제외 조건을 확인합니다.",
                ),
                authored["after"],
                *[_requirement(item) for item in control["evidence"]],
            ],
            "verification_steps": [
                authored["verify"],
                _text(
                    f"Check every required item ({control['requirement_mode']} mode), "
                    "its producer, scope, freshness, completeness and required approval roles "
                    "against the pinned specification.",
                    f"고정된 명세에 따라 모든 필수 항목({control['requirement_mode']} 방식)의 "
                    "생성 원천, "
                    "범위, 최신 여부, 완전성, 필수 승인 역할을 확인합니다.",
                ),
                _text(
                    f"Reassess {control_id} against independent observations; preserve missing and "
                    "blocked items rather than treating this illustration as satisfaction.",
                    f"독립적인 관측으로 {control_id}을 다시 평가합니다. "
                    "그림을 충족 근거로 간주하지 말고 "
                    "누락 및 차단 항목을 그대로 유지합니다.",
                ),
            ],
            "cautions": cautions,
            "diagram": _diagram(framework_id, control_id, title, authored),
            "sources": [
                {
                    "kind": "learn",
                    "url": url,
                    "label": _text(
                        "Microsoft Learn - pinned source; original FDAI example, "
                        "source license CC BY 4.0",
                        "Microsoft Learn - 고정한 원천, FDAI가 작성한 예시, "
                        "원천 라이선스 CC BY 4.0",
                    ),
                }
            ],
        },
        "content_digest",
    )


def build(root: Path) -> dict[str, bytes]:
    """Return exact packaged bytes without writing or making network requests."""
    authored = {
        "azure-waf": _parse(WAF_ROWS),
        "azure-mcsb": _parse(MCSB_ROWS),
        "azure-caf": _parse(CAF_ROWS),
    }
    source_files: set[Path] = set()
    urls, official = _sources(root, source_files)
    entries, pins, assessments = [], [], {}
    for framework_id, count in EXPECTED_COUNTS.items():
        path = Path(f"rule-catalog/framework-assessments/generated/{framework_id}.json")
        source_files.add(path)
        body = (root / path).read_bytes()
        framework = json.loads(body)
        controls = framework["controls"]
        identities = {control["control_id"] for control in controls}
        if (
            len(controls) != count
            or len(identities) != count
            or identities != set(authored[framework_id])
        ):
            raise ValueError(f"Authored/source control accounting mismatch: {framework_id}")
        pins.append(
            {
                "framework_id": framework_id,
                "source_revision": framework["source_revision_digest"],
                "assessment_catalog_digest": framework["catalog_digest"],
                "framework_definition_digest": framework["framework_definition_digest"],
                "expected_control_count": count,
            }
        )
        for control in sorted(controls, key=lambda item: item["control_id"]):
            entries.append(
                _entry(
                    framework,
                    control,
                    authored[framework_id][control["control_id"]],
                    urls[framework_id, control["control_id"]],
                )
            )
        assessments[framework_id] = body
    material = _seal(
        {"schema_version": "1.0.0", "pins": pins, "entries": entries}, "catalog_digest"
    )
    catalog = load_framework_guidance(_bytes(material))
    for framework_id, body in assessments.items():
        assert_framework_guidance_catalog(catalog, framework_id, body)
    output, shards = {}, []
    for index in range(0, len(entries), 16):
        name = f"framework-guidance-{index // 16:02}.json"
        body = _bytes({"entries": entries[index : index + 16]})
        if len(body) > MAXIMUM_SHARD_BYTES:
            raise ValueError(f"Generated guidance shard exceeds its byte limit: {name}")
        output[name] = body
        shards.append(
            {
                "file": name,
                "digest": "sha256:" + hashlib.sha256(body).hexdigest(),
                "entry_count": len(entries[index : index + 16]),
            }
        )
    authoring = {
        name: "sha256:" + hashlib.sha256((root / "scripts/catalog" / name).read_bytes()).hexdigest()
        for name in AUTHORING
    }
    manifest = {
        "schema_version": "1.0.0",
        "pins": pins,
        "catalog_digest": material["catalog_digest"],
        "authoring_digest": "sha256:" + canonical_digest(authoring),
        "source_files": {
            str(path): "sha256:" + hashlib.sha256((root / path).read_bytes()).hexdigest()
            for path in sorted(source_files)
        },
        "official_sources": official,
        "shards": shards,
    }
    output["framework-guidance.json"] = _bytes(_seal(manifest, "manifest_digest"))
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Fail if installed generated bytes differ"
    )
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = build(root)
    for name, body in output.items():
        path = root / DATA / name
        if arguments.check:
            if not path.is_file() or path.read_bytes() != body:
                raise SystemExit(f"Framework guidance requires regeneration: {name}")
        else:
            path.write_bytes(body)
    print(
        "Framework guidance: 59 WAF, 86 MCSB v1, 15 CAF; "
        + ("reproducible" if arguments.check else "generated")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
