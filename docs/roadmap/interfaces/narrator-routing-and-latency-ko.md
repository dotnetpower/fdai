---
title: Narrator Routing and Latency
translation_of: narrator-routing-and-latency.md
translation_source_sha: 640dd3817882fa2e37417c9d66386b6118a6e22a
translation_revised: 2026-08-07
---
# Narrator Routing and Latency

이 문서는 presentation narrator의 deployment 선택, latency 측정, operator preference 및 public-web
pool 동작을 소유합니다. T1 narration과 system-governed T2 reasoning의 경계를 유지합니다.

## Narrator latency routing

Console chat backend
(`fdai.delivery.operator_api.application.conversation.backend.LatencyRoutedChatBackend`)는 `t1.judge`
mini-stack deployment를 감싸고 각 turn에서 rolling p50 latency가 가장 낮은 후보를 선택합니다.
`resolved-models.json`에 `narrator_candidates`가 두 개 이상 있으면 활성화되고, 하나만 있으면
vision routing에 one-candidate latency wrapper가 필요하지 않은 한 `AzureAdChatBackend`를 직접
사용합니다. Concrete Azure 및 OpenAI-compatible transport는
`fdai.delivery.operator_api.adapters.conversation` 뒤에 있습니다.

Router는 T1 narrator traffic 전용입니다. T2 capability로 latency routing을 확장하려면 별도 설계
검토가 필요합니다. `t2.reasoner.primary` slot의 검토된 same-publisher 예외는
[LLM strategy](../architecture/llm-strategy-ko.md#t2-primary-latency-pool-invariant-safe-opt-in)가
소유합니다. 다음 두 제약이 경계를 유지합니다.

- **Mixed-model invariant**: `t2.reasoner.primary.publisher`와
  `t2.reasoner.secondary.publisher`는 달라야 합니다. Pair 전체를 속도로 routing하면 필수
  cross-check가 하나의 model family로 축소될 수 있습니다.
- **Judge 및 critic determinism**: composition은 `t1.judge`, `t2.critic`, debate orchestrator를
  configured deployment에 bind합니다. Runtime routing wrapper가 이 binding을 조용히 바꾸지 않습니다.

Latency-routed judge가 필요한 fork는 자체 quality gate, composition binding, audit evidence가 있는 별도
capability를 선언합니다.

Operator API는 operator traffic과 독립적으로 text 및 multimodal pool을 갱신합니다. Text는
`narrator_candidates`를 사용하고 image turn은 provisioned deployment와 `t1.vision` preference의
교집합을 `vision_candidates`로 내보냅니다. 각 pool은 별도 8-sample latency 및 time-to-first-token
(TTFT) window를 유지합니다. Startup은 text 후보를 두 번, vision 후보는 bounded 1 px image로
probe합니다. Periodic check는 기본값 `300`인 `FDAI_NARRATOR_PROBE_INTERVAL_SECONDS`마다 sample을
추가합니다. Vision capacity가 없으면 text binding을 빌리지 않고 image turn을 unavailable로 유지합니다.

## 사용자별 preference 및 TTFT

Settings > Models는 endpoint 또는 credential 없이 resolved T1/T2 inventory, bootstrap state 및 runtime
latency evidence를 projection합니다. 인증된 principal은 `Auto` routing을 사용하거나 현재 narrator
allowlist의 deployment 하나를 선택할 수 있습니다. 제거되거나 unavailable인 preference는 `Auto`로
fallback하고 server는 임의 model id를 차단합니다.

Preference는 explicit revision을 사용합니다. 생성은 revision `0`을 보내고 이후 write는 current
revision과 일치해야 합니다. State와 audit은 하나의 transaction에서 commit되므로 concurrent session은
서로 덮어쓰지 않고 `409`를 받습니다.

Streaming router는 첫 non-empty model token이 도착할 때 TTFT를 기록합니다. TTFT p50/p95와 total
latency p50/p95는 별도 rolling window와 sample count를 사용합니다. 측정되지 않은 TTFT는 unavailable로
유지합니다. Preference는 T1 narrator에만 적용됩니다. T1 internal judgment, embedding 및 모든 T2
secondary, critic, rubric, escalation assignment는 system-governed 상태를 유지합니다. T2 primary pool은
operator별로 개인화되지 않습니다.

Settings > Models는 T2 model-policy draft builder도 제공합니다. Operator API는
`rule-catalog/llm-registry.yaml`의 publisher 및 family preference만 projection합니다. Operator는
publisher가 다를 때만 primary 및 secondary 후보를 선택하고 governance PR용 validated YAML fragment를
복사할 수 있습니다. Browser는 선택을 runtime state에 쓰지 않습니다. Active pair는 catalog review,
resolver regeneration 및 deployment reload 이후에만 변경됩니다.

Local operator mode는 Azure CLI session에서 regional GPT catalog, subscription quota 및 existing
deployment를 결합할 수 있습니다. Async reader는 결과를 5분 동안 cache하고 explicit read-only refresh를
제공합니다. Family, version, lifecycle, supported SKU, available quota 및 deployment name만 반환합니다.
Deprecated chat, codex 및 realtime family는 새 T2 role 후보로 제공하지 않습니다. 모델 선택은 governance
draft를 만들 뿐 Azure를 변경하지 않습니다.

같은 page는 capability, provider, direct 또는 APIM route, API style, deployment, family, capacity,
feature, discovery source 및 verification time을 포함한 sanitized endpoint inventory를 projection합니다.
Endpoint reference, auth audience, resource digest, URL 및 credential은 제외합니다. Endpoint 등록, APIM
변경, resize, image 변경 및 T2 role assignment는 deployment 또는 catalog workflow로 유지됩니다.

## 대화형 web-search latency pool

Public-web lookup은 별도 Chat T2 tool invocation이며 T1 judgment나 action quality-gate pair가 아닙니다.
활성화하면 Azure Responses `WebSearchProvider`가 별도 `web_search_candidates` function-calling
pool을 사용하고 rolling p50이 가장 낮은 후보를 선택하며 나머지 후보로 failover합니다.
Deterministic web-search policy가 provider 호출 전에 turn을 승격합니다.

Local 및 deployed Operator API composition은
`application.conversation.capabilities.web_search`의 동일한 provider-neutral resolver를 사용합니다.
Environment loading, resolved-model candidate selection 및 Azure construction은
`adapters.conversation.web_search`에 유지합니다. Resolver는 server-owned allowlist와 injected provider만
받으며 operator text는 endpoint, deployment, credential 또는 provider scope를 선택할 수 없습니다.

Web-search pool은 같은 warm-up 및 periodic measurement pattern을 사용합니다. Periodic probe는
`web_search` tool 없이 minimal model response를 요청하고 실제 search는 end-to-end latency를 같은
window에 추가합니다. `FDAI_WEB_SEARCH_PROBE_INTERVAL_SECONDS`는 기본 `300`이며 `30` 미만을 허용하지
않습니다.

Settings > Models는 Owner에게 deployment-wide web-search enablement 및 exact-host allowlist를
제공합니다. Write는 같은 revisioned state-and-audit transaction을 사용하고 commit 후 live resolver를
갱신합니다. Registered resolver가 없으면 projection은 unavailable을 보고하고 write는 persistence 전에
`503`을 반환합니다. Configuration default만으로 provider availability를 증명하지 않습니다.

Page는 generated resolved-model snapshot의 sanitized filename, `kind=generated-file`, UTC modification
time을 `as_of`로 보고합니다. Full local path는 반환하지 않습니다. Discovery 및 provisioning label은
configured behavior를 설명할 뿐 freshness evidence를 대체하지 않습니다.

## Runtime delivery 결정

- **Resolved model delivery**: Day zero는 filesystem path 또는 inline JSON environment/secret reference를
  지원합니다. Direct Key Vault loader는 reconciler 작업과 함께 연기됩니다.
- **Local model fixture**: Ollama 또는 LM Studio fixture는 현재 포함하지 않습니다. 추가하더라도 explicit
  model binding이며 interactive local profile을 다시 정의하지 않습니다.
- **Reconciler alert**: 현재 Teams를 가정하며 reconciler 구현 시 확정합니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| T1/T2 capability와 quality-gate policy | [LLM strategy](../architecture/llm-strategy-ko.md) |
| Operator API runtime model과 DI seam | [Operator Console runtime model](operator-console-runtime-model-ko.md) |
| Local 및 deployed model resolution | [Dev and deploy parity](../deployment/dev-and-deploy-parity-ko.md) |
