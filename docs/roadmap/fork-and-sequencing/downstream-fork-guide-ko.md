---
title: Downstream Fork 가이드
translation_of: downstream-fork-guide.md
translation_source_sha: 14a3e993c7ada844739309413069447743b9746f
translation_revised: 2026-08-11
---

# 다운스트림 포크 가이드

다운스트림 FDAI 분포를 만들고 동기화 상태를 유지하며 지원되는 경계를 통해 기능을
제한하거나 확장하는 방법입니다. **포크 유지관리자**를 위한 단일 진입점입니다. 포크는
customization 프로파일을 패키지하며 배포, 테넌트, 환경, 운영 상태가 아닙니다.

업스트림 저장소는 의도적으로 범용하고 customer-agnostic 합니다
([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).
포크에는 범용으로 유지할 수 없는 다운스트림 어댑터 구현, 카탈로그 또는 표현
오버레이가 들어갑니다. 배포 값, 테넌트 신원, 시크릿, 환경, 승격 상태는
배포 구성 또는 시크릿 저장소에 남습니다. 아래 규칙은 포크가 충돌 없이
업스트림과 sync하고 업스트림 이력에 customer 값이 들어가지 않게 합니다.

전제 조건: DI 경계 카탈로그를 먼저
[project-structure.md § Customization via 의존성 주입](../architecture/project-structure-ko.md#customization-via-dependency-injection)에서
읽고, 이 가이드 전반에서 참조하는 T0/T1/T2 trust 라우터와 quality-
게이트 개념은
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)를
읽으세요 (`.github/**`는 English-only). 독립적인 런타임 및 customization 축은
[ADR-0002](../architecture/decisions/0002-independent-runtime-axes-ko.md)를 읽으세요. 이 문서는
그 참조를 절차적 recipe로 바꿉니다.

**목차**

1. [포크 모델 한눈에](#1-fork-모델-한눈에)
2. [Day-1 체크리스트](#2-day-1-체크리스트)
3. [유일한 강한 규칙](#3-유일한-강한-규칙)
4. [포크를 위한 저장소 레이아웃](#4-fork를-위한-저장소-레이아웃)
5. [경계 recipe](#5-seam-recipe)
 (LLM · OperatorMemoryStore · HilRejectMaterializer · WebSearch ·
 HilChannel · ScopeResolver · 비평자+Judge · Rule 카탈로그 · Rego
 오버레이 · 런타임 실패 모드 · 종단 간 테스트)
6. [업스트림 sync + 버전 pinning 전략](#6-upstream-sync-절차)
7. [Anti-pattern](#7-anti-pattern)
8. [다음 단계](#8-다음-단계)

**반복 용어.** "기본 비활성 가짜 (deny-by-default 가짜)" = 모든 호출에
대해 빈 / 거부를 반환하는 업스트림 in-memory 프로토콜 구현
(예: `NoOpWebSearchProvider`, `InMemoryHilChannel`) - 실제 어댑터
바인딩을 잊은 포크가 조용히 구멍을 열지 않고 안전하게 fail 하도록.
"Shadow-before-enforce" = 모든 새 ActionType은
`default_mode: shadow` (판단하고 로그만, 실행 없음)로 배포되고, 선언된
`promotion_gate`가 측정으로 green 확인된 뒤에만 `enforce`로 승격되는
불변식 -
[coding-conventions.instructions.md § 안전성](../../../.github/instructions/coding-conventions.instructions.md#safety)에
정의됨 (`.github/**`는 English-only).

포크가 추가한 모든 ActionType과 상태 변경 작업 흐름 단계는 헌법의 7개 안전조건을 모두
상속합니다. 프로바이더 연결, 카탈로그 항목, 환경 또는 포크 표시는 권한을 승격하거나
안전조건을 면제하거나 새 조합을 바로 강제 적용 모드로 바꾸지 않습니다.

## 1. 포크 모델 한눈에

- **업스트림** = 이 저장소. 범용한 컨트롤 플레인 (코어 엔진, DI
 경계, 기본 비활성 가짜, 카탈로그 스키마) 배포.
- **포크** = 선택적인 다운스트림 분포. 지원되는 경계로 적용하는 구체적인 어댑터와
 기능, 카탈로그, 정책, 표현 오버레이를 포함합니다.
- **배포** = 업스트림 또는 포크의 running 인스턴스입니다. 테넌트 신원, 시크릿 참조,
 리소스 범위, 환경, 승격 상태를 출처 컨트롤 밖에서 제공합니다.
- **기여 방향**: 업스트림은 포크에서 절대 pull하지 않음. 포크가
 개선을 위해 업스트림 `main`에서 pull. 포크가 모든 고객에게 유용한
 변경을 만들면, 그 변경은 **고객 값이 제거**되고 독립적인 업스트림
 PR로 배포됩니다.

각 축은 독립 상태를 유지합니다.

| 축 | 예 | 포크가 선택하나요? |
|----|----|---------------------|
| 분포 | 업스트림, 다운스트림 포크 | 예, 출처/패키지 경계만 선택 |
| 배포 환경 | dev, staging, 운영 | 아니요 |
| 근거 프로파일 | 권위 있는, 고정본 | 아니요 |
| 자율성 | 기능별 그림자, 강제 적용 | 아니요 |
| Human 및 실행기 신원 | Entra App 역할, Managed Identity | 아니요 |

하나의 포크는 배포가 없거나 서로 다른 환경에 여러 배포가 있을 수 있습니다.
업스트림도 직접 deploy할 수 있습니다. `.fdai-fork`, `FDAI_FORK`, `git config fdai.fork true`는
repository-integrity 검사만 활성화하며 런타임 코드는 이 값을 기준으로 분기하면 안 됩니다.

## 2. Day-1 체크리스트

포크에서 첫 `git commit` 전에 이것들을 하세요.

1. **Fresh clone에서 기준선이 green인지 확인**: `uv sync` 후
 `scripts/verify.sh --all`을 실행합니다. 이 fresh-clone 경계는 명시적인 전체
 리포지토리 검사입니다. 손대지 않은 체크아웃에서 업스트림 테스트 스위트가
 fail하면 포크 코드 추가 전에 멈추고 진단 - 포크는 red 기준선을
 절대 상속하지 말 것.
2. **구별되는 기본 브랜치 이름으로 clone** (선택적이지만 권장):
 `fork/main` 또는 `distribution/main` - `git push`가 실수로 업스트림을
 대상으로 하지 않도록.
3. **`git remote -v` 확인**: `origin`이 `dotnetpower/fdai`이
 아니라 포크 저장소를 가리켜야 함. 한 번 실수하면 고객 커밋이
 업스트림으로 leak될 가능성이 있음.
4. **포크의 CI에서 시크릿 검사 활성화** - 업스트림의
 `scripts/quality/repository/check-punctuation.sh`,
 `scripts/quality/repository/check-guids.sh`, `scripts/quality/architecture/check-core-imports.sh`,
 `scripts/quality/localization/check-translations.sh` 재사용. **이것만으로는
 충분하지 않습니다.** `check-guids.sh`는 `8-4-4-4-12` hex 형식에만
 매치 - 고객 리소스 이름, 엔드포인트, bearer 토큰 접두사, 짧은 계정
 id는 catch 하지 못합니다. Fork-specific 정규식 패턴 (같은 스타일의
 `check-customer-tokens.sh`)을 추가: 고객이 사용하는 리소스 이름
 접두사 (`acme-prod-*`), hostname 접미사 (`*.customer.example`),
 API 토큰 접두사 (있다면: `sk-...`, `xoxb-...`, `Bearer eyJ`),
 짧은 계정 id (12자리 AWS, 6-hex GCP project 접두사). OSS
 시크릿 scanner (`gitleaks`, `trufflehog`)도 함께 실행.
5. Azure 테넌트 / 구독 id, 고객 리소스 이름, 엔드포인트, 또는
 시크릿을 **절대 커밋하지 마세요**. 런타임에 환경 또는 Key Vault에서
 로드. 모든 SDK-family 시크릿 (API 키, 연결 문자열, 패스워드
 포함 DSN)은
 `fdai.shared.providers.secret_provider.SecretProvider`를
 경유 - 프로토콜 계약이 값의 로그 기록 / 영속을 금지.
6. Fork-owned 모듈을 위한 **`fork/` 최상위 디렉터리 생성**. 여기가
 composition-root 재정의, 어댑터, 룰 추가가 사는
 곳. `core/`는 100% 업스트림 유지.
7. **`pyproject.toml`에 포크 패키지 등록**: `fork/` 디렉터리를
 `[tool.setuptools.packages.find]` (또는 사용 중인 빌드 백엔드의
 대응 설정)에 추가하고, 프로세스 진입점을 `[project.scripts]`에
 등록. 업스트림 `pyproject`가 동작하는 기준선을 배포; 포크 편집은
 최소한의 delta.
8. **조립 루트를 wire**: 업스트림 `default_container(...)`를
 가져오기하고 포크가 소유한 경계를 swap하기 위해 `dataclasses.replace`를
 적용하는 얇은 Python 모듈. 프로세스 진입점을 업스트림의 `__main__`
 대신 이 모듈에서 가져오기하도록 이름 변경.
9. **업스트림 sync 설정**: `git 원격 add 업스트림
 https://github.com/dotnetpower/fdai.git`. 첫 divergence 전에
 [업스트림 sync 절차](#upstream-sync-절차)를 한 번 예행 연습.

## 3. 유일한 강한 규칙

**`services/core-control-plane/src/fdai/core/` 아래 파일을 절대 편집하지 마세요.** 지원되는 customization 경로는
경계를 사용합니다. `core/`를 편집하고
싶어질 때, 둘 중 하나가 일어나고 있는 것입니다:

1. 구성이나 가짜에 속하는 값을 주입하려 함. 이미 존재하는
 경계를 찾으세요.
2. 업스트림 설계에 진짜 공백을 발견함. 업스트림 issue를 열거나 fork-
 로컬 래퍼로 `core/`를 patch하지 않고 감싸는 변경을 배포하세요.
 그 후 래퍼를 scrub해서 업스트림에 기여.

이 규칙은 세 불변식으로 강제됩니다:

- 업스트림의 `scripts/quality/architecture/check-core-imports.sh`가 `delivery/*` 또는
 클라우드 SDK에서 가져오기하는 `core/` 파일을 거부.
- 업스트림의 `scripts/integrity/check-protected-paths.sh`가 변경된 파일을
 검사해 framework 표면 - `services/core-control-plane/src/fdai/core/`,
 `services/core-control-plane/src/fdai/composition/`, `services/core-control-plane/src/fdai/shared/providers/`,
 `services/core-control-plane/src/fdai/shared/contracts/`, `services/core-control-plane/src/fdai/agents/`,
 `rule-catalog/schema/`, `.github/instructions/` - 편집을 경고
 (업스트림)하거나 **하드 차단(포크)** 합니다. 포크는 `FDAI_FORK=1`
 (로컬 셸), **커밋된** `.fdai-fork` 표시 파일(트리에 따라가므로
 CI의 신뢰 신호 - env var는 그렇지 않음), 또는
 `git config fdai.fork true`로 차단 모드를 켭니다; 가드는 pre-push
 훅과 `protected-paths` CI 작업으로 실행되며, 후자는 PR Files 탭에
 파일별 `::warning::` annotation도 남깁니다.
- 조립 루트
 ([`services/core-control-plane/src/fdai/composition/`](../../../services/core-control-plane/src/fdai/composition))가
 `shared/providers/`의 프로토콜에 구체적 구현이 바인딩되는 유일한
 곳. 포크는 자체 조립 루트를 씀; 이 파일을 편집하지 않음.
 `.github/CODEOWNERS`가 리뷰 시점의 대응물입니다: framework 표면
 경로는 owners 팀으로 라우팅됩니다.
- **서명된 무결성 매니페스토**로 framework 표면 변조를 OFFLINE에서
 탐지합니다. 업스트림이
 [`security/integrity/manifest.json`](../../../security/integrity/manifest.json)
 (모든 framework-surface 파일의 SHA-256 맵)을 Ed25519 키로 서명하며,
 공개키는 트리에 동봉됩니다
 ([`upstream-signing-key.pub`](../../../security/integrity/upstream-signing-key.pub)).
 [`scripts/integrity/check-integrity.sh`](../../../scripts/integrity/check-integrity.sh)가
 표면을 다시 해싱하고 서명을 검증하는데 **네트워크도, OCSP도,
 인증서 체인도 필요 없습니다** - air-gapped 친화적입니다. 두 가지를
 독립적으로 보고합니다: **서명(서명)** 실패(위조되거나 손상된
 매니페스토 - 항상 오류입니다. 포크는 업스트림 개인키 없이는 유효한
 매니페스토를 만들 수 없기 때문입니다)와 **콘텐츠(내용)**
 불일치(편집/추가/삭제된 표면 파일 - 포크 모드에서는 하드 실패,
 업스트림에서는 권고). 표면 목록의 단일 소스는
 [`scripts/lib/framework-surface.txt`](../../../scripts/lib/framework-surface.txt)이며,
 가드와 매니페스토가 어긋나지 않도록 `check-protected-paths.sh`와
 공유합니다. 이것은 변조 **증거(근거)**이지 변조 **불가(증명)**가
 아닙니다: 포크 소유자는 여전히 자기 런타임을 통제하며 검증기 자체를
 지울 수 있으므로, 신뢰의 강제는 궁극적으로 포크가 편집할 수 있는
 파일이 아니라 업스트림이 통제하는 게이트의 몫입니다.

체크아웃을 언제든 오프라인으로 검증하려면:

```bash
scripts/integrity/check-integrity.sh  # 서명 + 콘텐츠, 완전 오프라인
```

`scripts/verify.sh`의 `framework-integrity` 게이트가 서명된 매니페스토가
존재하면 이를 자동으로 실행합니다.

## 4. 포크를 위한 저장소 레이아웃

권장 형태:

```
customer-x-fork/
 fork/
 __init__.py
 composition_root.py # upstream default_container() + replace() 호출
 entry.py    # 고객 프로세스 진입 (upstream의 __main__.py 대체)
 adapters/
  web_search.py  # 구체적 WebSearchProvider
  hil_channel.py  # 구체적 HilChannel (Teams / Slack)
  scope_resolver.py # ARM-id -> OperatorScope 파서
 rules/
  customer.yaml  # 고객별 rule catalog 추가
 overlays/
  risk_gate.rego  # 고객별 risk ceiling overlay
 <upstream tree, 변경 없음>
```

`fork/` 아래 모든 것이 고객 소유. 업스트림 파일은 byte-identical 유지,
단 `pyproject.toml` 예외 (포크는 자체 패키지 + 진입점 추가 가능).

## 5. 경계 recipe

각 recipe는 동일한 형태: **언제 재정의할지**, **경계**, **바인딩
방법**, **테스트 방법**. 모든 스니펫은 Python 3.12+와 업스트림 패키지가
`fdai`로 가져오기 가능하다고 가정.

Per-seam 조리서는 별도 파일에 위치:
[downstream-fork-seam-recipes-ko.md](downstream-fork-seam-recipes-ko.md).
Recipe는 연결 순서로 정렬 (ObjectType이 이를 참조하는 Rule 전에,
ActionType이 이를 이름 지정하는 Rule 전에 landing):

| Recipe | 주제 |
|--------|------|
| [5.1](downstream-fork-seam-recipes-ko.md#51-azure-openai-어댑터-llmbindings) | Azure OpenAI 어댑터 (`LlmBindings`) |
| [5.2](downstream-fork-seam-recipes-ko.md#52-operatormemorystore-in-memory--postgres--custom) | `OperatorMemoryStore` (in-memory / Postgres / custom) |
| [5.3](downstream-fork-seam-recipes-ko.md#53-hilrejectmaterializer--second-approval-채널) | `HilRejectMaterializer` + second-approval 채널 |
| [5.4](downstream-fork-seam-recipes-ko.md#54-websearchprovider) | `WebSearchProvider` |
| [5.5](downstream-fork-seam-recipes-ko.md#55-hilchannel-teams--slack--custom) | `HilChannel` (Teams / Slack / custom) |
| [5.6](downstream-fork-seam-recipes-ko.md#56-scoperesolver-arm-id---operatorscope) | `ScopeResolver` (ARM id -> `OperatorScope`) |
| [5.7](downstream-fork-seam-recipes-ko.md#57-criticmodel--judgemodel-debate-활성화) | `CriticModel` + `JudgeModel` (토론 활성화) |
| [5.8](downstream-fork-seam-recipes-ko.md#58-rule-catalog-추가) | Rule 카탈로그 추가 |
| [5.8a](downstream-fork-seam-recipes-ko.md#58a-ontology-objecttype--linktype-추가) | 온톨로지 `ObjectType` / `LinkType` 추가 |
| [5.9](downstream-fork-seam-recipes-ko.md#59-risk-overlay-rego) | Risk 오버레이 (Rego) |
| [5.10](downstream-fork-seam-recipes-ko.md#510-런타임-실패-모드와-abstain-계약) | 런타임 실패 모드와 abstain 계약 |
| [5.11](downstream-fork-seam-recipes-ko.md#511-fork-end-to-end-테스트) | 포크 종단 간 테스트 |
| [5.12](downstream-fork-seam-recipes-ko.md#512-actiontype-카탈로그-추가) | `ActionType` 카탈로그 추가 |
| [5.13](downstream-fork-seam-recipes-ko.md#513-delivery-adapter-커스텀-publisher) | 전달, incident-platform, on-call 프로바이더 연결 |
| [5.14](downstream-fork-seam-recipes-ko.md#514-console-readpanel-추가) | Console `ReadPanel` 추가 |
| [5.15](downstream-fork-seam-recipes-ko.md#515-fork-진입점-entrypy) | 포크 진입점 (`entry.py`) |
| [5.16](downstream-fork-seam-recipes-ko.md#516-매뉴얼-증류-manualsource--manualclassifier--distiller) | 매뉴얼 증류 (`ManualSource` / `ManualClassifier` / `Distiller`) |
| [5.17](downstream-fork-seam-recipes-ko.md#517-capability-bundle-등록) | `CapabilityBundle` 등록과 시작 시 cross-validation |

**새 비즈니스-오브젝트 버티컬 구축**: non-Resource ObjectType
수명 주기 (아키텍처-리뷰 제안, compliance-attestation 레코드,
incident-postmortem 작업 흐름)을 추가하는 포크에는
[downstream-fork-example-vertical-ko.md](downstream-fork-example-vertical-ko.md)
에 stitch된 walkthrough가 있음. 범용 `GovernanceProposal` 예시를
사용하고 위의 모든 recipe를 필요 순서로 cross-reference.

**Copy-ready shipped 예제**: 업스트림에 더 작은 종단 간 참조도
배포됨 - **`ops.change-summary`** on-demand `resource-group` 변경 요약
생성기. 6개 파일 (ObjectType `ChangeSummary`, LinkType `summarizes`,
ActionType `ops.publish-change-summary`, 룰 `ops.change-summary`, Rego,
Markdown 템플릿)과 1개 테스트 파일
([`services/core-control-plane/tests/verticals/test_change_summary_example.py`](../../../services/core-control-plane/tests/verticals/test_change_summary_example.py))
이 최소 작동 scaffold를 구성. 포크는 6개 파일을 복사해 자기 비즈니스
오브젝트로 이름 변경 하면 수명 주기 추가 전에 이미 green 기준선. 위 walkthrough는
작업 흐름이 검토자와 multi-step 승인을 필요로 할 때 그 위에 무엇이 자라는지
보여줌.

**계약 모델 확장 (드물게)**: 일곱 개 도메인 계약 모듈은
[`services/core-control-plane/src/fdai/shared/contracts/models/`](../../../services/core-control-plane/src/fdai/shared/contracts/models)
아래에 있으며 (`event.py` / `action.py` / `rule.py` / `incident.py` /
`ontology.py` / `workflow.py` / `document.py`), 전부 패키지 파사드에서 re-export 됩니다.
포크가 정당하게 bespoke 계약을 필요로 한다면 `ContractBase` (내부
`_Base` 의 공개 별칭) 를 상속하세요. 네 가지 불변식 (`extra=forbid`,
`frozen`, `str_strip_whitespace`, `validate_default`) 를 `model_config`
재선언 없이 상속받습니다:

```python
from fdai.shared.contracts.models import ContractBase, SemVer

class ForkAuditNote(ContractBase):
 schema_version: SemVer
 note_text: str
```

업스트림 모델은 편집 **금지** ([`check-protected-paths.sh`](../../../scripts/integrity/check-protected-paths.sh))
로 가드되는 framework 표면). 포크는 자기 자신의 패키지 하위에 서브
모듈을 추가하세요.

## 6. 업스트림 sync 절차

포크는 업스트림 `main`을 스케줄로 pull하여 건강을 유지 (매주가 좋은
기본값). 포크가 `core/`를 절대 편집하지 않고 고객 값을 절대 커밋하지
않으므로, 병합은 일반적으로 clean.

### 6.1 버전 pinning 전략

"업스트림 `main`을 매주 track"은 aspirational; 실무에서 포크는
**known-good 업스트림 참조**에 pin하고 pin을 의도적으로 advance 해야
SHOULD. 수용 가능한 두 전략:

1. **Tag에 pin** (권장). 업스트림은 이정표 경계에서 semver-adjacent
 태그를 컷. 포크의 `pyproject.toml`이 업스트림 패키지에 의존한다면
 (또는 포크의 `git subtree` / submodule 포인터가) 그 태그를 참조.
 Pin advance는 리뷰된 PR: 업스트림 CHANGELOG 읽기, 포크 테스트 스위트
 실행, 그 다음 advance.
2. **`upstream/main`의 SHA에 pin** with stated cadence. 같은 아이디어,
 더 굵은 granularity. 업스트림이 pre-1.0인 동안 적합.

**Breaking 프로토콜 변경**. 경계 프로토콜의 메서드 시그니처를 바꾸는
업스트림 변경은 breaking으로 태그되지 않더라도 breaking 변경으로 다룸.
업스트림 정책은 한 release 동안 새 프로토콜을 old와 함께 배포한 뒤
old를 제거; 포크는 그 구간 안에 마이그레이션을 완료해야 함. 모든
sync에서 `services/core-control-plane/src/fdai/shared/providers/**` +
`services/core-control-plane/src/fdai/composition/` 차이를 확인.

### 6.2 Sync 워크플로

```bash
# 일회성 설정
git remote add upstream https://github.com/dotnetpower/fdai.git

# 매 sync
git fetch upstream --tags
git checkout main
git merge upstream/main   # 또는 rebase - 팀 선택
# Conflict 해결 (fork 규칙 준수 시 일반적으로 zero)
./scripts/quality/repository/check-punctuation.sh  # sanity gate
./scripts/quality/localization/check-translations.sh
uv run pytest -q services/core-control-plane/tests/ fork/services/core-control-plane/tests/ # 전체 스위트
git push origin main
```

병합이 `core/` 내부에 충돌을 landing하면, 이는 포크가 강한 규칙을
조용히 위반했다는 신호. 포크 측 편집을 revert하고, 변경을 조립
루트 또는 어댑터로 이동, sync 재실행.

## 7. Anti-pattern

절대 하지 말 것. 이 중 어떤 것이든 merge-blocker:

- 포크 어디에든 **Azure 테넌트 id, 구독 id, 리소스 이름,
 엔드포인트, 시크릿을 커밋**. 환경 또는 Key Vault에서 `SecretProvider`로
 로드. 업스트림의 `check-guids.sh`는 `8-4-4-4-12` GUID 형식만 catch -
 고객 리소스 이름, hostname, bearer 토큰은 catch 하지 못합니다. 포크는
 자체 정규식 게이트 + OSS 시크릿 scanner를 계층 해야 함 (§2 항목 4 참조).
- **`services/core-control-plane/src/fdai/core/**` 또는 `services/core-control-plane/src/fdai/composition/` 파일을
 in-place 수정**. 포크는 이 모듈들에서 `import`해야 하지만 (그것이
 경계의 요점), 편집해서는 안 됩니다. 모든 커스터마이제이션은
 `default_container(...)`가 반환한 컨테이너에 `dataclasses.replace()`를
 거쳐 감. [유일한 강한 규칙](#3-유일한-강한-규칙) 참조.
- **`rule-catalog/schema/**` 편집**. 스키마를 넓히지 말고 포크 고유
 id 이름 공간 하에 새 카탈로그 항목 추가로 확장.
- **CI를 green으로 만들기 위해 업스트림 테스트 비활성화**. 업스트림
 테스트가 포크를 블록하면 업스트림 설계 변경이 필요하다는 신호 -
 issue 열기.
- **관찰 모드 없이 fork-added 액션을 자동 실행**. Shadow-before-
 강제 적용 불변식은 fork-added ActionType에도 업스트림 ActionType에
 적용되는 것과 정확히 동일하게 적용.
- **고객 신원을 담은 변경을 back-contribute**. 포크에서 업스트림으로
 가는 모든 PR은 고객 이름, id, 엔드포인트, 비공개 데이터셋 참조가
 반드시 scrub됨.
- 페어링된 English 소스의 `translation_source_sha`를 업데이트하지 않고
 **`-ko.md` 번역 커밋**. 업스트림의 `check-translations.sh` 게이트는
 fork-added 사용자가 보는 문서에도 적용됨.

## 8. 다음 단계

- [project-structure-ko.md § Customization via 의존성 주입](../architecture/project-structure-ko.md#customization-via-dependency-injection) -
 이 가이드가 operational 화하는 DI 경계 카탈로그.
- [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) -
 T0/T1/T2 trust 라우터, quality 게이트, risk 게이트, 포크의 룰이 흘러
 들어가는 living-rules 발견 루프 (`.github/**`는 English-only).
- [coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md) -
 안전성 불변식, shadow-mode 기본값, async-Protocol 계약, 포크가
 상속하는 docs-first + docs-after 규칙 (`.github/**`는 English-only).
- [deploy-and-onboard-ko.md](../deployment/deploy-and-onboard-ko.md) - 포크가
 프로비저닝하는 Azure 리소스 인벤토리 (Container Apps, Event Hubs,
 Postgres, Key Vault, ...).
- [prompt-composition-ko.md](../decisioning/prompt-composition-ko.md) - Evolving system
 프롬프트의 전체 설계 (Base + 작업 묶음 + 도구 매니페스트 + Operator
 Memory + 토론).
- [csp-neutrality-ko.md](../architecture/csp-neutrality-ko.md) - 포크가 Azure 리소스
 레이어를 대체 구현으로 교체하는 방법.
- [`docs/runbooks/`](../../runbooks) - 포크의 on-call이 실행하는 운영
 절차 (exemption 작업 흐름, HIL 에스컬레이션, 롤백, 인시던트 재생).
 Fork-specific 런북은 `fork/runbooks/` 아래 두고 업스트림 템플릿을
 참조.
- [capability-licensing-ko.md](capability-licensing-ko.md) - 이미지로 배포하는
 분포가 권한을 활성화하는 방법: 이미지 안의 공개 키,
 배포 설정의 서명된 토큰, available 축 전용 권한. License는 읽기 전용
 기능을 회수할 수 없으므로, 포크는 운영자가 무엇을 볼 수 있는지는
 전혀 막지 않으면서 무엇을 할 수 있는지만 통제할 수 있습니다. 토큰은 이미지 다이제스트나
 배포에 연결하십시오. 연결 없는 토큰은 그것을 읽을 수 있는 누구에게나 동작합니다.
- [generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md) -
 모든 포크가 준수하는 customer-agnostic 스코프 계약.
