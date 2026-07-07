---
title: 보안과 아이덴티티
translation_of: security-and-identity.md
translation_source_sha: 2fdeb6972d2814c6c951817ac18a2e05b71384e6
translation_revised: 2026-07-07
---

# 보안과 아이덴티티

자율성은 실행 권한을 요구하며, 그래서 아이덴티티와 안전이 가장 리스크 높은 표면입니다.
최소권한과 되돌릴 수 있음은 협상 불가입니다. 이 문서는 보안 모델의 진실 원본입니다;
[architecture.instructions.md](../../.github/instructions/architecture.instructions.md) 의
컨트롤 루프와 안전 불변식,
[app-shape.instructions.md](../../.github/instructions/app-shape.instructions.md) 의 토폴로지,
[coding-conventions.instructions.md](../../.github/instructions/coding-conventions.instructions.md)
의 코드/CI 게이트를 보완합니다.

## 심각도 어휘

- **P0 blocker** - auto-execution이 활성화되기 전에 해결·검증되어야 함; shadow 모드에서의
  승격을 블록.
- **P1** - 능력이 프로덕션(enforce 모드) 이벤트를 처리하기 전 필요.
- **P2** - 첫 enforce 이후 진행될 수 있는 하드닝; 소유자와 함께 Open Decisions에서 추적.

## 실행 아이덴티티

이 섹션은 **비-사람** executor 아이덴티티를 관장합니다. **사람** 아이덴티티 모델 - 콘솔과
ChatOps에 로그인하는 사람, 존재하는 Entra 그룹, 콘솔이 GitHub App으로 쓰기를 위임하는 방법 -
은 [user-rbac-and-identity-ko.md](user-rbac-and-identity-ko.md) 에 있습니다. 승인 ≠ 실행:
사람은 아래의 executor 아이덴티티를 절대 보유하지 않습니다.

- executor 는 "짧은 수명의, audience-scoped OIDC 토큰을 가져와" 만 노출하는 **`WorkloadIdentity`
  인터페이스** 를 통해 인증해야 합니다. 이것이 [Workload Identity 계약](csp-neutrality-ko.md#4-워크로드-아이덴티티-계약--oidc-토큰)
  의 구현입니다; 구체적 issuer (Azure 의 Managed Identity, AWS 의 IRSA, GCP 의 Workload
  Identity Federation, 어떤 K8s 위의 SPIFFE/SPIRE) 는 그 인터페이스 뒤에 위치하지 `core/`
  에는 없습니다.
- Azure 에서는 인터페이스가 **User-assigned Managed Identity** 로 뒷받침되며, 명시적
  **액션 화이트리스트** 로 범위 지정. 광범위 상주 권한 없음.
- `DefaultAzureCredential()` (또는 유사 이름의 SDK 진입점) 은 **`core/` 에서 금지** ;
  인터페이스 뒤의 Azure 프로바이더 어댑터 내부에서만 등장.
- **버티컬별 아이덴티티가 목표 종국 상태** 이며 로드맵에 걸쳐 단계화: Phase 1은 단일
  `mi-aw-executor` (Change Safety만) 을 배포, Phase 3에서 Resilience와 Cost Governance가
  도착할 때 `mi-aw-change` / `mi-aw-dr` / `mi-aw-finops` 로 분할 - 아래 [Identity Mapping (Phased)](#identity-mapping-phased) 참조.
- 사람 승인 아이덴티티(HIL)는 실행 아이덴티티와 별개; 승인과 실행은 절대 동일 principal이
  아니며, 어떤 아이덴티티도 다른 도메인의 아이덴티티를 assume할 수 없음(cross-domain assumption은
  단순히 미사용이 아니라 거부됨).
- 실행 아이덴티티는 **비대화형** : 대화형/콘솔 사인인 없음, 사람 자격증명 부착 없음, 이벤트
  루프 외 사용은 비활성화.
- **credential-free 인증 선호**: workload identity federation / OIDC 토큰 교환으로 executor가
  장기 시크릿을 보유하지 않음. 시크릿이 불가피한 곳에서는 단명·자동 로테이트(Secrets and
  Config 참조).

### Identity Mapping (Phased)

P0 Open Decision *"Executor-side identity mapping"* 을 해결합니다. Phase 1이 미사용 도메인별
인프라를 지지 않도록 계획은 단계화되지만, 인터페이스(리스크 게이트에서의 도메인별 라우팅)는
첫날부터 자리 잡아 Phase 3 분할이 재작성이 아니라 설정 변경이 됩니다.

| Phase | MI | Azure 롤 전략 | 스코프 |
|-------|-----|-------------|--------|
| **P1** (Change만) | 1 × `mi-aw-executor` | **Built-in 롤 구성** - 예: Change 액션 세트에 범위된 `Reader` + `Tag Contributor` + `Network Contributor`. 각 롤 할당은 IaC에 열거됨. | **RG-스코프**, 거버넌스된 리소스 그룹당 하나의 할당 (포크 Terraform이 `for_each rg` 반복). |
| **P2** (Custom Role 전환) | 1 × `mi-aw-executor` | Phase 1 shadow 로그에서 관찰된 액션 화이트리스트를 `actions:` 로 갖는 **Custom Role** 파생 - 이론이 아니라 측정 기반 최소권한. Custom Role은 governance PR에서 built-in 구성을 대체. | RG-스코프 (변경 없음). |
| **P3** (도메인 분할) | 3 × `mi-aw-change`, `mi-aw-dr`, `mi-aw-finops` | 각 MI가 자체 Custom Role, 해당 도메인의 shadow 로그에서 같은 방식으로 파생. Cross-domain assumption은 거부(위 불변식과 일치). | RG-스코프, 도메인별 스코프 세트. |

모든 phase에 적용되는 규칙 (MUST):

- **RG-스코프, 절대 subscription-wide 아님.** 새 RG는 포크가 명시적으로 할당 IaC에 추가할
  때만 거버넌스에 들어감 - 자동 확장 없음.
- **보완적 Azure Policy `deny`** 가 선언된 화이트리스트 밖의 MI 액션을 두 번째 방어선으로
  블록하여, 잘못 할당된 롤이 조용히 표면을 넓히지 못하게 함.
- **모든 액션 화이트리스트 변경은 governance PR** with `Justification:` 및 Managed
  Identity 롤 할당을 만지는 모든 변경에 Owner-티어 quorum
  ([user-rbac-and-identity-ko.md](user-rbac-and-identity-ko.md)).
- **Shadow 로그 캡처** 는 Phase 1 산출물: shadow 모드의 executor MI가 발행하는 모든 액션이
  호출할 정확한 Azure resource-provider 작업을 기록하여, Phase 2 Custom Role 파생이 결정론적
  이고 감사 가능하게 함.

Phase 3 분할은 리스크 게이트의 `Rule.domain` 라우팅(온톨로지 dispatch 필드에 이미 있음)을
재사용; 코어 코드 변경 없음 - 딜리버리 레이어가 `Rule.domain` 으로 MI를 선택하고 추가
IaC가 신규 MI를 프로비저닝.

## 인가 모델(Authorization Model)

- 모든 액션을 필요한 최소 롤/권한에 매핑; **기본 거부**.
- 최소권한을 관례가 아니라 기계적으로 강제: 액션 화이트리스트는 리스크 게이트에서 평가되는
  policy-as-code(OPA/Rego) 이며, 권한 있는 스코프는 상시 개방이 아니라 **just-in-time과
  time-bound** 로 부여되어 액션 윈도우 후 만료.
- 조직의 계정/아이덴티티 표준을 클라우드 인가 경로와 조화(예: Keycloak 같은 외부 IdP ↔ Entra
  ↔ Managed Identity). 이 매핑을 **P0 blocker** 로 취급; 종단 경로가 프로비저닝되고
  최소권한 프로브로 테스트되고 접근 재인증이 스케줄될 때만 해결됨.
- **접근 재인증**: 롤 할당은 고정 주기로 리뷰; 미사용/과광범위 부여는 취소. 재인증 결과는 감사.
- 자율 배포는 플랫폼 정책(예: Azure Policy `deny`) 을 존중해야 함; 컨트롤을 우회하는 대신
  **정책 예외 워크플로**(요청 가능, time-boxed, 감사, 소유자 승인) 제공.

## 시크릿과 설정

- 시크릿, 연결 문자열, 구독/테넌트 ID, 고객 식별자를 절대 하드코딩하지 않음. Secret scanning
  (예: gitleaks)이 CI에서 실행되고 positive finding은 머지를 블록
  ([coding-conventions.instructions.md](../../.github/instructions/coding-conventions.instructions.md)).
- **앱은 환경변수 (또는 K8s Secret 마운트) 만 읽습니다.** CSP secret SDK (`SecretClient`,
  `SecretsManagerClient`, `SecretManagerServiceClient` 등) 를 호출해서는 안 됩니다; 이것이
  [시크릿 계약](csp-neutrality-ko.md#3-시크릿-계약--환경변수--k8s-secret) 의 구현입니다.
  Azure 에서 주입 레이어는 **Container Apps native secret + Key Vault reference** ; Kubernetes
  에서는 `SecretStore` CRD 를 가진 **External Secrets Operator** .
- 시크릿은 `shared/providers/` 의 주입된 `SecretProvider` 로 접근하며, import 시점 전역 읽기는
  절대 금지.
- **라이프사이클**: 모든 시크릿은 소유자, 정의된 로테이션 간격, 자동 로테이션을 가짐; 손상되거나
  대체된 자료는 즉시 취소. 로테이트할 시크릿이 없도록 federated 토큰 선호.
- **Fail-closed**: 시크릿 주입 레이어 또는 토큰 발급자가 시작 시 사용 불가하면 프로세스가
  fail fast - 캐시된 또는 임베디드 자격증명으로 fallback 하지 않으며 degraded state 로
  시작하지 않음.
- 시크릿은 로그, 감사 엔트리, 에러 메시지, 테스트 픽스처, LLM 프롬프트에 등장하면 안 됨.
- 저장소를 고객-비종속으로 유지
  ([generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)).

## 데이터 보호

- 컨트롤 플레인이 처리하는 데이터(이벤트 페이로드, 도구 출력, 감사 기록, 임베딩)를 **분류**
  하고 최소화: 포인터/id를 저장, 원시 고객 바이트나 PII는 저장 안 함.
- 전송 중(TLS)과 정지 중 암호화; 키는 secret/key 저장소에서 관리, 코드에 없음.
- **LLM 데이터 처리**: T2 프롬프트는 신뢰 경계를 떠나기 전에 시크릿과 PII가 redact됨; 외부
  모델 벤더에 대한 데이터 잔류지와 no-retention 조건 강제. 감출 수 없는 민감 데이터가 필요한
  프롬프트는 전송되지 않고 HIL로 라우팅됨.

## 네트워크 경계

- executor와 코어 엔진은 **public inbound 엔드포인트 없음**; 인그레스는 이벤트 버스뿐.
  관리/API 표면은 private 네트워킹 뒤에 있음.
- **Egress는 allow-list 됨** - 요구된 클라우드 컨트롤 플레인과 모델 엔드포인트로; 유출과
  주입-주도 콜백을 억제하기 위해 outbound는 기본 거부.
- 레이어 아이덴티티는 네트워크 경계를 넘어 공유되지 않음; 읽기 전용 콘솔과 ChatOps는 executor
  아이덴티티를 절대 보유하지 않음
  ([app-shape.instructions.md](../../.github/instructions/app-shape.instructions.md)).

## 공급망 무결성

- 의존성은 lockfile로 고정; CI는 lockfile에서만 설치하고 취약성 스캔이 high-severity 발견을
  블록.
- rule 카탈로그와 IaC는 **protected 브랜치 + 서명 커밋/PR 리뷰** 뒤의 catalog-as-code;
  enforce 브랜치로의 직접 push 없음.
- 빌드 아티팩트(컨테이너 이미지)는 서명되고 provenance/SBOM 기록됨; executor는 검증된 고정
  digest만 pull, 절대 mutable `latest` 태그 아님.

## 안전 불변식 (모든 자율 액션)

1. **Stop-condition** - 액션을 중단시키는 정의된 halt 상태. ActionType 별로 `stop_conditions[]`
   에 선언되고 executor 가 apply 도중·이후에 평가.
2. **Rollback path** - 되돌리는 테스트된 방법. 온톨로지 `ActionType.rollback_contract` 는
   `pr_revert` / `scripted` / `pitr` / `snapshot_restore` / `state_forward_only` 중 하나여야
   함; **`none` 은 유효 값 아님**. 정말로 되돌릴 수 없는 mutation 은
   `ActionType.irreversible: true` 로 설정되어 risk-gate 가 HIL+quorum 라우팅; rollback 은
   여전히 best-effort 복구로 선언.
3. **Blast-radius limit** - 스코프 상한(non-prod 우선, 배치 크기, 속도) + 리소스별
   직렬화로 한 리소스에 대한 동시 액션은 상호 배제. `ActionType.blast_radius.computation =
   graph_derived` 는 risk-gate 가 Resource → Resource 그래프(`contains` + 역방향
   `depends_on`, depth 2) 로 실제 영향 집합을 계산하게 함 - 3-값 enum 은 상한이 아니라 bucket.
4. **Audit-log entry** - 누가/무엇을/왜/언제와 결과의 append-only 기록.

네 개 중 하나라도 빠지면 = 액션은 미완결이며 출시되지 않음. 각 불변식은 **테스트 가능**:
shadow-mode 테스트가 변형 없음 증명, rollback 테스트가 이전 상태 복원 증명, property-based
테스트가 "high-risk는 절대 auto-execute 하지 않는다"와 "액션 재적용은 no-op이다"를 단언.

## Rate Limiting과 Kill-Switch (DoS와 억제)

- 이벤트 루프와 executor는 **rate/budget cap**(티어별, 리소스별, 전역) 을 강제; cap 초과는
  HIL로 강등, 게이트 없는 auto-action이 되지 않음. 이것이 비용과 폭주/이벤트 홍수(DoS) 조건도
  bound.
- **전역 kill-switch** 는 모든 auto-execution을 즉시 중단하고 모든 경로를 shadow/HIL로 드롭;
  executor 아이덴티티 없이 조작 가능.
- **Break-glass** 절차는 필수 감사와 사후 리뷰 하에 범위된 비상 접근을 부여; break-glass
  사용은 알림을 발동하고 자동 만료.

## Shadow → Enforce 승격

- 새 능력은 **shadow 모드** 로 출시: judge와 log만, 실행 없음.
- Enforce로의 승격은 명시적, 액션별이며 **최소 shadow 기간과 표본 크기**, 임계 위 측정 정확도,
  shadow에서 **정책 위반 escape 0** 을 게이트로 함
  ([goals-and-metrics-ko.md](goals-and-metrics-ko.md)의 메트릭).
- 회귀는 자동으로 shadow로 강등; 모든 승격과 강등은 감사 엔트리를 씀.

## HIL 승인 무결성

- 승인과 실행은 별개 principal; **자기승인 없음**, 그리고 고-blast-radius 액션은 단일 승인자가
  아니라 **quorum(멀티 승인자)** 필요.
- 승인자는 MFA/phishing-resistant 자격증명으로 인증; 각 승인은 특정 액션 + idempotency key에
  바인딩되어 **다른 액션에 대해 재생될 수 없음**.
- **Timeout은 fail-closed**: 미승인 HIL 항목이 timeout 또는 reject 시 no-op + 감사 엔트리로
  귀결, 절대 기본-실행 아님.

## 감사가능성(Auditability)

- 감사 저장소는 append-only이며 자율성의 신뢰 기반.
- **Tamper-evidence**: 엔트리는 hash-chain(각 기록이 이전을 커밋)되고 주기적으로 anchor/서명
  되어 삭제나 편집이 감지 가능; 가능한 곳에서 write-once/WORM 저장.
- **부인 방지**: 각 엔트리는 인증된 actor 아이덴티티(executor 또는 승인자)와 모드(shadow/enforce)
  를 기록하여 액션을 나중에 부인할 수 없음.
- 모든 액션은 다음에 링크: 트리거 이벤트, 결정한 티어, 인용된 규칙/정책, 리스크 결정(auto/HIL),
  승인자(HIL인 경우), idempotency 키, 롤백 참조.
- **보존**: legal-hold 지원과 함께 정의된 불변 보존 윈도우; 기록은 윈도우 경과 전에 purge 불가.
- 이 저장소의 감사 데이터는 고객-비종속; 실제 환경 기록은 포크의 런타임 저장소에만 있고 여기
  커밋되지 않음.

## 위협 모델 (STRIDE)

이벤트 페이로드와 도구 출력은 **untrusted** ; 결정론적 verifier와 정책 재검사가 권위이며,
모델이나 이벤트 텍스트가 아님.

| STRIDE | 위협 | 완화 |
|--------|------|------|
| **Spoofing** | 위조된 이벤트 / 임퍼소네이트된 승인자 | 인증된(서명된) 이벤트 소스; MFA + 액션-바인딩 승인; federated 아이덴티티 |
| **Tampering** | 변조된 규칙/IaC, 주입된 아티팩트 | 서명 커밋, protected 브랜치, 서명/고정 아티팩트 + SBOM |
| **Repudiation** | 나중에 부인된 액션 | Hash-chain된 actor-attributed append-only 감사 |
| **Info disclosure** | 로그 또는 LLM 프롬프트를 통한 시크릿/PII 유출 | Redaction, no-secret-in-prompt, 암호화, egress allow-list |
| **DoS** | 이벤트 홍수 / 폭주 루프 / 예산 소진 | Rate/budget cap, HIL로 circuit-break, kill-switch |
| **Elevation** | 과광범위 또는 cross-domain 액션 | Per-domain 아이덴티티, JIT time-bound 스코프, cross-assumption 거부, no self-approval |
| **Prompt injection** | 악성 페이로드가 T2 조종 | T2는 untrusted 취급; verifier + 정책 재검사가 권위 |

## Open Decisions

| 우선순위 | 결정 | 소유자 | 목표 |
|----------|------|--------|------|
| ~~P0~~ | ~~Executor-side identity mapping~~ - **해결** in [Identity Mapping (Phased)](#identity-mapping-phased) | - | - |
| ~~P0~~ | ~~Risk-classification policy (auto vs HIL) and initial policy approver~~ - **해결** in [risk-classification-ko.md](risk-classification-ko.md) | - | - |
| P1 | 정책 예외 워크플로 소유자와 SLA | TBD | 프로덕션 전 |
| P1 | 감사 tamper-evidence 스킴(hash-chain + anchoring 주기) | TBD | 프로덕션 전 |
| P1 | Kill-switch와 break-glass 런북과 드릴 스케줄 | TBD | 프로덕션 전 |
| P2 | 컴플라이언스 컨트롤 매핑(MCSB / CIS / SOC 2) 과 증거 수집 | TBD | 첫 enforce 이후 |
| P2 | 아이덴티티별 시크릿 로테이션 간격과 federation 커버리지 | TBD | 첫 enforce 이후 |
