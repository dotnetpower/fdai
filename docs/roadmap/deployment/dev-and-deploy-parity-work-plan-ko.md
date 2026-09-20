---
translation_of: dev-and-deploy-parity-work-plan.md
translation_source_sha: c68196015901aa86133311dff6611f443e4d4e63
translation_revised: 2026-09-20
---

# 개발 및 배포 동등성 작업 계획

이 문서는 로컬 및 배포 실행 프로필의 동등성을 유지하기 위한 단계별 구현 계획을 담당합니다. 상위 문서는 동등성 계약, 감사, 검증 게이트를 유지합니다.

## 설계 개요

이 문서는 [dev-and-deploy-parity-ko.md](dev-and-deploy-parity-ko.md)에 포함되어 있던 상세 계약을 그대로 보존하는 집중 소유 문서입니다.

## 작업 계획 (phased, 가산)

각 단계는 헤드에서 빌드/테스트 가능한 상태 유지. 멀티 클라우드는 **TBD**
([copilot-instructions § 구현 Focus](../../../.github/copilot-instructions.md#implementation-focus-must)).

**2026-07-21 기준 상태**: W-A에서 W-G까지 **배포됨**; W-H (문서 동기화)는
이 문서 초안과 함께 배포된 상태; W-I (매주 조정기 작업)는 연기. 각 작업 항목은
실제 럭딩된 범위(코드, 테스트, 게이트 커버리지)를 반영.

### W-A: LLM용 구성 스키마 + dev-mode 플래그 ✅  *(기준선, 배포)*

- `services/core-control-plane/src/fdai/shared/config/schema.json` + `models.py` 에 `LlmConfig` 추가:
  - `mode`: `local-fake` | `azure`. `local-fake`는 명시적 테스트/mock 연결이며 배포
    환경이 선택하지 않습니다.
  - `resolved_models_path`: 옵셔널 KV 시크릿 이름 또는 파일시스템 경로.
  - `capabilities`: 기능 이름 리스트 (`t1.embedding`, `t1.judge`,
    `t2.reasoner.primary`, `t2.reasoner.secondary`) - 레지스트리를 미러.
  - `t2_primary_latency_routing`: bool, 기본값 `true`. T2 기본
    제안자를 동일 발행기 후보 풀 내에서 지연 라우팅(invariant-safe;
    강제 적용 on). 리졸버가 >= 2 풀 을 발행(`--emit-primary-pool`) 할 때만
    적용; 단일 기본 로 pin 하려면 `false`.
    [llm-strategy-ko.md](../architecture/llm-strategy-ko.md) 의
    "T2 기본 지연 시간 풀" 참조.
- Fail-fast 검증기: `mode == "azure"` 는 `resolved_models_path` 필수.
- 테스트: 스키마 + pydantic 검증기.

### W-B: `rule-catalog/llm-registry.yaml` + 스키마 ✅ *(catalog-as-code, 배포)*

- 신규 파일: 업스트림 기본값 있는 `rule-catalog/llm-registry.yaml` (mini → Opus 계층).
- JSON 스키마: `rule-catalog/schema/llm-registry.schema.json`.
- Python 로더: `fdai.rule_catalog.schema.llm_registry` - 다른 곳에서 쓰는 aggregating
  fail-close 패턴 사용 (`exemption.py` 참고).
- 테스트: 스키마 검증, mixed-model 불변식 체크.

### W-C: 초기화 해석기 CLI ✅ *(배포자-스코프, 배포)*

- 신규: `services/core-control-plane/src/fdai/rule_catalog/schema/llm_resolver_cli.py`.
- 입력: `--registry`, `--region`, `--subscription-id`, `--dry-run`, `--out`.
- 기본 고정본 모드는 카탈로그/권한/할당량 JSON 세 개를 요구해 offline CI를 지원합니다.
- `--use-azure-cli` 모드는 기존 `az login` 맥락과 선택적 `AZURE_CONFIG_DIR`을 사용해
  모델 카탈로그, 역할 배정, 사용량/할당량, 프로비저닝된 용량을 읽기 전용 조회합니다.
- `resolved-models.json` 발행 (또는 `--dry-run` 은 stdout).
- [배포자-스코프 LLM 프로비저닝](#배포자-스코프-llm-프로비저닝) 의 모든 체크 강제.
- 테스트: 두 SDK 클라이언트 mock; precedence + mixed-model 불변식 + `hil-only` 대체 경로 +
  동일 입력 멱등적 출력 assert.

### W-D: Azure OpenAI Terraform 모듈 + preflight ✅ *(infra, 배포)*

- 신규: `infra/modules/llm/azure-openai/`.
  - `main.tf`: `azurerm_cognitive_account` (종류=`OpenAI`) + 입력 변수의
    `resolved_capabilities` 로부터 N개 `azurerm_cognitive_deployment`.
  - `variables.tf`: `enable_llm` (기본값 `false` - 최소 배포도 성공하도록), `resolved_capabilities` (해석기로부터의 객체 목록), Azure OpenAI와 partner Foundry account가 공유하는 명시적 `llm_public_network_access_enabled` 선택 항목을 제공합니다. 공용 액세스는 기본적으로 비활성화됩니다. 직접 공개 개발 래퍼는 배포 소유 model endpoint에서 이를 활성화하며, 보호된 환경은 기본 거부 network ACL과 명시적 신뢰 원본 규칙을 유지하는 것이 좋습니다. 모든 모드에서 key 인증은 비활성화됩니다.
  - `outputs.tf`: `endpoint`, `deployments` 지도, `resource_id`.
- 역할 배정: 실행기 MI → 계정의 `Cognitive Services OpenAI User`.
- 루트 `infra/main.tf` 에서 `var.enable_llm` 조건부로 모듈 wire.
- `infra/README.md` 갱신: 해석기 먼저 → `enable_llm=true` 로 `terraform apply`.

### W-E: Azure OpenAI 어댑터 클래스 ✅ *(전달, 배포)*

- `services/core-control-plane/src/fdai/delivery/azure/llm/embeddings.py` - `EmbeddingModel` 을 구현하는
  `AzureOpenAIEmbeddingModel`, injected 비동기 `httpx` + `WorkloadIdentity`.
- `services/core-control-plane/src/fdai/delivery/azure/llm/cross_check.py` - `CrossCheckModel` 구현
  `AzureOpenAICrossCheckModel`.
- 타임아웃, retry-after honouring, 구조화된 출력 (`response_format={"type":"json_object"}`)
  - [llm-strategy.md § 프로바이더 Abstraction](../architecture/llm-strategy-ko.md#provider-abstraction) 참조.
- 테스트: `httpx.MockTransport` + 녹화 고정본 - 라이브 네트워크 없음.

### W-F: Composition-root 배선 ✅ *(연결, 배포)*

- `Container` 확장: `embedding_model: EmbeddingModel`, `cross_check_models`,
  `verifier_policy`, `grounding_source` 필드.
- `default_container(config)`는 `local-fake`에 결정론적 연결을 넣고 `azure`에는
  아직 연결되지 않은 컨테이너를 반환합니다. 런타임 초기화가
  `bind_azure_llm_bindings`/`wire_azure_container`를 호출해 `resolved-models.json`을 로드하고
  기능별 어댑터를 연결합니다. 누락 항목은 fail fast합니다.
- 테스트: 양쪽 가지; `local-fake` 가 `delivery.azure.llm` 을 가져오기 안 함 assert.

### W-G: 고정본 신원 + 시크릿 + 인벤토리 어댑터 ✅ *(테스트 지원, 배포)*

- `shared/providers/testing/` 의 `EnvSecretProvider` (dev 사용 반영해
  `shared/providers/local/` 로 이름 변경).
- `LocalWorkloadIdentity` - 고정본 어댑터만 수락하는 인-메모리 OIDC 토큰을 발급합니다.
  Interactive 로컬은 이를 Thor 신원으로 사용하지 않습니다.
- `FileFixtureInventory` - 포크 가 생성자에 넘긴 어떤 YAML 고정본 든 (`fixture=Path(...)`) 에서 `Resource` 레코드를 읽는다. 업스트림은 시드 고정본 를 배송하지 않으며, 권장 컨벤션은 `services/core-control-plane/tests/scenarios/inventory/*.yaml` (고정된 시나리오 재생 옆) 이라 verticals 가 ARG 없이 예행 실행 가능.
- 테스트 + docstring이 정확한 fork-side 패턴 시연.

### W-H: 문서 동기화  *(이 단계)*

- ✅ 이 문서 자체.
- [deploy-and-onboard.md § 런타임 구성 매트릭스](deploy-and-onboard-ko.md#runtime-configuration-matrix)
  에 `LLM_MODE`, `LLM_RESOLVED_MODELS_PATH` 추가.
- [deploy-and-onboard.md § Azure Resource 인벤토리](deploy-and-onboard-ko.md#azure-resource-inventory-minimum-set)
  에 행 11 (Azure OpenAI, 명시적 선택) 추가.
- [tech-stack.md § 로컬 개발](../architecture/tech-stack-ko.md#local-development) 에서
  권위 있는 interactive 어댑터와 명시적 고정본을 구분합니다.
- [llm-strategy.md § 초기화 Provisioner](../architecture/llm-strategy-ko.md#bootstrap-provisioner) 를
  배포자-권한 게이트에 대해 이 문서 참조로.

### W-I: 조정기 weekly 작업  *(later 단계 - deferred)*

Future 작업으로 유지. 전체 설계는 이미
[llm-strategy.md § 조정기 작업](../architecture/llm-strategy-ko.md#reconciler-job) 에 있음;
`infra/modules/compute/container-apps-job/` 재사용 + Python 엔트리로 shipping.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 상위 설계 | [개발 및 배포 동등성](dev-and-deploy-parity-ko.md) |
| 제공 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/deployment/dev-and-deploy-parity-work-plan.md) |
