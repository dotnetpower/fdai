---
title: Fork Seam Recipe 조리서
translation_of: downstream-fork-seam-recipes.md
translation_source_sha: a1bf6836eeebe129b02fc043bbb0696f154205a3
translation_revised: 2026-08-11
---

# 포크 경계 Recipes

다운스트림 FDAI 포크를 위한 per-seam 조리서. 각 항목은 동일한 형태를
따릅니다: **언제 재정의**, **경계**, **바인딩 방법**, **테스트
방법**. 모든 스니펫은 Python 3.12+와 업스트림 패키지가 `fdai`로 가져오기
가능하다고 가정합니다.

이 파일은 [downstream-fork-guide-ko.md](downstream-fork-guide-ko.md)
의 동반 문서 - 허브 파일이 포크 모델, Day-1 체크리스트, one-hard-rule,
repo 레이아웃, 업스트림 sync, anti-pattern을 소유합니다. 그 허브를 먼저
읽지 않았다면 거기서 시작하세요 - 아래 recipe들은 포크의 조립
루트와 repo 레이아웃이 이미 그 가이드를 따르고 있다고 가정합니다.

이 recipe들을 stitch해서 **비즈니스-오브젝트 버티컬을 처음부터**
붙이는 walkthrough는
[downstream-fork-example-vertical-ko.md](downstream-fork-example-vertical-ko.md)
참조.

### 5.1 Azure OpenAI 어댑터 (LlmBindings)

**언제 재정의**: 다른 Azure OpenAI 엔드포인트, 다른 배포 세트,
또는 비-Azure LLM 프로바이더를 가리킬 때.

**경계**: `fdai.composition.LlmBindings`가 `embedding_model`,
`cross_check_models`, `critic_model`, `judge_model`,
`debate_orchestrator`를 담고 있음. 업스트림 `bind_azure_llm_bindings()`
factory가 `resolved-models.json`을 읽고 Azure OpenAI 어댑터를 wire.

**실제 운영 `resolved-models.json`은 배포 산출물입니다.** 초기화
`llm_resolver_cli`가 생성하며 `LLM_RESOLVED_MODELS_PATH`는 파일 시스템 경로 또는 inline JSON을
받습니다. 실제 운영 결과에는 deployer/구독/배포/지역 출처 이력이 있으므로 포크에
커밋하지 않습니다. 업스트림의 tracked `resolved-models*.json`은 all-zero 신원을 사용하는
synthetic 생성된 기준선이며 hand-edit하지 않습니다. Direct Key Vault 로더는 조정기와
함께 연기됐고, 현재 secretRef env 또는 mounted 파일이 day-zero 전달 방식입니다.

**바인딩 방법 (Azure 엔드포인트 재정의)**:

업스트림이 전체 Azure wire-up을 위한 **공개 조립 API**를
배포: [`wire_azure_container`](../../../services/core-control-plane/src/fdai/composition/__init__.py) +
선언적 [`AzureWireOverrides`](../../../services/core-control-plane/src/fdai/composition/__init__.py)
데이터 클래스. 포크는 구체적인 어댑터로 `AzureWireOverrides` 하나를 만들어
넘기면 됩니다 - 함수가 작성기, 도구 레지스트리, 프롬프트 조립
(base / 비평자 / 판정자), 내부 `bind_azure_llm_bindings()` 호출을 한
단계로 처리.

```python
# fork/composition_root.py
from pathlib import Path
from fdai.composition import (
 AzureWireOverrides, default_container, wire_azure_container,
)
from fdai.core.operator_memory import InMemoryOperatorMemoryStore
from fork.adapters.scope_resolver import resolve_azure_scope

async def build_container(config, *, identity, http_client):
 container = default_container(config)
 return await wire_azure_container(
  container,
  http_client=http_client,
  identity=identity,
  overrides=AzureWireOverrides(
   endpoint="https://oai-customer-x.openai.azure.com",
   catalog_root=Path("rule-catalog"),
   operator_memory_store=InMemoryOperatorMemoryStore(),
   scope_resolver=resolve_azure_scope, # fork 소유 (5.6 참조)
   # tool_providers=... 로 function calling 활성화 (아래)
  ),
 )
```

`AzureWireOverrides`의 `__post_init__`는 빈 `endpoint`나 `None`
`operator_memory_store`에 fail-close - 포크 버그가 첫 이벤트에서
작성기 안쪽에서 드러나는 게 아니라 생성 시점에서 잡힙니다.
Operator 기억을 안 쓰는 포크도 `InMemoryOperatorMemoryStore()`를
명시적으로 전달해야 함 - API가 필수 경계의 기본값 제공을 거부합니다.

**하위 호환성**: 업스트림의 `runtime.configuration._finalize_llm_bindings`는
env var (`FDAI_LLM_ENDPOINT`, `FDAI_CATALOG_ROOT`,
`FDAI_OPERATOR_MEMORY_DSN`)를 읽고 `wire_azure_container`에
위임하는 얇은 래퍼. 기존 테스트와 업스트림 진입점은 변경 없이 계속
작동. Env-driven 배선을 선호하는 포크는 래퍼를 호출; 프로그램적
조립을 원하는 포크는 `wire_azure_container`를 직접 호출.

**바인딩 방법 (비-Azure LLM)**: 네 개 프로토콜 (`EmbeddingModel`,
`CrossCheckModel`, `CriticModel`, `JudgeModel`)을 구현하고
`LlmBindings`를 직접 생성해서 swap:

```python
new_bindings = LlmBindings(
 embedding_model=MyBedrockEmbeddings(),
 cross_check_models=(MyProposer(), MyDoubleChecker()),
)
return replace(container, llm_bindings=new_bindings)
```

**테스트 방법**: 단위 테스트에는 업스트림 in-memory 가짜
(`MatchTypeCrossCheckModel`, `DeterministicEmbeddingModel`) 재사용;
wire-level 검사에는 실제 운영 어댑터를 `httpx.MockTransport`에 대해 실행
(`services/core-control-plane/tests/delivery/azure/llm/test_adapters.py` 참조).

### 5.2 OperatorMemoryStore (in-memory / Postgres / custom)

**언제 재정의**: 배포된 `InMemoryOperatorMemoryStore`에서 지속
스토리지로 전환.

**경계**: `fdai.core.operator_memory.OperatorMemoryStore`
프로토콜 - 세 개의 비동기 메서드: `append`, `list_active_for_scope`,
`supersede`.

**바인딩 방법 (Postgres)**: 환경 변수
`FDAI_OPERATOR_MEMORY_DSN` 설정; 업스트림의
`_build_operator_memory_store()`가 자동으로 `PostgresOperatorMemoryStore`
선택. 코드 변경 불필요.

**바인딩 방법 (커스텀 저장소)**: 프로토콜을 구현하고, 조립 루트에서
인스턴스를 `DefaultPromptComposer(operator_memory_store=...)`에 전달.

**테스트 방법**: 단위 테스트에서 `InMemoryOperatorMemoryStore` 재사용;
커스텀 저장소를 배포하면 `services/core-control-plane/tests/persistence/test_postgres_operator_memory.py`
모양을 미러링 (offline 정책 테스트 + DSN 환경 변수로 gated된 통합
테스트).

### 5.3 HilRejectMaterializer + second-approval 채널

**언제 재정의**: Operator 기억 파이프라인 활성화. Materializer는
업스트림이 배포하는 순수 도메인 모듈; 이를 트리거하는 "second 승인"
채널은 배포마다 UI가 다르므로 (Teams 버튼, git PR, 커스텀 CLI)
fork-first.

**경계**: `fdai.core.operator_memory.HilRejectMaterializer`.
`OperatorMemoryStore`로 생성하고 포크가 사용하는 어떤 채널에서든
`await materializer.materialize(hil_response, second_approver, material)`
호출.

**바인딩 방법 (Teams Adaptive 카드 콜백)**:

Teams 웹훅은 Python `HilResponse` 객체가 아니라 raw JSON을
전달합니다 - 콜백이 materializer 호출 전에 페이로드 필드로부터
응답을 재구성.

```python
# fork/adapters/hil_second_approval.py
from datetime import UTC, datetime

from fdai.core.operator_memory import (
 HilRejectMaterial, HilRejectMaterializer, MemoryCategory, ScopeKind,
)
from fdai.shared.providers.hil_channel import HilDecision, HilResponse

async def handle_teams_approval_click(payload, *, materializer, second_approver_oid):
 hil_response = HilResponse(
  approval_id=payload["approval_id"],
  decision=HilDecision.REJECT,  # 거부된 이유만 materialise
  approver_id=payload["first_approver_oid"],
  received_at=datetime.now(tz=UTC),
  reason=payload["reject_reason"], # upstream에서 pre-redacted
 )
 material = HilRejectMaterial(
  scope_kind=ScopeKind.RESOURCE_GROUP,
  scope_ref=payload["resource_group_ref"],
  category=MemoryCategory.PREFERENCE,
  source_ref=f"hil.reject:{payload['approval_id']}",
 )
 return await materializer.materialize(
  hil_response=hil_response,
  second_approver=second_approver_oid,
  material=material,
 )
```

**테스트 방법**: `InMemoryOperatorMemoryStore` + 합성 `HilResponse`로
`services/core-control-plane/tests/core/operator_memory/test_hil_pipeline.py` 미러링.

### 5.4 WebSearchProvider

**언제 재정의**: 웹 검색 활성화. 업스트림은
`NoOpWebSearchProvider`를 배포하여 모든 쿼리에 zero 스니펫 반환 -
아무것도 하지 않는 포크는 웹 검색이 조용히 비활성화됨.

**경계**: `fdai.core.web_search.WebSearchProvider` 프로토콜 -
하나의 비동기 `search(query) -> WebSearchResult` 메서드.

**바인딩 방법 (Bing 예시)**:

**두 개의 허용 목록이 계층됩니다**: `query.allowed_domains`
(per-event 범위, 호출자 설정)과 `self._deploy_allowlist` (deploy-
시간 curated 기본 출처, 포크의 platform team이 설정). 프로바이더는
두 허용 목록의 **교집합**에 있는 도메인을 가진 스니펫만 반환 - 조회가
per-event 구획을 narrow하고, deploy 허용 목록은 절대 상한을 부여.

Bing API 키는 실제 운영 시크릿 입니다: 체크인된 리터럴이 아니라 조립
시간에 배포된 `SecretProvider` 경계를 통해 해결하세요. 프로바이더의
프로토콜 계약이 반환된 문자열의 로그 기록을 금지합니다.

```python
# fork/adapters/web_search.py
from fdai.core.web_search import (
 WebSearchProvider, WebSearchQuery, WebSearchResult, WebSnippet
)
from fdai.shared.providers.secret_provider import SecretProvider

class BingWebSearchProvider(WebSearchProvider):
 def __init__(
  self,
  *,
  secret_provider: SecretProvider,
  secret_name: str,
  deploy_allowlist: frozenset[str],
 ) -> None:
  self._secret_provider = secret_provider
  self._secret_name = secret_name
  self._deploy_allowlist = deploy_allowlist # curated primary source

 async def search(self, query: WebSearchQuery) -> WebSearchResult:
  api_key = await self._secret_provider.get(self._secret_name)
  # `api_key`는 이 호출에 scoped; 절대 로그 금지, `self`에 저장 금지,
  # WebSearchResult reasons tuple에 포함 금지.
  effective = self._deploy_allowlist & set(query.allowed_domains)
  if not effective:
   return WebSearchResult(
    query=query, reasons=("allowlist_intersection_empty",),
   )
  # 1. query.text를 self._api_key와 함께 Bing API에 POST.
  # 2. domain이 ``effective``에 없는 hit는 모두 drop.
  # 3. WebSnippet tuple 빌드, query.max_results와
  # query.budget_ms를 soft deadline으로 존중.
  # 4. WebSearchResult(query=query, snippets=(...)) 반환.
  return WebSearchResult(query=query, snippets=()) # fork가 body 채움
```

**모든 스니펫은 모델 턴에 주입되기 전
`wrap_web_snippet(snippet=..., allowed_domains=query.allowed_domains)`을
반드시 통과해야 합니다** - 배포된 sanitizer가 도메인 허용 목록, 주입
표시 탐지, `trusted="false"` XML 묶음을 실행.

**테스트 방법**: `services/core-control-plane/tests/core/web_search/test_web_search.py` 미러링.
업스트림 테스트는 sanitizer + `NoOpWebSearchProvider`를 커버; 포크는
`httpx.MockTransport`로 자체 어댑터 레벨 테스트 추가.

### 5.5 HilChannel (Teams / Slack / custom)

**언제 재정의**: 어떤 HIL 흐름든 활성화. 업스트림은 in-memory 가짜를
배포; 실제 배포는 실제 운영 채널을 반드시 바인딩해야 함.

**경계**: `fdai.shared.providers.hil_channel.HilChannel`
프로토콜 - `send` (Adaptive 카드 전달)와 `poll` (결정 observe).

**바인딩 방법**: 두 메서드를 Teams 들어오는 웹훅 / Bot Framework
REST / Slack Web API / 원하는 것에 대해 구현. 조립 루트에
인스턴스 전달, HIL 승인이 전달되는 컨트롤 루프에 wire.

**테스트 방법**: 파이프라인 테스트에는
`fdai.shared.providers.testing.hil_channel.InMemoryHilChannel`
재사용; `httpx.MockTransport`로 어댑터의 wire-level 테스트 추가.

**Control-loop 배선 (upstream-보조)**: `FDAI_CHATOPS_WEBHOOK_URL` 이
설정되는 즉시 `__main__` 이 `HilResumeCoordinator` (액션 보류 + A1 승인
카드 push) 를 자동 바인드한다 - 포크는 웹훅 만 공급하면 되며 코드
변경 없음. 모든 최종 결정에 대한 A2 operational-alert push 는
채널 어댑터(`fdai.delivery.notifications.*`), 업스트림
`StateStoreHilEscalationSink` (`on_all_fail` fail-safe 큐), 포크의 매트릭스
재정의 (`config/notifications-matrix.yaml` 의 자리 표시자 를 실제 채널
id 로) 로 `NotificationRouter` (`fdai.core.notifications`) 를 조립해
`notification_router=` 로 컨트롤 루프 에 전달한다.

### 5.6 ScopeResolver (ARM id -> OperatorScope)

**언제 재정의**: 실제 이벤트에 대해 운영자 기억 활성화. 업스트림이
CSP-neutral을 유지하므로 `QualityCandidate.target_resource_ref`를
`OperatorScope(resource_group_ref, resource_ref)`로 바꾸는 파서는
fork-first.

**경계**: `bind_azure_llm_bindings()`에 `scope_resolver=`로 전달되는
plain callable `Callable[[QualityCandidate], OperatorScope | None]`.

**바인딩 방법**:

```python
# fork/adapters/scope_resolver.py
import re
from fdai.core.operator_memory import OperatorScope
from fdai.core.quality_gate.gate import QualityCandidate

_ARM_RE = re.compile(
 r"^/subscriptions/[^/]+/resourceGroups/(?P<rg>[^/]+)"
 r"(?:/providers/[^/]+/[^/]+/(?P<name>[^/]+))?"
)

def resolve_azure_scope(candidate: QualityCandidate) -> OperatorScope | None:
 match = _ARM_RE.match(candidate.target_resource_ref)
 if match is None:
  return None
 return OperatorScope(
  resource_group_ref=match.group("rg"),
  resource_ref=match.group("name"), # ARM id가 RG에서 끝나면 None
 )
```

그 후 조립 루트에서:

```python
return bind_azure_llm_bindings(
 ..., scope_resolver=resolve_azure_scope,
)
```

**테스트 방법**: 파서에 대한 순수 단위 테스트 (ARM id in, `OperatorScope`
out); 업스트림 테스트 의존성 없음.

### 5.7 CriticModel + JudgeModel (토론 활성화)

**언제 재정의**: 토론 루프 활성화.

**경계**:
[`rule-catalog/llm-registry.yaml`](../../../rule-catalog/llm-registry.yaml)의
두 기능: `t2.critic` (업스트림이 이미 선언) + `t1.judge`
(업스트림이 이미 선언). `bind_azure_llm_bindings`가
`DebateOrchestrator`를 자동 생성하려면 포크의 `resolved-models.json`에
둘 다 포함되어야 함.

**바인딩 방법**: 두 기능이 `resolved-models.json`에 나타나도록
지역별 카탈로그 고정본에 대해 LLM 해석기 CLI 실행. 업스트림 CLI는
[`services/core-control-plane/src/fdai/rule_catalog/schema/llm_resolver_cli.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/llm_resolver_cli.py)에
위치; 다음처럼 호출: `uv 실행 python -m fdai.rule_catalog.스키마.llm_resolver_cli
--registry rule-catalog/llm-registry.yaml --region <your-region>
--subscription-id <sub> --deployer-object-id <oid> --catalog-fixture
<fixture.json> --permission-fixture <perm.json> --quota-fixture
<quota.json> --out /path/to/resolved-models.json`. 지역이 그 중
하나를 호스팅할 수 없으면 기능이 `hil-only` 상태로 landing하고
오케스트레이터는 unbound 유지 - graceful degrade.

**라우터 구성**: ActionType id의 명시적 선택 denylist / 허용 목록이
`DebateRouterConfig`에 위치. 조립 시 하나 생성해서
오케스트레이터와 함께 `QualityGate(debate_router_config=...)`에 전달.
Precedence 규칙은
[prompt-composition.md § Wave 4.5 delta-2a](../decisioning/prompt-composition-ko.md#wave-45-delta-2a---무엇이-배포되었나)
참조.

**테스트 방법**: `services/core-control-plane/tests/core/quality_gate/test_gate.py`의 `_StubCritic`
/ `_StubJudge` 패턴 재사용. 에스컬레이션 매트릭스 (PROCEED / ABORT /
라우터 킬스위치)는 이미 업스트림에 커버됨; 포크의 테스트는 실제 운영 어댑터에
집중.

### 5.8 Rule 카탈로그 추가

**언제 재정의**: 고객별 룰 추가.

**경계**: `load_rule_catalog(...)`가 소비하는 `rule-catalog/catalog/`
YAML 파일. 포크는 자체 디렉터리 (예: `fork/rules/`)를 배포하고
**별도** `load_rule_catalog` 호출로 전달.

**중복 `id`는 hard 오류**. `load_rule_catalog`는 한 루트 안의 중복을 거부하고,
두 루트를 합친 뒤 `RuleIndex.build`가 cross-root 중복을 거부합니다. 온톨로지 전달은
`id`가 전역적으로 유일함에 의존합니다. 이것이 의미하는 바:

- Rule 추가: 포크 고유 id 부여 (예: 포크 이름 공간으로 접두사,
 `customer-x.storage.owner-tag.required`)하고 `fork/rules/`에 배포.
 이것이 유일한 지원 케이스.
 **여러 포크를 유지관리하는 managed-service 팀**은 두 레벨 convention을
 채택 SHOULD: `<tenant-code>.<domain>.<name>` - 여기서
 `<tenant-code>`는 짧은 opaque 코드 (고객 이름 절대 아님), 포크
 룰 카탈로그 최상단에 예약된 이름 공간으로 한 번 등록. 두 포크가 같은
 `<tenant-code>`를 선택하면 merge-time id 충돌 - 이래서 코드는 의미
 라벨이 아니라 짧은 랜덤 문자열이어야 합니다.
- 업스트림 룰 비활성화: 동일-id 재정의를 배포하지 말 것.
 Exemption 작업 흐름 ([`rule-catalog/exemptions/`](../../../rule-catalog/exemptions)
 + [`docs/runbooks/exemption-workflow-ko.md`](../../runbooks/exemption-workflow-ko.md))
 를 사용 - 범위에 대해 룰을 억제하는 감사된, time-boxed 방식.
- 업스트림 룰의 동작 변경: fork-patch 하지 말고 업스트림 issue를
 열 것. 업스트림 룰 카탈로그는 customer-agnostic; 그 동작에 대한
 customer-specific 변경은 업스트림에 구성 knob이 필요하다는 신호.

**바인딩 방법**: 두 카탈로그를 부하하고 concatenate하도록 조립
루트 확장. `load_rule_catalog`는 `tuple[Rule, ...]` 반환:

```python
from pathlib import Path
from fdai.core.tiers.t0_deterministic.index import RuleIndex
from fdai.rule_catalog.schema.rule import load_rule_catalog

upstream_rules = load_rule_catalog(
 Path("rule-catalog/catalog"),
 schema_registry=registry,
 action_types=action_types,
 resource_types=resource_types,
 policies_root=Path("policies"),
 remediation_root=Path("rule-catalog/remediation"),
)
fork_rules = load_rule_catalog(
 Path("fork/rules"),
 schema_registry=registry,
 action_types=action_types,
 resource_types=resource_types,
)
index = RuleIndex.build(upstream_rules + fork_rules)
```

`RuleIndex.build`가 두 루트 사이의 중복 id를 최종 fail-close합니다. 인덱스를 만들지 않는
별도 소비자도 결합 튜플의 id uniqueness를 같은 방식으로 검사해야 합니다.

**테스트 방법**: 배포된 rule-loader 테스트를 템플릿으로 재사용
(`services/core-control-plane/tests/rule_catalog/test_rule_catalog.py`); fork-specific 고정본
디렉터리와 두 카탈로그가 id 충돌 없이 로드되는 smoke 테스트 추가.

### 5.8a 온톨로지 ObjectType / LinkType 추가

**언제 재정의**: `Resource`가 아닌 일급 business 객체를 추가할 때 -
예를 들어 아키텍처 리뷰 제안(architecture-review 제안), 변경 티켓,
compliance-attestation 기록. 기존 Resource subtype에 대한 규칙만
customize한다면 이 절은 건너뛰고 5.8만으로 충분.

**경계**:
- `fdai.rule_catalog.schema.object_type.load_object_type_catalog(root, *, schema_registry)`
- `fdai.rule_catalog.schema.link_type.load_link_type_catalog(root, *, schema_registry, object_types=...)`

두 로더 모두 배포된 `ontology/object-type` / `ontology/link-type` JSON
스키마와 `fdai.shared.contracts.models`의 pydantic 모델로 검증된 변경할 수 없는 튜플을 반환합니다.
각 로더는 루트 내부 중복을 거부합니다. 업스트림 + 포크 튜플을 합칠 때는 조립 루트가
cross-root `name` uniqueness를 별도로 검사해야 합니다.

**새 ObjectType 추가 방법**:

1. ObjectType당 YAML 하나를 fork-local 디렉터리에 배치 (예:
 `fork/vocabulary/object-types/GovernanceProposal.yaml`). 형태는 배포된
 [`rule-catalog/vocabulary/object-types/`](../../../rule-catalog/vocabulary/object-types)
 built-in들을 참고. `name`은 PascalCase (`^[A-Z][A-Za-z0-9]{0,63}$`);
 `key`는 declared 속성 이름이어야 함.
2. LinkType당 YAML 하나를 `fork/vocabulary/link-types/`에 배치 (예:
 `assigned_reviewer.yaml`). `from_type` / `to_type`은 결합된
 ObjectType 레지스트리 (업스트림 + 포크)에서 해석되어야 함;
 오타면 로더가 fail-close. `name`은 snake_case
 (`^[a-z][a-z0-9_]{0,63}$`).
3. 조립 루트에서 두 루트를 로드하고 `dataclasses.replace`로 주입:

 ```python
 from dataclasses 가져오기 replace
 from pathlib 가져오기 경로

 from fdai.rule_catalog.스키마.object_type 가져오기 load_object_type_catalog
 from fdai.rule_catalog.스키마.link_type 가져오기 load_link_type_catalog

 upstream_objects = load_object_type_catalog(
  경로("rule-catalog/vocabulary/object-types"),
  schema_registry=레지스트리,
 )
 fork_objects = load_object_type_catalog(
  경로("포크/vocabulary/object-types"),
  schema_registry=레지스트리,
 )
 objects = upstream_objects + fork_objects
  object_names = [항목.이름 for 항목 in objects]
  if len(object_names) != len(집합(object_names)):
  raise ValueError("중복 ObjectType 이름 across 업스트림 and 포크 roots")

 upstream_links = load_link_type_catalog(
  경로("rule-catalog/vocabulary/link-types"),
  schema_registry=레지스트리,
  object_types=objects,
 )
 fork_links = load_link_type_catalog(
  경로("포크/vocabulary/link-types"),
  schema_registry=레지스트리,
  object_types=objects,
 )
  links = upstream_links + fork_links
  link_names = [항목.이름 for 항목 in links]
  if len(link_names) != len(집합(link_names)):
  raise ValueError("중복 LinkType 이름 across 업스트림 and 포크 roots")
 컨테이너 = replace(
  컨테이너,
  ontology_object_types=objects,
  ontology_link_types=links,
 )
 ```

**Rule 전달 주의**: 배포된 `Rule.resource_type` 필드는 로드 시
`ResourceType` 레지스트리 (`Resource` ObjectType의 subtype 레지스트리)
와 교차 검증됨. 비-Resource ObjectType을 대상하는 규칙이 필요하면:

- business 객체의 subtype들을 ResourceType 항목으로 modeling해서
 기존 전달을 그대로 씀 (많은 거버넌스 흐름에는 충분), 또는
- `Rule.applies_to`를 Resource ObjectType 너머로 일반화하는 업스트림
 issue를 열림. 룰 로더를 fork-patch하지 말 것; cross-reference는
 로드 타이밍에 오타를 잡는 안전성 경계.

**테스트 방법**: `services/core-control-plane/tests/rule_catalog/test_object_type_catalog.py`와
`services/core-control-plane/tests/rule_catalog/test_link_type_catalog.py`를 mirror. 포크
테스트는 joint 부하 (업스트림 + 포크 루트)와, 새 ObjectType이 필요한
소비자(assurance twin, 운영자 콘솔, custom 전달 어댑터)
에서 dispatchable한지 assert 하나에 집중.

**작동 참조**: 업스트림이 `ChangeSummary` (
[`rule-catalog/vocabulary/object-types/ChangeSummary.yaml`](../../../rule-catalog/vocabulary/object-types/ChangeSummary.yaml)
)과 `summarizes` LinkType (
[`rule-catalog/vocabulary/link-types/summarizes.yaml`](../../../rule-catalog/vocabulary/link-types/summarizes.yaml)
)을 포크의 첫 비즈니스 ObjectType을 위한 copy-ready 참조로 배포.
전체 scaffold는
[downstream-fork-example-vertical-ko.md](downstream-fork-example-vertical-ko.md)
에서 walkthrough.

**Anti-pattern**:
- 배포된 `rule-catalog/vocabulary/object-types/*.yaml` 편집 -
 built-in ObjectType 변경은 포크가 아닌 업스트림으로.
- 포크 루트만 로드 - LinkType 로더는 결합된 레지스트리로 엔드포인트를
 검증하므로, built-in ObjectType을 가리키는 포크 LinkType (예:
 `assigned_reviewer: Reviewer -> Resource`)은 업스트림이 빠지면
 fail-close.

### 5.9 Risk 오버레이 (Rego)

**언제 재정의**: 환경 / 고객별로 RiskGate 상한을 조임 (Rego
오버레이는 자율성을 낮추기만 가능하고 절대 올릴 수 없음, per
[execution-model-ko.md § 통합 RiskGate](../decisioning/execution-model-ko.md#3-통합-riskgate)).

**현재 상태**: **Rego 오버레이 wire는 execution-model 설계에
스코프되어 있지만 `services/core-control-plane/src/fdai/core/risk_gate/`의 RiskGate
모듈은 아직 오버레이 파일을 로드하지 않습니다.** 오늘 두 개의 권위 있는
결정 표면: (a) ActionType 스키마의 `ceiling_by_tier` 블록
(배포된 온톨로지 YAML을 직접 편집하고 변경이 customer-agnostic이면
업스트림 PR 열기)과 (b) `DebateRouterConfig`의
`always_for_action_types` / `never_for_action_types` (5.7 참조).

**오버레이 wire가 landing할 때까지 포크 지침**: 의도된 tighter 상한을
포크의 룰 카탈로그 추가 (5.8)의 ActionType-level `ceiling_by_tier`
재정의로 인코딩, 또는 `DebateRouterConfig`의
`never_for_action_types` denylist로 해당 ActionType의 토론 승격을
완전히 블록.

**추적**: 오버레이 wire는 Wave 4.5 delta-2b의 후속 조치로 계획됨;
 landing되면 이 섹션에 `RiskGate(overlay_path=...)` 바인딩 문서화.

### 5.10 런타임 실패 모드와 판단 보류 계약

모든 경계는 실제 운영 어댑터가 런타임에 실패할 때의 문서화된 동작을
갖습니다. 포크의 어댑터는 컨트롤 루프가 게이트되지 않은 액션이 아니라
HIL로 degrade 하도록 이 계약을 준수해야 합니다.

| 경계 | 실제 운영 어댑터 실패 | 기대 동작 |
|------|------------------|-----------|
| `EmbeddingModel` / `CrossCheckModel` | HTTP 에러, 시간 초과 | Raise; 업스트림이 catch하고 quality 후보를 abstain (HIL). 합성 빈 응답을 절대 반환하지 말 것. |
| `CriticModel` / `JudgeModel` | HTTP 에러, 할당량 | Raise; `DebateOrchestrator`가 `DebateVerdict.ABORT`와 `error_class`를 반환 -> HIL. |
| `WebSearchProvider` | HTTP 에러, 시간 초과 | Raise하거나 빈 결과를 반환할 수 있습니다. 호출자가 exception을 정제된 `provider_error` 근거로 변환하며 액션 권한을 높이지 않습니다. |
| `HilChannel.send` | 배달 실패 | Raise; 업스트림이 로그하고 감사 trail이 승인을 `dispatch_failed`로 표시. 액션은 pending 유지; auto-execute 없음. |
| `HilChannel.poll` | 백엔드 unreachable | Raise; 업스트림이 다음 틱에서 승인을 `pending`으로 유지. |
| `OperatorMemoryStore` | 쓰기 시 DB down | Raise; 항목이 저장되지 않으며 호출자가 승인 작업 흐름을 실패 시 차단합니다. |
| `OperatorMemoryStore` | 읽기 시 DB down | Raise; 작성기가 stale/빈 기억으로 조용히 진행하지 않고 현재 요청을 실패 시 차단합니다. |
| `SecretProvider.get` | 시크릿 누락된 / KV down | `SecretNotFoundError` raise; 시작 시 fail-fast. 누락된 시크릿은 절대 조용히 기본값되지 않음. |
| `ScopeResolver` | 리소스 참조 파싱 불가 | `None` 반환; materializer는 그 이벤트에 대해 operator-memory 첨부를 건너뜀하지만 액션 자체는 블록되지 않음. |
| `RemediationPrPublisher` (5.13) | PR 호스트 down | Raise; 실행기가 `execution_failed` 감사 엔트리를 기록하고 액션은 그림자 유지. `PublishReceipt`를 조작하지 말 것. |
| `ReadPanel.render` (5.14) | 데이터 소스 down | 빈 패널 본문 반환 + 패널 모델이 지원하면 `reasons=("<source-error>",)` 표시, 아니면 HTTP 503 raise. 패널은 어떤 코드 경로에서도 액션을 실행하지 말 것. |

공통 불변식: **실제 운영 어댑터 에러에서 성공을 조작하지 말 것**.
포크의 어댑터가 위 표의 계약을 준수할 수 없다면, 관찰 가능한 최초
지점에서 HIL로 escalate 하세요.

### 5.11 포크 종단 간 테스트

포크의 테스트 스위트는 두 역할을 갖습니다: (a) 포크의 실제 운영 어댑터가
프로토콜을 준수함을 증명, (b) composition-root 변경 후에도 업스트림
계약이 여전히 유지됨을 증명. CI가 어느 쪽이 깨졌는지 triage 하도록
둘을 분리하세요.

**권장 레이아웃**:

```
fork/
 services/core-control-plane/tests/
 adapters/  # live 어댑터의 wire-level 테스트
 composition/  # composition_root를 end-to-end로 실행하는 테스트
 contract/  # 얇은 Protocol 준수 테스트 (아래 참조)
```

**프로토콜 준수 테스트 패턴** - 포크가 대체하는 모든 경계에 대해, 테스트
더블로 어댑터를 인스턴스화하고 런타임에 프로토콜 형태를 만족하는지
assert 하는 한 페이지짜리 테스트를 작성:

```python
from fdai.core.web_search import WebSearchProvider

def test_bing_provider_is_websearch_protocol():
 provider = BingWebSearchProvider(
  secret_provider=StubSecretProvider({"bing": "test"}),
  secret_name="bing",
  deploy_allowlist=frozenset({"example.com"}),
 )
 assert isinstance(provider, WebSearchProvider) # runtime_checkable
```

**양쪽 스위트 실행**:

```bash
uv run pytest -q services/core-control-plane/tests/ fork/services/core-control-plane/tests/  # 전체 CI 실행
uv run pytest -q services/core-control-plane/tests/     # upstream 계약 회귀만
uv run pytest -q fork/services/core-control-plane/tests/    # fork 어댑터 검사만
```

**포크의 `pyproject.toml`에서 pytest-asyncio auto-mode 상속**
(`[tool.pytest.ini_options]` 아래): `asyncio_mode = "auto"`. 업스트림은
비동기 경계 테스트가 표시 없이 되도록 이를 설정; 이를 생략한 포크는
의문의 "비동기 함수 not awaited" 경고를 볼 것입니다.

### 5.12 ActionType 카탈로그 추가

**언제 재정의**: 배포된 카탈로그가 커버하지 않는 새 변경 카테고리
도입. 대표 예시: `governance.assign-reviewers` (제안을 검토자
세트로 라우팅), `governance.publish-decision` (승인 결과 기록),
`remediate.rotate-fork-signing-key` (포크 소유의 커스텀 롤백을
가진 교대). 기존 ActionType (예: `remediate.tag-add`)을 재사용하는
새 룰만 필요하다면 이 recipe는 건너뛰고 5.8만으로 충분.

**경계**:
`fdai.rule_catalog.schema.action_type.load_action_type_catalog(...)`
가 소비하는 `rule-catalog/action-types/` YAML 파일. 포크는 자체
디렉터리 (예: `fork/action-types/`)를 배포하고 5.8이 룰을 concatenate
하는 방식과 동일하게 두 카탈로그를 concatenate 하거나, 배포된
ActionType을 조정할 때는 형제 디렉터리에 same-name 오버레이를 배치
(아래 "Fork-side 오버레이" 참조).

**필수 스키마 필드** (로드 시 검증, 업스트림 ActionType과 이 파이프라인을
통해 승격하는 포크 ActionType 모두에 `default_mode=shadow` 강제):

- `name` - 안정된 id, snake / dot / dash 토큰 (예:
 `governance.assign-reviewers`). 모든 카탈로그 루트에서 전역 유일.
- `operation` - `fdai.shared.contracts.models`의 `Operation` enum에
 있는 CSP-neutral 동사 (`tag`, `create`, `update`, `delete`, `scale`,
 `restart`, `rotate`, `revert`, ...). `configure`는 현재 enum에 없습니다. 존재하지 않는
 동사가 필요하면 업스트림 issue 열 것 - enum은 감사 어휘라서
 포크되지 않아야 함.
- `interfaces` - 실행기가 존중하는 `ActionInterface` 이름 리스트
 (예: `ControlPlane`, `DataPlaneMutating`, `IdempotentByKey`,
 `RequiresInventoryFresh`). `DataPlane`과 `Governance`는 현재 enum이 아닙니다. Risk-gate가 이
 세트로 feature vector를 구성.
- `rollback_contract` - `pr_revert`, `scripted`, `pitr`,
 `snapshot_restore`, `state_forward_only` 중 하나. 레거시 `none`
 값은 사라짐; 진짜로 one-way 변경은 `irreversible: true`를
 세팅하고 risk-gate가 HIL+정족수로 라우팅하지만, 여전히
 최선 노력 롤백 설명을 반드시 선언해야 함.
- `default_mode` - 업스트림과 포크의 모든 새 카탈로그 항목은 반드시 `shadow`입니다.
 로더가 `enforce`를 거부하며 승격 상태는 권위 있는 레지스트리가 별도로 소유합니다.
- `promotion_gate` - `min_shadow_days`, `min_samples`, `min_accuracy`,
 `max_policy_escapes`. Rule 배정은 이 값들을 조일 MAY 하지만
 느슨하게 하지 말 것.
- `preconditions[]` / `stop_conditions[]` - T0 검증기가 risk-gate
 전에 평가하는 결정론적 검사. 빈 리스트는 실행기가 독립 불변식을
 가질 때만 허용 (예: 멱등적 tag 집합); 대부분의 `governance.*`
 ActionType은 최소 하나를 선언.
- `trigger_kind` (선택) - `{kind: rule_violation}`, `{kind: operator_request}`, 또는
 `{kind: both}` 객체. `operator_request` 또는 `both`일 때는 콘솔이 조정기
 경계에서 인자를 검증하도록 `argument_schema` (JSON 스키마)
 도 반드시 선언.

**바인딩 방법 (concatenation)**:

```python
from pathlib import Path
from dataclasses import replace

from fdai.rule_catalog.schema.action_type import load_action_type_catalog

upstream_actions = load_action_type_catalog(
 Path("rule-catalog/action-types"),
 schema_registry=registry,
 probes_root=Path("rule-catalog/probes"),
)
fork_actions = load_action_type_catalog(
 Path("fork/action-types"),
 schema_registry=registry,
 probes_root=None, # fork는 자체 probe 배포 MAY; None이면 cross-check skip
)
action_types = upstream_actions + fork_actions
action_names = [item.name for item in action_types]
if len(action_names) != len(set(action_names)):
 raise ValueError("duplicate ActionType name across upstream and fork roots")
```

Rule 로더 (5.8)는 `action_types=action_types`를 받아서 결합된 세트에
대해 모든 `remediates:` 참조를 해석.

**Fork-side 오버레이** (YAML 편집 없이 배포된 ActionType 조정):
`load_action_type_catalog`가 선택적
`overlay_root=Path("fork/action-types-overrides")`를 받음. 그
디렉터리의 모든 YAML은 업스트림 ActionType과 일치하는 `name:`을
carry; 선언된 키는 pydantic 모델 검증 전에 업스트림 매핑에 deep-merge.
리스트는 통째로 대체되므로 (preconditions, stop_conditions), precondition을
추가하려는 포크는 오버레이 이름 아래에 전체 precondition 리스트를 배포.
업스트림에 매칭이 없는 `name`을 가진 오버레이는 rejected - 오타가 조용히
phantom ActionType을 도입할 수 없음.

**테스트 방법**: `services/core-control-plane/tests/rule_catalog/test_action_type_catalog.py`를
템플릿으로 재사용. 포크 테스트는 다음을 assert SHOULD:

- 모든 포크 ActionType이 오류 없이 `load_action_type_from_mapping`을
 round-trip,
- `default_mode`가 포크의 shadow-first 정책과 일치,
- `promotion_gate` 값이 non-degenerate,
- `trigger_kind`가 operator-request를 허용할 때 `argument_schema` 존재.

**작동 참조**: 업스트림이
[`ops.publish-change-summary`](../../../rule-catalog/action-types/ops.publish-change-summary.yaml)
을 shadow-mode ActionType으로 배포 - operator-request `argument_schema`,
`pr_revert` 롤백 계약, 짝 룰 + Rego + Markdown 템플릿 포함. 새 변경
카테고리의 시작점으로 ObjectType/LinkType까지 포함한 6개 파일 scaffold를 복사.

**Anti-pattern**:

- 배포된 `rule-catalog/action-types/*.yaml` 편집 - ObjectType 편집과
 동일 규칙: 배포된 ActionType은 업스트림으로, 포크는 새로 배포하거나
 오버레이.
- `irreversible: true`만으로 롤백 침묵. `rollback_contract`는
 reversal이 최선 노력일 때도 필수.
- 측정된 그림자 창 없이 신규 ActionType 카테고리를 `default_mode: enforce`
 로 - 포크에서도 마찬가지.

### 5.13 전달 어댑터 (커스텀 발행기)

**언제 재정의**: 액션 출력을 Git 교정 PR 이외의 채널에
publish. 대표 포크 예시: 거버넌스 결정용 Confluence 페이지 발행기,
변경 티켓을 여는 Slack 알림 어댑터, CAB 요청을 여는 ServiceNow
브리지. 포크가 다른 소유자/repo에 대해 배포된 `gitops-pr` 발행기만
재사용하면 코드 불필요 - `FDAI_GITOPS_TOKEN`, `FDAI_GITOPS_OWNER`,
`FDAI_GITOPS_REPO`만 세팅.

**경계**: `fdai.shared.providers.remediation_pr.RemediationPrPublisher`
프로토콜 - 하나의 비동기 메서드:

```python
class RemediationPrPublisher(Protocol):
 async def publish(self, pr: RemediationPr) -> PublishReceipt: ...
```

`RemediationPr`은 완전히 렌더된 페이로드 (제목, 본문, patch, patch_path, labels,
액션/멱등성 id)를 carry하고, `PublishReceipt`는 감사 로그가 나중에
인용할 수 있는 고정된 `pr_ref`를 반드시 포함. 업스트림 실행기는
Protocol-typed; 포크가 발행기를 만들어서 조립 루트로 주입.

**이름**: 타입 이름이 `RemediationPrPublisher`인 것은 역사적 이유
(Git PR이 첫 채널). 프로토콜 형태는 채널 무관. Confluence 페이지나
ServiceNow 티켓을 대상하는 포크 어댑터는 일급 구현이지 workaround가
아님.

**바인딩 방법 (Confluence 페이지 발행기 예시)**:

```python
# fork/adapters/confluence_publisher.py
from fdai.shared.providers.remediation_pr import (
 PublishReceipt, RemediationPr, RemediationPrPublisher,
)
from fdai.shared.providers.secret_provider import SecretProvider

class ConfluencePagePublisher(RemediationPrPublisher):
 """렌더된 governance-decision 페이지를 Confluence space에 publish."""

 def __init__(
  self,
  *,
  secret_provider: SecretProvider,
  api_token_secret: str,
  base_url: str,
  space_key: str,
 ) -> None:
  self._secret_provider = secret_provider
  self._api_token_secret = api_token_secret
  self._base_url = base_url
  self._space_key = space_key

 async def publish(self, pr: RemediationPr) -> PublishReceipt:
  token = await self._secret_provider.get(self._api_token_secret)
  # 1. pr.title / pr.body / pr.patch를 Confluence body로 번역.
  # 2. self._space_key와 함께 <base_url>/wiki/rest/api/content에 POST.
  # 3. 응답에서 page id와 self-link 추출.
  # 4. audit log가 정확한 revision을 back-link 하도록 pr_ref가
  # page id를 인용하는 PublishReceipt 반환.
  return PublishReceipt(
   pr_ref="confluence:page:<id>",
   url="<page-url>",
   already_existed=False,
  )
```

**Composition-root 배선** (기본 발행기 대체):

```python
# fork/composition_root.py
from fork.adapters.confluence_publisher import ConfluencePagePublisher
from fdai.core.executor import ShadowExecutor
# ... build_control_loop() 안에서 ...

publisher = ConfluencePagePublisher(
 secret_provider=secret_provider, # fork composition이 별도로 구성
 api_token_secret="confluence.api.token",
 base_url="https://example.atlassian.net",
 space_key="ARB",
)
executor = ShadowExecutor(
 publisher=publisher,
 audit_store=audit_store,
 renderer=renderer,
 resource_lock=resource_lock,
)
```

`ShadowExecutor`가 발행기를 직접 받음; ActionType (5.12)이 변경
카테고리와 `rollback_contract`를 선언하고, `rollback_contract`가
실행기의 unwind 방식을 결정. Confluence 페이지의 경우 자연스러운
롤백은 원본을 대체 하는 "철회" companion 페이지를 함께
publish 한다면 `pr_revert`, space 정책이 추가 전용라면
`state_forward_only`. `none`은 선택하지 말 것 - 더 이상 유효한 값이
아님.

**테스트 방법**: `services/core-control-plane/tests/delivery/gitops_pr/test_adapter.py` 미러링.
Wire 테스트는 벤더 API에 대해 `httpx.MockTransport` 사용; 계약
테스트는 프로토콜이 `@runtime_checkable`이므로 런타임에
`isinstance(adapter, RemediationPrPublisher)` assert.

**Anti-pattern**:

- 발행기가 Resource 자체에 변경을 실행. 전달은 변환 결과
 표면; 실행기 + risk-gate가 변경 계약을 소유. 발행기가
 Resource에 side-effect를 내면 정책 bypass.
- 해결된 시크릿을 로그하거나 저장. `SecretProvider.get`은 실제 운영
 문자열 반환; 요청 lifetime 이상 `self`에 두지 말고 호출-scoped로
 유지.
- 전달 어댑터를 포크 소유 룰 로직과 번들링. 어댑터는
 `fork/adapters/` 아래, 룰 카탈로그는 `fork/rules/` 아래로 분리해서
 각 side에 격리된 테스트 표면 유지.

### 5.14 Console ReadPanel 추가

**언제 재정의**: 읽기 전용 콘솔에 버티컬 대시보드 추가 - FinOps
비용 요약, 표류 보드, 거버넌스 결정 이력, DR-drill 실행 로그.
배포된 `/audit`, `/kpi`, `/hil-queue` 라우트만 소비한다면 이 recipe
건너뛰기.

**경계**: `fdai.delivery.operator_api.routes.panels.ReadPanel` 프로토콜 +
[`fdai.delivery.operator_api.main`](../../../services/operator-service/src/fdai_operator_service/)
의 `OperatorApiConfig.extra_panels` 튜플. `ReadPanel`은 자체 HTTP 경로를
선언하고 `render()`에서 직렬화된 모델 반환; Operator API가 각 패널을
GET-only 라우트로 mount 하며 경로는 빌드 시 검증 (`/`로 시작, `..`
탐색 없음).

**읽기 전용 계약 (MUST)**:

- `ReadPanel.render`는 상태를 mutate 하거나 어떤 액션도 트리거해서는
 안 됨 - 변환 결과 표면 전용. 작업 흐름을 트리거하려는 패널은
 이벤트 버스에 `Signal`을 발행 하는 방식으로 하지 실행기 호출로
 하지 말 것.
- [`panels.py`](../../../services/operator-service/src/fdai_operator_service/) 아래
 업스트림 `ExampleFinOpsPanel`은 참조 구현이며 기본으로
 **등록되지 않음**. 그 형태를 복사하되 가져오기해서 재등록하지 말 것 -
 업스트림은 의도적으로 UI를 최소로 유지.

**바인딩 방법 (포크 패널 예시)**:

```python
# fork/adapters/read_panels.py
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fdai.delivery.operator_api.routes.panels import ReadPanel

@dataclass(frozen=True)
class GovernanceDecisionsPanel(ReadPanel):
 """리뷰어 세트 + outcome을 가진 최근 governance 결정."""

 path: str = "/panels/governance/decisions"
 name: str = "governance-decisions"

 async def render(self, *, params: Mapping[str, str]) -> dict[str, Any]:
  # 1. fork의 projection store 조회 (Postgres 뷰, read model, ...).
  # 2. 콘솔에 안전하지 않은 identity 값은 redact.
  # 3. JSON-serialisable dict 반환; Operator API가 직렬화.
  return {
   "items": [],   # {proposal_id, decided_at, reviewers, outcome} 리스트
   "generated_at": "...",
  }
```

**Composition-root 배선** (포크의 `entry.py`에 등록):

```python
# fork/entry.py
from fdai.delivery.operator_api.main import OperatorApiConfig, build_app
from fork.adapters.read_panels import GovernanceDecisionsPanel

app = build_app(
 authenticator=authenticator,
 read_model=read_model,
 config=OperatorApiConfig(
  extra_panels=(GovernanceDecisionsPanel(),),
 ),
)
```

**콘솔 UI (프론트엔드)**: 배포된 콘솔 (`console/`)은 최소 읽기 전용
SPA. 새 패널을 배포하는 포크는 패널이 sidebar에 나타나도록
`console/src/panels.tsx` (또는 UI 스택의 등가 레지스트리)에도 등록
MUST. 그 콘솔 편집은 포크의 repo `console/` 아래에서만 살고 업스트림
`console/`은 범용 유지.

**테스트 방법**: `services/operator-service/tests/`가 업스트림의
mount / path-validation 로직을 커버. 포크는 다음을 추가:

1. 스텁된 데이터 소스로 패널의 `render()`에 대한 단위 테스트.
2. Starlette 테스트 클라이언트로 `build_app(authenticator=..., read_model=...,
 구성=OperatorApiConfig(extra_panels=(YourPanel(),)))`
 를 부팅하고 패널이 선언된 경로의 GET으로 도달 가능한지 assert 하는
 HTTP-level 테스트.
3. 패널이 non-GET 동사를 거부하는지 assert 하는 부정 테스트
 (mount 코드가 강제하지만 포크 표류에 대한 방어).

**Anti-pattern**:

- 패널에서 액션 실행 (실행기 메서드를 호출하는 양식 게시). 콘솔은
 읽기 표면; 승인은 ChatOps나 PR로 흐르지 패널 버튼으로 흐르지
 않음.
- 실제 운영 클라우드 SDK를 읽는 패널. 배포된 인벤토리 / 변환 결과 저장소
 사용; 벤더 API에 직접 talk 하는 패널은 상태를 중복하고
 split-brain 표류 유발.
- 프론트엔드 레지스트리 편집 건너뛰기. UI 엔트리 없는 백엔드-전용 패널은
 문서화되지 않은 HTTP 표면 - 추적 가능하지만 사용 불가.

### 5.15 포크 진입점 (`entry.py`)

**언제 재정의**: 모든 실제 포크. Day-1 체크리스트가
"업스트림 `__main__` 대신 이 모듈에서 가져오기 하도록 프로세스
진입점을 이름 변경"이라고 명시; 이 recipe는 작동하는 `fork/entry.py`가
어떻게 생겼는지 보여줍니다.

**경계**: 업스트림의 [`services/core-control-plane/src/fdai/__main__.py`](../../../services/core-control-plane/src/fdai/__main__.py)는
`fdai.runtime.*`의 호환성 파사드입니다. `_resolve_catalog_root`,
`_build_audit_store`, `_build_operator_memory_store`,
`_build_pattern_library`, `_build_publisher`, `_build_hil_channel`,
`_finalize_llm_bindings`, `_build_control_loop`, `_consume`, `_run` -
그래서 포크의 `entry.py`는 소유한 헬퍼를 대체하면서 동일한 형태를
조립.

**호환성 보조 로직으로 재사용** (업스트림에서 가져오기, 재정의 금지):

- `_resolve_catalog_root` / `_resolve_policies_root` -
 환경 / 파일시스템 발견.
- `_finalize_llm_bindings` - env-driven 업스트림 항목을 위한 호환성 래퍼.
 Programmatic 포크 조립은 공개 `wire_azure_container` + `AzureWireOverrides`를
 직접 사용하는 것이 기본입니다.
- `_consume` / `_run` - Kafka 이벤트 루프와 최상위 signal-handling
 scaffolding.

**교체** (포크가 각각 소유):

- `_build_publisher` - 포크가 전달 어댑터 (5.13)를 배포하면 이
 헬퍼를 발행기 반환하는 것으로 대체.
- `_build_hil_channel` - 포크가 HilChannel 어댑터 (5.5)를 배포하면
 이 헬퍼 대체.
- `_build_control_loop` - 카탈로그, ActionType, 온톨로지 (5.8a),
 룰의 조립. 포크는 보통 업스트림 헬퍼를 호출하고 반환값을
 wrap 하거나, 본문을 복사해서 fork-카탈로그 concatenation을 추가.

**골격**:

```python
# fork/entry.py
"""Fork process entrypoint - upstream의 __main__ 헬퍼를 wrap.

추가:
- fork rule catalog + ActionType catalog + ObjectType/LinkType catalog
 concatenation,
- Confluence publisher (5.13),
- Teams HilChannel 어댑터 (5.5),
- Governance 대시보드 (5.14).

Fork가 소유하지 않는 모든 것은 upstream에서 곧바로 import 하여 `main`
이 동일한 signal-handling 계약을 계속 받도록 함.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import replace
from pathlib import Path

import httpx

from fdai.__main__ import (
 _consume,
 _finalize_llm_bindings,
 _resolve_catalog_root,
 _resolve_policies_root,
 _run,
)
from fdai.composition import Container, default_container_from_env
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.rule_catalog.schema.link_type import load_link_type_catalog
from fdai.rule_catalog.schema.object_type import load_object_type_catalog
from fdai.rule_catalog.schema.rule import load_rule_catalog

from fork.adapters.confluence_publisher import ConfluencePagePublisher
from fork.adapters.hil_channel_teams import TeamsHilChannel

_LOGGER = logging.getLogger("fork.startup")


async def build_container_with_fork_catalogs(
 *, http_client: httpx.AsyncClient,
) -> Container:
 container = default_container_from_env()

 catalog_root = _resolve_catalog_root()
 fork_root = Path("fork")
 registry = container.schema_registry

 # ObjectType / LinkType concatenation (recipe 5.8a).
 upstream_objects = load_object_type_catalog(
  catalog_root / "vocabulary" / "object-types", schema_registry=registry,
 )
 fork_objects = load_object_type_catalog(
  fork_root / "vocabulary" / "object-types", schema_registry=registry,
 )
 objects = upstream_objects + fork_objects
 upstream_links = load_link_type_catalog(
  catalog_root / "vocabulary" / "link-types",
  schema_registry=registry, object_types=objects,
 )
 fork_links = load_link_type_catalog(
  fork_root / "vocabulary" / "link-types",
  schema_registry=registry, object_types=objects,
 )
 container = replace(
  container,
  ontology_object_types=objects,
  ontology_link_types=upstream_links + fork_links,
 )

 # ActionType concatenation (recipe 5.12) 후 Rule concatenation (5.8)은
 # 아래에서 자체 _build_control_loop wrapper 안에서 발생.

 return await _finalize_llm_bindings(container, http_client=http_client)


async def _fork_run() -> int:
 async with httpx.AsyncClient(timeout=30.0) as http:
  container = await build_container_with_fork_catalogs(http_client=http)
  # ... 여기에 fork publisher + HIL channel 빌드 후 _consume에 handoff.
  # 전체 wiring은 fork/composition_root.py 참조.
  return await _consume(container=container, http_client=http)


def main() -> int:
 logging.basicConfig(level=logging.INFO)
 try:
  return asyncio.run(_fork_run())
 except KeyboardInterrupt:
  return 130


if __name__ == "__main__":
 sys.exit(main())
```

**pyproject.toml 스크립트 엔트리** (`uv run` / 컨테이너 CMD가 여기로
오도록 포크의 진입점 등록):

```toml
[project.scripts]
fdai = "fork.entry:main"
```

업스트림은 동일한 `fdai` 스크립트를 `fdai.__main__:main`을 가리키게
배포; 스크립트 이름을 재정의 하면 포크의 Dockerfile에서 빌드된
컨테이너 이미지가 CMD 변경 없이도 자동으로 포크 진입점을 실행.

**테스트 방법**: `services/core-control-plane/tests/composition/test_entry.py` (fork-local)이
in-memory 가짜에 대해 `build_container_with_fork_catalogs`를 실행하고
다음을 assert SHOULD:

1. `container.ontology_object_types`가 업스트림과 포크 이름을 모두
 포함.
2. `local-fake` 모드에서 `_finalize_llm_bindings` 후
 `container.llm_bindings`가 non-None.
3. 잘못된 구성 env가 조용히 degrade 된 컨테이너가 아니라 fail-fast
 시작을 생성.

**Anti-pattern**:

- 전체 `__main__.py`를 copy-paste 해서 in-place 편집. 업스트림 sync
 방어선을 잃음. Wrap 하거나 가져오기; 전체 파일을 fork-clone 하지 말
 것.
- Azure 모드에서 env-driven `_finalize_llm_bindings`와 programmatic
 `wire_azure_container`를 섞어 두 번 연결. 둘 중 하나를 선택하고 공개
 `AzureWireOverrides` 검증을 우회하지 마세요.
- 포크의 `entry.py`를 `fdai` 이외의 스크립트 이름으로 등록하고 컨테이너
 CMD 업데이트 잊음. 결과: 이미지가 업스트림의 `__main__`을 실행하고
 포크 배선은 하나도 실행되지 않음.

### 5.16 매뉴얼 증류 (`ManualSource` / `ManualClassifier` / `Distiller`)

**언제 재정의**: 도입 회사의 운영/배포 매뉴얼을 결정론적 규칙,
워크플로우, 정책으로 컴파일해 흡수할 때
([manual-distillation-ko.md](../rules-and-detection/manual-distillation-ko.md)
참조). 증류할 산문 매뉴얼이 없으면 이 섹션은 건너뛴다.

**경계** (셋 다 업스트림에서 abstain하므로, 미배선 포크는 규칙을
날조하지 않고 아무것도 증류하지 않는다):

- `fdai.shared.providers.manual_source.ManualSource` - 매뉴얼을
 발견하고 각각을 `ManualDocument`로 전달. 기본 `EmptyManualSource`는
 아무것도 제공하지 않는다. 업스트림 제네릭 `DropDirectoryManualSource`는
 로컬 폐기 디렉토리를 읽어 크레덴셜-프리 접근 모드 전부를 한 번에
 커버한다(운영자 폐기, 콘솔 업로드, email-in, iPaaS / Power Automate
 웹훅). `bind_drop_directory_manual_source(container, root=...)`로
 배선한다. SharePoint / Confluence / Notion 커넥터나 위임-토큰 fetch는
 고객 데이터이며 동일 프로토콜 뒤에서 포크에 산다.
- `fdai.shared.providers.manual_classifier.ManualClassifier` - 값싼
 "이것이 운영 절차인가?" 호출. 기본 `AbstainingManualClassifier`는 모든
 후보를 `UNCERTAIN`으로 표시해 자동 증류 대신 HIL 선별로 라우팅한다.
 포크는 `replace(container, manual_classifier=...)`로 소형 모델 분류기를
 배선한다.
- `fdai.shared.providers.distiller.Distiller` - LLM 추출기. 기본
 `AbstainingDistiller`는 아무것도 추출하지 않는다. 포크는
 `replace(container, distiller=...)`로 LLM 기반 distiller를 배선한다.

결정론적 단계(triage 필터, exact dedupe, 민감도 시크릿 / PII 가드,
최신성 차이, 커버리지)는 업스트림이며 포크 작업이 필요 없다. 빌드
타임 오케스트레이터
`fdai.rule_catalog.pipeline.distill.orchestrator.build_distillation_plan`가
이들을 하나의 inert `DistillationPlan`으로 엮는다;
`python -m fdai.rule_catalog.파이프라인.distill_cli --drop-dir <dir>
--snapshot <file>`로 한 번의 통과를 실행한다. 계획은 inert하다 - 증류된
후보는 강제 적용 전에 여전히 grounding / 그림자 / 회귀 / 승격
게이트를 거친다.

**테스트 방법**: 배포된 distill 테스트를 템플릿으로 재사용
(`services/core-control-plane/tests/rule_catalog/pipeline/distill/*`); 포크 픽스처 디렉토리를 추가하고
(1) `ManualSource.list_candidates`가 기대 후보를 반환하는지, (2) 민감도를
건드리는 픽스처가 `distilled`가 아니라 `held`로 라우팅되는지, (3)
`Distiller` 출력이 `source_ref` 출처 이력을 인용하고 커버리지 차이를
통과하는지 assert한다.

**안티패턴**:

- 테넌트 전체에 대한 광범위 상시 서비스-프린시펄 읽기 크레덴셜 보유.
 증류는 빌드 타임이고 매뉴얼 리비전당 한 번 실행되므로, push / 위임으로
 뒤집고 상시 크레덴셜을 보유하지 않는다(설계 문서의 접근 표 참조).
- 민감도 가드를 건드리는 매뉴얼을 자동 증류. `HOLD` 처리 결과는 반드시
 HIL로 라우팅해야 하며, distiller로 직행해선 안 된다.
- 매뉴얼이나 증류된 규칙을 업스트림에 커밋. 이들은 고객 데이터이며 5.8의
 규칙 카탈로그 추가와 똑같이 포크에만 산다.

### 5.17 기능 번들 등록

**사용 시점**: 하나의 포크 기능에 운영자용 발견과 reasoning 도구,
`ActionType`, `Workflow` 연결이 함께 필요할 때 사용합니다. 인프라 프로바이더 하나만
교체한다면 앞의 더 좁은 recipe를 사용하세요.

**경계**: `CapabilityBundle`은 `Capability` 메타데이터,
`CapabilityBinding` 참조, reasoning-tool 프로바이더를 함께 묶습니다.
`fdai.composition.install_capability_bundle(...)`로 설치합니다. Installer는 새
`Container`를 반환하며 원본은 변경하지 않습니다. `ActionType` 또는 `Workflow`
연결은 타입이 지정된 참조일 뿐이며 대상을 직접 호출하지 않습니다.

**바인딩 방법**:

1. 업스트림과 포크의 도구, ActionType, 작업 흐름 카탈로그를 함께 로드합니다.
2. 포크 소유 프로바이더와 `CapabilityBundle`을 구성합니다.
3. 로드한 카탈로그 객체를 `install_capability_bundle`에 전달합니다.
4. Azure 모드에서는 반환된 컨테이너를 `wire_azure_container`에 전달합니다.
 설치된 reasoning-tool 프로바이더는 자동으로 포함됩니다.

Installer는 알 수 없는 대상, 누락 또는 중복 프로바이더, 도구 산출물에 선언된
프로바이더와 번들의 불일치, 참조되지 않은 프로바이더가 있으면 시작을 차단합니다.
복사해서 사용할 수 있는 state-query 프로바이더와 조립 보조 로직은
[`fdai.fork_examples.capability_bundle`](../../../examples/extension-kit/)를
참조하세요.

**테스트 방법**: 원본 컨테이너에 포크 연결이 없는지, 반환된 컨테이너가
기능을 해석하는지, 잘못된 참조가 프로바이더 I/O 전에 실패하는지, 프로바이더
출력이 도구 산출물의 출력 계약을 만족하는지 확인합니다. 변경 기능은 그림자
모드로 유지하고 해석된 대상을 직접 호출하지 말고 일반 risk-gate와 실행기 경로로
테스트하세요.

**Anti-pattern**:

- 동일 프로바이더를 번들과 `AzureWireOverrides.tool_providers` 양쪽에 등록합니다.
 중복 id는 시작 오류입니다.
- 번들을 변경 작업용 범용 함수 디스패처로 사용합니다. 변경은 컨트롤 루프가
 관리하는 `ActionType` 호출로 유지합니다.
