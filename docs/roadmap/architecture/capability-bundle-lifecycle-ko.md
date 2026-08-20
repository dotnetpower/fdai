---
title: 기능 번들 수명 주기
translation_of: capability-bundle-lifecycle.md
translation_source_sha: 1faf291d05412df4065733e968ffbf2ecba5dfca
translation_revised: 2026-08-21
---
# 기능 번들 수명 주기

이 문서는 포크가 탐색 가능한 기능을 등록하고 산출물을 검증한 뒤 별도 실행 경로를 만들지 않고
설치, 활성화, 비활성화 및 제거 단계를 거치는 방법을 정의합니다. [프로젝트
구조](project-structure-ko.md)의 의존성 주입 모델을 구체화하며 모든 변경 요청을 기존 trust,
risk, 실행, 복구 및 감사 경로에 유지합니다.

> **권한 경계:** 번들 및 확장 활성화는 타입이 지정된 메타데이터, 참조 및 검토된 프로바이더만
> 등록합니다. 승인 또는 실행 권한을 부여하지 않습니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 번들 검증 및 변경할 수 없는 런타임 등록 | implemented | `core/capability_catalog/`, `composition/install_capability_bundle`, 집중 기능 카탈로그 테스트 | 알 수 없는 대상, 프로바이더 불일치, 중복 id 및 끊어진 참조는 현재 런타임을 바꾸지 않고 활성화를 차단합니다. |
| 영속 trusted artifact 및 스킬 공개 | implemented | `core/supply_chain/`, `delivery/trust/`, PostgreSQL trusted-artifact 어댑터 | 산출물은 exact 내용, 서명, 발행자, 상태 및 개정 번호를 유지하며 런타임 공개는 재검증된 기록에서 재구성됩니다. |
| 통제된 외부 스킬 출처 수명 주기 | implemented | `core/skills/source_registry.py`, `core/supply_chain/skill_source_*.py`, 스킬 출처 API 경로 | 설치는 비활성 상태로 시작하고 철회는 출처 이력을 유지하며 운영은 명령 뒤 공개를 다시 부하합니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-21 | implemented | 런타임 동작이나 권한을 변경하지 않고 기존 기능 번들 및 trusted-artifact 수명 주기를 집중 소유 문서로 옮겼습니다. | `current change`; 문서 크기, 번역, 경로 및 링크 검사입니다. | 하나의 exact revision에서 완전한 설치, 활성화, 비활성화, 철회 및 공개 reload의 통제된 운영 근거를 보존합니다. |

### 남은 작업

- [ ] 번들 요청이 타입이 지정된 작업 경로를 우회하지 않음을 입증하면서 설치, 활성화,
  비활성화, 철회 및 공개 reload를 다루는 exact-revision 통제 수명 주기 증적 하나를 보존합니다.

## 번들 등록

포크가 인프라 경계를 교체하는 대신 탐색 가능한 기능을 추가할 때는 `CapabilityBundle`을
사용합니다. 번들은 운영자에게 표시할 `Capability` 메타데이터, 하나의 타입이 지정된
`CapabilityBinding`, 선택적 검토된 `ToolArtifact` 메타데이터, reasoning-tool
`ToolProvider` 구현을 함께 묶습니다. 연결은 이미 로드된 reasoning 도구, 같은 번들이 제공하는
도구 또는 기존 `ActionType`, `Workflow`를 가리킵니다. 별도 실행 경로를 정의하거나 산출물에서
프로바이더 코드를 부하하지 않습니다.

`fdai.composition.install_capability_bundle(...)`로 번들을 설치합니다. Installer는 로드된
카탈로그에서 cross-reference를 만들고 검증된 등록을 `capability_runtime`에 포함하는 새
`Container`를 반환합니다. 대상이 없거나, 프로바이더가 누락 또는 중복되거나, 도구에 선언된
프로바이더와 번들이 일치하지 않거나, 패키지 도구가 참조되지 않거나, 패키지 도구 id가 다른
출처를 shadow하면 시작이 차단됩니다. 검증이 실패해도 입력 컨테이너는 변경되지 않습니다.

`wire_azure_container(...)`는 file-backed 도구 카탈로그와 설치된 런타임의 패키지 도구를 결합한
다음 런타임 프로바이더와 명시적인 `AzureWireOverrides.tool_providers`를 결합합니다. 중복 도구
또는 프로바이더 id는 암시적으로 덮어쓰지 않고 설정 오류로 처리합니다. `ActionType`과
`Workflow` 연결은 참조일 뿐이며 변경 요청은 계속 trust 라우터, risk 게이트, 실행기, 감사
경로로 다시 들어갑니다. 복사해서 사용할 수 있는 읽기 전용 프로바이더와 번들은 [Core 패키지
루트](../../../services/core-control-plane/src/fdai/)를 참조하세요.

## 확장 수명 주기

배포에서 해당 번들에 설치, 활성화, 비활성화 또는 제거 수명 주기가 필요하면
`core/capability_catalog/extensions.py`의 `ExtensionManager`를 사용합니다. 설치는 보관
SHA-256 다이제스트, 주입된 발행자 trust 결정, host-version 호환성,
manifest-to-bundle 기능 동등성을 검증합니다. 검증된 확장은 비활성 상태로 설치됩니다. 활성화는
변경할 수 없는 base와 활성화된 번들 전체에서 후보 `CapabilityRuntime`을 다시 만들므로 알 수
없는 ActionType, Workflow, reasoning 도구 또는 프로바이더가 있으면 현재 manager를 바꾸지 않고
활성화를 차단합니다. 제거 전에 확장을 비활성화합니다.

이 수명 주기는 dynamic 코드 로더나 공개 패키지 downloader가 아닙니다. 포크 조립 루트가 이미
검토한 프로바이더 구현과 trust 검증기를 제공합니다. 확장 활성화는 타입이 지정된 메타데이터와
참조만 등록합니다. 모든 변경은 기존 파이프라인을 계속 사용하고 ActionType 또는 Workflow 계약에
따라 shadow 모드에서 시작합니다.

## 신뢰할 수 있는 산출물 저장

`core/supply_chain/`은 확장과 스킬이 공유하는 영속 trusted-artifact 계약 및 설치 조정을
소유합니다. 설치는 먼저 기존 확장 또는 스킬 수명 주기를 통과한 다음 exact raw 산출물, detached
서명, 발행자 출처, 다이제스트, 비활성 상태를 저장합니다. 영속 쓰기가 실패하면 후보 카탈로그를
호출자에게 반환하지 않습니다. `delivery/trust/`는 서로 다른 확장 및 스킬 서명 도메인을 사용하는
source-keyed Ed25519 검증기를 제공하므로 서명은 산출물 종류, 출처, id, 버전, 내용 다이제스트
사이에서 재생될 수 없습니다.

운영은 `PostgresTrustedArtifactStore`와 `trusted_artifact` 표를 사용합니다. 확장 및 스킬 id는
하나의 스키마를 공유하지만 `artifact_kind`로 분리됩니다. 삽입은 예상 개정 번호 0을 요구하고
갱신은 exact 개정 번호 및 1 증가를 요구합니다. 표는 내용 크기, SHA-256, 64-byte 서명, 상태,
시각, 개정 번호 제약을 반복합니다. 비공개 키 또는 프로바이더 자격 증명은 저장하지 않습니다.
운영 Operator API 시작은 스킬 기록을 부하하고 `FDAI_SKILL_TRUSTED_PUBLISHERS_PATH`에서 발행자
공개 키를 해석한 뒤 재검증된 `RuntimeSkillDisclosure`를 atomic하게 publish합니다. Bragi,
선택적 타입이 지정된 RPC, GET-only Skills 패널이 이를 공유하며 로컬 조립은 영속 저장소가 없으면
빈 실패 시 차단 스냅샷을 냅니다.

통제된 multi-skill 매니페스트는 별도 `skill_bundle` 산출물 종류와
`fdai.skill-bundle-signature.v1` 도메인을 사용합니다. 시작은 스킬을 번들보다 먼저 재구성해
shared 런타임 스냅샷 publish 전에 exact 구성원 버전과 활성 상태를 검증합니다. 세 읽기 화면은
이 스냅샷 하나를 공유합니다. 스냅샷을 다시 publish하면 Bragi 명령, 읽기 범위
`skill_bundles.*` RPC 연산, Skills 패널 점검 페이로드가 함께 움직입니다. 모든 번들 거절은
고정된 영어 토큰 어휘에서 가져온 내용 없는 안정된 이유를 반환합니다. 거부된 describe와
거부된 load는 각각 자신의 거절 진단을 추가하며 연결되지 않은 번들 카탈로그는 호출자 매개변수
오류가 아니라 그 안정된 이유 중 하나입니다. 연결되지 않은 카탈로그의 설치 개수는 0입니다.

## 외부 스킬 출처

승인된 외부 스킬 저장소는 [스킬 출처 관리](../interfaces/skill-source-management-ko.md)의 별도
영속 출처 파이프라인을 사용합니다. `core/skills/source_registry.py`는 변경할 수 없는 출처 신원을
소유하고 `core/supply_chain/skill_source_*.py`는 격리 구역, 비활성 후보 승인, scheduled ETag
새로 고침, 철회 정책을 소유합니다. PostgreSQL 어댑터는 Alembic `0045`의 다섯 표를 저장합니다.
읽기 담당 GET 경로는 출처 근거를 제공하고 별도 Approver 및 Owner POST 경로는 비활성 후보를
설치하거나 출처 이력을 삭제하지 않고 철회합니다. 운영은 두 명령 뒤 런타임 공개를 reload하여
영속 disablement를 즉시 반영합니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 조립 루트와 주입 가능한 경계 | [프로젝트 구조](project-structure-ko.md#의존성-주입을-통한-커스터마이제이션) |
| 다운스트림 등록 절차 | [다운스트림 포크 가이드](../fork-and-sequencing/downstream-fork-guide-ko.md) |
| 영속 외부 스킬 출처 | [스킬 출처 관리](../interfaces/skill-source-management-ko.md) |
