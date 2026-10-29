---
title: WARA 근거 입력 및 보고서 내보내기
translation_of: wara-assessment-evidence.md
translation_source_sha: 91b4eb2e3fb397eeecc57a266d423a0ce938ced3
translation_revised: 2026-10-30
---
# WARA 근거 입력 및 보고서 내보내기

정기 WARA 평가에서 정확한 Azure 관찰 결과와 서명된 수동 검토 증적을 함께 사용하고 전체
결과를 내보낼 수 있습니다. 원본 사용 가능 여부, 수집 성공, 권고 충족은 서로 다른 상태입니다.

> 이 기능은 읽기 전용 shadow 평가입니다. 작업을 실행하려면 승인된 배포, 정확한 워크로드
> 범위, 기존 실행 ID가 필요합니다. 이 옵션은 Azure 실행 권한을 부여하지 않습니다.

## 이 가이드의 범위

작업은 인증된 수동 증적 묶음을 읽고, 범위가 제한된 원본 WARA Collector 맥락을 가져오며,
JSON, CSV, Excel, PowerPoint 파일을 작성할 수 있습니다. 누락되거나 유효하지 않은 근거는
알 수 없음으로 유지하며 보고서를 규정 준수 점수로 해석하지 않습니다.

## 신뢰할 수 있는 수동 증적 생성자 구성

생성자의 공개 키 신뢰 파일은 증적 파일과 별도로 설치합니다. 배포 소유자가 신뢰 파일을
관리하며 증적 묶음 안에서 제공한 공개 키는 수락하지 않습니다. 키 설치, 교체, 철회는
증적 제출이 아니라 배포 관리 작업입니다.

```json
{
  "schema_version": "1.0.0",
  "bindings": [{
    "key_id": "review-key-example",
    "producer": "workload-evidence-owner",
    "public_key_base64": "<base64-encoded-Ed25519-public-key>",
    "workload_ids": ["workload-example"],
    "valid_from": "2026-10-29T00:00:00Z",
    "valid_until": "2026-10-30T00:00:00Z",
    "revoked": false
  }]
}
```

예시 유효 기간은 승인된 현재 기간으로 바꿉니다. 생성자는 개인 키를 FDAI 구성, 소스,
채팅, 로그 밖에서 보관합니다.

## 서명된 증적 묶음 생성

묶음은 `key_id`, `payload`, `signature_base64`를 포함합니다. 등록된 Ed25519 키로
`fdai.delivery.wara_manual_evidence.manual_evidence_signing_bytes(key_id, payload)`가
반환하는 바이트에 서명합니다. 서명은 키 ID와 정규화된 페이로드를 모두 포함합니다.

| 페이로드 필드 | 필요한 의미 |
|---------------|-------------|
| `schema_version` | `1.0.0` |
| `producer` | 각 권고가 요구하는 신뢰된 생성자 슬롯 |
| `workload_id`, `scope_digest` | 현재 평가의 정확한 범위 |
| `framework_revision`, `crosswalk_digest` | 현재 고정된 원본과 구현 |
| `ontology_release` | 현재의 정확한 의미 리비전 |
| `inventory_generation` | 현재 관찰된 인벤토리 세대 |
| `receipts` | 명시적 대체 검토를 포함하여 수동 `WaraEvidenceReceipt` 객체 최대 393개 |

각 증적은 `recommendation_id`, `evidence_ref`, `evidence_kind`, `producer`,
`scope_digest`, `source_revision`, `inventory_generation`, `observed_at`, `recorded_at`,
`evidence_digest`, `freshness_ceiling_seconds`, `complete`, `truncated`, `conflicting`,
`synthetic`, `provider_error`, `outcome`을 제공합니다. 선택 필드인
`applicability_approval_ref`는 런타임이 요구하는 검토된 적용 제외 처리와 승인을 대신하지 않습니다.

권고가 지정한 정확한 자료 종류, 생성자, 유효 기간 상한을 사용합니다. 결과 값은
`satisfied`, `failed`, `not_applicable`, `unknown`입니다. 서명은 생성자의 진술을 인증할
뿐 복구 훈련이 실제로 수행됐음을 증명하거나 오래된 자료와 합성 자료를 유효하게 만들지 않습니다.
지원하지 않는 필드, 중복된 권고 증적, 신뢰되지 않거나 만료된 키, 변조, 고정 값 대체는
명시적인 오류로 처리합니다. 각 입력 파일의 상한은 1 MiB입니다.

두 경로를 함께 구성합니다.

```text
FDAI_WARA_MANUAL_EVIDENCE_FILE=/var/run/fdai/wara/evidence.json
FDAI_WARA_MANUAL_TRUST_FILE=/var/run/fdai/wara/trust.json
```

작업은 평가 전에 파일을 읽습니다. 결과는 서명된 페이로드와 정확한 신뢰 바인딩을 포함하여
내용으로 식별되는 진술 참조 및 독립적인 근거 다이제스트를 유지합니다. 재현을 위해 서명 묶음과 적용된 신뢰 리비전을 배포의 증적 보관소에
보존합니다. FDAI에는 개인 서명 키가 필요하지 않습니다.

## 원본 Collector 맥락 가져오기

`FDAI_WARA_COLLECTOR_CONTEXT_FILE`을 기존 원본 WARA Collector JSON 파일로 지정하고
보고서 디렉터리를 구성합니다. 파일이 선언한 구독 집합은 평가의 ARM 대상 구독 집합과 정확히
일치해야 합니다. 범위가 더 넓거나 누락되거나 형식이 잘못되면 수락하지 않습니다.

가져오기 어댑터는 `advisory`, `outages`, `retirements`, `supportTickets`, `serviceHealth`를
연결합니다. 보고서에는 수와 원본 다이제스트만 포함하며 비공개 티켓 내용은 포함하지 않습니다.
누락된 컬렉션은 관찰된 0이 아니라 사용 불가로 표시합니다. 파일 상한은 16 MiB이며 컬렉션별
상한은 레코드 10,000개입니다.

서명되지 않은 Collector 파일은 **미검증 구독 맥락**이며 최신 워크로드 근거가 아닙니다.
권고의 적용 여부, 평가, 충족, 권한을 바꾸지 않습니다. 이 연결 경로는 원본 Collector를
대체하거나 새로운 Azure 실환경 수집을 수행하지 않습니다.

## 같은 평가를 네 가지 형식으로 내보내기

기존 `fdai-wara-assessment` 진입점을 실행하기 전에 `FDAI_WARA_REPORT_DIRECTORY`을 배포가
소유한 출력 디렉터리로 지정합니다. 저장 경로는 내용으로 식별되는 같은 기본 이름에
`.json`, `.csv`, `.xlsx`, `.pptx` 확장자를 붙입니다. 출력 파일 권한은 `0600`입니다.

- 알 수 없음과 차단 상태를 포함하여 모든 활성 권고를 보존합니다.
- 모든 형식에서 같은 원본, 인벤토리, 범위, 결과 다이제스트, 평가 시각을 사용합니다.
- Excel은 텍스트 전용 셀을 사용하며 메타데이터와 위젯 오류를 별도 시트에 보존합니다.
- PowerPoint는 행을 조용히 누락하지 않고 전체 내용을 페이지로 나눕니다.
- Office 입력은 인코딩된 보고서 데이터 8 MiB, PowerPoint는 슬라이드 1,000개로 제한합니다.
- 누락된 추가 원본은 명시적으로 사용 불가 상태를 유지합니다.
- 형식이 잘못되거나 변조된 평가를 유효한 shadow 보고서로 내보낼 수 없습니다.

파일 작성은 게시, 공개 승인, 실환경 배포 인증이 아닙니다. 독립 Operator 보고 서비스는
HTTP 형식을 별도로 등록합니다.

## 다음 단계

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 평가 및 근거 경계 | [WARA 평가](../roadmap/rules-and-detection/wara-assessment-ko.md) |
| 공통 형식 인코더 | [보고 하위 시스템](../roadmap/interfaces/reporting-subsystem-ko.md) |
