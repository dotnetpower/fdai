---
title: Fork Seam Recipe 조리서
translation_of: downstream-fork-seam-recipes.md
translation_source_sha: 73dab6569022903bbbffe9032b057cac7c311da6
translation_revised: 2026-07-11
---

# Fork Seam Recipes

Downstream FDAI fork를 위한 per-seam 조리서. 각 항목은 동일한 형태를
따릅니다: **언제 override**, **seam**, **바인딩 방법**, **테스트
방법**. 모든 스니펫은 Python 3.12+와 upstream 패키지가 `fdai`로 import
가능하다고 가정합니다.

이 파일은 [downstream-fork-guide-ko.md](downstream-fork-guide-ko.md)
의 동반 문서 - hub 파일이 fork 모델, Day-1 체크리스트, one-hard-rule,
repo 레이아웃, upstream sync, anti-pattern을 소유합니다. 그 hub를 먼저
읽지 않았다면 거기서 시작하세요 - 아래 recipe들은 fork의 composition
root와 repo 레이아웃이 이미 그 가이드를 따르고 있다고 가정합니다.

이 recipe들을 stitch해서 **비즈니스-오브젝트 vertical을 처음부터**
붙이는 walkthrough는
[downstream-fork-example-vertical-ko.md](downstream-fork-example-vertical-ko.md)
참조.

**Contents**

1. [Azure OpenAI 어댑터 (LlmBindings)](#51-azure-openai-어댑터-llmbindings)
2. [OperatorMemoryStore](#52-operatormemorystore-in-memory--postgres--custom)
3. [HilRejectMaterializer + second-approval 채널](#53-hilrejectmaterializer--second-approval-채널)
4. [WebSearchProvider](#54-websearchprovider)
5. [HilChannel (Teams / Slack / custom)](#55-hilchannel-teams--slack--custom)
6. [ScopeResolver (ARM id -> OperatorScope)](#56-scoperesolver-arm-id---operatorscope)
7. [CriticModel + JudgeModel (debate 활성화)](#57-criticmodel--judgemodel-debate-활성화)
8. [Rule catalog 추가](#58-rule-catalog-추가)
9. [Ontology ObjectType / LinkType 추가](#58a-ontology-objecttype--linktype-추가)
10. [Risk overlay (Rego)](#59-risk-overlay-rego)
11. [런타임 실패 모드와 abstain 계약](#510-런타임-실패-모드와-abstain-계약)
12. [Fork end-to-end 테스트](#511-fork-end-to-end-테스트)
13. [ActionType 카탈로그 추가](#512-actiontype-카탈로그-추가)
14. [Delivery adapter (커스텀 publisher)](#513-delivery-adapter-커스텀-publisher)
15. [Console ReadPanel 추가](#514-console-readpanel-추가)
16. [Fork 진입점 (`entry.py`)](#515-fork-진입점-entrypy)

### 5.1 Azure OpenAI 어댑터 (LlmBindings)

**언제 override**: 다른 Azure OpenAI endpoint, 다른 deployment 세트,
또는 비-Azure LLM provider를 가리킬 때.

**Seam**: `fdai.composition.LlmBindings`가 `embedding_model`,
`cross_check_models`, `critic_model`, `judge_model`,
`debate_orchestrator`를 담고 있음. Upstream `bind_azure_llm_bindings()`
factory가 `resolved-models.json`을 읽고 Azure OpenAI 어댑터를 wire.

**`resolved-models.json`은 런타임 secret이지 체크인된 아티팩트가
아닙니다.** Bootstrap `llm_resolver_cli` (5.7 참조)가 생성하고 Key
Vault에 저장하며, `LLM_RESOLVED_MODELS_PATH`가 지정하는 컨테이너
경로 (예: `/mnt/secrets/resolved-models.json`)에 mount 됩니다.
Fork는 이 파일을 커밋해서는 안 됩니다: 배포자의 subscription id,
deployment 이름, region 메타데이터가 담깁니다. llm-registry, quota,
지역 가용성이 변할 때 재생성; resolver는 idempotent - 입력이 동일하면
동일한 파일을 생성합니다.

**바인딩 방법 (Azure endpoint override)**:

Upstream이 전체 Azure wire-up을 위한 **public composition API**를
배포: [`wire_azure_container`](../../../src/fdai/composition/__init__.py) +
선언적 [`AzureWireOverrides`](../../../src/fdai/composition/__init__.py)
dataclass. Fork는 concrete 어댑터로 `AzureWireOverrides` 하나를 만들어
넘기면 됩니다 - 함수가 composer, tool registry, prompt composition
(base / critic / judge), 내부 `bind_azure_llm_bindings()` 호출을 한
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
            scope_resolver=resolve_azure_scope,   # fork 소유 (5.6 참조)
            # tool_providers=... 로 function calling 활성화 (아래)
        ),
    )
```

`AzureWireOverrides`의 `__post_init__`는 빈 `endpoint`나 `None`
`operator_memory_store`에 fail-close - fork 버그가 첫 이벤트에서
composer 안쪽에서 드러나는 게 아니라 생성 시점에서 잡힙니다.
Operator memory를 안 쓰는 fork도 `InMemoryOperatorMemoryStore()`를
명시적으로 전달해야 함 - API가 필수 seam의 기본값 제공을 거부합니다.

**하위 호환성**: upstream의 `__main__._finalize_llm_bindings`는 이제
env var (`FDAI_LLM_ENDPOINT`, `FDAI_CATALOG_ROOT`,
`FDAI_OPERATOR_MEMORY_DSN`)를 읽고 `wire_azure_container`에
위임하는 얇은 wrapper. 기존 테스트와 upstream 진입점은 변경 없이 계속
작동. Env-driven wiring을 선호하는 fork는 wrapper를 호출; 프로그램적
composition을 원하는 fork는 `wire_azure_container`를 직접 호출.

**바인딩 방법 (비-Azure LLM)**: 네 개 Protocol (`EmbeddingModel`,
`CrossCheckModel`, `CriticModel`, `JudgeModel`)을 구현하고
`LlmBindings`를 직접 생성해서 swap:

```python
new_bindings = LlmBindings(
    embedding_model=MyBedrockEmbeddings(),
    cross_check_models=(MyProposer(), MyDoubleChecker()),
)
return replace(container, llm_bindings=new_bindings)
```

**테스트 방법**: 단위 테스트에는 upstream in-memory fake
(`MatchTypeCrossCheckModel`, `DeterministicEmbeddingModel`) 재사용;
wire-level 검사에는 live 어댑터를 `httpx.MockTransport`에 대해 실행
(`tests/delivery/azure/llm/test_adapters.py` 참조).

### 5.2 OperatorMemoryStore (in-memory / Postgres / custom)

**언제 override**: 배포된 `InMemoryOperatorMemoryStore`에서 지속
스토리지로 전환.

**Seam**: `fdai.core.operator_memory.OperatorMemoryStore`
Protocol - 세 개의 async 메서드: `append`, `list_active_for_scope`,
`supersede`.

**바인딩 방법 (Postgres)**: 환경 변수
`FDAI_OPERATOR_MEMORY_DSN` 설정; upstream의
`_build_operator_memory_store()`가 자동으로 `PostgresOperatorMemoryStore`
선택. 코드 변경 불필요.

**바인딩 방법 (커스텀 store)**: Protocol을 구현하고, composition root에서
instance를 `DefaultPromptComposer(operator_memory_store=...)`에 전달.

**테스트 방법**: 단위 테스트에서 `InMemoryOperatorMemoryStore` 재사용;
커스텀 store를 배포하면 `tests/persistence/test_postgres_operator_memory.py`
모양을 미러링 (offline 정책 테스트 + DSN 환경 변수로 gated된 integration
테스트).

### 5.3 HilRejectMaterializer + second-approval 채널

**언제 override**: Operator memory 파이프라인 활성화. Materializer는
upstream이 배포하는 순수 도메인 모듈; 이를 트리거하는 "second approval"
채널은 배포마다 UI가 다르므로 (Teams 버튼, git PR, 커스텀 CLI)
fork-first.

**Seam**: `fdai.core.operator_memory.HilRejectMaterializer`.
`OperatorMemoryStore`로 생성하고 fork가 사용하는 어떤 채널에서든
`await materializer.materialize(hil_response, second_approver, material)`
호출.

**바인딩 방법 (Teams Adaptive Card 콜백)**:

Teams webhook은 Python `HilResponse` 객체가 아니라 raw JSON을
전달합니다 - 콜백이 materializer 호출 전에 payload 필드로부터
response를 재구성.

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
        decision=HilDecision.REJECT,        # 거부된 이유만 materialise
        approver_id=payload["first_approver_oid"],
        received_at=datetime.now(tz=UTC),
        reason=payload["reject_reason"],    # upstream에서 pre-redacted
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
`tests/core/operator_memory/test_hil_pipeline.py` 미러링.

### 5.4 WebSearchProvider

**언제 override**: 웹 검색 활성화. Upstream은
`NoOpWebSearchProvider`를 배포하여 모든 쿼리에 zero snippet 반환 -
아무것도 하지 않는 fork는 웹 검색이 조용히 비활성화됨.

**Seam**: `fdai.core.web_search.WebSearchProvider` Protocol -
하나의 async `search(query) -> WebSearchResult` 메서드.

**바인딩 방법 (Bing 예시)**:

**두 개의 allowlist가 layer됩니다**: `query.allowed_domains`
(per-event scope, caller 설정)과 `self._deploy_allowlist` (deploy-
time curated primary source, fork의 platform team이 설정). Provider는
두 allowlist의 **교집합**에 있는 domain을 가진 snippet만 반환 - query가
per-event slice를 narrow하고, deploy allowlist는 절대 상한을 부여.

Bing API 키는 live secret 입니다: 체크인된 리터럴이 아니라 composition
time에 배포된 `SecretProvider` seam을 통해 해결하세요. Provider의
Protocol 계약이 반환된 문자열의 로그 기록을 금지합니다.

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
        self._deploy_allowlist = deploy_allowlist  # curated primary source

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
        #    query.budget_ms를 soft deadline으로 존중.
        # 4. WebSearchResult(query=query, snippets=(...)) 반환.
        return WebSearchResult(query=query, snippets=())  # fork가 body 채움
```

**모든 스니펫은 모델 turn에 주입되기 전
`wrap_web_snippet(snippet=..., allowed_domains=query.allowed_domains)`을
반드시 통과해야 합니다** - 배포된 sanitizer가 도메인 allowlist, injection
marker 탐지, `trusted="false"` XML envelope을 실행.

**테스트 방법**: `tests/core/web_search/test_web_search.py` 미러링.
Upstream 테스트는 sanitizer + `NoOpWebSearchProvider`를 커버; fork는
`httpx.MockTransport`로 자체 어댑터 레벨 테스트 추가.

### 5.5 HilChannel (Teams / Slack / custom)

**언제 override**: 어떤 HIL flow든 활성화. Upstream은 in-memory fake를
배포; 실제 배포는 live 채널을 반드시 바인딩해야 함.

**Seam**: `fdai.shared.providers.hil_channel.HilChannel`
Protocol - `send` (Adaptive Card dispatch)와 `poll` (결정 observe).

**바인딩 방법**: 두 메서드를 Teams Incoming Webhook / Bot Framework
REST / Slack Web API / 원하는 것에 대해 구현. Composition root에
instance 전달, HIL 승인이 dispatch되는 control loop에 wire.

**테스트 방법**: 파이프라인 테스트에는
`fdai.shared.providers.testing.hil_channel.InMemoryHilChannel`
재사용; `httpx.MockTransport`로 어댑터의 wire-level 테스트 추가.

**Control-loop wiring (upstream-보조)**: `FDAI_CHATOPS_WEBHOOK_URL` 이
설정되는 즉시 `__main__` 이 `HilResumeCoordinator` (액션 park + A1 승인
카드 push) 를 자동 바인드한다 - 포크는 webhook 만 공급하면 되며 코드
변경 없음. 모든 terminal 결정에 대한 A2 operational-alert push 는
채널 어댑터(`fdai.delivery.notifications.*`), upstream
`StateStoreHilEscalationSink` (`on_all_fail` fail-safe 큐), 포크의 matrix
override (`config/notifications-matrix.yaml` 의 placeholder 를 실제 channel
id 로) 로 `NotificationRouter` (`fdai.core.notifications`) 를 조립해
`notification_router=` 로 control loop 에 전달한다.

### 5.6 ScopeResolver (ARM id -> OperatorScope)

**언제 override**: 실제 이벤트에 대해 operator memory 활성화. Upstream이
CSP-neutral을 유지하므로 `QualityCandidate.target_resource_ref`를
`OperatorScope(resource_group_ref, resource_ref)`로 바꾸는 파서는
fork-first.

**Seam**: `bind_azure_llm_bindings()`에 `scope_resolver=`로 전달되는
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
        resource_ref=match.group("name"),  # ARM id가 RG에서 끝나면 None
    )
```

그 후 composition root에서:

```python
return bind_azure_llm_bindings(
    ..., scope_resolver=resolve_azure_scope,
)
```

**테스트 방법**: 파서에 대한 순수 단위 테스트 (ARM id in, `OperatorScope`
out); upstream 테스트 의존성 없음.

### 5.7 CriticModel + JudgeModel (debate 활성화)

**언제 override**: Debate loop 활성화.

**Seam**:
[`rule-catalog/llm-registry.yaml`](../../../rule-catalog/llm-registry.yaml)의
두 capability: `t2.critic` (upstream이 이미 선언) + `t1.judge`
(upstream이 이미 선언). `bind_azure_llm_bindings`가
`DebateOrchestrator`를 자동 생성하려면 fork의 `resolved-models.json`에
둘 다 포함되어야 함.

**바인딩 방법**: 두 capability가 `resolved-models.json`에 나타나도록
지역별 카탈로그 fixture에 대해 LLM resolver CLI 실행. Upstream CLI는
[`src/fdai/rule_catalog/schema/llm_resolver_cli.py`](../../../src/fdai/rule_catalog/schema/llm_resolver_cli.py)에
위치; 다음처럼 호출: `uv run python -m fdai.rule_catalog.schema.llm_resolver_cli
--registry rule-catalog/llm-registry.yaml --region <your-region>
--subscription-id <sub> --deployer-object-id <oid> --catalog-fixture
<fixture.json> --permission-fixture <perm.json> --quota-fixture
<quota.json> --out /path/to/resolved-models.json`. 지역이 그 중
하나를 호스팅할 수 없으면 capability가 `hil-only` 상태로 landing하고
orchestrator는 unbound 유지 - graceful degrade.

**Router config**: ActionType id의 opt-in denylist / allowlist가
`DebateRouterConfig`에 위치. Composition 시 하나 생성해서
orchestrator와 함께 `QualityGate(debate_router_config=...)`에 전달.
Precedence 규칙은
[prompt-composition.md § Wave 4.5 delta-2a](../decisioning/prompt-composition-ko.md#wave-45-delta-2a---무엇이-배포되었나)
참조.

**테스트 방법**: `tests/core/quality_gate/test_gate.py`의 `_StubCritic`
/ `_StubJudge` 패턴 재사용. Escalation 매트릭스 (PROCEED / ABORT /
router 킬스위치)는 이미 upstream에 커버됨; fork의 테스트는 live 어댑터에
집중.

### 5.8 Rule catalog 추가

**언제 override**: 고객별 rule 추가.

**Seam**: `load_rule_catalog(...)`가 소비하는 `rule-catalog/catalog/`
YAML 파일. Fork는 자체 디렉터리 (예: `fork/rules/`)를 배포하고
**별도** `load_rule_catalog` 호출로 전달.

**중복 `id`는 hard error**. `load_rule_catalog`는 root를 넘나들며
같은 id 엔트리에 fail-close - ontology dispatch는 `id`가 전역적으로
유일함에 의존. 이것이 의미하는 바:

- Rule 추가: fork 고유 id 부여 (예: fork namespace로 prefix,
  `customer-x.storage.owner-tag.required`)하고 `fork/rules/`에 배포.
  이것이 유일한 지원 케이스.
  **여러 fork를 유지관리하는 managed-service 팀**은 두 레벨 convention을
  채택 SHOULD: `<tenant-code>.<domain>.<name>` - 여기서
  `<tenant-code>`는 짧은 opaque code (고객 이름 절대 아님), fork
  rule catalog 최상단에 예약된 namespace로 한 번 등록. 두 fork가 같은
  `<tenant-code>`를 선택하면 merge-time id 충돌 - 이래서 코드는 의미
  라벨이 아니라 짧은 랜덤 문자열이어야 합니다.
- Upstream rule 비활성화: 동일-id override를 배포하지 말 것.
  Exemption workflow ([`rule-catalog/exemptions/`](../../../rule-catalog/exemptions)
  + [`docs/runbooks/exemption-workflow-ko.md`](../../runbooks/exemption-workflow-ko.md))
  를 사용 - scope에 대해 rule을 억제하는 audit된, time-boxed 방식.
- Upstream rule의 동작 변경: fork-patch 하지 말고 upstream issue를
  열 것. Upstream rule catalog은 customer-agnostic; 그 동작에 대한
  customer-specific 변경은 upstream에 config knob이 필요하다는 신호.

**바인딩 방법**: 두 카탈로그를 load하고 concatenate하도록 composition
root 확장. `load_rule_catalog`는 `tuple[Rule, ...]` 반환:

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

**테스트 방법**: 배포된 rule-loader 테스트를 template으로 재사용
(`tests/rule_catalog/schema/test_rule.py`); fork-specific fixture
디렉터리와 두 카탈로그가 id 충돌 없이 로드되는 smoke test 추가.

### 5.8a Ontology ObjectType / LinkType 추가

**언제 override**: `Resource`가 아닌 일급 business object를 추가할 때 -
예를 들어 아키텍처 리뷰 제안(architecture-review proposal), change ticket,
compliance-attestation record. 기존 Resource subtype에 대한 규칙만
customize한다면 이 절은 건너뛰고 5.8만으로 충분.

**Seam**:
- `fdai.rule_catalog.schema.object_type.load_object_type_catalog(root, *, schema_registry)`
- `fdai.rule_catalog.schema.link_type.load_link_type_catalog(root, *, schema_registry, object_types=...)`

두 로더 모두 배포된 `ontology/object-type` / `ontology/link-type` JSON
Schema와 `fdai.shared.contracts.models`의 pydantic 모델로 검증된
immutable tuple을 반환. upstream 루트와 fork 루트 간 `name` 중복은
hard error - 온톨로지 dispatch와 assurance twin 모두 `name`으로 index함.

**새 ObjectType 추가 방법**:

1. ObjectType당 YAML 하나를 fork-local 디렉터리에 배치 (예:
   `fork/vocabulary/object-types/GovernanceProposal.yaml`). shape는 배포된
   [`rule-catalog/vocabulary/object-types/`](../../../rule-catalog/vocabulary/object-types)
   built-in들을 참고. `name`은 PascalCase (`^[A-Z][A-Za-z0-9]{0,63}$`);
   `key`는 declared property 이름이어야 함.
2. LinkType당 YAML 하나를 `fork/vocabulary/link-types/`에 배치 (예:
   `assigned_reviewer.yaml`). `from_type` / `to_type`은 결합된
   ObjectType 레지스트리 (upstream + fork)에서 resolve되어야 함;
   오타면 로더가 fail-close. `name`은 snake_case
   (`^[a-z][a-z0-9_]{0,63}$`).
3. composition root에서 두 루트를 로드하고 `dataclasses.replace`로 주입:

   ```python
   from dataclasses import replace
   from pathlib import Path

   from fdai.rule_catalog.schema.object_type import load_object_type_catalog
   from fdai.rule_catalog.schema.link_type import load_link_type_catalog

   upstream_objects = load_object_type_catalog(
       Path("rule-catalog/vocabulary/object-types"),
       schema_registry=registry,
   )
   fork_objects = load_object_type_catalog(
       Path("fork/vocabulary/object-types"),
       schema_registry=registry,
   )
   objects = upstream_objects + fork_objects

   upstream_links = load_link_type_catalog(
       Path("rule-catalog/vocabulary/link-types"),
       schema_registry=registry,
       object_types=objects,
   )
   fork_links = load_link_type_catalog(
       Path("fork/vocabulary/link-types"),
       schema_registry=registry,
       object_types=objects,
   )
   container = replace(
       container,
       ontology_object_types=objects,
       ontology_link_types=upstream_links + fork_links,
   )
   ```

**Rule dispatch 주의**: 배포된 `Rule.resource_type` 필드는 로드 시
`ResourceType` 레지스트리 (`Resource` ObjectType의 subtype 레지스트리)
와 cross-check됨. 비-Resource ObjectType을 target하는 규칙이 필요하면:

- business object의 subtype들을 ResourceType 항목으로 modeling해서
  기존 dispatch를 그대로 씀 (많은 governance flow에는 충분), 또는
- `Rule.applies_to`를 Resource ObjectType 너머로 일반화하는 upstream
  issue를 open. rule loader를 fork-patch하지 말 것; cross-reference는
  로드 타이밍에 오타를 잡는 safety boundary.

**테스트 방법**: `tests/rule_catalog/test_object_type_catalog.py`와
`tests/rule_catalog/test_link_type_catalog.py`를 mirror. fork
테스트는 joint load (upstream + fork 루트)와, 새 ObjectType이 필요한
consumer(assurance twin, operator console, custom delivery adapter)
에서 dispatchable한지 assert 하나에 집중.

**작동 reference**: upstream이 `ChangeSummary` (
[`rule-catalog/vocabulary/object-types/ChangeSummary.yaml`](../../../rule-catalog/vocabulary/object-types/ChangeSummary.yaml)
)과 `summarizes` LinkType (
[`rule-catalog/vocabulary/link-types/summarizes.yaml`](../../../rule-catalog/vocabulary/link-types/summarizes.yaml)
)을 fork의 첫 비즈니스 ObjectType을 위한 copy-ready reference로 배포.
전체 scaffold는
[downstream-fork-example-vertical-ko.md](downstream-fork-example-vertical-ko.md)
에서 walkthrough.

**Anti-pattern**:
- 배포된 `rule-catalog/vocabulary/object-types/*.yaml` 편집 -
  built-in ObjectType 변경은 fork가 아닌 upstream으로.
- fork 루트만 로드 - LinkType 로더는 결합된 레지스트리로 endpoint를
  검증하므로, built-in ObjectType을 가리키는 fork LinkType (예:
  `assigned_reviewer: Reviewer -> Resource`)은 upstream이 빠지면
  fail-close.

### 5.9 Risk overlay (Rego)

**언제 override**: 환경 / 고객별로 RiskGate ceiling을 조임 (Rego
overlay는 autonomy를 낮추기만 가능하고 절대 올릴 수 없음, per
[execution-model-ko.md § 통합 RiskGate](../decisioning/execution-model-ko.md#3-통합-riskgate)).

**현재 상태**: **Rego overlay wire는 execution-model 설계에
스코프되어 있지만 `src/fdai/core/risk_gate/`의 RiskGate
모듈은 아직 overlay 파일을 로드하지 않습니다.** 오늘 두 개의 authoritative
decision surface: (a) ActionType 스키마의 `ceiling_by_tier` 블록
(배포된 ontology YAML을 직접 편집하고 변경이 customer-agnostic이면
upstream PR 열기)과 (b) `DebateRouterConfig`의
`always_for_action_types` / `never_for_action_types` (5.7 참조).

**Overlay wire가 landing할 때까지 fork 지침**: 의도된 tighter ceiling을
fork의 rule catalog 추가 (5.8)의 ActionType-level `ceiling_by_tier`
override로 인코딩, 또는 `DebateRouterConfig`의
`never_for_action_types` denylist로 해당 ActionType의 debate 승격을
완전히 block.

**추적**: Overlay wire는 Wave 4.5 delta-2b의 follow-up으로 계획됨;
 landing되면 이 섹션에 `RiskGate(overlay_path=...)` 바인딩 문서화.

### 5.10 런타임 실패 모드와 abstain 계약

모든 seam은 live 어댑터가 런타임에 실패할 때의 문서화된 동작을
갖습니다. Fork의 어댑터는 컨트롤 루프가 게이트되지 않은 액션이 아니라
HIL로 degrade 하도록 이 계약을 준수해야 합니다.

| Seam | Live 어댑터 실패 | 기대 동작 |
|------|------------------|-----------|
| `EmbeddingModel` / `CrossCheckModel` | HTTP 에러, timeout | Raise; upstream이 catch하고 quality candidate를 abstain (HIL). 합성 빈 응답을 절대 반환하지 말 것. |
| `CriticModel` / `JudgeModel` | HTTP 에러, quota | Raise; `DebateOrchestrator`가 catch하고 `debate_status="unresolved"` 반환 -> HIL. |
| `WebSearchProvider` | HTTP 에러, timeout | `WebSearchResult(query=query, snippets=(), reasons=("<provider-error>",))` 반환. Raise 하지 말 것 - snippet은 보조 증거이지 gate가 아님. |
| `HilChannel.send` | 배달 실패 | Raise; upstream이 로그하고 audit trail이 승인을 `dispatch_failed`로 표시. 액션은 pending 유지; auto-execute 없음. |
| `HilChannel.poll` | 백엔드 unreachable | Raise; upstream이 다음 tick에서 승인을 `pending`으로 유지. |
| `OperatorMemoryStore` | 쓰기 시 DB down | Raise; materializer가 second-approver 레코드를 rollback하고 reject는 audit-only 이벤트로 유지. |
| `OperatorMemoryStore` | 읽기 시 DB down | `()` 반환; composer는 빈 operator-memory 블록으로 진행. Prompt composition은 빈 store에서 survive 해야 함. |
| `SecretProvider.get` | Secret missing / KV down | `SecretNotFoundError` raise; 시작 시 fail-fast. Missing secret은 절대 조용히 default되지 않음. |
| `ScopeResolver` | 리소스 ref 파싱 불가 | `None` 반환; materializer는 그 이벤트에 대해 operator-memory 첨부를 skip하지만 액션 자체는 block되지 않음. |
| `RemediationPrPublisher` (5.13) | PR 호스트 down | Raise; executor가 `execution_failed` audit 엔트리를 기록하고 액션은 shadow 유지. `PublishReceipt`를 조작하지 말 것. |
| `ReadPanel.render` (5.14) | 데이터 소스 down | 빈 panel body 반환 + panel 모델이 지원하면 `reasons=("<source-error>",)` marker, 아니면 HTTP 503 raise. Panel은 어떤 코드 경로에서도 액션을 실행하지 말 것. |

공통 invariant: **live 어댑터 에러에서 성공을 조작하지 말 것**.
Fork의 어댑터가 위 표의 계약을 준수할 수 없다면, 관찰 가능한 최초
지점에서 HIL로 escalate 하세요.

### 5.11 Fork end-to-end 테스트

Fork의 테스트 스위트는 두 역할을 갖습니다: (a) fork의 live 어댑터가
Protocol을 준수함을 증명, (b) composition-root 변경 후에도 upstream
계약이 여전히 유지됨을 증명. CI가 어느 쪽이 깨졌는지 triage 하도록
둘을 분리하세요.

**권장 레이아웃**:

```
fork/
  tests/
    adapters/        # live 어댑터의 wire-level 테스트
    composition/     # composition_root를 end-to-end로 실행하는 테스트
    contract/        # 얇은 Protocol 준수 테스트 (아래 참조)
```

**Protocol 준수 테스트 패턴** - fork가 대체하는 모든 seam에 대해, 테스트
더블로 어댑터를 인스턴스화하고 런타임에 Protocol 형태를 만족하는지
assert 하는 한 페이지짜리 테스트를 작성:

```python
from fdai.core.web_search import WebSearchProvider

def test_bing_provider_is_websearch_protocol():
    provider = BingWebSearchProvider(
        secret_provider=StubSecretProvider({"bing": "test"}),
        secret_name="bing",
        deploy_allowlist=frozenset({"example.com"}),
    )
    assert isinstance(provider, WebSearchProvider)  # runtime_checkable
```

**양쪽 스위트 실행**:

```bash
uv run pytest -q tests/ fork/tests/       # 전체 CI 실행
uv run pytest -q tests/                   # upstream 계약 회귀만
uv run pytest -q fork/tests/              # fork 어댑터 검사만
```

**Fork의 `pyproject.toml`에서 pytest-asyncio auto-mode 상속**
(`[tool.pytest.ini_options]` 아래): `asyncio_mode = "auto"`. Upstream은
async seam 테스트가 marker 없이 되도록 이를 설정; 이를 생략한 fork는
의문의 "async function not awaited" 경고를 볼 것입니다.

### 5.12 ActionType 카탈로그 추가

**언제 override**: 배포된 카탈로그가 커버하지 않는 새 mutation 카테고리
도입. 대표 예시: `governance.assign-reviewers` (proposal을 Reviewer
세트로 라우팅), `governance.publish-decision` (승인 outcome 기록),
`remediate.rotate-fork-signing-key` (fork 소유의 커스텀 rollback을
가진 rotation). 기존 ActionType (예: `remediate.tag-add`)을 재사용하는
새 rule만 필요하다면 이 recipe는 건너뛰고 5.8만으로 충분.

**Seam**:
`fdai.rule_catalog.schema.action_type.load_action_type_catalog(...)`
가 소비하는 `rule-catalog/action-types/` YAML 파일. Fork는 자체
디렉터리 (예: `fork/action-types/`)를 배포하고 5.8이 rule을 concatenate
하는 방식과 동일하게 두 카탈로그를 concatenate 하거나, 배포된
ActionType을 조정할 때는 sibling 디렉터리에 same-name overlay를 배치
(아래 "Fork-side overlay" 참조).

**필수 스키마 필드** (로드 시 검증, upstream ActionType과 이 파이프라인을
통해 승격하는 fork ActionType 모두에 `default_mode=shadow` 강제):

- `name` - 안정된 id, snake / dot / dash 토큰 (예:
  `governance.assign-reviewers`). 모든 카탈로그 root에서 전역 유일.
- `operation` - `fdai.shared.contracts.models`의 `Operation` enum에
  있는 CSP-neutral 동사 (`tag`, `create`, `update`, `delete`, `scale`,
  `restart`, `rotate`, `configure`, `revert`, ...). 존재하지 않는
  동사가 필요하면 upstream issue 열 것 - enum은 audit 어휘라서
  fork되지 않아야 함.
- `interfaces` - executor가 존중하는 `ActionInterface` 이름 리스트
  (예: `ControlPlane`, `DataPlane`, `Governance`). Risk-gate가 이
  세트로 feature vector를 구성.
- `rollback_contract` - `pr_revert`, `scripted`, `pitr`,
  `snapshot_restore`, `state_forward_only` 중 하나. 레거시 `none`
  값은 사라짐; 진짜로 one-way mutation은 `irreversible: true`를
  세팅하고 risk-gate가 HIL+quorum으로 라우팅하지만, 여전히
  best-effort rollback 설명을 반드시 선언해야 함.
- `default_mode` - 모든 upstream 배포에서 반드시 `shadow`. Fork 자체
  카탈로그는 이전 배포에서 이미 검증한 카테고리에 대해 Day-1
  `enforce`를 세팅 MAY 하지만, fork CI는 동일한 "shadow first, measure
  로 promote" invariant를 유지 SHOULD.
- `promotion_gate` - `min_shadow_days`, `min_samples`, `min_accuracy`,
  `max_policy_escapes`. Rule assignment는 이 값들을 조일 MAY 하지만
  느슨하게 하지 말 것.
- `preconditions[]` / `stop_conditions[]` - T0 verifier가 risk-gate
  전에 평가하는 결정론적 검사. 빈 리스트는 executor가 독립 invariant를
  가질 때만 허용 (예: idempotent tag set); 대부분의 `governance.*`
  ActionType은 최소 하나를 선언.
- `trigger_kind` (선택) - `rule_violation`, `operator_request`, 또는
  `both`. `operator_request` 또는 `both`일 때는 콘솔이 coordinator
  boundary에서 argument를 검증하도록 `argument_schema` (JSON Schema)
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
    probes_root=None,   # fork는 자체 probe 배포 MAY; None이면 cross-check skip
)
action_types = upstream_actions + fork_actions
```

Rule 로더 (5.8)는 `action_types=action_types`를 받아서 결합된 세트에
대해 모든 `remediates:` 참조를 resolve.

**Fork-side overlay** (YAML 편집 없이 배포된 ActionType 조정):
`load_action_type_catalog`가 선택적
`overlay_root=Path("fork/action-types-overrides")`를 받음. 그
디렉터리의 모든 YAML은 upstream ActionType과 일치하는 `name:`을
carry; 선언된 키는 pydantic 모델 검증 전에 upstream 매핑에 deep-merge.
리스트는 통째로 대체되므로 (preconditions, stop_conditions), precondition을
추가하려는 fork는 overlay name 아래에 전체 precondition 리스트를 배포.
Upstream에 매칭이 없는 `name`을 가진 overlay는 rejected - 오타가 조용히
phantom ActionType을 도입할 수 없음.

**테스트 방법**: `tests/rule_catalog/test_action_type_catalog.py`를
template으로 재사용. Fork 테스트는 다음을 assert SHOULD:

- 모든 fork ActionType이 오류 없이 `load_action_type_from_mapping`을
  round-trip,
- `default_mode`가 fork의 shadow-first 정책과 일치,
- `promotion_gate` 값이 non-degenerate,
- `trigger_kind`가 operator-request를 허용할 때 `argument_schema` 존재.

**작동 reference**: upstream이
[`ops.publish-change-summary`](../../../rule-catalog/action-types/ops.publish-change-summary.yaml)
을 shadow-mode ActionType으로 배포 - operator-request `argument_schema`,
`pr_revert` rollback 계약, 짝 rule + Rego + Markdown 템플릿 포함. 새 mutation
카테고리의 시작점으로 이 4개 파일 scaffold를 복사.

**Anti-pattern**:

- 배포된 `rule-catalog/action-types/*.yaml` 편집 - ObjectType 편집과
  동일 규칙: 배포된 ActionType은 upstream으로, fork는 새로 배포하거나
  overlay.
- `irreversible: true`만으로 rollback 침묵. `rollback_contract`는
  reversal이 best-effort일 때도 필수.
- 측정된 shadow 창 없이 신규 ActionType 카테고리를 `default_mode: enforce`
  로 - fork에서도 마찬가지.

### 5.13 Delivery adapter (커스텀 publisher)

**언제 override**: 액션 output을 Git remediation PR 이외의 채널에
publish. 대표 fork 예시: governance 결정용 Confluence 페이지 publisher,
change ticket을 여는 Slack 알림 어댑터, CAB 요청을 여는 ServiceNow
bridge. Fork가 다른 owner/repo에 대해 배포된 `gitops-pr` publisher만
재사용하면 코드 불필요 - `FDAI_GITOPS_TOKEN`, `FDAI_GITOPS_OWNER`,
`FDAI_GITOPS_REPO`만 세팅.

**Seam**: `fdai.shared.providers.remediation_pr.RemediationPrPublisher`
Protocol - 하나의 async 메서드:

```python
class RemediationPrPublisher(Protocol):
    async def publish(self, pr: RemediationPr) -> PublishReceipt: ...
```

`RemediationPr`은 완전히 렌더된 payload (title, body, diff, labels,
correlation id)를 carry하고, `PublishReceipt`는 audit log가 나중에
인용할 수 있는 stable `external_ref`를 반드시 포함. Upstream executor는
Protocol-typed; fork가 publisher를 만들어서 composition root로 주입.

**이름**: 타입 이름이 `RemediationPrPublisher`인 것은 역사적 이유
(Git PR이 첫 채널). Protocol shape는 채널 무관. Confluence 페이지나
ServiceNow ticket을 target하는 fork 어댑터는 일급 구현이지 workaround가
아님.

**바인딩 방법 (Confluence 페이지 publisher 예시)**:

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
        # 1. pr.title / pr.body / pr.diff를 Confluence body로 번역.
        # 2. self._space_key와 함께 <base_url>/wiki/rest/api/content에 POST.
        # 3. 응답에서 page id와 self-link 추출.
        # 4. audit log가 정확한 revision을 back-link 하도록 external_ref
        #    가 page id를 인용하는 PublishReceipt 반환.
        return PublishReceipt(
            external_ref="confluence:page:<id>",
            url="<page-url>",
            observed_at=pr.correlation_id.timestamp,
        )
```

**Composition-root wiring** (기본 publisher 대체):

```python
# fork/composition_root.py
from fork.adapters.confluence_publisher import ConfluencePagePublisher
from fdai.core.executor import ShadowExecutor
# ... build_control_loop() 안에서 ...

publisher = ConfluencePagePublisher(
    secret_provider=container.secret_provider,
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

`ShadowExecutor`가 publisher를 직접 받음; ActionType (5.12)이 mutation
카테고리와 `rollback_contract`를 선언하고, `rollback_contract`가
executor의 unwind 방식을 결정. Confluence 페이지의 경우 자연스러운
rollback은 원본을 supersede 하는 "retract" companion 페이지를 함께
publish 한다면 `pr_revert`, space 정책이 append-only라면
`state_forward_only`. `none`은 선택하지 말 것 - 더 이상 유효한 값이
아님.

**테스트 방법**: `tests/delivery/gitops_pr/test_publisher.py` 미러링.
Wire 테스트는 벤더 API에 대해 `httpx.MockTransport` 사용; contract
테스트는 Protocol이 `@runtime_checkable`이므로 런타임에
`isinstance(adapter, RemediationPrPublisher)` assert.

**Anti-pattern**:

- Publisher가 Resource 자체에 mutation을 실행. Delivery는 projection
  surface; executor + risk-gate가 mutation 계약을 소유. Publisher가
  Resource에 side-effect를 내면 policy bypass.
- 해결된 secret을 로그하거나 persist. `SecretProvider.get`은 live
  문자열 반환; 요청 lifetime 이상 `self`에 두지 말고 호출-scoped로
  유지.
- Delivery adapter를 fork 소유 rule 로직과 번들링. 어댑터는
  `fork/adapters/` 아래, rule catalog는 `fork/rules/` 아래로 분리해서
  각 side에 격리된 테스트 surface 유지.

### 5.14 Console ReadPanel 추가

**언제 override**: 읽기 전용 콘솔에 vertical 대시보드 추가 - FinOps
비용 요약, drift 보드, governance 결정 이력, DR-drill 실행 로그.
배포된 `/audit`, `/kpi`, `/hil-queue` 라우트만 소비한다면 이 recipe
건너뛰기.

**Seam**: `fdai.delivery.read_api.panels.ReadPanel` Protocol +
[`fdai.delivery.read_api.main`](../../../src/fdai/delivery/read_api/main.py)
의 `ReadApiConfig.extra_panels` 튜플. `ReadPanel`은 자체 HTTP 경로를
선언하고 `render()`에서 직렬화된 모델 반환; read-API가 각 panel을
GET-only 라우트로 mount 하며 경로는 빌드 시 검증 (`/`로 시작, `..`
traversal 없음).

**Read-only 계약 (MUST)**:

- `ReadPanel.render`는 상태를 mutate 하거나 어떤 액션도 트리거해서는
  안 됨 - projection surface 전용. Workflow를 트리거하려는 panel은
  event bus에 `Signal`을 emit 하는 방식으로 하지 executor 호출로
  하지 말 것.
- [`panels.py`](../../../src/fdai/delivery/read_api/routes/panels.py) 아래
  upstream `ExampleFinOpsPanel`은 reference 구현이며 기본으로
  **등록되지 않음**. 그 shape를 복사하되 import해서 재등록하지 말 것 -
  upstream은 의도적으로 UI를 최소로 유지.

**바인딩 방법 (fork panel 예시)**:

```python
# fork/adapters/read_panels.py
from dataclasses import dataclass

from fdai.delivery.read_api.panels import ReadPanel

@dataclass(frozen=True)
class GovernanceDecisionsPanel(ReadPanel):
    """리뷰어 세트 + outcome을 가진 최근 governance 결정."""

    path: str = "/panels/governance/decisions"

    async def render(self) -> dict:
        # 1. fork의 projection store 조회 (Postgres 뷰, read model, ...).
        # 2. 콘솔에 안전하지 않은 identity 값은 redact.
        # 3. JSON-serialisable dict 반환; read-API가 직렬화.
        return {
            "items": [],           # {proposal_id, decided_at, reviewers, outcome} 리스트
            "generated_at": "...",
        }
```

**Composition-root wiring** (fork의 `entry.py`에 등록):

```python
# fork/entry.py
from fdai.delivery.read_api.main import ReadApiConfig, build_app
from fork.adapters.read_panels import GovernanceDecisionsPanel

app = build_app(
    config=ReadApiConfig(
        extra_panels=(GovernanceDecisionsPanel(),),
    ),
)
```

**콘솔 UI (프론트엔드)**: 배포된 콘솔 (`console/`)은 최소 read-only
SPA. 새 panel을 배포하는 fork는 panel이 sidebar에 나타나도록
`console/src/panels.tsx` (또는 UI 스택의 등가 registry)에도 등록
MUST. 그 콘솔 편집은 fork의 repo `console/` 아래에서만 살고 upstream
`console/`은 generic 유지.

**테스트 방법**: `tests/delivery/read_api/test_panels.py`가 upstream의
mount / path-validation 로직을 커버. Fork는 다음을 추가:

1. 스텁된 데이터 소스로 panel의 `render()`에 대한 unit 테스트.
2. FastAPI test client로 `build_app(ReadApiConfig(extra_panels=(YourPanel(),)))`
   를 부팅하고 panel이 선언된 경로의 GET으로 도달 가능한지 assert 하는
   HTTP-level 테스트.
3. Panel이 non-GET verb를 거부하는지 assert 하는 negative 테스트
   (mount 코드가 강제하지만 fork drift에 대한 방어).

**Anti-pattern**:

- Panel에서 액션 실행 (executor 메서드를 호출하는 form POST). 콘솔은
  read surface; 승인은 ChatOps나 PR로 흐르지 panel 버튼으로 흐르지
  않음.
- Live 클라우드 SDK를 읽는 panel. 배포된 inventory / projection store
  사용; 벤더 API에 직접 talk 하는 panel은 상태를 duplicate하고
  split-brain drift 유발.
- 프론트엔드 registry 편집 건너뛰기. UI 엔트리 없는 백엔드-전용 panel은
  문서화되지 않은 HTTP surface - trace 가능하지만 사용 불가.

### 5.15 Fork 진입점 (`entry.py`)

**언제 override**: 모든 실제 fork. Day-1 체크리스트가
"upstream `__main__` 대신 이 모듈에서 import 하도록 process
진입점을 rename"이라고 명시; 이 recipe는 작동하는 `fork/entry.py`가
어떻게 생겼는지 보여줍니다.

**Seam**: upstream의
[`src/fdai/__main__.py`](../../../src/fdai/__main__.py)는 작은
헬퍼들로 의도적으로 구성됨 - `_resolve_catalog_root`,
`_build_audit_store`, `_build_operator_memory_store`,
`_build_pattern_library`, `_build_publisher`, `_build_hil_channel`,
`_finalize_llm_bindings`, `_build_control_loop`, `_consume`, `_run` -
그래서 fork의 `entry.py`는 소유한 헬퍼를 대체하면서 동일한 shape를
composition.

**그대로 재사용** (upstream에서 import, 재정의 금지):

- `_resolve_catalog_root` / `_resolve_policies_root` -
  환경 / 파일시스템 discovery.
- `_finalize_llm_bindings` - `wire_azure_container`를 wrap하고
  endpoint / catalog / memory-store env var를 pull.
- `_consume` / `_run` - Kafka 이벤트 루프와 최상위 signal-handling
  scaffolding.

**교체** (fork가 각각 소유):

- `_build_publisher` - fork가 delivery adapter (5.13)를 배포하면 이
  헬퍼를 publisher 반환하는 것으로 대체.
- `_build_hil_channel` - fork가 HilChannel 어댑터 (5.5)를 배포하면
  이 헬퍼 대체.
- `_build_control_loop` - 카탈로그, ActionType, ontology (5.8a),
  rule의 composition. Fork는 보통 upstream 헬퍼를 호출하고 반환값을
  wrap 하거나, body를 복사해서 fork-카탈로그 concatenation을 추가.

**Skeleton**:

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

**pyproject.toml script 엔트리** (`uv run` / 컨테이너 CMD가 여기로
오도록 fork의 진입점 등록):

```toml
[project.scripts]
fdai = "fork.entry:main"
```

Upstream은 동일한 `fdai` script를 `fdai.__main__:main`을 가리키게
배포; script 이름을 override 하면 fork의 Dockerfile에서 빌드된
컨테이너 이미지가 CMD 변경 없이도 자동으로 fork 진입점을 실행.

**테스트 방법**: `tests/composition/test_entry.py` (fork-local)이
in-memory fake에 대해 `build_container_with_fork_catalogs`를 실행하고
다음을 assert SHOULD:

1. `container.ontology_object_types`가 upstream과 fork 이름을 모두
   포함.
2. `local-fake` 모드에서 `_finalize_llm_bindings` 후
   `container.llm_bindings`가 non-None.
3. 잘못된 config env가 조용히 degrade 된 container가 아니라 fail-fast
   시작을 생성.

**Anti-pattern**:

- 전체 `__main__.py`를 copy-paste 해서 in-place 편집. Upstream sync
  방어선을 잃음. Wrap 하거나 import; 전체 파일을 fork-clone 하지 말
  것.
- Azure 모드에서 `_finalize_llm_bindings` 우회. 그 헬퍼가 올바른
  env-var 계약으로 `wire_azure_container`를 호출하는 유일한 곳; fork가
  `wire_azure_container`를 직접 호출하면 env fallback을 놓칠 가능성
  높음.
- Fork의 `entry.py`를 `fdai` 이외의 script 이름으로 등록하고 컨테이너
  CMD 업데이트 잊음. 결과: 이미지가 upstream의 `__main__`을 실행하고
  fork wiring은 하나도 실행되지 않음.

### 5.16 매뉴얼 증류 (`ManualSource` / `ManualClassifier` / `Distiller`)

**언제 override**: 도입 회사의 운영/배포 매뉴얼을 결정론적 규칙,
워크플로우, 정책으로 컴파일해 흡수할 때
([manual-distillation-ko.md](../rules-and-detection/manual-distillation-ko.md)
참조). 증류할 산문 매뉴얼이 없으면 이 섹션은 건너뛴다.

**seam** (셋 다 upstream에서 abstain하므로, 미배선 fork는 규칙을
날조하지 않고 아무것도 증류하지 않는다):

- `fdai.shared.providers.manual_source.ManualSource` - 매뉴얼을
  발견하고 각각을 `ManualDocument`로 전달. 기본 `EmptyManualSource`는
  아무것도 제공하지 않는다. upstream 제네릭 `DropDirectoryManualSource`는
  로컬 drop 디렉토리를 읽어 크레덴셜-프리 접근 모드 전부를 한 번에
  커버한다(운영자 drop, 콘솔 업로드, email-in, iPaaS / Power Automate
  웹훅). `bind_drop_directory_manual_source(container, root=...)`로
  배선한다. SharePoint / Confluence / Notion 커넥터나 위임-토큰 fetch는
  고객 데이터이며 동일 Protocol 뒤에서 fork에 산다.
- `fdai.shared.providers.manual_classifier.ManualClassifier` - 값싼
  "이것이 운영 절차인가?" 호출. 기본 `AbstainingManualClassifier`는 모든
  후보를 `UNCERTAIN`으로 표시해 자동 증류 대신 HIL 선별로 라우팅한다.
  fork는 `replace(container, manual_classifier=...)`로 소형 모델 분류기를
  배선한다.
- `fdai.shared.providers.distiller.Distiller` - LLM 추출기. 기본
  `AbstainingDistiller`는 아무것도 추출하지 않는다. fork는
  `replace(container, distiller=...)`로 LLM 기반 distiller를 배선한다.

결정론적 단계(triage 필터, exact dedupe, 민감도 secret / PII 가드,
freshness diff, coverage)는 upstream이며 fork 작업이 필요 없다. 빌드
타임 오케스트레이터
`fdai.rule_catalog.pipeline.distill.orchestrator.build_distillation_plan`가
이들을 하나의 inert `DistillationPlan`으로 엮는다;
`python -m fdai.rule_catalog.pipeline.distill_cli --drop-dir <dir>
--snapshot <file>`로 한 번의 pass를 실행한다. plan은 inert하다 - 증류된
후보는 enforce 전에 여전히 grounding / shadow / regression / promotion
게이트를 거친다.

**테스트 방법**: 배포된 distill 테스트를 템플릿으로 재사용
(`tests/rule_catalog/pipeline/distill/*`); fork 픽스처 디렉토리를 추가하고
(1) `ManualSource.list_candidates`가 기대 후보를 반환하는지, (2) 민감도를
건드리는 픽스처가 `distilled`가 아니라 `held`로 라우팅되는지, (3)
`Distiller` 출력이 `source_ref` provenance를 인용하고 coverage diff를
통과하는지 assert한다.

**안티패턴**:

- 테넌트 전체에 대한 광범위 상시 서비스-프린시펄 read 크레덴셜 보유.
  증류는 빌드 타임이고 매뉴얼 리비전당 한 번 실행되므로, push / 위임으로
  뒤집고 상시 크레덴셜을 보유하지 않는다(설계 문서의 접근 표 참조).
- 민감도 가드를 건드리는 매뉴얼을 자동 증류. `HOLD` disposition은 반드시
  HIL로 라우팅해야 하며, distiller로 직행해선 안 된다.
- 매뉴얼이나 증류된 규칙을 upstream에 커밋. 이들은 고객 데이터이며 5.8의
  규칙 카탈로그 추가와 똑같이 fork에만 산다.
