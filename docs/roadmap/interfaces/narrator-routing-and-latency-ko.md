---
title: 서술기 라우팅과 지연 시간
translation_of: narrator-routing-and-latency.md
translation_source_sha: a8adcb751900b2987f6232e9ccddb6cc73cd3480
translation_revised: 2026-09-06
---
# 서술기 라우팅과 지연 시간

이 문서는 대화 표현을 위한 배포 선택, 지연 시간 측정, 운영자 선호 설정, 공개 웹 검색 풀의
동작을 정의합니다. T1 경량 모델의 작성과 독립 검토를 시스템이 통제하는 T2 추론과 구분합니다.

> **구현 상태:** Core 소유 mini 라우팅은 구현되었으며 집중 검사를 통과했습니다. 로컬 합성 탐색과
> 인증된 Console DOM 근거를 아래에 기록했습니다. 통합 런타임, 시각적 상호작용 및 전체 턴 지연
> 시간 검증은 아직 일부만 완료되었습니다. 탐색 처리 시간만으로 대화가 빨라졌다고 볼 수 없습니다.

## 서술기 지연 시간 라우팅

독립된 Operator Service가 인증된 대화 HTTP 경계를 소유하고 Kafka로 의미 처리 턴을 중계합니다.
표준 로컬 및 배포 환경의 의미 처리 경로에서 모델 선택과 추론은 Core가 담당합니다. Operator와
Console은 운영자 문장에서 배포를 선택하거나 실행 권한을 받지 않으며, 모델 사용 가능 상태를
검증된 운영 근거로 취급하지 않습니다.

Core는 별도의 범위가 제한된 준비 상태 경로에서 구성된 모델 대상을 검증합니다. 모델 ID를
사용할 수 없으면 의미 전송을 계속 실행하면서 계획 전에 타입이 지정된 인증 보류 결과를
반환합니다. 어휘 기반 라우팅으로 대체하거나 Operator HTTP ID를 빌려 쓰지 않습니다.

### Core 소유 mini 후보 선택

Core는 검증된 서술기 후보 풀을 재사용하고 mini 후보를 최대 4개까지 허용합니다. 각 후보의
신원, 공급자, 모델 계열 및 공급자 연결은 정확한 모델 해석 결과의 배포 메타데이터로 확인합니다.
배포 이름만으로 모델 계열이나 기능을 판단하지 않습니다. 보류되었거나 검증되지 않은 대상은
제외하며, 탐색 요청으로 대상을 검색하거나 프로비저닝하거나 추가하지 않습니다.

각 후보는 성공한 탐색 요청의 처리 시간을 최근 8개까지 보관합니다. 설정한 탐색 간격의 2배보다
오래되지 않은 표본만 p50(중앙값)과 p95 계산에 사용합니다. 최신 측정값이 있는 후보는 p50 순서로
정렬하고, 오래되었거나 측정되지 않은 후보는 구성된 대체 순서를 유지하되 가장 빠르다고 표현하지
않습니다. 실패한 대상은 이후 탐색이 성공할 때까지 제외합니다.

일반 적응형 T1 계획과 답변 단계는 선택된 작성 모델을 사용합니다. 검토와 재검증은 같은 풀에서
사용 가능한 독립 mini 모델이 담당합니다. 독립적인 모델 쌍이 없으면 작성 모델이 자기 답변을
검토하는 대신 적응형 경로를 사용 불가로 유지합니다. 모델 팩터리는 턴마다 변경 불가능한 선택
하나를 고정하고, 지연 실행 작업을 포함한 모든 단계가 이를 공유합니다. 이후 탐색은 다음 턴부터
영향을 줍니다. 탐색을 비활성화하면 구성된 모델 선택을 유지하며 실측 속도를 주장하지 않습니다.

### 과금되는 탐색 요청의 한도

`FDAI_T1_MINI_PROBE_ENABLED`의 기본값은 `0`입니다. 로컬 프로필에서도 과금되는 합성 모델 요청을
명시적으로 승인한 뒤에만 `1`로 설정합니다. 이 설정은 허용한 비용 지출의 상한을 정할 뿐,
리소스 작업, T2 사용 또는 제한 없는 모델 호출을 승인하지 않습니다. 로컬 실행 환경을 선택해도
탐색은 자동으로 활성화되지 않습니다.

| 한도 | 값 |
|------|----|
| 탐색 간격 | `FDAI_NARRATOR_PROBE_INTERVAL_SECONDS`: 기본 `300`초, 허용 범위 `30-3600` |
| 주기별 후보 요청 수 | 최대 `4`회, 허용된 mini 후보마다 한 번 |
| 요청 내용 | 정확히 `OK`만 반환하도록 하는 고정 합성 요청. 운영자 프롬프트, 대화 이력, 도구 근거는 제외 |
| 최대 출력 토큰 | 요청당 `256` |
| 요청 제한 시간 | `8`초 |
| 주기 제한 시간 | 변환 결과 발행을 포함해 `35`초 |
| StateStore 쓰기 제한 시간 | 발행마다 `5`초 |
| 성공 표본 구간 | 후보당 최대 `8`개. 최신성 한도는 `2 * interval` |

Core 런타임은 즉시 실행하는 첫 주기와 후속 주기 실행을 관리하며, 주기가 겹치지 않게 합니다.
초기 변환 결과 발행에 실패하면 오류를 상위로 전달하고 탐색을 시작하지 않습니다. 주기 중 발행
실패는 재시도 없이 기록하며, 이 쓰기에도 전체 주기 제한 시간을 적용합니다.
종료 시 자신이 소유한 작업을 취소합니다. HTTP `429`, HTTP `503`, 공급자 시간 초과 또는 주기
제한 시간 도달 시 해당 주기를 끝내며 같은 요청을 재시도하거나 T2로 대체하지 않습니다.
다음에 예정된 주기에서만 다시 측정할 수 있습니다. 합성 `OK` 요청의 성공은 요청 처리 시간을
측정할 뿐 첫 토큰까지의 시간(TTFT), 답변 품질 또는 전체 대화 지연 시간을 입증하지 않습니다.

### 읽기 전용 상태 변환 결과

Core는 버전이 지정된 `conversation:t1-mini-routing:v1` StateStore 변환 결과를 쓰는 유일한
주체입니다. 이 결과에는 정제된 배포 표시명, 선택 이유, 후보 처리 시간과 상태, 최신성 한도가
들어가며 `execution_authority=false`를 유지합니다. 엔드포인트, 자격 증명, 운영자 내용 또는
공유 작업 흐름 권한은 포함하지 않습니다.

Operator는 구조와 최신성을 한도 안에서 검증한 뒤에만 이 변환 결과를 읽고, `model`과
`router`만 `/chat/health`에 추가합니다. 라우팅 데이터가 없거나 잘못되었거나 만료되어도 의미
전송의 사용 가능 상태를 바꾸거나 모델이 정상이라고 꾸며낼 수 없습니다. 상태의 사용 가능 여부는
의미 브리지의 전송 준비 상태를 뜻하며, 추론 성공이나 검증된 답변을 뜻하지 않습니다.

Console의 모델 배지는 `T1`과 변환 결과의 배포 이름을 표시합니다. 도구 설명은 후보별 처리 시간,
표본 수 및 측정 완료, 오래됨, 미측정, 실패 상태를 구분합니다. Command Deck이 열려 있고 화면에
표시되는 동안에만 30초마다 상태를 조회하며, 브라우저는 모델 탐색을 실행하지 않습니다.
이 읽기 변환 결과는 두 번째 기록 주체, 서비스 간 구현 가져오기, 데이터베이스 데이터 재작성
또는 공유 결정 상태를 만들지 않습니다.

### 유지되는 경계와 기존 서술기

구성된 T2 기본 모델(연결된 경우 Sol)은 선택적 보강 단계로 유지하며, mini 지연 시간으로 탐색하거나
선택하지 않습니다. 그 출력도 독립 검토를 다시 거칩니다. 운영 T2의 서로 다른 공급자 요구사항과
구성된 `t1.judge`, `t2.critic`, 토론 연결은 바뀌지 않습니다. 이 역할로 지연 시간 라우팅을
확장하려면 별도 설계 검토가 필요합니다. 검토된 T2 기본 모델 예외는 계속
[LLM 전략](../architecture/llm-strategy-ko.md#t2-기본-라우팅-및-통제된-복구)에서 정의합니다.

`LocalAzureNarratorAdapters`는 별도의 기존 로컬 서술기이며 의미 Kafka 경로가 아닙니다. 이 서술기의
정렬된 대체 후보, 텍스트 및 비전 탐색, 최근 p50/TTFT 구간, 실패 벌점 및 Operator 소유 주기
스케줄러는 Core mini 라우팅의 구현이 아닙니다. 모델 측정값을 얻으려고 기존 서술기와 의미 Kafka를
함께 활성화하지 않습니다. 불투명한 대화 이미지 식별자를 검증된 크기 제한 바이트로 변환하는 서버
소유 해석기가 없으면 이미지 턴은 계속 사용 불가입니다. 클라이언트 이미지 필드는 그 권한을
대신할 수 없습니다.

## 대화형 의미 계획 지연 시간

대화형 질문은 Core가 기능을 선택하기 전에 스키마로 검증되는 의미 판단 경계를 통과합니다. 이 경계가
바인딩된 Resource 상태, Resource Health 또는 Service Health 함수에 대해 모호하지 않은 읽기
intent를 반환하면 Core는 타입 기반 프레임을 결정론적으로 만들고 두 번째 프레임 모델 호출을
생략합니다. 정확한 함수가 principal 범위 매니페스트에 있어야 하며, 일반 검증기, 근거 실행, 답변 검사는
그대로 수행합니다. 새롭거나 모호하거나 작업과 관련됐거나 바인딩되지 않은 질문은 일반 프레임 계획
경로를 유지합니다.
공급자 호출은 자유 형식 JSON 객체와 반복된 텍스트 스키마 대신 엄격한 구조화 출력을 사용합니다.
첫 번째 턴의 운영 판단은 수락된 타입 의미 판단이 이미 운영 요청임을 증명하므로 소셜 사전 검사를
실행하지 않습니다. 직접 응답 후보는 소셜 답변을 렌더링하기 전에 독립 사전 검사를 계속 요구하며,
이전 턴이 있는 요청은 확인 응답이나 승인 대기 컨텍스트가 의미를 바꿀 수 있으므로 사전 검사를
유지합니다.

Console 시작 질문에는 계약으로 검증된 함수 기반 질문만 표시합니다. 의미 런타임이 아직 증명할 수 없는
브라우저 작성 화면 요약, tier 추정, 대기 중인 결정 또는 비용 기회 대신 서버 소유의 현재 근거를
요청합니다. 질문 은행은 표시되는 각 시작 질문의 이중 언어 문구, 타입 기반 intent, 보존 근거 출처,
집중 계약 검증을 기록합니다.

적극적인 T2 복구는 모든 환경에서 기본적으로 비활성화합니다. Owner는 감사되고 범위가 제한된 복구
실험을 한 번 활성화할 수 있지만, 개발 프로세스에서 실행된다는 이유만으로 대화형 요청이 T2를 사용하지
않습니다. 모델 투명성은 완료된 모든 의미 판단, 프레임, 계획 모델 호출의 실측 처리 시간과 사용 가능한
토큰 사용량을 기록합니다. 전체 턴 시간에는 모델 호출이 아닌 결정론적 작업과 provider 작업도 계속
포함합니다.

## 합성 대화 및 프롬프트 확인

[적응형 응답](../../../mocks/ui/deck-sources-v2.html)과
[인시던트 대화](../../../mocks/ui/incident-conversation.html) 시안은 결론, 부족한 근거,
조사 기록을 에이전트 답변 안에 표시합니다. 조사 완료와 인시던트 복구는 구분하며,
취소하면 그때까지 표시된 작업만 보존합니다.
적응형 시안의 모의 LLM 서술 단계에서는
[`system-prompt.example.md`](../../../mocks/ui/assets/prompts/system-prompt.example.md)를
파일 행 아래에 펼쳐 보여줍니다. 모달을 띄우거나 입력창을 막지 않으며, 읽기 전용 Markdown
보기와 복사, 다운로드를 지원합니다. 기록 누락과 읽기 실패는 명시적으로 표시하고,
파일을 접으면 진행 중인 읽기를 취소합니다. 이 파일은 실제 런타임에서 수집한 프롬프트가
아니라 공개 합성 예제입니다. 이 시안은 프로덕션의 프롬프트 수집, 권한, 모델 라우팅을 바꾸지 않습니다.

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
이를 `fdai.pantheon.objects`로 multiplex할 때 두 모드는 동일한 physical marker, hash 기반
consumer-group 파생, managed-identity 전송 및 shared physical DLQ 동작을 사용합니다.

로컬과 배포 환경의 Operator API 조립은 고정된 parity 매니페스트에 있는 서비스 소유의 인증된
읽기 전용 `/agents/activity` 경로도 동일하게 노출합니다. 이 경로는 영속 활동 변환 결과를 읽으며
결정, 승인 또는 실행 권한을 갖지 않습니다.

별도 웹 검색 풀은 자체 초기 측정과 주기 측정 방식을 유지합니다. 주기적 탐색은 `web_search` 도구 없이
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
  지원합니다. 서비스 소유 비동기 Key Vault 출처 어댑터는 이제 공식 Azure vault origin과
  audience, 정확한 secret 신원, 크기, JSON 구조, 활성화 및 만료 상태, 전체 마감을 검증하면서
  값을 노출하지 않습니다. 수명 주기 전용 조립이 이 출처를 구성하고 애플리케이션 lifespan이
  하나의 비동기 소유자를 호출합니다. 이 소유자는 후속 서비스를 시작하기 전에 기능 바인딩과
  수명 주기 보류 평가에 변경 불가능한 출처 리비전 하나를 발행합니다.
- **로컬 모델 고정본**: Ollama나 LM Studio 고정본은 현재 포함하지 않습니다. 나중에 추가하더라도
  명시적인 모델 연결일 뿐, 대화형 로컬 프로파일을 다시 정의하지 않습니다.
- **조정기 전달**: 주간 workflow는 정제된 근거를 보존하고 검토가 필요할 때 멱등적 초안 PR을
  엽니다. Teams 경고를 보내지 않으며 활성화 권한이 없습니다.

## Qualification 지연 시간 SLO

버전이 지정된 `chatops-latency-v1` 계약은 PR 회귀 검사와 라이브 카나리(`live_canary`) 및
릴리스(`release`)
근거를 분리합니다. 각 단계는 하나의 소유 환경, 최소 표본 수, 순서가 지정된 p50, p95, p99
상한을 갖습니다.

| 단계 | 환경 | 최소 표본 수 | p50 | p95 | p99 |
|------|------|-------------:|----:|----:|----:|
| 첫 토큰까지 걸린 시간 | `live_canary` | 30 | 1000 ms | 2500 ms | 5000 ms |
| 최종 답변 | `release` | 500 | 8000 ms | 20000 ms | 30000 ms |
| 결정론 검증 | `pr_regression` | 100 | 250 ms | 750 ms | 1500 ms |
| 채널 확인 응답 | `live_canary` | 30 | 1000 ms | 5000 ms | 9000 ms |
| 전체 전달 | `release` | 500 | 10000 ms | 25000 ms | 40000 ms |

단계 소유자는 미리 측정한 기간, 타임스탬프 권위 출처(`timestamp_authority`), 추적 및 출처 이력
약속값을 제공합니다. 순수 Core 축약기는 완료, 수정, 판단 보류, 미지원, 대체 경로, 잘림, 시간
초과 표본의 백분위수와 결과 수를 계산합니다. 시간 초과, 부족한 표본 수 또는 상한을 넘는 백분위수는 해당 단계를
실패로 처리합니다.
`LatencyStageReceipt`는 호출자가 기간을 직접 제출하지 못하게 합니다. 단계 소유자가 monotonic
시작 및 완료 값을 제공하면 adapter는 증적 환경이 설치된 단계 계약과 일치한 후에만 밀리초를
파생합니다.

콘텐츠가 없는 표본을 수집한 후 저장소 벤치마크 어댑터를 실행합니다.

```bash
uv run python scripts/evaluation/chatops_quality_latency.py \
  --input <latency-samples.json> \
  --output <latency-evidence.json> \
  --require-slo
```

출력은 실행 신원과 정본 표본 매니페스트를 해시합니다. 추적 ID, 출처 이력 레코드, 답변 텍스트,
principal, 엔드포인트 또는 고객 식별자를 노출하지 않고 단계, 환경, 백분위수, 표본 수,
타임스탬프 권위 출처, 결과 수, 출처 리비전 및 계약 근거를 보존합니다. 이 축약기는 완전한
상관관계 추적을 주장하지 않습니다. 추적 완전성은 독립 요구사항으로 유지됩니다.

인접한 `chatops_quality_trace.py` 명령은 독립 추적 요구사항을 검증합니다. 완전한 추적에는
세션, 요청, 턴, 도구 또는 에이전트 근거, 제안, 결정, 전달, 감사에 대해 순서가 지정된 약속값이
정확히 하나씩 들어갑니다. 모든 이벤트는 같은 correlation digest를 사용하고 이전 레코드에
연결되며, 권위 있는 타임스탬프와 출처 이력 약속값을 운반하고, 추적 구간 안에 있어야 합니다.
누락, 중복, 순서 변경, 다른 상관관계 또는 끊어진 연결이 있으면 `complete_trace=false`로
유지합니다.

```bash
uv run python scripts/evaluation/chatops_quality_trace.py \
  --input <trace-commitments.json> \
  --output <trace-evidence.json> \
  --require-complete
```

## 로컬 mini 라우팅 근거 (2026-09-06)

구현 세션에서 현재 변경에 대해 보고한 근거의 범위는 다음과 같습니다.

- **집중 검사:** Python은 `229 passed`이며 PostgreSQL 사례 2개는 실행 대상에서 제외했습니다.
  명시적 활성화 구성 검사 6개도 추가로 통과했습니다. Console은 순서대로 `147`, `48`, 최종 `160`개를
  통과했습니다. 이 집합들은 중복되므로 합산하지 않습니다. 최종 Console 타입 검사와 프로덕션 빌드도 통과했습니다.
- **실제 합성 탐색:** Core의 첫 두 예정 주기에서 T2 없이 mini 탐색 8회를 완료했습니다.
  처음에는 `843 ms`인 `narrator-gpt-5-mini`를 선택했고 다른 값은 `1288`, `1517`, `2086 ms`였습니다.
  세 번째와 네 번째 주기에서는 가장 빠른 후보가 `gpt-4.1-mini`로 바뀌었으며, 이 모델의 마지막
  관측 p50은 약 `1068 ms`였습니다. 합성 탐색 처리 시간이지 전체 턴의 속도나 품질은 아닙니다.
- **인증된 화면 표현:** 일반 대화와 화면 맥락 대화의 Console DOM 배지 및 도구 설명이 바뀐 선택과
  측정값에 일치했습니다. Electron 숨김 상태로 화면 이미지 및 포인터 검증은 여전히 제한되며,
  시각 검사를 통과했다고 주장하지 않습니다.
- **런타임 출처:** Operator는 기존 커밋 `9ed204592`에 이 작업 소유 상태 파일 5개만 더한
  격리 작업 트리에서 실행했으며, 그 환경의 집중 검사 `152`개가 통과했습니다. `auth.py`는 해당
  기준 커밋과 같았습니다. 공유 작업 트리의 무관한 `auth.py` 변경은 `idtyp`이 없는 기존 토큰을
  거부하며, 이번 작업은 그 소스를 수정하지 않았습니다. 격리 환경 결과는 미커밋 변경이 있는 전체
  작업 트리를 검증하지 않습니다. 이번 작업에서는 커밋하거나 푸시하지 않았습니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| Core mini 라우팅 및 턴별 모델 선택 | implemented | `services/core-control-plane/src/fdai/delivery/azure/llm/t1_latency.py`; `services/core-control-plane/src/fdai/composition/wire_t1_routing.py`; `wire_adaptive_conversation.py`; [집중 검사 근거](#로컬-mini-라우팅-근거-2026-09-06) | Python 229개 통과, PostgreSQL 사례 2개 실행 제외이며 명시적 활성화 구성 검사 6개도 추가로 통과했습니다. 검증된 mini 신원, 변경 불가능한 작성/검토 모델 선택 및 기존 T2/작업 품질 검사 연결을 유지합니다. |
| Core가 관리하는 명시적 선택형 탐색 | implemented | `services/core-control-plane/src/fdai/delivery/azure/llm/t1_probe.py`; `services/core-control-plane/src/fdai/runtime/bootstrap_tasks.py`; [집중 검사 및 로컬 근거](#로컬-mini-라우팅-근거-2026-09-06) | 집중 검사를 통과했습니다. 예정된 주기 4회에서 가장 빠른 후보의 변경을 관측했으며 발행에도 주기 한도를 적용합니다. 합성 처리 시간은 전체 턴의 속도 개선을 입증하지 않습니다. |
| 의미 처리 상태의 라우팅 변환 결과 및 Console 배지 | implemented | `services/operator-service/src/fdai_operator_service/families/conversation/t1_model_health.py`; `console/src/deck/backend-health.ts`; `console/src/deck/use-deck-backend-health.ts`; [근거의 범위](#로컬-mini-라우팅-근거-2026-09-06) | 최종 Console 160개는 앞선 147/48개 집합과 중복되며 최종 타입 검사/빌드도 통과했습니다. 격리된 Operator는 152개 통과했습니다. 일반/화면 맥락 DOM 배지와 도구 설명은 측정값과 일치하지만 시각 및 전체 작업 트리 런타임 검증은 미완료입니다. |
| 합성 대화 및 인라인 프롬프트 확인 | implemented | `mocks/ui/deck-sources-v2.html`; `mocks/ui/incident-conversation.html`; `console/tests/e2e/{adaptive-prompt-mock,deck-adaptive-mock,incident-conversation-mock}.spec.ts`; 집중 Playwright 및 타입 검사 | 시안에만 적용되는 표현입니다. 프롬프트 뷰어는 합성 예제를 읽으며 프로덕션의 수집과 권한 확인은 바꾸지 않습니다. |
| 로컬 정렬 narrator 후보 fallback | implemented | `services/operator-service/src/fdai_operator_service/adapters/local_narrator.py`; `services/operator-service/tests/test_local_narrator.py`; 집중 배포 수명 주기 테스트 | Service 내부 어댑터는 파일 또는 계획에 봉인된 인라인 JSON을 읽고 선택적 배포 SHA를 검증하며, 수명이 짧은 토큰을 얻어 정렬된 후보를 시도하고 Core를 가져오거나 실행 권한을 받지 않은 채 정제된 상태를 노출합니다. |
| 해석된 narrator 후보 수집 | implemented | `services/core-control-plane/tests/rule_catalog/schema/test_narrator_collection.py`; 모델 해석기 및 레지스트리 | Focused 검사는 검토된 모델 해석 입력에서 `narrator_candidates` 수집을 다룹니다. |
| 직접 Key Vault 해석 모델 출처 어댑터 | implemented | `adapters/resolved_models_key_vault.py`; 집중 Operator 테스트 | 비동기 어댑터는 주입된 토큰 공급자와 HTTP 클라이언트를 사용하고 신뢰할 수 없는 origin, redirect, 불일치 secret 신원, 비활성 또는 만료 값, 과도한 크기나 중첩, secret을 포함한 표현을 거부합니다. 시작 조립과 통제된 런타임 근거는 열려 있습니다. |
| 이동 text p50/TTFT, 범위가 제한된 refresh 및 장애 조치 | implemented | `services/operator-service/src/fdai_operator_service/adapters/local_narrator.py`; `narrator_latency.py`; `narrator_payloads.py`; focused Operator 테스트 | 독립 service는 샘플 8개짜리 latency 및 TTFT 창을 유지하고 비어 있지 않은 첫 SSE token을 측정하며 범위가 제한된 probe를 coalescing하고 text 후보를 정렬하며 unanimous 429/503 상태를 보존하고 malformed 또는 oversized 출력을 fail closed로 처리합니다. |
| 기존 서술기의 주기적 갱신 소유자 | implemented | `services/operator-service/src/fdai_operator_service/adapters/narrator_periodic_scheduler.py`; `environment.py`; `composition.py`; 집중 스케줄러 및 조립 테스트 | Operator 수명 주기는 기존 로컬 Azure 서술기에서만 즉시 및 주기적 실행 하나를 소유하며, 의미 Kafka와 함께 실행하지 않습니다. 이 검사는 새 Core mini 탐색 소유자를 검증하지 않습니다. |
| 비전 후보 probe 및 이미지 턴 라우팅 | in-progress | `services/operator-service/src/fdai_operator_service/adapters/local_narrator.py`; focused vision-probe 및 image-unavailable 테스트 | 비전 후보는 독립된 측정 probe 창을 갖습니다. 서버 소유 image resolver가 검증되고 범위가 제한된 byte를 공급할 때까지 이미지 턴은 사용 불가 상태이며 text binding을 빌리지 않습니다. |
| 사용자별 라우팅 선호 설정 및 런타임 지연 시간 변환 결과 | in-progress | `services/operator-service/src/fdai_operator_service/adapters/narrator_preferences.py`; `services/operator-service/tests/test_narrator_preferences.py` | Service-local 개정 번호 기반 저장소는 principal마다 `Auto` 또는 허용된 배포 하나를 유지하고, 임의 모델 id를 거부하며, 오래된 개정 번호에는 충돌을 반환하고, principal을 격리하고, 제거된 배포는 저장된 선택을 버리지 않고 `Auto` 로 저하시킵니다. 정제된 변환 결과는 모드, 개정 번호, 허용 목록, 이동 timing 근거를 endpoint나 credential 없이 노출하며 T2 연결을 개인화하지 않는다고 선언합니다. 영속 저장, 인증된 Settings 경로, 배포 pinning 계약은 남아 있습니다. |
| 환경 T1/T2 바인딩 초안 및 보호된 계획 | implemented | 공통 `ModelBindingPolicy`; Operator IAM 경로 및 PostgreSQL 어댑터; Console 모델 편집기; 보호된 해석기 및 배포 워크플로; 집중 테스트 | Owner 전용 초안은 리비전 및 멱등성 제한과 함께 영속화됩니다. 평가 및 계획 요청에는 권한이 없고 활성 산출물 다이제스트를 결합하며 보호된 배포 워크플로를 통해서만 활성화에 도달합니다. 공급자 및 롤백 증적은 남아 있습니다. |
| 답변 연속성 및 프롬프트 ablation 설정 | implemented | Operator 런타임 설정 경로 및 PostgreSQL 어댑터, Core 시작 스냅샷, 콘솔 런타임 정책, 집중 Core, Operator 및 콘솔 검사 | Owner 변경은 비활성 제안과 리비전으로 보호된 Core 정책 레코드를 하나의 트랜잭션으로 영속화합니다. 두 설정은 재시작 후 적용되고, 프롬프트 ablation은 정보만 줄이며, 연속성은 보류 또는 미지원 표현만 변경합니다. |
| 공개 웹 후보 라우팅 | in-progress | `services/operator-service/src/fdai_operator_service/application/conversation/capabilities/web_search/`; `services/operator-service/src/fdai_operator_service/adapters/conversation/web_search/`; focused Operator 테스트 | 프로바이더 중립 및 Azure 구성 경로가 있습니다. 로컬 및 배포 프로파일의 관리되는 이동 지연 시간 및 장애 조치 근거가 남아 있습니다. |
| 5단계 qualification 지연 시간 계약 | implemented | [`quality_latency.py`](../../../services/core-control-plane/src/fdai/core/conversation_assurance/quality_latency.py), [`chatops_quality_latency.py`](../../../scripts/evaluation/chatops_quality_latency.py), 집중 검사 | 버전이 지정된 계약은 PR 회귀, 라이브 카나리, 릴리스 단계를 분리하고 표본 하한과 p50/p95/p99 상한을 적용하며 콘텐츠가 없는 근거를 생성합니다. 라이브 또는 릴리스 벤치마크 증적을 주장하지 않습니다. |
| 단계 소유자 timing 증적 adapter | implemented | [`quality_latency.py`](../../../services/core-control-plane/src/fdai/core/conversation_assurance/quality_latency.py), 집중 Core 검사 | Adapter는 monotonic 단계 소유자 값에서 기간을 파생하고 설치된 계약과 다른 환경을 차단합니다. Runtime 연결은 미완료 상태입니다. |
| 8단계 상관관계 추적 계약 | implemented | [`quality_trace.py`](../../../services/core-control-plane/src/fdai/core/conversation_assurance/quality_trace.py), [`chatops_quality_trace.py`](../../../scripts/evaluation/chatops_quality_trace.py), 집중 검사 | 축약기는 하나의 correlation digest, 이전 레코드 연결, 권위 있는 타임스탬프, 출처 이력 약속값을 갖는 세션부터 감사까지의 순서가 지정된 연결을 요구합니다. 라이브 완전 추적 증적을 주장하지 않습니다. |
| Timing 근거 연결 | implemented | [`quality_timing.py`](../../../services/core-control-plane/src/fdai/core/conversation_assurance/quality_timing.py), 집중 검사 | 완전한 집합에는 고유 추적 500개 이상이 있어야 하며 latency 산출물의 설치된 계약, 출처 리비전, 추적 수 및 추적 집합 약속값과 정확히 일치해야 합니다. |
| 선택적 report-format parity | implemented | `fdai_operator_service.reporting.optional_pdf_report_encoder`; `IncidentRcaReportingProjectionReader`; Operator composition 및 경로 테스트 | 로컬 및 배포 Operator composition은 같은 service-local loader와 authoritative audit-backed Incident report reader를 사용합니다. Venue, 환경 및 identity는 report 권한을 바꾸지 않습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-09-05 | implemented | 인시던트 및 적응형 답변을 개선하고 완료 후에도 조사 기록을 유지하며, 대화를 막지 않는 인라인 합성 Markdown 프롬프트 보기를 추가했습니다. | `current change`; 위에 나열한 시안 Playwright 파일 세 개의 집중 시나리오, 공용 스타일 검사, Console 타입 검사를 통과했습니다. | 프로덕션 도입에는 별도 검토와 인증 및 권한 범위에 맞는 근거가 필요합니다. 런타임 프롬프트 수집을 구현했다고 주장하지 않습니다. |
| 2026-09-02 | implemented | T2를 개인화하거나 작업 권한을 부여하지 않으면서 리비전으로 보호된 답변 연속성 및 프롬프트 ablation 설정, 시작 시 일관된 Core 스냅샷, 지역화된 콘솔 control을 추가했습니다. | `current change`, 프롬프트 조립 구현 기록의 집중 Core, Operator 및 콘솔 검사입니다. | 런타임 검증을 주장하기 전에 통제된 shadow 캠페인을 보존합니다. |
| 2026-08-28 | implemented | Benchmark 기간을 호출자가 작성하지 못하게 하고 PR/카나리/릴리스 환경 불일치를 차단하는 단계 소유자 증적 adapter를 추가했습니다. | `current change`; 집중 Core latency 검사(`8 passed`); Ruff 및 strict mypy. | 권위 있는 단계 소유자에 증적을 연결하고 통제 근거를 보존해야 합니다. |
| 2026-08-28 | implemented | Qualification timing 상태를 파생하기 전에 latency 산출물과 완전 추적 집합을 연결했습니다. | `current change`; 집중 연결 검사(`4 passed`); 결합 latency/trace/timing 검사(`23 passed`). | Runtime 생산자를 연결하고 일치하는 통제 근거 집합 하나를 보존해야 합니다. |
| 2026-08-28 | implemented | 8단계 콘텐츠 없는 상관관계 추적 축약기와 `--require-complete` CLI를 추가했습니다. | `current change`; 집중 Core 및 CLI 검사(`8 passed`); Ruff 및 strict mypy. | 권위 있는 레코드 생산자를 연결하고 완전한 PR/카나리/릴리스 추적 증적 하나를 보존해야 합니다. |
| 2026-08-28 | implemented | 5단계 `chatops-latency-v1` SLO 계약, 결정론 백분위수 축약기 및 콘텐츠가 없는 벤치마크 CLI를 추가했습니다. | `current change`; 집중 Core 및 CLI 검사(`11 passed`); Ruff 및 strict mypy. | 지연 시간 qualification을 주장하기 전에 권위 있는 단계 생산자를 연결하고 PR/카나리/릴리스 증적을 보존하며 완전한 상관관계 추적을 검증해야 합니다. |
| 2026-08-14 | in-progress | 구현 ledger를 도입하고 어떤 지연 시간 및 선호 설정 동작이 대상 설계로 남는지 명확히 했으며 이전 출처 이력은 재구성하지 않았습니다. | `current change`; 구현 범위 표에 나열된 현재 로컬 narrator, 해석기, 웹 검색 source 및 focused 검사입니다. | 독립 service 지연 시간 창과 선호 설정을 구현한 뒤 관리되는 로컬 및 배포 근거를 보존해야 합니다. |
| 2026-08-14 | implemented | 로컬 및 배포 Operator composition에서 선택적 PDF report 등록을 동일하게 유지했습니다. | `current change`; service-local optional loader, package-extra 계약, composition binding 및 focused 경로/composition 테스트입니다. | Package availability를 실행 권한으로 취급하지 않고 별도의 인증된 Incident report 증적을 보존해야 합니다. |
| 2026-08-14 | implemented | 로컬 및 배포 Operator composition에서 authoritative Incident RCA report materialization을 동일하게 유지했습니다. | `current change`; service-local audit-backed report reader, composition binding 및 focused reader/family 테스트입니다. | 별도의 인증된 Incident report 증적을 보존해야 합니다. |
| 2026-08-14 | implemented | 범위가 제한되고 coalescing된 text 및 vision probe, 측정된 장애 조치, 엄격한 SSE 및 출력 제한, 범위가 제한된 Azure CLI credential 획득을 갖춘 service-local 이동 text latency 및 TTFT 라우팅을 추가했습니다. | `current change`; narrator adapter 모듈; focused local narrator 및 credential 테스트 `21 passed`; 통합 Operator 및 Core narrator 검사가 통과했습니다. | 주기적 refresh와 서버 소유 image resolver를 binding한 뒤 관리되는 local 및 deployed timing 근거를 보존합니다. |
| 2026-08-14 | implemented | 검증된 interval 구성, 실패 격리, duplicate-start 억제 및 종료 cleanup을 갖춘 하나의 즉시 및 주기적 narrator refresh loop를 Operator lifecycle에 binding했습니다. | `current change`; scheduler, environment, composition, local narrator cleanup 및 focused 테스트 `66 passed`. | 서버 소유 image resolver를 binding하고 관리되는 local 및 deployed timing 근거를 보존합니다. |
| 2026-08-16 | in-progress | 개정 번호 기반 principal별 narrator 선호 설정 저장소와 정제된 Settings 변환 결과를 추가했습니다. `Auto` 와 허용된 배포만 허용하고, 오래된 개정 번호는 충돌하며, principal은 격리되고, 제거된 배포는 저장된 선택을 유지한 채 `Auto` 로 저하됩니다. T2 연결은 개인화되지 않습니다. | `current change`; `services/operator-service/src/fdai_operator_service/adapters/narrator_preferences.py`; `pytest services/operator-service/tests/test_narrator_preferences.py` (14 passed). | 영속 저장과 인증된 Settings 경로를 binding한 뒤 관리되는 timing 증적을 보존합니다. |
| 2026-08-19 | implemented | 보호된 해석기의 정확한 인라인 JSON과 SHA를 Operator 시작에 연결하고 제안 전용 주간 조정기를 추가했습니다. 다이제스트가 다르면 서술기 구성을 차단하며, 공급자 실패는 정제된 판단 보류를 만들고 PR을 열지 않습니다. | `current change`; 집중 서술기, 수명 주기, 계획 검증기, Terraform 및 권한 workflow 테스트. | 통제된 로컬/배포 timing 및 조정기 실행 근거를 보존하며 직접 Key Vault 읽기는 계속 연기합니다. |
| 2026-08-23 | implemented | 해석 모델 JSON을 위한 서비스 소유 비동기 Key Vault 출처 어댑터를 추가했습니다. 어댑터는 토큰 및 HTTP 공급자를 주입 상태로 유지하고, 일치하는 cloud audience를 가진 현재 Azure Key Vault DNS suffix만 허용하며, 응답 신원을 요청한 secret 및 버전에 결합하고, 하나의 전체 마감 안에서 실패 시 차단 처리합니다. | `current change`; 집중 Key Vault 출처 테스트와 15회의 비평 및 하드닝 라운드입니다. | 현재 파일 또는 인라인 출처를 교체하기 전에 비동기 시작 소유자, 변경 불가능한 출처 개정 발행, Core/Operator parity 바인딩 및 통제된 로컬/배포 근거를 추가합니다. |
| 2026-08-24 | implemented | 프로비저닝된 SKU와 PTU 용량, 정확한 활성 다이제스트 제한, 분리된 초안, 평가 및 보호된 계획 요청을 포함해 T1/T2 `auto`, `pinned`, `hil-only` 모드를 위한 환경 전체 정책 편집기를 추가했습니다. | `current change`; 공통 계약, Operator 경로 및 저장소, Console 정책 편집기, 해석기, 워크플로 및 Terraform 검사. | 보호된 공급자 평가, 적용, 독립 검증 및 롤백 증적을 보존합니다. |
| 2026-09-05 | implemented | 서비스 소유 출처를 Operator 애플리케이션 수명 주기의 첫 위치에 연결했습니다. 이 소유자는 한 번만 로드하고 JSON을 검증하며 `LLM_RESOLVED_MODELS_SHA256` 불일치를 거부한 뒤 후속 서비스를 시작합니다. 직접 Key Vault는 배포 출처 seam으로 유지하고 구성된 파일 또는 인라인 콘텐츠는 로컬 호환성을 보존합니다. | `current change`; 집중 Operator 운영 조립 및 Key Vault 출처 테스트입니다. | 정확한 출처 리비전에 대한 통제된 배포 시작 영수증 하나를 보존합니다. |
| 2026-09-06 | in-progress | Core 소유의 명시적 선택형 mini 탐색, 최신성을 반영한 라우팅, 변경 불가능한 턴별 독립 검토, 읽기 전용 Operator/Console 상태 변환 결과를 기존 서술기와 구분해 정의했습니다. | `current change`; 새 구현 범위 세 행의 소스 경로와 이 이중 언어 설계 변경입니다. 집중 구현 및 문서 검증은 아직 완료되지 않았으며, 커밋이나 런타임 증적은 주장하지 않습니다. | 한도, 실패, 턴별 격리, 변환 결과 검증 및 표시 중 상태 갱신을 입증하고, 대화가 빨라졌다고 주장하기 전에 승인된 측정을 보존합니다. |
| 2026-09-06 | implemented | T2와 독립 검토를 유지하면서 mini 라우팅, 한도 있는 탐색, 상태 변환 결과 및 배지 최신성/숨겨진 브라우저 처리를 완료했습니다. | `current change`; [범위가 제한된 근거](#로컬-mini-라우팅-근거-2026-09-06): Python 229개 통과, PostgreSQL 사례 2개 실행 제외, 중복되는 Console 검사 집합 각각 147개와 48개 통과, 타입 검사/빌드 통과, 격리된 Operator 152개 통과, 예정된 mini 탐색 8회 및 인증된 DOM 표시 확인입니다. | PostgreSQL, 통합 런타임 및 표시되는 브라우저의 근거를 완료합니다. 전체 턴의 속도 개선, 시각 검사 통과, 새 커밋 또는 푸시된 리비전은 주장하지 않습니다. |
| 2026-09-06 | implemented | 변환 결과 발행을 35초 주기에 포함하고 별도의 5초 쓰기 한도를 적용했으며 발행은 재시도하지 않습니다. | `current change`; 명시적 활성화 구성 검사 6개와 최종 Console 160개/타입 검사/빌드를 통과했습니다. 세 번째/네 번째 예정 주기에서 가장 빠른 mini가 바뀌었고 인증된 일반/화면 맥락 DOM 배지와 도구 설명이 일치했습니다. Console 검사 집합은 중복됩니다. | PostgreSQL, 통합 런타임, 화면 이미지/포인터 검증 및 전체 턴 비교는 남아 있습니다. 약 1068 ms인 합성 p50은 대화 속도 개선 주장이 아닙니다. |

### 남은 작업

- [x] 집중 Python 라우팅/탐색 검사 229개 통과와 PostgreSQL 사례 2개 실행 제외를
  [로컬 근거](#로컬-mini-라우팅-근거-2026-09-06)에 기록했습니다.
- [x] 추가 명시적 활성화 구성 검사 6개, 최종 Console 160개/타입 검사/빌드 통과를 기록했습니다.
  앞선 147/48개 집합과 중복됩니다. 격리된 Operator 검사 152개도 통과했습니다.
- [x] Core의 예정된 주기 4회와 가장 빠른 mini의 변경을 관측했고, T2 없이 인증된 일반 및
  화면 맥락 DOM 배지와 도구 설명이 합성 측정값에 일치함을 확인했습니다.
- [ ] 실행 대상에서 제외한 PostgreSQL 사례 2개를 완료하고 조정된 단일 소스 스냅샷의 통합 런타임
  근거를 보존합니다. 격리된 Operator 결과는 무관한 인증 변경을 검증하지 않습니다.
- [ ] 화면에 표시되는 브라우저에서 모델 배지와 도구 설명을 화면 이미지 및 포인터 검사로
  검증합니다. 숨겨진 Electron의 DOM 근거만으로는 시각적 수락 조건을 충족하지 않습니다.
- [ ] 실제 지연 시간 개선을 주장하기 전에 명시적으로 승인된 한도 있는 대화 비교를 보존합니다.
  합성 `OK` 처리 시간만으로는 충분하지 않습니다.
- [x] 위의 집중 Playwright 파일 세 개에서 시안 전용 대화 및 인라인 프롬프트 시나리오를 검증했습니다. 프로덕션 도입은 이번 변경 범위에 포함하지 않습니다.
- [x] 독립 텍스트 및 비전 후보 탐색, 별도 이동 지연 시간 및 TTFT 창, 범위가 제한된 갱신, 장애 조치 및 사용 불가 동작을 구현하고 focused 테스트를 추가합니다.
- [x] 검증된 interval, 실패 격리, duplicate-start 억제 및 종료 cleanup을 갖춘 주기적 refresh owner를 binding합니다.
- [ ] 이미지 턴 라우팅을 완료로 표시하기 전에 서버 소유 conversation-image resolver를 binding합니다.
- [x] 개정 번호 기반 principal별 `Auto` 또는 허용된 narrator 선호 설정 저장소와 정제된 Settings 변환 결과가 `services/operator-service/src/fdai_operator_service/adapters/narrator_preferences.py` 에 있으며 `pytest services/operator-service/tests/test_narrator_preferences.py` (`14 passed`) 가 이를 증명합니다. 변환 결과는 `personalizes_t2_bindings: false` 를 선언하고 endpoint나 credential 자료를 담지 않습니다. 영속 저장과 인증된 Settings 경로는 남아 있습니다.
- [ ] Narrator 선호 설정 저장소를 principal별 영속 저장과 인증된 Settings 경로에 binding하고, 그 경로를 통해 개정 번호 충돌과 principal 범위를 증명합니다.
- [ ] Narrator 및 웹 검색 후보 선택, 첫 토큰 시간, 실패, 복구 및 정제된 상태에 대한 관리되는 로컬 및 배포 증적을 보존합니다.
- [x] 신뢰할 수 있는 origin, 신원, 범위, 만료, timeout 및 secret-redaction 검사를 갖춘 service-owned 비동기 직접 Key Vault 모델 해석 결과 출처 어댑터를 구현하고 집중 테스트합니다.
- [x] 비동기 Operator 시작 소유자를 통해 Key Vault 출처를 연결하고, Core가 자체 리비전을 수명 주기 보류 평가 및 기능 바인딩과 공유하는 동안 Core/Operator 출처 리비전 parity를 보존합니다.
- [x] 시작 실패 시 획득한 모든 수명 주기 서비스의 정리를 시도하고 원래 출처 리비전 경계를 숨기지 않은 채 정리 실패를 보고합니다.
- [ ] 통제된 제안 전용 조정기 실행 하나와 정확한 출처 리비전에 대한 배포 Operator 시작 영수증 하나를 보존합니다.
- [ ] 런타임이 봉인된 정책과 모델 버전을 로드했음을 독립 검증하는 근거를 포함해 정확한 환경 정책 평가 및 보호된 PTU 계획, 적용, 롤백 캠페인 하나를 보존합니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| T1/T2 기능과 품질 게이트 정책 | [LLM 전략](../architecture/llm-strategy-ko.md) |
| Operator API 런타임 모델과 의존성 주입 경계 | [오퍼레이터 콘솔 런타임 모델](operator-console-runtime-model-ko.md) |
| 로컬 및 배포 환경의 모델 해석 | [개발과 배포의 동등성](../deployment/dev-and-deploy-parity-ko.md) |
