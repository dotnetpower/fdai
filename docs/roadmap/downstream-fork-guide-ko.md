---
title: Downstream Fork 가이드
translation_of: downstream-fork-guide.md
translation_source_sha: f1a22a771f150653992e0a25319e11d107dd5f55
translation_revised: 2026-07-06
---

# Downstream Fork 가이드

이 저장소를 fork하고, fork를 깨끗하게 유지하고, 고객별로
커스터마이즈하는 방법. **Fork 유지관리자** - upstream AIOpsPilot을
가져가서 특정 배포 (고객 tenant, 컴플라이언스 체제, 개념 증명 환경)에
맞춰 조정하는 엔지니어를 위한 단일 진입점입니다.

Upstream 저장소는 의도적으로 generic하고 customer-agnostic 합니다
([generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)).
Fork는 모든 고객별 값, rule, 어댑터, 비밀이 사는 곳입니다. 아래 규칙은
fork가 conflict 없이 upstream과 sync 가능하고 upstream이 고객 값을
zero로 볼 수 있게 존재합니다.

전제 조건: DI seam 카탈로그를 먼저
[project-structure.md § Customization via Dependency Injection](project-structure-ko.md#customization-via-dependency-injection)에서
읽고, 이 가이드 전반에서 참조하는 T0/T1/T2 trust router와 quality-
gate 개념은
[architecture.instructions.md](../../.github/instructions/architecture.instructions.md)를
읽으세요 (`.github/**`는 English-only). 이 문서는 그 참조들을 절차적
recipe로 바꿉니다.

**목차**

1. [Fork 모델 한눈에](#1-fork-모델-한눈에)
2. [Day-1 체크리스트](#2-day-1-체크리스트)
3. [유일한 강한 규칙](#3-유일한-강한-규칙)
4. [Fork를 위한 저장소 레이아웃](#4-fork를-위한-저장소-레이아웃)
5. [Seam recipe](#5-seam-recipe)
   (LLM · OperatorMemoryStore · HilRejectMaterializer · WebSearch ·
   HilChannel · ScopeResolver · Critic+Judge · Rule catalog · Rego
   overlay · 런타임 실패 모드 · End-to-end 테스트)
6. [Upstream sync + 버전 pinning 전략](#6-upstream-sync-절차)
7. [Anti-pattern](#7-anti-pattern)
8. [다음 단계](#8-다음-단계)

**반복 용어.** "기본 비활성 fake (deny-by-default fake)" = 모든 호출에
대해 empty / reject를 반환하는 upstream in-memory Protocol 구현
(예: `NoOpWebSearchProvider`, `InMemoryHilChannel`) - 실제 어댑터
바인딩을 잊은 fork가 조용히 구멍을 열지 않고 안전하게 fail 하도록.
"Shadow-before-enforce" = 모든 새 ActionType은
`default_mode: shadow` (판단하고 로그만, 실행 없음)로 배포되고, 선언된
`promotion_gate`가 measurement로 green 확인된 뒤에만 `enforce`로 승격되는
invariant -
[coding-conventions.instructions.md § Safety](../../.github/instructions/coding-conventions.instructions.md#safety)에
정의됨 (`.github/**`는 English-only).

## 1. Fork 모델 한눈에

- **Upstream** = 이 저장소. Generic한 컨트롤 플레인 (core engine, DI
  seam, 기본 비활성 fake, 카탈로그 스키마) 배포.
- **Fork** = 고객 팀이 소유한 별도 저장소. Tenant identity, secret
  ref, allowlist, per-customer rule, 기본 비활성 fake를 대체하는
  구체적 어댑터 포함.
- **기여 방향**: upstream은 fork에서 절대 pull하지 않음. Fork가
  개선을 위해 upstream `main`에서 pull. Fork가 모든 고객에게 유용한
  변경을 만들면, 그 변경은 **고객 값이 제거**되고 독립적인 upstream
  PR로 배포됩니다.

## 2. Day-1 체크리스트

Fork에서 첫 `git commit` 전에 이것들을 하세요.

1. **Fresh clone에서 baseline이 green인지 확인**: `uv sync` 후
   `uv run pytest -q`. 손대지 않은 checkout에서 upstream 테스트 스위트가
   fail하면 fork 코드 추가 전에 멈추고 진단 - fork는 red baseline을
   절대 상속하지 말 것.
2. **구별되는 기본 브랜치 이름으로 clone** (선택적이지만 권장):
   `fork/main` 또는 `customer-x/main` - `git push`가 실수로 upstream을
   대상으로 하지 않도록.
3. **`git remote -v` 확인**: `origin`이 `dotnetpower/aiopspilot`이
   아니라 fork 저장소를 가리켜야 함. 한 번 실수하면 고객 커밋이
   upstream으로 leak될 가능성이 있음.
4. **Fork의 CI에서 secret scanning 활성화** - upstream의
   `scripts/check-english-only.sh`, `scripts/check-punctuation.sh`,
   `scripts/check-guids.sh`, `scripts/check-core-imports.sh`,
   `scripts/check-translations.sh` 재사용. **이것만으로는
   충분하지 않습니다.** `check-guids.sh`는 `8-4-4-4-12` hex 형식에만
   매치 - 고객 리소스 이름, endpoint, bearer 토큰 prefix, 짧은 account
   id는 catch 하지 못합니다. Fork-specific regex 패턴 (같은 스타일의
   `check-customer-tokens.sh`)을 추가: 고객이 사용하는 리소스 이름
   prefix (`acme-prod-*`), hostname suffix (`*.customer.example`),
   API 토큰 prefix (있다면: `sk-...`, `xoxb-...`, `Bearer eyJ`),
   짧은 account id (12자리 AWS, 6-hex GCP project prefix). OSS
   secret scanner (`gitleaks`, `trufflehog`)도 함께 실행.
5. Azure tenant / subscription id, 고객 리소스 이름, endpoint, 또는
   secret을 **절대 커밋하지 마세요**. 런타임에 환경 또는 Key Vault에서
   로드. 모든 SDK-family secret (API key, connection string, 패스워드
   포함 DSN)은
   `aiopspilot.shared.providers.secret_provider.SecretProvider`를
   경유 - Protocol 계약이 값의 로그 기록 / 영속을 금지.
6. Fork-owned 모듈을 위한 **`fork/` (또는 `customer/`) 최상위 디렉터리
   생성**. 여기가 composition-root override, 어댑터, rule 추가가 사는
   곳. `core/`는 100% upstream 유지.
7. **`pyproject.toml`에 fork 패키지 등록**: `fork/` 디렉터리를
   `[tool.setuptools.packages.find]` (또는 사용 중인 빌드 backend의
   대응 설정)에 추가하고, 프로세스 진입점을 `[project.scripts]`에
   등록. Upstream `pyproject`가 동작하는 baseline을 배포; fork 편집은
   최소한의 delta.
8. **Composition root를 wire**: upstream `default_container(...)`를
   import하고 fork가 소유한 seam을 swap하기 위해 `dataclasses.replace`를
   적용하는 얇은 Python 모듈. 프로세스 진입점을 upstream의 `__main__`
   대신 이 모듈에서 import하도록 이름 변경.
9. **Upstream sync 설정**: `git remote add upstream
   https://github.com/dotnetpower/aiopspilot.git`. 첫 divergence 전에
   [Upstream sync 절차](#upstream-sync-절차)를 한 번 rehearsal.

## 3. 유일한 강한 규칙

**`src/aiopspilot/core/` 아래 파일을 절대 편집하지 마세요.** Fork가
커스터마이즈하고 싶은 모든 것에는 seam이 있습니다. `core/`를 편집하고
싶어질 때, 둘 중 하나가 일어나고 있는 것입니다:

1. Configuration이나 fake에 속하는 값을 주입하려 함. 이미 존재하는
   seam을 찾으세요.
2. Upstream 설계에 진짜 gap을 발견함. Upstream issue를 열거나 fork-
   local wrapper로 `core/`를 patch하지 않고 감싸는 변경을 배포하세요.
   그 후 wrapper를 scrub해서 upstream에 기여.

이 규칙은 두 invariant로 강제됩니다:

- Upstream의 `scripts/check-core-imports.sh`가 `delivery/*` 또는
  클라우드 SDK에서 import하는 `core/` 파일을 거부.
- Composition root
  ([`src/aiopspilot/composition.py`](../../src/aiopspilot/composition.py))가
  `shared/providers/`의 Protocol에 구체적 구현이 바인딩되는 유일한
  곳. Fork는 자체 composition root를 씀; 이 파일을 편집하지 않음.

## 4. Fork를 위한 저장소 레이아웃

권장 형태:

```
customer-x-fork/
  fork/
    __init__.py
    composition_root.py    # upstream default_container() + replace() 호출
    entry.py               # 고객 프로세스 진입 (upstream의 __main__.py 대체)
    adapters/
      web_search.py        # 구체적 WebSearchProvider
      hil_channel.py       # 구체적 HilChannel (Teams / Slack)
      scope_resolver.py    # ARM-id -> OperatorScope 파서
    rules/
      customer.yaml        # 고객별 rule catalog 추가
    overlays/
      risk_gate.rego       # 고객별 risk ceiling overlay
  <upstream tree, 변경 없음>
```

`fork/` 아래 모든 것이 고객 소유. Upstream 파일은 byte-identical 유지,
단 `pyproject.toml` 예외 (fork는 자체 패키지 + 진입점 추가 가능).

## 5. Seam recipe

각 recipe는 동일한 형태: **언제 override할지**, **seam**, **바인딩
방법**, **테스트 방법**. 모든 스니펫은 Python 3.12+와 upstream 패키지가
`aiopspilot`로 import 가능하다고 가정.

### 5.1 Azure OpenAI 어댑터 (LlmBindings)

**언제 override**: 다른 Azure OpenAI endpoint, 다른 deployment 세트,
또는 비-Azure LLM provider를 가리킬 때.

**Seam**: `aiopspilot.composition.LlmBindings`가 `embedding_model`,
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
배포: [`wire_azure_container`](../../src/aiopspilot/composition.py) +
선언적 [`AzureWireOverrides`](../../src/aiopspilot/composition.py)
dataclass. Fork는 concrete 어댑터로 `AzureWireOverrides` 하나를 만들어
넘기면 됩니다 - 함수가 composer, tool registry, prompt composition
(base / critic / judge), 내부 `bind_azure_llm_bindings()` 호출을 한
단계로 처리.

```python
# fork/composition_root.py
from pathlib import Path
from aiopspilot.composition import (
    AzureWireOverrides, default_container, wire_azure_container,
)
from aiopspilot.core.operator_memory import InMemoryOperatorMemoryStore
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
            scope_resolver=resolve_azure_scope,   # fork \uc18c\uc720 (5.6 \ucc38\uc870)
            # tool_providers=... \ub85c function calling \ud65c\uc131\ud654 (\uc544\ub798)
        ),
    )
```

`AzureWireOverrides`의 `__post_init__`는 빈 `endpoint`나 `None`
`operator_memory_store`에 fail-close - fork 버그가 첫 이벤트에서
composer 안쪽에서 드러나는 게 아니라 생성 시점에서 잡힙니다.
Operator memory를 안 쓰는 fork도 `InMemoryOperatorMemoryStore()`를
명시적으로 전달해야 함 - API가 필수 seam의 기본값 제공을 거부합니다.

**하위 호환성**: upstream의 `__main__._finalize_llm_bindings`는 이제
env var (`AIOPSPILOT_LLM_ENDPOINT`, `AIOPSPILOT_CATALOG_ROOT`,
`AIOPSPILOT_OPERATOR_MEMORY_DSN`)를 읽고 `wire_azure_container`에
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

**Seam**: `aiopspilot.core.operator_memory.OperatorMemoryStore`
Protocol - 세 개의 async 메서드: `append`, `list_active_for_scope`,
`supersede`.

**바인딩 방법 (Postgres)**: 환경 변수
`AIOPSPILOT_OPERATOR_MEMORY_DSN` 설정; upstream의
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

**Seam**: `aiopspilot.core.operator_memory.HilRejectMaterializer`.
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

from aiopspilot.core.operator_memory import (
    HilRejectMaterial, HilRejectMaterializer, MemoryCategory, ScopeKind,
)
from aiopspilot.shared.providers.hil_channel import HilDecision, HilResponse

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

**Seam**: `aiopspilot.core.web_search.WebSearchProvider` Protocol -
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
from aiopspilot.core.web_search import (
    WebSearchProvider, WebSearchQuery, WebSearchResult, WebSnippet
)
from aiopspilot.shared.providers.secret_provider import SecretProvider

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

**Seam**: `aiopspilot.shared.providers.hil_channel.HilChannel`
Protocol - `send` (Adaptive Card dispatch)와 `poll` (결정 observe).

**바인딩 방법**: 두 메서드를 Teams Incoming Webhook / Bot Framework
REST / Slack Web API / 원하는 것에 대해 구현. Composition root에
instance 전달, HIL 승인이 dispatch되는 control loop에 wire.

**테스트 방법**: 파이프라인 테스트에는
`aiopspilot.shared.providers.testing.hil_channel.InMemoryHilChannel`
재사용; `httpx.MockTransport`로 어댑터의 wire-level 테스트 추가.

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
from aiopspilot.core.operator_memory import OperatorScope
from aiopspilot.core.quality_gate.gate import QualityCandidate

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
[`rule-catalog/llm-registry.yaml`](../../rule-catalog/llm-registry.yaml)의
두 capability: `t2.critic` (upstream이 이미 선언) + `t1.judge`
(upstream이 이미 선언). `bind_azure_llm_bindings`가
`DebateOrchestrator`를 자동 생성하려면 fork의 `resolved-models.json`에
둘 다 포함되어야 함.

**바인딩 방법**: 두 capability가 `resolved-models.json`에 나타나도록
지역별 카탈로그 fixture에 대해 LLM resolver CLI 실행. Upstream CLI는
[`src/aiopspilot/rule_catalog/schema/llm_resolver_cli.py`](../../src/aiopspilot/rule_catalog/schema/llm_resolver_cli.py)에
위치; 다음처럼 호출: `uv run python -m aiopspilot.rule_catalog.schema.llm_resolver_cli
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
[prompt-composition.md § Wave 4.5 delta-2a](prompt-composition-ko.md#wave-45-delta-2a---무엇이-배포되었나)
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
  Exemption workflow ([`rule-catalog/exemptions/`](../../rule-catalog/exemptions/)
  + [`docs/runbooks/exemption-workflow-ko.md`](../runbooks/exemption-workflow-ko.md))
  를 사용 - scope에 대해 rule을 억제하는 audit된, time-boxed 방식.
- Upstream rule의 동작 변경: fork-patch 하지 말고 upstream issue를
  열 것. Upstream rule catalog은 customer-agnostic; 그 동작에 대한
  customer-specific 변경은 upstream에 config knob이 필요하다는 신호.

**바인딩 방법**: 두 카탈로그를 load하고 concatenate하도록 composition
root 확장. `load_rule_catalog`는 `tuple[Rule, ...]` 반환:

```python
from pathlib import Path
from aiopspilot.core.tiers.t0_deterministic.index import RuleIndex
from aiopspilot.rule_catalog.schema.rule import load_rule_catalog

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

### 5.9 Risk overlay (Rego)

**언제 override**: 환경 / 고객별로 RiskGate ceiling을 조임 (Rego
overlay는 autonomy를 낮추기만 가능하고 절대 올릴 수 없음, per
[execution-model-ko.md § 통합 RiskGate](execution-model-ko.md#3-통합-riskgate)).

**현재 상태**: **Rego overlay wire는 execution-model 설계에
스코프되어 있지만 `src/aiopspilot/core/risk_gate/`의 RiskGate
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
| `CriticModel` / `JudgeModel` | HTTP 에러, quota | Raise; `DebateOrchestrator`가 catch하고 `debate_status="unresolved"` 반환 → HIL. |
| `WebSearchProvider` | HTTP 에러, timeout | `WebSearchResult(query=query, snippets=(), reasons=("<provider-error>",))` 반환. Raise 하지 말 것 - snippet은 보조 증거이지 gate가 아님. |
| `HilChannel.send` | 배달 실패 | Raise; upstream이 로그하고 audit trail이 승인을 `dispatch_failed`로 표시. 액션은 pending 유지; auto-execute 없음. |
| `HilChannel.poll` | 백엔드 unreachable | Raise; upstream이 다음 tick에서 승인을 `pending`으로 유지. |
| `OperatorMemoryStore` | 쓰기 시 DB down | Raise; materializer가 second-approver 레코드를 rollback하고 reject는 audit-only 이벤트로 유지. |
| `OperatorMemoryStore` | 읽기 시 DB down | `()` 반환; composer는 빈 operator-memory 블록으로 진행. Prompt composition은 빈 store에서 survive 해야 함. |
| `SecretProvider.get` | Secret missing / KV down | `SecretNotFoundError` raise; 시작 시 fail-fast. Missing secret은 절대 조용히 default되지 않음. |
| `ScopeResolver` | 리소스 ref 파싱 불가 | `None` 반환; materializer는 그 이벤트에 대해 operator-memory 첨부를 skip하지만 액션 자체는 block되지 않음. |

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
from aiopspilot.core.web_search import WebSearchProvider

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

## 6. Upstream sync 절차

Fork는 upstream `main`을 스케줄로 pull하여 건강을 유지 (매주가 좋은
default). Fork가 `core/`를 절대 편집하지 않고 고객 값을 절대 커밋하지
않으므로, merge는 일반적으로 clean.

### 6.1 버전 pinning 전략

"upstream `main`을 매주 track"은 aspirational; 실무에서 fork는
**known-good upstream ref**에 pin하고 pin을 의도적으로 advance 해야
SHOULD. 수용 가능한 두 전략:

1. **Tag에 pin** (권장). Upstream은 milestone 경계에서 semver-adjacent
   태그를 컷. Fork의 `pyproject.toml`이 upstream 패키지에 의존한다면
   (또는 fork의 `git subtree` / submodule 포인터가) 그 태그를 참조.
   Pin advance는 리뷰된 PR: upstream CHANGELOG 읽기, fork 테스트 스위트
   실행, 그 다음 advance.
2. **`upstream/main`의 SHA에 pin** with stated cadence. 같은 아이디어,
   더 굵은 granularity. Upstream이 pre-1.0인 동안 적합.

**Breaking Protocol 변경**. Seam Protocol의 메서드 시그니처를 바꾸는
upstream 변경은 breaking으로 태그되지 않더라도 breaking 변경으로 다룸.
Upstream 정책은 한 release 동안 새 Protocol을 old와 함께 배포한 뒤
old를 제거; fork는 그 window 안에 마이그레이션을 완료해야 함. 모든
sync에서 `src/aiopspilot/shared/providers/**` +
`src/aiopspilot/composition.py` diff를 확인.

### 6.2 Sync 워크플로

```bash
# 일회성 설정
git remote add upstream https://github.com/dotnetpower/aiopspilot.git

# 매 sync
git fetch upstream --tags
git checkout main
git merge upstream/main            # 또는 rebase - 팀 선택
# Conflict 해결 (fork 규칙 준수 시 일반적으로 zero)
./scripts/check-english-only.sh    # sanity gate
./scripts/check-translations.sh
uv run pytest -q tests/ fork/tests/  # 전체 스위트
git push origin main
```

Merge가 `core/` 내부에 conflict를 landing하면, 이는 fork가 강한 규칙을
조용히 위반했다는 신호. Fork 측 편집을 revert하고, 변경을 composition
root 또는 어댑터로 이동, sync 재실행.

## 7. Anti-pattern

절대 하지 말 것. 이 중 어떤 것이든 merge-blocker:

- Fork 어디에든 **Azure tenant id, subscription id, 리소스 이름,
  endpoint, secret을 커밋**. 환경 또는 Key Vault에서 `SecretProvider`로
  로드. Upstream의 `check-guids.sh`는 `8-4-4-4-12` GUID 형식만 catch -
  고객 리소스 이름, hostname, bearer 토큰은 catch 하지 못합니다. Fork는
  자체 regex gate + OSS secret scanner를 layer 해야 함 (§2 항목 4 참조).
- **`src/aiopspilot/core/**` 또는 `src/aiopspilot/composition.py` 파일을
  in-place 수정**. Fork는 이 모듈들에서 `import`해야 하지만 (그것이
  seam의 요점), 편집해서는 안 됩니다. 모든 커스터마이제이션은
  `default_container(...)`가 반환한 컨테이너에 `dataclasses.replace()`를
  거쳐 감. [유일한 강한 규칙](#3-유일한-강한-규칙) 참조.
- **`rule-catalog/schema/**` 편집**. 스키마를 넓히지 말고 fork 고유
  id namespace 하에 새 카탈로그 entry 추가로 확장.
- **CI를 green으로 만들기 위해 upstream 테스트 비활성화**. Upstream
  테스트가 fork를 block하면 upstream 설계 변경이 필요하다는 신호 -
  issue 열기.
- **shadow mode 없이 fork-added action을 자동 실행**. Shadow-before-
  enforce invariant는 fork-added ActionType에도 upstream ActionType에
  적용되는 것과 정확히 동일하게 적용.
- **고객 identity를 담은 변경을 back-contribute**. Fork에서 upstream으로
  가는 모든 PR은 고객 이름, id, endpoint, private 데이터셋 참조가
  반드시 scrub됨.
- 페어링된 English 소스의 `translation_source_sha`를 업데이트하지 않고
  **`-ko.md` 번역 커밋**. Upstream의 `check-translations.sh` 게이트는
  fork-added user-facing 문서에도 적용됨.

## 8. 다음 단계

- [project-structure-ko.md § Customization via Dependency Injection](project-structure-ko.md#customization-via-dependency-injection) -
  이 가이드가 operational 화하는 DI seam 카탈로그.
- [architecture.instructions.md](../../.github/instructions/architecture.instructions.md) -
  T0/T1/T2 trust router, quality gate, risk gate, fork의 rule이 흘러
  들어가는 living-rules discovery 루프 (`.github/**`는 English-only).
- [coding-conventions.instructions.md](../../.github/instructions/coding-conventions.instructions.md) -
  Safety invariant, shadow-mode default, async-Protocol 계약, fork가
  상속하는 docs-first + docs-after 규칙 (`.github/**`는 English-only).
- [deploy-and-onboard-ko.md](deploy-and-onboard-ko.md) - Fork가
  프로비저닝하는 Azure 리소스 인벤토리 (Container Apps, Event Hubs,
  Postgres, Key Vault, ...).
- [prompt-composition-ko.md](prompt-composition-ko.md) - Evolving system
  prompt의 전체 설계 (Base + Task Pack + Tool Manifest + Operator
  Memory + Debate).
- [csp-neutrality-ko.md](csp-neutrality-ko.md) - Fork가 Azure 리소스
  레이어를 대체 구현으로 교체하는 방법.
- [`docs/runbooks/`](../runbooks/) - Fork의 on-call이 실행하는 운영
  절차 (exemption workflow, HIL escalation, rollback, incident replay).
  Fork-specific runbook은 `fork/runbooks/` 아래 두고 upstream 템플릿을
  참조.
- [generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md) -
  모든 fork가 준수하는 customer-agnostic 스코프 계약.
