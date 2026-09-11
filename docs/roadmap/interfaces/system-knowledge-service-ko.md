---
title: 시스템 지식 서비스
translation_of: system-knowledge-service.md
translation_source_sha: 9be2c83aac3bf4c7440afb367423cc5e332cce2a
translation_revised: 2026-09-11
---
# 시스템 지식 서비스

이 문서는 FDAI 자체의 설계, 구현, 검증 상태 및 알려진 미비점에 관한 범위가 제한된 질문에
전용 Teams 멘션 봇으로 답하는 독립 FDAI 마이크로서비스를 정의합니다. 이 서비스는 읽기 전용
제품 지식 표면이며 운영 조회, 승인 또는 실행 경로가 되지 않습니다.

> **범위:** 이 서비스는 release에 고정된 FDAI 저장소 지식으로만 답합니다. 고객 문서, 실시간
> Azure 상태, Incident 근거, 사용자 대화 기록 및 관리 리소스 작업은 이 서비스 범위에 포함하지
> 않습니다.
>
> **배포 경계:** 이 서비스는 자체 이미지, 상태 확인 경계, Teams 애플리케이션 신원 및 release
> 산출물을 갖는 독립 패키지 형태의 여섯 번째 서비스 후보입니다. Core, Operator Service 또는 기존
> A3 채널 edge workload 안에서 실행하지 않습니다. 보호된 배포 요약 및 정리 단계는 보호된 원본
> 검증기가 성공한 후에만 실행합니다.
>
> **권한 경계:** 모든 응답은 `execution_authority=false`를 포함합니다. Teams 멘션, 검색한 레코드,
> 구현 상태 또는 인용한 소스는 FDAI 동작을 설명할 수 있지만 변경을 승인할 수 없습니다.

## 설계 개요

전용 Teams 봇은 직접 멘션을 수신하고 Bot service token, tenant, team, channel, recipient 및
sender mapping을 검증한 후 검증된 봇 멘션만 제거합니다. 서비스는 추적되는 설계 문서와 범위가
제한된 소스 메타데이터로 컴파일한 변경 불가능한 카탈로그를 검색합니다. 설계, 구현, 제한 및
인용을 포함한 간결한 응답 하나를 렌더링하고 안전하게 다시 시도할 수 있는 메시지 claim을 기록한
후 동일한 Teams 대화에 답합니다.

```text
Teams @mention
  -> System Knowledge Service
  -> service-token, tenant, team, channel, recipient, and sender verification
  -> release-bound SystemKnowledgeCatalog
  -> deterministic exact and bilingual lexical retrieval
  -> design + implementation + limitations + citations
  -> durable message claim
  -> same-conversation Teams reply
```

Muninn은 release context index의 최종 책임을 유지합니다. Bragi는 결정적 대화 표현 프로필을
소유합니다. 서비스는 이 기존 책임을 위한 기계적 인프라이며 Pantheon agent를 추가하거나 이름을
바꾸지 않습니다.

## 초기 설계

첫 번째 선택지는 기존 Operator A3 채널 edge를 확장하고 Core 내부에서
`BehaviorKnowledgeIndex`를 복원하는 것이었습니다. Teams 요청은 `SemanticTurnBridge`를 계속
통과하고 Core가 저장소 동작 레코드를 검색한 뒤 일반 채널 렌더러가 결과를 반환합니다.

이 선택지는 가장 많은 코드를 재사용하고 Teams 유입 경로를 하나로 유지합니다.

## 설계 비평

초기 선택지는 서로 독립적이어야 하는 두 수명 주기를 결합합니다.

- **장애 격리:** 저장소 카탈로그 적재와 자체 지식 검색이 운영 대화 경로를 사용할 수 없게 만들 수
  있습니다.
- **Release 격리:** Core와 Operator 이미지에 문서 및 소스 개정에 따라 바뀌는 저장소 유래
  산출물이 필요해집니다.
- **신원 범위:** 제품 지식 봇에는 운영 principal 범위, 프로바이더 읽기 자격 증명 또는 작업 기능이
  필요하지 않습니다.
- **배포 주기:** FDAI 설계와 구현 지식은 운영 컨트롤 플레인을 다시 배포하지 않고 갱신할 수
  있습니다.
- **채널 의도:** 전용 봇에서는 수락한 모든 멘션이 시스템 지식 조회입니다. 키워드 라우팅이
  필요하지 않고 일반 A3 봇은 운영 요청 해석을 계속 담당합니다.
- **롤백:** 지식 봇을 비활성화해도 Core, Operator Service 또는 기존 채널 전달을 롤백하면 안
  됩니다.

따라서 기존 A3 런타임을 공유하면 프로세스 수는 줄지만 장애, 신원 및 release 결합도가 높아집니다.

## 보강된 설계

보강된 설계는 `fdai-system-knowledge-service`를 별도 distribution으로 만듭니다.

- **별도 프로세스:** 서비스는 자체 패키지, entry point, 이미지, 상태 확인 및 범위가 제한된 구성을
  가집니다.
- **별도 Teams 앱:** 배포는 전용 봇 애플리케이션을 공급하고 승인된 표준 채널에만 설치합니다.
  첫 release에서는 모든 메시지를 읽는 RSC(resource-specific consent)를 요청하지 않습니다.
- **멘션 전용 유입:** 인증된 activity에 정확한 봇 recipient의 mention entity가 있을 때만 채널
  메시지를 수락합니다.
- **Release 고정 카탈로그:** build 명령은 추적되는 파일에서 구조화 레코드와 소스 인용을
  컴파일합니다. 런타임 이미지에는 카탈로그만 포함하며 저장소 소스나 Git 자격 증명을 넣지
  않습니다.
- **결정적 검색:** 정확한 alias를 먼저 정렬합니다. 정규화한 영어 token과 한국어 두 음절 token을
  사용해 범위가 제한된 lexical fallback을 제공합니다. 점수가 낮으면 명시적인 사용 불가 답변을
  반환합니다.
- **상태 분리:** 각 레코드는 `not_started`, `in_progress`, `implemented`, `validated`,
  `deferred`, `not_applicable`을 구분합니다.
- **운영 권한 없음:** 서비스에는 Azure 프로바이더 reader, Event Hubs producer, action catalog,
  승인 callback 또는 executor 신원이 없습니다.

## 지식 계약

`SystemKnowledgeRecord`는 검색 단위입니다.

| 필드 | 목적 |
|------|------|
| `knowledge_id`, `subject_id` | 안정적인 신원과 비교 그룹 |
| `status`, `owner` | 현재 전달 상태와 책임 subsystem |
| `question_aliases` | 검토된 영어 및 한국어 질문 |
| `designed_behavior` | 권위 있는 설계가 요구하는 동작 |
| `implemented_behavior` | 현재 소스와 집중 검사가 입증한 동작 |
| `limitations` | 누락, 오래됨, 미검증 또는 의도적으로 제외된 동작 |
| `sources` | 저장소 상대 경로, symbol, line, blob SHA, kind 및 authority role |
| `generated_at` | 컴파일한 각 산출물의 생성 경계를 명시하도록 `catalog_digest` 계산에 포함하는 UTC 빌드 시각 |
| `source_revision`, `catalog_digest` | 정확한 release 및 전체 카탈로그 신원 |

`catalog_digest`는 스키마 버전, 소스 개정, 빌드 시각, 레코드 및 권한 플래그를 포함합니다. 따라서
같은 레코드를 다른 시각에 다시 빌드하면 별개의 패키지 산출물이 생성됩니다. 서식만 압축한 경우를
포함해 인용한 소스가 바뀌면 패키징 전에 카탈로그를 다시 빌드해야 blob 고정값과 다이제스트가
release 트리와 일치합니다.

컴파일한 카탈로그는 중복 식별자, 중복 exact alias, 추적되지 않는 경로, 잘못된 소스 범위,
digest 불일치 및 소스 없는 레코드를 차단합니다. 소스 본문은 런타임 응답에 포함하지 않습니다.
`source_revision`은 현재 checkout과 보호된 `origin/main`의 merge-base이며 rebase 또는 squash
통합 후에도 보호된 main의 조상으로 유지합니다. 각 소스의 `blob_sha`는 현재 검토된 checkout을
별도로 고정하므로 카탈로그 내용이 갱신되어도 side branch 계보를 release 기준점으로 지정하지
않습니다.

## Teams 신뢰 경계

서비스는 검색 전에 다음 값을 검증합니다.

1. Bot service JWT 서명, 고정 algorithm, issuer, audience, 시간 및 `serviceurl`.
2. Activity `channelId=msteams` 및 정확한 허용 service URL.
3. 구성된 tenant, team 및 channel.
4. 사용 가능한 지식 principal 하나에 매핑된 sender `aadObjectId`.
5. 구성된 bot application과 같은 activity recipient.
6. `mentioned.id`가 해당 recipient와 같은 mention entity.

서비스는 정확한 mention entity text를 제거해 질문을 만듭니다. `<at>` markup만으로 mention 신원을
추론하지 않습니다. 지원하지 않는 activity, 크기 초과 body 및 알 수 없는 mapping은 검색 전에
차단됩니다. 첫 release에서는 private 및 shared channel을 지원하지 않으므로 배포 구성의 team 및
channel allowlist에서 제외해야 합니다.

## 전달 및 실패 동작

| 실패 | 안전한 동작 |
|------|-------------|
| 잘못된 service token | `401`을 반환하고 검색하거나 보내지 않음 |
| 알 수 없는 tenant, team, channel, sender 또는 recipient | `403`을 반환하고 검색하거나 보내지 않음 |
| 직접 봇 멘션 누락 | `202`를 반환하고 조회를 기록하거나 보내지 않음 |
| 멘션 제거 후 질문이 비어 있음 | 범위가 제한된 사용 안내 전송 |
| 카탈로그 개정 불일치 | 준비 상태를 사용 불가로 유지하고 답변을 보내지 않음 |
| 관련 레코드 없음 | 검증된 시스템 지식 레코드가 일치하지 않았음을 표시 |
| 증적 전 프로바이더 차단 | 다시 시도할 수 있는 claim 해제 |
| 증적 중단 | 모호한 terminal claim을 보존하고 다시 보내지 않음 |
| 프로세스 재시작 | 프로바이더 전송 전에 실행 장소별 영속 claim store 재사용 |

로컬 구현은 서비스 소유 SQLite claim store를 사용합니다. 배포 구현은 기존 비공개 storage
account의 Managed Identity Blob CAS(compare-and-swap) 원장을 사용합니다. Storage key,
connection string 또는 file share를 만들지 않습니다. 시작할 때 container를 탐색하고 중단된
`processing` claim을 제거하며 중단된 `sending` claim을 terminal `ambiguous`로 전환합니다. 첫
배포는 replica 하나를 유지합니다. 더 많은 replica는 동시성, 비용 및 롤백 근거로 서비스 분리
scorecard를 닫을 때까지 차단됩니다.

독립 Terraform root는 전용 UAMI(user-assigned managed identity), 비공개 claim container,
`AcrPull`, `Storage Blob Data Contributor`, `Key Vault Secrets User`, replica 하나의 Container
App, F0 Azure Bot 및 Teams channel 하나를 소유합니다. 보호된 workflow는 plan-only를 기본으로
사용하며 apply 전에 정확한 CI, image attestation, plan 및 context digest, 명시적 `enable` 또는
`disable` 전환을 요구합니다.

## 출시 순서

1. 카탈로그, 결정적 검색, 멘션 검증 및 응답 렌더러를 build하고 검사합니다.
2. 저장소 소스 없이 서비스와 이미지를 패키징합니다.
3. 합성 signed activity로 로컬 Activity Protocol canary를 실행합니다.
4. 보호된 Terraform plan을 적용하고 결정적 Teams package를 build한 뒤 필요한 Microsoft Graph
   app catalog 권한을 가진 tenant 관리자가 설치합니다.
5. 운영 준비를 선언하기 전에 mention-only 수신, 동일 대화 응답, 재시작 중복 제거, 비활성화 및
   롤백을 검증합니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 현재 구현 상태 | [시스템 지식 서비스 구현 원장](../../roadmap-implementation/interfaces/system-knowledge-service.md) |
| 전용 Teams 봇 배포 및 설치 | [시스템 지식 Teams 온보딩](../../runbooks/system-knowledge-teams-onboarding-ko.md) |
| 일반 운영 Teams 대화 | [운영 A3 채널 런타임](production-a3-channel-runtime-ko.md) |
| 사람 신원 및 역할 경계 | [사용자 RBAC 및 Entra 신원](user-rbac-and-identity-ko.md) |
| 서비스 분리 수락 gate | [서비스 분리 및 데이터 소유권](../architecture/service-graduation-and-ownership-ko.md) |
| 기존 구조화 동작 설계 | [동작 지식](behavior-knowledge-ko.md) |
