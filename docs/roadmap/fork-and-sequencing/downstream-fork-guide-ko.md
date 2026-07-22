---
title: Downstream Fork 가이드
translation_of: downstream-fork-guide.md
translation_source_sha: 6a97e5c1869a84fa4f17b3aea92a3eb7d459f600
translation_revised: 2026-07-22
---

# Downstream Fork 가이드

Downstream FDAI distribution을 만들고 동기화 상태를 유지하며 지원되는 seam을 통해 capability를
제한하거나 확장하는 방법입니다. **Fork 유지관리자**를 위한 단일 진입점입니다. Fork는
customization profile을 package하며 deployment, tenant, environment, production state가 아닙니다.

Upstream 저장소는 의도적으로 generic하고 customer-agnostic 합니다
([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).
Fork에는 generic으로 유지할 수 없는 downstream adapter implementation, catalog 또는 presentation
overlay가 들어갑니다. Deployment value, tenant identity, secret, environment, promotion state는
deployment configuration 또는 secret store에 남습니다. 아래 규칙은 fork가 conflict 없이
upstream과 sync하고 upstream history에 customer value가 들어가지 않게 합니다.

전제 조건: DI seam 카탈로그를 먼저
[project-structure.md § Customization via Dependency Injection](../architecture/project-structure-ko.md#customization-via-dependency-injection)에서
읽고, 이 가이드 전반에서 참조하는 T0/T1/T2 trust router와 quality-
gate 개념은
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)를
읽으세요 (`.github/**`는 English-only). 독립적인 runtime 및 customization 축은
[ADR-0002](../architecture/decisions/0002-independent-runtime-axes-ko.md)를 읽으세요. 이 문서는
그 참조를 절차적 recipe로 바꿉니다.

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
[coding-conventions.instructions.md § Safety](../../../.github/instructions/coding-conventions.instructions.md#safety)에
정의됨 (`.github/**`는 English-only).

## 1. Fork 모델 한눈에

- **Upstream** = 이 저장소. Generic한 컨트롤 플레인 (core engine, DI
  seam, 기본 비활성 fake, 카탈로그 스키마) 배포.
- **Fork** = 선택적인 downstream distribution. 지원되는 seam으로 적용하는 concrete adapter와
  capability, catalog, policy, presentation overlay를 포함합니다.
- **Deployment** = upstream 또는 fork의 running instance입니다. Tenant identity, secret reference,
  resource scope, environment, promotion state를 source control 밖에서 제공합니다.
- **기여 방향**: upstream은 fork에서 절대 pull하지 않음. Fork가
  개선을 위해 upstream `main`에서 pull. Fork가 모든 고객에게 유용한
  변경을 만들면, 그 변경은 **고객 값이 제거**되고 독립적인 upstream
  PR로 배포됩니다.

각 축은 독립 상태를 유지합니다.

| 축 | 예 | Fork가 선택하나요? |
|----|----|---------------------|
| Distribution | upstream, downstream fork | 예, source/package boundary만 선택 |
| Deployment environment | dev, staging, production | 아니요 |
| Evidence profile | authoritative, fixture | 아니요 |
| Autonomy | capability별 shadow, enforce | 아니요 |
| Human 및 executor identity | Entra App Role, Managed Identity | 아니요 |

하나의 fork는 deployment가 없거나 서로 다른 environment에 여러 deployment가 있을 수 있습니다.
Upstream도 직접 deploy할 수 있습니다. `.fdai-fork`, `FDAI_FORK`, `git config fdai.fork true`는
repository-integrity 검사만 활성화하며 runtime code는 이 값을 기준으로 분기하면 안 됩니다.

## 2. Day-1 체크리스트

Fork에서 첫 `git commit` 전에 이것들을 하세요.

1. **Fresh clone에서 baseline이 green인지 확인**: `uv sync` 후
   `uv run pytest -q`. 손대지 않은 checkout에서 upstream 테스트 스위트가
   fail하면 fork 코드 추가 전에 멈추고 진단 - fork는 red baseline을
   절대 상속하지 말 것.
2. **구별되는 기본 브랜치 이름으로 clone** (선택적이지만 권장):
  `fork/main` 또는 `distribution/main` - `git push`가 실수로 upstream을
   대상으로 하지 않도록.
3. **`git remote -v` 확인**: `origin`이 `dotnetpower/fdai`이
   아니라 fork 저장소를 가리켜야 함. 한 번 실수하면 고객 커밋이
   upstream으로 leak될 가능성이 있음.
4. **Fork의 CI에서 secret scanning 활성화** - upstream의
   `scripts/quality/repository/check-punctuation.sh`,
   `scripts/quality/repository/check-guids.sh`, `scripts/quality/architecture/check-core-imports.sh`,
   `scripts/quality/localization/check-translations.sh` 재사용. **이것만으로는
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
   `fdai.shared.providers.secret_provider.SecretProvider`를
   경유 - Protocol 계약이 값의 로그 기록 / 영속을 금지.
6. Fork-owned 모듈을 위한 **`fork/` 최상위 디렉터리 생성**. 여기가
  composition-root override, 어댑터, rule 추가가 사는
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
   https://github.com/dotnetpower/fdai.git`. 첫 divergence 전에
   [Upstream sync 절차](#upstream-sync-절차)를 한 번 rehearsal.

## 3. 유일한 강한 규칙

**`src/fdai/core/` 아래 파일을 절대 편집하지 마세요.** 지원되는 customization 경로는
seam을 사용합니다. `core/`를 편집하고
싶어질 때, 둘 중 하나가 일어나고 있는 것입니다:

1. Configuration이나 fake에 속하는 값을 주입하려 함. 이미 존재하는
   seam을 찾으세요.
2. Upstream 설계에 진짜 gap을 발견함. Upstream issue를 열거나 fork-
   local wrapper로 `core/`를 patch하지 않고 감싸는 변경을 배포하세요.
   그 후 wrapper를 scrub해서 upstream에 기여.

이 규칙은 세 invariant로 강제됩니다:

- Upstream의 `scripts/quality/architecture/check-core-imports.sh`가 `delivery/*` 또는
  클라우드 SDK에서 import하는 `core/` 파일을 거부.
- Upstream의 `scripts/integrity/check-protected-paths.sh`가 변경된 파일을
  검사해 framework surface - `src/fdai/core/`,
  `src/fdai/composition/`, `src/fdai/shared/providers/`,
  `src/fdai/shared/contracts/`, `src/fdai/agents/`,
  `rule-catalog/schema/`, `.github/instructions/` - 편집을 경고
  (upstream)하거나 **하드 차단(fork)** 합니다. Fork는 `FDAI_FORK=1`
  (로컬 셸), **커밋된** `.fdai-fork` marker 파일(트리에 따라가므로
  CI의 신뢰 신호 - env var는 그렇지 않음), 또는
  `git config fdai.fork true`로 차단 모드를 켭니다; 가드는 pre-push
  훅과 `protected-paths` CI job으로 실행되며, 후자는 PR Files 탭에
  파일별 `::warning::` annotation도 남깁니다.
- Composition root
  ([`src/fdai/composition/`](../../../src/fdai/composition))가
  `shared/providers/`의 Protocol에 구체적 구현이 바인딩되는 유일한
  곳. Fork는 자체 composition root를 씀; 이 파일을 편집하지 않음.
  `.github/CODEOWNERS`가 리뷰 시점의 대응물입니다: framework surface
  경로는 owners 팀으로 라우팅됩니다.
- **서명된 무결성 매니페스토**로 framework surface 변조를 OFFLINE에서
  탐지합니다. Upstream이
  [`security/integrity/manifest.json`](../../../security/integrity/manifest.json)
  (모든 framework-surface 파일의 SHA-256 맵)을 Ed25519 키로 서명하며,
  공개키는 트리에 동봉됩니다
  ([`upstream-signing-key.pub`](../../../security/integrity/upstream-signing-key.pub)).
  [`scripts/integrity/check-integrity.sh`](../../../scripts/integrity/check-integrity.sh)가
  surface를 다시 해싱하고 서명을 검증하는데 **네트워크도, OCSP도,
  인증서 체인도 필요 없습니다** - air-gapped 친화적입니다. 두 가지를
  독립적으로 보고합니다: **서명(signature)** 실패(위조되거나 손상된
  매니페스토 - 항상 오류입니다. Fork는 upstream 개인키 없이는 유효한
  매니페스토를 만들 수 없기 때문입니다)와 **콘텐츠(content)**
  불일치(편집/추가/삭제된 surface 파일 - fork 모드에서는 하드 실패,
  upstream에서는 권고). surface 목록의 단일 소스는
  [`scripts/lib/framework-surface.txt`](../../../scripts/lib/framework-surface.txt)이며,
  가드와 매니페스토가 어긋나지 않도록 `check-protected-paths.sh`와
  공유합니다. 이것은 변조 **증거(evidence)**이지 변조 **불가(proof)**가
  아닙니다: fork 소유자는 여전히 자기 런타임을 통제하며 검증기 자체를
  지울 수 있으므로, 신뢰의 강제는 궁극적으로 fork가 편집할 수 있는
  파일이 아니라 upstream이 통제하는 게이트의 몫입니다.

체크아웃을 언제든 오프라인으로 검증하려면:

```bash
scripts/integrity/check-integrity.sh        # 서명 + 콘텐츠, 완전 오프라인
```

`scripts/verify.sh`의 `framework-integrity` 게이트가 서명된 매니페스토가
존재하면 이를 자동으로 실행합니다.

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
`fdai`로 import 가능하다고 가정.

Per-seam 조리서는 별도 파일에 위치:
[downstream-fork-seam-recipes-ko.md](downstream-fork-seam-recipes-ko.md).
Recipe는 bind 순서로 정렬 (ObjectType이 이를 참조하는 Rule 전에,
ActionType이 이를 이름 지정하는 Rule 전에 landing):

| Recipe | 주제 |
|--------|------|
| [5.1](downstream-fork-seam-recipes-ko.md#51-azure-openai-어댑터-llmbindings) | Azure OpenAI 어댑터 (`LlmBindings`) |
| [5.2](downstream-fork-seam-recipes-ko.md#52-operatormemorystore-in-memory--postgres--custom) | `OperatorMemoryStore` (in-memory / Postgres / custom) |
| [5.3](downstream-fork-seam-recipes-ko.md#53-hilrejectmaterializer--second-approval-채널) | `HilRejectMaterializer` + second-approval 채널 |
| [5.4](downstream-fork-seam-recipes-ko.md#54-websearchprovider) | `WebSearchProvider` |
| [5.5](downstream-fork-seam-recipes-ko.md#55-hilchannel-teams--slack--custom) | `HilChannel` (Teams / Slack / custom) |
| [5.6](downstream-fork-seam-recipes-ko.md#56-scoperesolver-arm-id---operatorscope) | `ScopeResolver` (ARM id -> `OperatorScope`) |
| [5.7](downstream-fork-seam-recipes-ko.md#57-criticmodel--judgemodel-debate-활성화) | `CriticModel` + `JudgeModel` (debate 활성화) |
| [5.8](downstream-fork-seam-recipes-ko.md#58-rule-catalog-추가) | Rule catalog 추가 |
| [5.8a](downstream-fork-seam-recipes-ko.md#58a-ontology-objecttype--linktype-추가) | Ontology `ObjectType` / `LinkType` 추가 |
| [5.9](downstream-fork-seam-recipes-ko.md#59-risk-overlay-rego) | Risk overlay (Rego) |
| [5.10](downstream-fork-seam-recipes-ko.md#510-런타임-실패-모드와-abstain-계약) | 런타임 실패 모드와 abstain 계약 |
| [5.11](downstream-fork-seam-recipes-ko.md#511-fork-end-to-end-테스트) | Fork end-to-end 테스트 |
| [5.12](downstream-fork-seam-recipes-ko.md#512-actiontype-카탈로그-추가) | `ActionType` 카탈로그 추가 |
| [5.13](downstream-fork-seam-recipes-ko.md#513-delivery-adapter-커스텀-publisher) | Delivery, incident-platform, on-call provider binding |
| [5.14](downstream-fork-seam-recipes-ko.md#514-console-readpanel-추가) | Console `ReadPanel` 추가 |
| [5.15](downstream-fork-seam-recipes-ko.md#515-fork-진입점-entrypy) | Fork 진입점 (`entry.py`) |
| [5.16](downstream-fork-seam-recipes-ko.md#516-매뉴얼-증류-manualsource--manualclassifier--distiller) | 매뉴얼 증류 (`ManualSource` / `ManualClassifier` / `Distiller`) |
| [5.17](downstream-fork-seam-recipes-ko.md#517-capability-bundle-등록) | `CapabilityBundle` 등록과 시작 시 cross-validation |

**새 비즈니스-오브젝트 vertical 구축**: non-Resource ObjectType
lifecycle (아키텍처-리뷰 proposal, compliance-attestation 레코드,
incident-postmortem workflow)을 추가하는 fork에는
[downstream-fork-example-vertical-ko.md](downstream-fork-example-vertical-ko.md)
에 stitch된 walkthrough가 있음. Generic `GovernanceProposal` 예시를
사용하고 위의 모든 recipe를 필요 순서로 cross-reference.

**Copy-ready shipped 예제**: upstream에 더 작은 end-to-end reference도
배포됨 - **`ops.change-summary`** on-demand `resource-group` 변경 요약
생성기. 6개 파일 (ObjectType `ChangeSummary`, LinkType `summarizes`,
ActionType `ops.publish-change-summary`, rule `ops.change-summary`, Rego,
Markdown 템플릿)과 1개 테스트 파일
([`tests/verticals/test_change_summary_example.py`](../../../tests/verticals/test_change_summary_example.py))
이 최소 작동 scaffold를 구성. Fork는 6개 파일을 복사해 자기 비즈니스
오브젝트로 rename 하면 lifecycle 추가 전에 이미 green baseline. 위 walkthrough는
workflow가 reviewer와 multi-step 승인을 필요로 할 때 그 위에 무엇이 자라는지
보여줌.

**Contract 모델 확장 (드물게)**: 일곱 개 도메인 contract 모듈은
[`src/fdai/shared/contracts/models/`](../../../src/fdai/shared/contracts/models)
아래에 있으며 (`event.py` / `action.py` / `rule.py` / `incident.py` /
`ontology.py` / `workflow.py` / `document.py`), 전부 패키지 파사드에서 re-export 됩니다.
포크가 정당하게 bespoke contract를 필요로 한다면 `ContractBase` (내부
`_Base` 의 공개 별칭) 를 상속하세요. 네 가지 invariant (`extra=forbid`,
`frozen`, `str_strip_whitespace`, `validate_default`) 를 `model_config`
재선언 없이 상속받습니다:

```python
from fdai.shared.contracts.models import ContractBase, SemVer

class ForkAuditNote(ContractBase):
    schema_version: SemVer
    note_text: str
```

Upstream 모델은 편집 **금지** ([`check-protected-paths.sh`](../../../scripts/integrity/check-protected-paths.sh))
로 가드되는 framework surface). 포크는 자기 자신의 패키지 하위에 서브
모듈을 추가하세요.

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
sync에서 `src/fdai/shared/providers/**` +
`src/fdai/composition/` diff를 확인.

### 6.2 Sync 워크플로

```bash
# 일회성 설정
git remote add upstream https://github.com/dotnetpower/fdai.git

# 매 sync
git fetch upstream --tags
git checkout main
git merge upstream/main            # 또는 rebase - 팀 선택
# Conflict 해결 (fork 규칙 준수 시 일반적으로 zero)
./scripts/quality/repository/check-punctuation.sh     # sanity gate
./scripts/quality/localization/check-translations.sh
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
- **`src/fdai/core/**` 또는 `src/fdai/composition/` 파일을
  in-place 수정**. Fork는 이 모듈들에서 `import`해야 하지만 (그것이
  seam의 요점), 편집해서는 안 됩니다. 모든 커스터마이제이션은
  `default_container(...)`가 반환한 컨테이너에 `dataclasses.replace()`를
  거쳐 감. [유일한 강한 규칙](#3-유일한-강한-규칙) 참조.
- **`rule-catalog/schema/**` 편집**. 스키마를 넓히지 말고 fork 고유
  id namespace 하에 새 카탈로그 entry 추가로 확장.
- **CI를 green으로 만들기 위해 upstream 테스트 비활성화**. Upstream
  테스트가 fork를 block하면 upstream 설계 변경이 필요하다는 신호 -
  issue 열기.
- **관찰 모드 없이 fork-added action을 자동 실행**. Shadow-before-
  enforce invariant는 fork-added ActionType에도 upstream ActionType에
  적용되는 것과 정확히 동일하게 적용.
- **고객 identity를 담은 변경을 back-contribute**. Fork에서 upstream으로
  가는 모든 PR은 고객 이름, id, endpoint, private 데이터셋 참조가
  반드시 scrub됨.
- 페어링된 English 소스의 `translation_source_sha`를 업데이트하지 않고
  **`-ko.md` 번역 커밋**. Upstream의 `check-translations.sh` 게이트는
  fork-added user-facing 문서에도 적용됨.

## 8. 다음 단계

- [project-structure-ko.md § Customization via Dependency Injection](../architecture/project-structure-ko.md#customization-via-dependency-injection) -
  이 가이드가 operational 화하는 DI seam 카탈로그.
- [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) -
  T0/T1/T2 trust router, quality gate, risk gate, fork의 rule이 흘러
  들어가는 living-rules discovery 루프 (`.github/**`는 English-only).
- [coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md) -
  Safety invariant, shadow-mode default, async-Protocol 계약, fork가
  상속하는 docs-first + docs-after 규칙 (`.github/**`는 English-only).
- [deploy-and-onboard-ko.md](../deployment/deploy-and-onboard-ko.md) - Fork가
  프로비저닝하는 Azure 리소스 인벤토리 (Container Apps, Event Hubs,
  Postgres, Key Vault, ...).
- [prompt-composition-ko.md](../decisioning/prompt-composition-ko.md) - Evolving system
  prompt의 전체 설계 (Base + Task Pack + Tool Manifest + Operator
  Memory + Debate).
- [csp-neutrality-ko.md](../architecture/csp-neutrality-ko.md) - Fork가 Azure 리소스
  레이어를 대체 구현으로 교체하는 방법.
- [`docs/runbooks/`](../../runbooks) - Fork의 on-call이 실행하는 운영
  절차 (exemption workflow, HIL escalation, rollback, incident replay).
  Fork-specific runbook은 `fork/runbooks/` 아래 두고 upstream 템플릿을
  참조.
- [generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md) -
  모든 fork가 준수하는 customer-agnostic 스코프 계약.
