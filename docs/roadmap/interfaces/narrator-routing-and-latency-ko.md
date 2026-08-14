---
title: 서술기 라우팅과 지연 시간
translation_of: narrator-routing-and-latency.md
translation_source_sha: e9eef8f4f9a5191ad9da207e6df20d7bcdc0b1ac
translation_revised: 2026-08-15
---
# 서술기 라우팅과 지연 시간

이 문서는 서술을 담당하는 모델의 배포 선택, 지연 시간 측정, 운영자 선호 설정, 공개 웹 검색
풀의 동작을 소유합니다. T1 서술과 시스템이 통제하는 T2 추론 사이의 경계를 지킵니다.

## 서술기 지연 시간 라우팅

독립된 Operator Service가 인증된 대화 HTTP 경계를 소유합니다. 표준 로컬 프로파일에서는
서비스 내부의 `LocalAzureNarratorAdapters`가 준비된 모델 해석 산출물을 읽고 Azure CLI에서 수명이
짧은 Cognitive Services 토큰을 받아, Core를 가져오거나 실행 권한을 갖지 않은 채로 정렬된
`narrator_candidates`를 시도합니다. 모델 해석 산출물과 토큰을 모두 쓸 수 있을 때만 상태를 사용
가능으로 보고하며, 권위 있는 근거와 단정 검증 증적이 없으면 모델 지식만으로 만든 답변을
명시적으로 미검증 상태로 둡니다.

운영 환경의 대화 전달에는 주입된 변환 및 스트림 어댑터가 계속 필요합니다. 예전에 프로세스 안에
있던 `LatencyRoutedChatBackend`는 최상위 Operator 구현과 함께 제거됐으며, 이동 평균 p50/TTFT
기반 선택과 멀티모달 라우팅은 현재 구성된 운영 기능이 아니라 독립 서비스가 목표로 삼는
동작입니다.

라우터는 T1 서술 트래픽 전용입니다. 지연 시간 라우팅을 T2 기능으로 넓히려면 별도 설계
검토가 필요합니다. `t2.reasoner.primary` 자리에 대해 검토를 거친 동일 공급자 예외는
[LLM 전략](../architecture/llm-strategy-ko.md#t2-primary-latency-pool-invariant-safe-opt-in)이
소유합니다. 다음 두 제약이 경계를 지킵니다.

- **혼합 모델 불변식**: `t2.reasoner.primary.publisher`와
  `t2.reasoner.secondary.publisher`는 달라야 합니다. 짝 전체를 속도로 라우팅하면 필수적인
  교차 검증이 하나의 모델 계열로 줄어들 수 있습니다.
- **판정자와 비평자의 결정성**: 조립 계층은 `t1.judge`, `t2.critic`, 토론 오케스트레이터를
  구성된 배포에 고정해 연결합니다. 런타임 라우팅 래퍼가 이 연결을 몰래 바꾸지 못합니다.

지연 시간으로 라우팅되는 판정자가 필요한 포크는 자체 품질 게이트, 조립 연결, 감사 근거를 갖춘
별도 기능을 선언합니다.

독립 로컬 service는 이제 coalescing되고 범위가 제한된 명시적 주기 하나로 텍스트 및 비전 풀을
갱신합니다. 각 텍스트 후보를 두 번, 각 비전 후보를 범위가 제한된 1픽셀 이미지로 한 번 탐색하고,
샘플 8개짜리 지연 시간 및 첫 토큰까지의 시간(TTFT) 창을 따로 유지하며, 측정된 p50으로 텍스트
턴을 정렬하고 범위가 제한된 장애 조치를 수행합니다. 측정되지 않은 후보에는 한 번의 warm-up
기회를 주고 실패한 후보는 풀에서 제거하지 않고 범위가 제한된 penalty를 기록합니다.

Operator Service에는 opaque conversation-image id를 검증되고 범위가 제한된 byte로 바꾸는 서버
소유 resolver가 없으므로 이미지 턴은 계속 사용 불가 상태입니다. 클라이언트가 제공한 이미지
필드는 이 권한을 대신할 수 없습니다. `FDAI_NARRATOR_PROBE_INTERVAL_SECONDS`의 주기적 scheduler도
대상 동작으로 남아 있으며 구현된 `refresh()` 진입점은 명시적이고 process-local입니다.

## 사용자별 선호 설정과 TTFT

대상 Settings > Models 화면은 엔드포인트나 자격 증명 없이 해석된 T1/T2 목록, 초기화 상태, 런타임 지연
시간 근거를 보여줍니다. 인증된 principal은 `Auto` 라우팅을 쓰거나 현재 서술기 허용 목록에 있는
배포 하나를 고를 수 있습니다. 제거됐거나 쓸 수 없게 된 선호 설정은 `Auto`로 되돌리며, 서버는
임의의 모델 식별자를 차단합니다.

대상 선호 설정은 명시적인 개정 번호를 씁니다. 생성 시에는 개정 번호 `0`을 보내고 이후 쓰기는 현재
개정 번호와 일치해야 합니다. 상태와 감사 기록은 하나의 트랜잭션에서 커밋되므로, 동시에 진행된
세션은 서로 덮어쓰지 않고 `409`를 받습니다.

대상 스트리밍 라우터는 비어 있지 않은 첫 모델 토큰이 도착할 때 TTFT를 기록합니다. TTFT p50/p95와 전체
지연 시간 p50/p95는 각각 별도의 이동 창과 샘플 개수를 씁니다. 측정되지 않은 TTFT는 사용 불가로
둡니다. 선호 설정은 T1 서술기에만 적용됩니다. T1 내부 판단, 임베딩, 그리고 모든 T2 보조,
비평자, 평가 기준, 에스컬레이션 배정은 시스템이 통제하는 상태로 남습니다. T2 기본 풀은
운영자별로 개인화하지 않습니다.

Settings > Models는 T2 모델 정책 초안 작성기도 제공합니다. Operator API는
`rule-catalog/llm-registry.yaml`의 공급자 및 계열 선호 설정만 보여줍니다. 운영자는 공급자가
다를 때만 기본 및 보조 후보를 고를 수 있고, 거버넌스 PR에 쓸 검증된 YAML 조각을 복사할 수
있습니다. 브라우저는 선택 내용을 런타임 상태에 쓰지 않습니다. 활성 짝은 카탈로그 검토, 해석기
재생성, 배포 재로드를 거친 뒤에만 바뀝니다.

로컬 운영자 모드는 Azure CLI 세션에서 지역별 GPT 카탈로그, 구독 할당량, 기존 배포를 묶어 볼 수
있습니다. 비동기 읽기는 결과를 5분간 캐시하고 명시적인 읽기 전용 새로 고침을 제공합니다. 계열,
버전, 수명 주기, 지원 SKU, 가용 할당량, 배포 이름만 돌려줍니다. 지원이 중단된 chat, codex,
realtime 계열은 새 T2 역할 후보로 제공하지 않습니다. 모델 선택은 거버넌스 초안을 만들 뿐 Azure를
바꾸지 않습니다.

같은 페이지는 기능, 프로바이더, 직접 또는 APIM 경로, API 방식, 배포, 계열, 용량, 특징,
발견 출처, 확인 시각을 포함한 정제된 엔드포인트 목록을 보여줍니다. 엔드포인트 참조, 인증 대상,
리소스 다이제스트, URL, 자격 증명은 제외합니다. 엔드포인트 등록, APIM 변경, 크기 조정, 이미지
변경, T2 역할 배정은 배포 또는 카탈로그 작업 흐름으로 남깁니다.

## 대화형 웹 검색 지연 시간 풀

공개 웹 조회는 별개의 Chat T2 도구 호출이며 T1 판단이나 액션 품질 게이트 짝이 아닙니다.
활성화하면 Azure Responses `WebSearchProvider`가 별도 `web_search_candidates` 함수 호출
풀을 쓰고, 이동 평균 p50이 가장 낮은 후보를 고르며, 나머지 후보로 장애 조치합니다.
결정론적 웹 검색 정책이 프로바이더 호출 전에 턴을 승격시킵니다.

로컬과 배포 환경의 Operator API 조립은
`application.conversation.capabilities.web_search`에 있는 동일한 프로바이더 중립적 해석기를 씁니다.
환경 변수 로딩, 모델 해석 결과 기반 후보 선택, Azure 객체 구성은
`adapters.conversation.web_search`에 남깁니다. 해석기는 서버가 소유한 허용 목록과 주입된
프로바이더만 받으며, 운영자가 입력한 텍스트는 엔드포인트, 배포, 자격 증명, 프로바이더 범위를
선택할 수 없습니다.

로컬과 배포 환경의 semantic turn도 동일한 logical 요청 및 변환 결과 이름을 사용합니다. 배포가
이를 `aw.pantheon.objects`로 multiplex할 때 두 모드는 동일한 physical marker, hash 기반
consumer-group 파생, managed-identity 전송 및 shared physical DLQ 동작을 사용합니다.

로컬과 배포 환경의 Operator API 조립은 고정된 parity 매니페스트에 있는 서비스 소유의 인증된
읽기 전용 `/agents/activity` 경로도 동일하게 노출합니다. 이 경로는 영속 활동 변환 결과를 읽으며
결정, 승인 또는 실행 권한을 갖지 않습니다.

웹 검색 풀은 같은 예열 및 주기적 측정 방식을 씁니다. 주기적 탐색은 `web_search` 도구 없이
최소한의 모델 응답을 요청하고, 실제 검색은 종단 간 지연 시간을 같은 창에 더합니다.
`FDAI_WEB_SEARCH_PROBE_INTERVAL_SECONDS`는 기본값이 `300`이며 `30` 미만은 허용하지
않습니다.

Settings > Models는 Owner에게 배포 전체의 웹 검색 활성화와 정확한 호스트 허용 목록을
제공합니다. 쓰기는 같은 개정 번호 기반 상태-감사 트랜잭션을 쓰고 커밋 뒤에 살아 있는 해석기를
갱신합니다. 등록된 해석기가 없으면 화면은 사용 불가로 보고하고 쓰기는 저장 전에 `503`을
돌려줍니다. 구성 기본값만으로는 프로바이더를 쓸 수 있다는 증거가 되지 않습니다.

이 페이지는 생성된 모델 해석 스냅샷의 정제된 파일 이름, `kind=generated-file`, UTC 수정 시각을
`as_of`로 보고합니다. 전체 로컬 경로는 돌려주지 않습니다. 발견 및 프로비저닝 라벨은 구성된
동작을 설명할 뿐 최신성 근거를 대신하지 않습니다.

## 런타임 전달 결정 사항

- **모델 해석 결과 전달**: 초기에는 파일 시스템 경로 또는 인라인 JSON 환경 변수/시크릿 참조를
  지원합니다. Key Vault를 직접 읽는 방식은 조정기 작업과 함께 다음으로 미룹니다.
- **로컬 모델 고정본**: Ollama나 LM Studio 고정본은 현재 포함하지 않습니다. 나중에 추가하더라도
  명시적인 모델 연결일 뿐, 대화형 로컬 프로파일을 다시 정의하지 않습니다.
- **조정기 경고**: 현재는 Teams를 가정하며 조정기를 구현할 때 확정합니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 로컬 정렬 narrator 후보 fallback | implemented | `services/operator-service/src/fdai_operator_service/adapters/local_narrator.py`; `services/operator-service/tests/test_local_narrator.py` | Service 내부 어댑터는 해석된 산출물을 읽고 수명이 짧은 토큰을 얻어 정렬된 후보를 시도하며 Core를 가져오거나 실행 권한을 받지 않고 정제된 상태를 노출합니다. |
| 해석된 narrator 후보 수집 | implemented | `services/core-control-plane/tests/rule_catalog/schema/test_narrator_collection.py`; 모델 해석기 및 레지스트리 | Focused 검사는 검토된 모델 해석 입력에서 `narrator_candidates` 수집을 다룹니다. |
| 이동 text p50/TTFT, 범위가 제한된 refresh 및 장애 조치 | implemented | `services/operator-service/src/fdai_operator_service/adapters/local_narrator.py`; `narrator_latency.py`; `narrator_payloads.py`; focused Operator 테스트 | 독립 service는 샘플 8개짜리 latency 및 TTFT 창을 유지하고 비어 있지 않은 첫 SSE token을 측정하며 범위가 제한된 probe를 coalescing하고 text 후보를 정렬하며 unanimous 429/503 상태를 보존하고 malformed 또는 oversized 출력을 fail closed로 처리합니다. |
| 비전 후보 probe 및 이미지 턴 라우팅 | in-progress | `services/operator-service/src/fdai_operator_service/adapters/local_narrator.py`; focused vision-probe 및 image-unavailable 테스트 | 비전 후보는 독립된 측정 probe 창을 갖습니다. 서버 소유 image resolver가 검증되고 범위가 제한된 byte를 공급할 때까지 이미지 턴은 사용 불가 상태이며 text binding을 빌리지 않습니다. |
| 사용자별 라우팅 선호 설정 및 런타임 지연 시간 변환 결과 | not-started | [사용자별 선호 설정과 TTFT](#사용자별-선호-설정과-ttft) | 개정 번호 기반 선호 설정, TTFT 변환 결과 및 배포 pinning 계약은 대상 동작으로 남아 있습니다. |
| 공개 웹 후보 라우팅 | in-progress | `services/operator-service/src/fdai_operator_service/application/conversation/capabilities/web_search/`; `services/operator-service/src/fdai_operator_service/adapters/conversation/web_search/`; focused Operator 테스트 | 프로바이더 중립 및 Azure 구성 경로가 있습니다. 로컬 및 배포 프로파일의 관리되는 이동 지연 시간 및 장애 조치 근거가 남아 있습니다. |
| 선택적 report-format parity | implemented | `fdai_operator_service.reporting.optional_pdf_report_encoder`; `IncidentRcaReportingProjectionReader`; Operator composition 및 경로 테스트 | 로컬 및 배포 Operator composition은 같은 service-local loader와 authoritative audit-backed Incident report reader를 사용합니다. Venue, 환경 및 identity는 report 권한을 바꾸지 않습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-14 | in-progress | 구현 ledger를 도입하고 어떤 지연 시간 및 선호 설정 동작이 대상 설계로 남는지 명확히 했으며 이전 출처 이력은 재구성하지 않았습니다. | `current change`; 구현 범위 표에 나열된 현재 로컬 narrator, 해석기, 웹 검색 source 및 focused 검사입니다. | 독립 service 지연 시간 창과 선호 설정을 구현한 뒤 관리되는 로컬 및 배포 근거를 보존해야 합니다. |
| 2026-08-14 | implemented | 로컬 및 배포 Operator composition에서 선택적 PDF report 등록을 동일하게 유지했습니다. | `current change`; service-local optional loader, package-extra 계약, composition binding 및 focused 경로/composition 테스트입니다. | Package availability를 실행 권한으로 취급하지 않고 별도의 인증된 Incident report 증적을 보존해야 합니다. |
| 2026-08-14 | implemented | 로컬 및 배포 Operator composition에서 authoritative Incident RCA report materialization을 동일하게 유지했습니다. | `current change`; service-local audit-backed report reader, composition binding 및 focused reader/family 테스트입니다. | 별도의 인증된 Incident report 증적을 보존해야 합니다. |
| 2026-08-14 | implemented | 범위가 제한되고 coalescing된 text 및 vision probe, 측정된 장애 조치, 엄격한 SSE 및 출력 제한, 범위가 제한된 Azure CLI credential 획득을 갖춘 service-local 이동 text latency 및 TTFT 라우팅을 추가했습니다. | `current change`; narrator adapter 모듈; focused local narrator 및 credential 테스트 `21 passed`; 통합 Operator 및 Core narrator 검사가 통과했습니다. | 주기적 refresh와 서버 소유 image resolver를 binding한 뒤 관리되는 local 및 deployed timing 근거를 보존합니다. |

### 남은 작업

- [x] 독립 텍스트 및 비전 후보 탐색, 별도 이동 지연 시간 및 TTFT 창, 범위가 제한된 갱신, 장애 조치 및 사용 불가 동작을 구현하고 focused 테스트를 추가합니다.
- [ ] 이미지 턴 라우팅을 완료로 표시하기 전에 주기적 refresh owner와 서버 소유 conversation-image resolver를 binding합니다.
- [ ] T2 연결을 개인화하지 않으면서 개정 번호 기반 principal별 `Auto` 또는 허용된 narrator 선호 설정 저장소와 정제된 Settings 변환 결과를 구현합니다.
- [ ] Narrator 및 웹 검색 후보 선택, 첫 토큰 시간, 실패, 복구 및 정제된 상태에 대한 관리되는 로컬 및 배포 증적을 보존합니다.
- [ ] 검토된 service-owned 어댑터 경계를 통해서만 연기된 직접 Key Vault 모델 해석 결과 loader와 조정기 알림 경로를 구현합니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| T1/T2 기능과 품질 게이트 정책 | [LLM 전략](../architecture/llm-strategy-ko.md) |
| Operator API 런타임 모델과 의존성 주입 경계 | [오퍼레이터 콘솔 런타임 모델](operator-console-runtime-model-ko.md) |
| 로컬 및 배포 환경의 모델 해석 | [개발과 배포의 동등성](../deployment/dev-and-deploy-parity-ko.md) |
