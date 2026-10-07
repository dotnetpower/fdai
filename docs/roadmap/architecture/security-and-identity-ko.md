---
title: 보안과 아이덴티티
translation_of: security-and-identity.md
translation_source_sha: 83f7c5296fde46b3e5efab6a0d850a5926bbd3c1
translation_revised: 2026-10-07
---

# 보안과 아이덴티티

자율성은 실행 권한을 요구하며, 그래서 아이덴티티와 안전이 가장 리스크 높은 표면입니다. 최소권한과 되돌릴 수 있음은 협상 불가입니다. 이 문서는 보안 모델의 진실 원본입니다;
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) 의
컨트롤 루프와 안전 불변식,
[app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md) 의 토폴로지,
[coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)
의 코드/CI 게이트를 보완합니다. 선언 목록의 `available`, `queryable`, `readable` facet은 후보 의미를 나타낼 뿐 권한을 증명하지 않습니다. Core는 선택한 선언 종류를 현재 principal 매니페스트로 제한합니다. 이 facet은 접근 권한을 부여하거나 관측 상태를 만들거나 정확한 release 검증을 우회할 수 없습니다.
## 심각도 어휘

- **P0 차단 요인** - auto-execution이 활성화되기 전에 해결·검증되어야 함; shadow 모드에서의
  승격을 블록.
- **P1** - 능력이 프로덕션(강제 적용 모드) 이벤트를 처리하기 전 필요.
- **P2** - 첫 강제 적용 이후 진행될 수 있는 하드닝; 소유자와 함께 열림 Decisions에서 추적.

## 실행 아이덴티티

이 섹션은 **비-사람** 실행기 아이덴티티를 관장합니다. **사람** 아이덴티티 모델 - 콘솔과
ChatOps에 로그인하는 사람, 존재하는 Entra 그룹, 콘솔이 GitHub App으로 쓰기를 위임하는 방법 -
은 [user-rbac-and-identity-ko.md](../interfaces/user-rbac-and-identity-ko.md) 에 있습니다. 승인 ≠ 실행:
사람은 아래의 실행기 아이덴티티를 절대 보유하지 않습니다.

기본 제품 프로필에는 실행기 신원, Entra 애플리케이션, FDAI 사람 역할 그룹, Graph 권한,
HIL 채널 또는 관리 리소스 쓰기 역할이 없습니다. Azure 관찰 신원은 범위가 제한된 `Reader`를
사용하며 배포는 구성된 읽기 출처에만 `Monitoring Reader`, `Log Analytics Reader`, `Cost
Management Reader`, `AKS read-only`(Cluster User와 RBAC Reader) 또는 `Storage Blob Data
Reader`를 파생합니다. 역할을 직접 선택하거나 묶을 수 없습니다. Console과 governed-execution 추가 기능은 엔터프라이즈 아이덴티티 거버넌스를 요구하므로, 신원 전제 조건 없이 사람을 인증하는 표면은 없습니다. 기본값은 Azure Policy 할당을
요구하지 않고 `Reader`로 볼 수 있는 리소스 메타데이터를 평가하며, 더 많은 접근이 필요한
출처는 지원되지 않음으로 보고합니다. `Contributor`, `User Access Administrator`, Graph
애플리케이션 권한 및 모든 쓰기 역할은 기본 프로필 밖에 있습니다.

- 실행기 는 "짧은 수명의, audience-scoped OIDC 토큰을 가져와" 만 노출하는 **`WorkloadIdentity`
  인터페이스** 를 통해 인증해야 합니다. 이것이 [워크로드 신원 계약](csp-neutrality-ko.md#4-워크로드-아이덴티티-계약--oidc-토큰)
  의 구현입니다; 구체적 발급자 (Azure 의 Managed Identity, AWS 의 IRSA, GCP 의 워크로드
  신원 Federation, 어떤 K8s 위의 SPIFFE/SPIRE) 는 그 인터페이스 뒤에 위치하지 `core/`
  에는 없습니다.
- Azure 에서는 인터페이스가 **User-assigned Managed Identity** 로 뒷받침되며, 명시적
  **액션 화이트리스트** 로 범위 지정. 광범위 상주 권한 없음.
- Kubernetes에서는 격리된 실행기 ServiceAccount만 쓰기 권한을 받을 수 있습니다.
  Namespace Role은 등록된 네 Kubernetes ActionType에 필요한 Pod `get` 및 `delete`,
  Deployment `get` 및 `patch`, Deployment scale `get` 및 `update`로 제한됩니다.
  Core와 인벤토리 ServiceAccount에는 Kubernetes 쓰기 권한이 없습니다.
- `DefaultAzureCredential()` (또는 유사 이름의 SDK 진입점) 은 **`core/` 에서 금지** ;
  인터페이스 뒤의 Azure 프로바이더 어댑터 내부에서만 등장.
- **버티컬별 신원은 집계 라우터 신원과 함께 프로비저닝됩니다.** Terraform은
  `id-<workload><suffix>-executor`, `-change`, `-resilience`, `-finops` 신원을 생성합니다.
  Fork-owned 정책 모듈이 버티컬 액션 whitelist를 연결합니다. 아래 [신원 대응](#identity-mapping)을
  참조하세요.
- 사람 승인 아이덴티티(HIL)는 실행 아이덴티티와 별개; 승인과 실행은 절대 동일 principal이
  아니며, 어떤 아이덴티티도 다른 도메인의 아이덴티티를 assume할 수 없음(cross-domain assumption은
  단순히 미사용이 아니라 거부됨).
- 실행 아이덴티티는 **비대화형** : 대화형/콘솔 사인인 없음, 사람 자격증명 부착 없음, 이벤트
  루프 외 사용은 비활성화.
- [독립 운영 근거](../rules-and-detection/independent-operational-evidence-ko.md) 검증기는 별도의
  실행기가 아닌 워크로드 아이덴티티입니다. 자신의 principal이 출처, 생산자, 검토자, 실행기 계열
  principal 중 하나와 같으면 시작을 거부하고, 배포된 발급 호출은 등록된 생산자 워크로드 신원에서 온
  것만 받으며, 시작 시 자신의 Azure 역할을 다시 읽습니다. 삽입 전용 증명 저장소 작성자 역할과 고정
  매개변수 `SECURITY DEFINER` 출처 함수에 대한 `EXECUTE` 권한만 보유하고, 출처 뷰나 테이블을 직접
  `SELECT`하지 않습니다. 용도는 다른 principal이 작성하는 저장소를 검증기 자신의 아이덴티티로 읽을 때만
  연결됩니다. 생산자나 Operator가 쓸 수 있는 행은 플랫폼이나 인벤토리 출처를 대신하지 못하므로, 그런
  출처가 없는 읽기 확인은 연결하지 않은 상태로 남습니다.
- **credential-free 인증 선호**: 워크로드 신원 federation / OIDC 토큰 교환으로 실행기가
  장기 시크릿을 보유하지 않음. 시크릿이 불가피한 곳에서는 단명·자동 로테이트(Secrets and
  구성 참조).

### 신원 대응

P0 열림 결정 *"Executor-side 신원 대응"*을 해결합니다. 현재 Terraform 형태는
집계 action-router 신원 하나와 버티컬 신원 세 개를 유지하므로 전달 어댑터는
`core/` 변경 없이 도메인별 principal을 선택할 수 있습니다.

| 신원 | 현재 목적 | Azure 역할 전략 | 범위 |
|----------|----------|----------------|-------|
| `id-<workload><suffix>-executor` | 집계 control-loop 전송 계층과 액션 라우팅 | 업스트림은 topic-scoped Event Hubs 접근, Key Vault 시크릿 읽기 같은 런타임 platform 역할만 부여 | 리소스 또는 서비스 범위, subscription-wide 금지 |
| `id-<workload><suffix>-change` | 변경 안전성 전달 principal | fork-owned 액션 whitelist 또는 측정된 custom 역할 | 변경 안전성이 관리하는 리소스 그룹 |
| `id-<workload><suffix>-resilience` | 복원력 및 복구 전달 principal | fork-owned 액션 whitelist 또는 측정된 custom 역할 | 관리되는 복구 범위 |
| `id-<workload><suffix>-finops` | 비용 거버넌스 전달 principal | fork-owned 액션 whitelist 또는 측정된 custom 역할 | 관리되는 cost-optimization 범위 |

실행 권한 확인은 프로바이더 중립적인 참조 `identity/change`, `identity/resilience`,
`identity/finops`를 사용합니다. Terraform은 대응 UAMI를 첨부하고 클라이언트 id만 전달
조립에 노출합니다. 권한 확인 결과가 하나의 참조를 선택하면 액션과 direct-API
요청이 이를 보존하고 전달 라우터가 일치하는 `WorkloadIdentity`를 선택합니다. 알 수 없거나
연결되지 않은 참조는 집계 실행기 신원으로 대체 경로하지 않고 거부됩니다.
알림 과다 수신 작업은 일반 direct-API 대체 경로에 도달하지 않습니다. 알림 전용 unavailable 경로가
shadow와 enforce 모드 모두에서 이 작업을 보류하고, 다른 direct-API 작업은 실행기 미연결 거부를 유지합니다.

읽기 전용 인벤토리, 인제스트, canary와 다른 서비스 신원은 이 실행기 집합과 분리됩니다.
버티컬 신원 생성 자체는 리소스 권한을 부여하지 않으며 역할 배정은 명시적
포크 배포 정책입니다.

모든 단계에 적용되는 규칙 (MUST):

- **RG-스코프, 절대 subscription-wide 아님.** 새 RG는 포크가 명시적으로 할당 IaC에 추가할
  때만 거버넌스에 들어감 - 자동 확장 없음.
- **보완적 Azure Policy `deny`** 가 선언된 화이트리스트 밖의 MI 액션을 두 번째 방어선으로
  블록하여, 잘못 할당된 롤이 조용히 표면을 넓히지 못하게 함.
- **모든 액션 화이트리스트 변경은 거버넌스 PR** with `Justification:` 및 Managed
  신원 롤 할당을 만지는 모든 변경에 Owner-티어 정족수
  ([user-rbac-and-identity-ko.md](../interfaces/user-rbac-and-identity-ko.md)).
- **Shadow 로그 캡처** 는 shadow 모드의 실행기 MI가 발행하는 모든 액션이
  호출할 정확한 Azure resource-provider 작업을 기록하여, 단계 2 Custom 역할 파생이 결정론적
  이고 감사 가능하게 함.

전달 계층은 액션 도메인에서 버티컬 MI를 선택하며 코어 코드 변경은 필요 없습니다.

## 인가 모델(권한 확인 모델)

실행 권한 확인은
[실행 권한 부여 온톨로지](../decisioning/execution-authorization-ontology-ko.md)에 정의된
프로바이더 중립적인 기능 온톨로지와 scoped 정책 배정으로 확인합니다. 액션 승인은 실행기
접근 권한을 부여하지 않습니다. 권한이 없으면 원래 액션을 보류하고 별도의 exact-plan
`AccessGrantRequest`를 생성할 수 있습니다. 독립된 protected deployer가 승인된 권한 부여를 적용하며,
fresh effective-access 근거가 있어야 액션을 처음부터 다시 평가합니다.

- 모든 액션을 필요한 최소 롤/권한에 매핑; **기본 거부**.
- 최소권한을 관례가 아니라 기계적으로 강제: 액션 화이트리스트는 리스크 게이트에서 평가되는
  policy-as-code(OPA/Rego) 이며, 권한 있는 스코프는 상시 개방이 아니라 **just-in-time과
  time-bound** 로 부여되어 액션 윈도우 후 만료.
- 조직의 계정/아이덴티티 표준을 클라우드 인가 경로와 조화(예: Keycloak 같은 외부 IdP ↔ Entra
  ↔ Managed Identity). 이 매핑을 **P0 차단 요인** 로 취급; 종단 경로가 프로비저닝되고
  최소권한 프로브로 테스트되고 접근 재인증이 스케줄될 때만 해결됨.
- **접근 재인증**: 롤 할당은 고정 주기로 리뷰; 미사용/과광범위 부여는 취소. 재인증 결과는 감사.
- 자율 배포는 플랫폼 정책(예: Azure Policy `deny`) 을 존중해야 함; 컨트롤을 우회하는 대신
  **정책 예외 워크플로**(요청 가능, time-boxed, 감사, 소유자 승인) 제공.

## 시크릿과 설정

- 시크릿, 연결 문자열, 구독/테넌트 ID, 고객 식별자를 절대 하드코딩하지 않음. 시크릿 검사
  (예: gitleaks)이 CI에서 실행되고 긍정 발견 사항은 머지를 블록
  ([coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)).
- **앱은 환경변수 (또는 K8s 시크릿 마운트) 만 읽습니다.** CSP 시크릿 SDK (`SecretClient`,
  `SecretsManagerClient`, `SecretManagerServiceClient` 등) 를 호출해서는 안 됩니다; 이것이
  [시크릿 계약](csp-neutrality-ko.md#3-시크릿-계약--환경변수--k8s-secret) 의 구현입니다.
  AKS 기본 구성의 주입 계층은 **관리형 Key Vault CSI 공급자 + 워크로드 신원**이며, 고정된 참조를
  namespace별 Kubernetes Secret으로 동기화합니다. 기존 Container Apps 설치는 호환 경로로만
  native Key Vault 참조를 유지합니다.
- 시크릿은 `shared/providers/` 의 주입된 `SecretProvider` 로 접근하며, 가져오기 시점 전역 읽기는
  절대 금지.
- **라이프사이클**: 모든 시크릿은 소유자, 정의된 로테이션 간격, 자동 로테이션을 가짐; 손상되거나
  대체된 자료는 즉시 취소. 로테이트할 시크릿이 없도록 federated 토큰 선호.
- **실패 시 차단**: 시크릿 주입 레이어 또는 토큰 발급자가 시작 시 사용 불가하면 프로세스가
  fail fast - 캐시된 또는 임베디드 자격증명으로 대체 경로 하지 않으며 degraded 상태 로
  시작하지 않음.
- 시크릿은 로그, 감사 엔트리, 에러 메시지, 테스트 픽스처, LLM 프롬프트에 등장하면 안 됨.
- 저장소를 고객-비종속으로 유지
  ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).

## 데이터 보호

- 컨트롤 플레인이 처리하는 데이터(이벤트 페이로드, 도구 출력, 감사 기록, 임베딩)를 **분류**
  하고 최소화: 포인터/id를 저장, 원시 고객 바이트나 PII는 저장 안 함.
- 전송 중(TLS)과 정지 중 암호화; 키는 시크릿/키 저장소에서 관리, 코드에 없음.
- **LLM 데이터 처리**: T2 프롬프트는 신뢰 경계를 떠나기 전에 시크릿과 PII가 redact됨; 외부
  모델 벤더에 대한 데이터 잔류지와 no-retention 조건 강제. 감출 수 없는 민감 데이터가 필요한
  프롬프트는 전송되지 않고 HIL로 라우팅됨.
- **근거 출처 격리**: 독립 읽기 전용 출처는 별도의 유한 deadline을 사용합니다. 한 출처의
  timeout이 다른 출처에서 이미 완료된 근거를 버릴 수 없으며, 사용할 수 없거나 빈 근거가 정상
  관측, 원인 주장 또는 실행 권한으로 바뀌지 않습니다.
- **코드 보안 조치 팩**: 팩은 공개되지 않은 취약점 상세를 개발자 PC와 코딩 에이전트 서비스로
  전달합니다. 반출하려면 배포 환경이 승인한 제공자(데이터 상주, 학습 미사용, 보존 기간, 허용된 팩
  모드), 서명된 매니페스트, 레지스트리 기록이 필요하며, 결과 가져오기는 그 기록만 신뢰합니다.
  알림과 에이전트 버스 메시지에는 건수와 불투명한 이슈 ID만 담고 코드나 경로는 담지 않습니다.
  [코드 보안 점검 결과](../operations/code-security-findings-ko.md#조치-팩)를 참조하세요.
- **코드 보안 LLM 렌즈**: 선택 사항인 렌즈 레인은 범위가 제한된 소스 발췌를 설정된 모델 배포로
  보내므로 같은 데이터 상주와 no-retention 조건이 적용됩니다. 출력은 신뢰하지 않으며, 근거가
  확인되고 정족수가 합의한 후보만 비활성 가설이 됩니다.

## 네트워크 경계

- 실행기와 코어 엔진은 **공개 인바운드 엔드포인트 없음**; 인그레스는 이벤트 버스뿐.
  관리/API 표면은 비공개 네트워킹 뒤에 있음.
- **Egress는 allow-list 됨** - 요구된 클라우드 컨트롤 플레인과 모델 엔드포인트로; 유출과
  주입-주도 콜백을 억제하기 위해 아웃바운드는 기본 거부.
- 레이어 아이덴티티는 네트워크 경계를 넘어 공유되지 않음; 선택적 정책 관리 추가 기능을 포함한
  콘솔과 ChatOps는 실행기 아이덴티티를 절대 보유하지 않음
  ([app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md)).

## 공급망 무결성

- 의존성은 lockfile로 고정; CI는 lockfile에서만 설치하고 취약성 스캔이 high-severity 발견을
  블록.
- 룰 카탈로그와 IaC는 **protected 브랜치 + 서명 커밋/PR 리뷰** 뒤의 catalog-as-code;
  강제 적용 브랜치로의 직접 push 없음.
- 빌드 아티팩트(컨테이너 이미지)는 서명되고 출처 이력/SBOM 기록됨; 실행기는 검증된 고정
  다이제스트만 pull, 절대 변경 가능한 `latest` 태그 아님.

## 7개 안전조건 (모든 자율 상태 변경 액션)

1. **Stop-condition** - 액션을 중단시키는 정의된 halt 상태. ActionType 별로 `stop_conditions[]`
   에 선언되고 실행기 가 적용 도중·이후에 평가.
2. **Rollback 경로** - 되돌리는 테스트된 방법. 온톨로지 `ActionType.rollback_contract` 는
   `pr_revert` / `scripted` / `pitr` / `snapshot_restore` / `state_forward_only` 중 하나여야
   함; **`none` 은 유효 값 아님**. 정말로 되돌릴 수 없는 변경 은
   `ActionType.irreversible: true` 로 설정되어 risk-gate 가 HIL+정족수 라우팅; 롤백 은
   여전히 최선 노력 복구로 선언.
3. **Blast-radius 한도** - 스코프 상한(non-prod 우선, 배치 크기, 속도) + 리소스별
   직렬화로 한 리소스에 대한 동시 액션은 상호 배제. `ActionType.blast_radius.computation =
   graph_derived` 는 risk-gate 가 Resource → Resource 그래프(`contains` + 역방향
   `depends_on`, 깊이 2) 로 실제 영향 집합을 계산하게 함 - 3-값 enum 은 상한이 아니라 버킷.
4. **What-if 또는 예행 실행** - 변경 전에 성공한 버전 고정 예측 증명.
5. **Logical-target 잠금** - 영향을 받는 모든 대상의 잠금과 인과 순서. 관리 리소스 변경에는
  정확한 리소스 ID를 사용합니다.
6. **멱등성** - 전송과 재시도 전반의 안정적인 키 및 중복 억제.
7. **감사 수명 주기** - side 효과 전에 추가 전용 의도를 기록하고 이후 최종
  실행 및 결과로 닫습니다.

안전조건 중 하나라도 빠지면 액션은 미완결이며 출시할 수 없습니다. 각 안전조건은 **테스트할
수 있습니다**. Shadow-mode 테스트는 변경이 없음을 증명하고 롤백 테스트는 이전 상태
복원을 증명합니다. 속성 기반 테스트는 영향이 큰 실행에 현재 또는 상시 사람 승인이 있고,
침묵은 권한을 부여하지 않으며, 비가역 작업은 상시 권한을 사용하지 않고, 재시도는 no-op임을
단언합니다. 순수 A0 읽기는 변경 롤백, 예행 실행 및 잠금 대신 제한된 읽기 권한과 증거
계약을 따릅니다. 독립적인 효과 검증이 모든 성공 주장을 게이트합니다.

### 대상 잠금 담당 이행

변경 경로마다 근거가 있는 대상 잠금 담당자는 한 명입니다. 선택된 실행기가 근거 공급자를
필수 준비 상태로 검사할 때까지 기존 리소스 주장 fence를 유지합니다. 이행 중에 두 대상
잠금을 함께 획득하는 방식은 허용하지 않습니다.

| 경로 | 현재 대상 잠금 경계 | 이행 후 필요한 담당자 |
|------|---------------------|------------------------|
| Thor 디스패치 | 일반 실행기 호출을 감싸는 기존 대상 잠금과 별도 영구 리소스 주장 | 영구 주장은 유지합니다. 선택된 실행기가 근거 공급자 누락을 차단할 때만 중복 대상 잠금을 제거합니다. |
| PR native/manual | 멱등성 mutex 다음에 실행기 내부의 기존 대상 잠금을 획득합니다. | 선택된 PR 실행기가 게시 및 최종 저장까지 하나의 근거 대상 잠금을 소유합니다. |
| Direct API | 멱등성 mutex 다음에 실행기 내부의 기존 대상 잠금을 획득합니다. | Direct API 실행기가 공급자 커밋 연속성과 최종 저장까지 하나의 근거 대상 잠금을 소유합니다. |
| 도구 호출 | 멱등성 mutex 다음에 실행기 내부의 기존 대상 잠금을 획득합니다. | 도구 호출 실행기가 공급자 커밋 연속성과 최종 저장까지 하나의 근거 대상 잠금을 소유합니다. |
| 작업 흐름 | 선택된 실행기를 조정하며 별도 `ExecutionPath`를 정의하지 않습니다. | 선택된 실행기가 대상 잠금을 소유합니다. 작업 흐름은 변경 불가능한 사전 묶음 약속을 전달하고 대상을 다시 잠그지 않습니다. |
| Isolated 실행기 | 공유 묶음 재검증은 #628에서 열린 작업입니다. | Isolated 실행기는 디스패치 전에 누락되거나 오래된 근거 소유권을 차단하고 기존 잠금 경계를 대신 사용하지 않아야 합니다. |
| 통제된 카오스 카탈로그 | 어댑터는 harness 실행 전에 모든 정규 대상 식별자에 대한 주입된 분산 잠금, 대상별 영속 실행 점유 기록, 배타적 `injecting` 비교 후 교체를 보유합니다. 점유는 검증된 복구, 거부, 주입 시도 없는 실패 또는 감사된 별도의 Var 종료 결정 뒤에만 넘어갑니다. | `runtime/delivery.py`의 런타임 바인딩은 도구 호출 실행기의 대상 잠금에 다시 들어가지 않고 어댑터에 근거가 있는 대상 잠금 하나를 넘겨야 합니다(#94). |

### PostgreSQL 연속성 승인

효과 대상 시스템은 구성이 검토된 `EffectSinkContinuityPolicy` 하나를 제공할 때까지 운영에서
지원되지 않습니다. 정책은 fence 및 멱등 실행, 완전한 잠금 세션 원자성, 또는 영구 결과 불명
격리 및 권위 있는 조정을 포함한 취소 중 하나를 선택합니다. 일반 Direct API 또는 도구
범주는 연속성 전략이 아닙니다.

PostgreSQL 근거 공급자는 다음 경계를 따릅니다.

- 하나의 전용 연결이 전체 획득 컨텍스트에서 정확한 advisory key를 소유합니다. 다시 연결하거나
  연결을 바꾸면 새 획득이 되며 이전 획득을 계속할 수 없습니다.
- 획득은 DSN이나 기능 권한이 있는 토큰을 저장하지 않고 데이터베이스 신원, backend 프로세스
  ID, backend 세션 구분자, 요청 다이제스트, 소유자 참조 다이제스트를 결속합니다.
- `granted=true`인 `pg_locks`는 특정 시점의 기반 시스템 관찰입니다. 공급자 소유 UTC 시각과
  계약의 최대 5초가 평가 범위를 제한하지만 미래 소유권을 예측하지는 않습니다.
- 공급자는 advisory unlock의 부울 결과를 확인합니다. 연결 상실, 잠금 행 누락, 알 수 없는
  unlock 결과는 상실 또는 알 수 없는 해제 근거와 영구 대상 격리를 생성합니다.
- 대상 시스템 커밋은 격리를 해제하거나 운영 성공을 주장하지 않습니다. 선택된 대상 시스템
  정책은 안정적인 멱등성 또는 권위 있는 상태 조정을 제공해야 하며 독립 효과 검증은 별도
  최종 축으로 유지됩니다.

## 비율 Limiting과 비상 정지 (DoS와 억제)

- 이벤트 루프와 실행기는 **비율/예산 상한**(티어별, 리소스별, 전역) 을 강제; 상한 초과는
  HIL로 강등, 게이트 없는 auto-action이 되지 않음. 이것이 비용과 폭주/이벤트 홍수(DoS) 조건도
  한계.
- **전역 비상 정지** 는 모든 auto-execution을 즉시 중단하고 모든 경로를 shadow/HIL로 드롭;
  실행기 아이덴티티 없이 조작 가능. risk 게이트 는 이를 `KillSwitch.is_engaged()` 가 공급하는
  `kill_switch` 상한 축으로 실현합니다. ([execution-model-ko.md](../decisioning/execution-model-ko.md)
  2.6b). 운영 런타임은 모든 권한 결정 전에 PostgreSQL에서 상태를 읽으며 읽기에 실패하면
  engaged 상태로 처리합니다. Owner와 Break-Glass principal은 `POST /system/kill-switch`를 통해
  상태를 변경하고, 개정 번호 compare-and-set과 감사 항목이 같은 트랜잭션에 기록됩니다.
- **Break-glass** 절차는 필수 감사와 사후 리뷰 하에 범위된 비상 접근을 부여; break-glass
  사용은 알림을 발동하고 자동 만료.

## Shadow → 강제 적용 승격

- 새 능력은 **shadow 모드** 로 출시: 판정자와 로그만, 실행 없음.
- 강제 적용로의 승격은 명시적, 액션별이며 **최소 shadow 기간과 표본 크기**, 임계 위 측정 정확도,
  shadow에서 **정책 위반 escape 0** 을 게이트로 함
  ([goals-and-metrics-ko.md](goals-and-metrics-ko.md)의 메트릭).
- 권한 있는 설치 운영자는 게이트 통과 전에 기능을 승격할 수도 있음. 이 귀속 재정의는 그
  시점의 게이트 상태를 기록하고, 모든 화면에 표시되며, 다른 곳에서 승격 증거로 인정되지 않음.
  회귀 강등과 공급업체의 기능 회수가 이 재정의보다 우선함
  ([운영자 거버넌스 프로필](../decisioning/operator-governance-profiles-ko.md)). 승격 레지스트리는
  `promotion_kind`를 저장하고, 주입된 검증기가 Var 승인 영수증을 확인한 뒤에만 재정의를 받아들임.
  `governance.override-promote-action-type` 경로는 Thor의 direct promotion adapter를 통해 그
  영수증을 발급하고 검증함.
- 회귀는 자동으로 shadow로 강등; 모든 승격과 강등은 감사 엔트리를 씀.
- Working-context 정책 후보는 액션 기능을 얻지 않고 같은 기능 권한을
  사용합니다. 비활성화된 상태로 설치되고 범위가 제한된 off-path 비교를 실행하며, 승격에는
  정확한 버전, 근거 구간, 롤백 대상이 필요합니다. 불변식 위반 시 정책별 kill
  전환이 engage됩니다. [컨텍스트 선택 정책](../decisioning/context-selection-policy-ko.md)을
  참고하세요.
  Core 종료 시 진행 중인 비교 평가에 5초를 허용한 뒤 남은 작업을 취소하고 상태 저장소를
  닫습니다. 중단된 비교는 승격 근거가 될 수 없습니다.
- Operator가 작성한 정책 개정은 Mimir가 내보낼 수 없는 설치 키로 서명하고 원시 서명, 버전이 있는
  키 id, 서명 메시지 형식을 보존합니다. Core는 활성화 전과 활성 개정을 허용 정책 또는 승인 프로필
  경로에서 사용하기 전에 그 서명을 검증합니다. 누락, 변조, 잘못된 키 서명은 활성화 없음 또는 사람
  승인으로 안전하게 차단됩니다.
- T2 환각 루브릭 구간도 같은 근거 규칙을 따르며 권한을 얻지 않습니다. 구간 모드는 배포가 영수증
  원본과 검증기를 바인딩한 경우에만 독립 검증된 영수증으로 ActionType별로 정해집니다. 영수증이
  없거나 만료, 거부, 불일치하면 shadow로 유지되며, 강제 적용 모드에서도 신뢰도를 낮출 수만
  있습니다. [환각 루브릭 게이트](../decisioning/hallucination-rubric-gate-ko.md)를 참고하세요.

## 사람 승인 무결성

- 승인과 실행은 별개 principal; **자기승인 없음**, 그리고 고-blast-radius 액션은 단일 승인자가
  아니라 **정족수(멀티 승인자)** 필요. 단독 운영자 프로덕션 프로필이 유일한 프로덕션 예외이며,
  지정된 운영자 한 명이 승인하고 감사는 원래 정족수와 유효 정족수 1을 기록함
  ([운영자 거버넌스 프로필](../decisioning/operator-governance-profiles-ko.md)). Core는 이 결정
  규칙을 구현하지만 런타임 승인 경로는 아직 활성 프로필 개정을 전달하지 않음.
- 승인자는 MFA/phishing-resistant 자격증명으로 인증; 각 승인은 특정 액션 + 멱등성 키에
  바인딩되어 **다른 액션에 대해 재생될 수 없음**.
- **시간 초과는 실패 시 차단입니다**: 현재 승인 또는 유효한 기존 상시 승인이 없는 HIL 항목은
  no-op 및 감사 엔트리로 종료됩니다. 침묵은 승인을 만들지 않습니다. 상시 승인은
  [에스컬레이션 및 상시 권한](../decisioning/escalation-and-standing-authority-ko.md)의 제한된
  A3-E 계약을 통해서만 적용됩니다.
- 이벤트 버스의 결정 메시지는 전달 수단일 뿐 승인이 아닙니다. Operator는 대기 중인 승인을 검증하는
  같은 트랜잭션에서 영속 결정 영수증을 기록하고, Core는 메시지가 그 영수증과 일치할 때만 결정을
  라우팅합니다. 위조되거나 변경된 메시지는 park, 정족수 슬롯, 실행기에 닿기 전에 거부됩니다.

## 감사가능성(Auditability)

- 감사 저장소는 추가 전용이며 자율성의 신뢰 기반.
- **Tamper-evidence**: 엔트리는 hash-chain(각 기록이 이전을 커밋)되고 주기적으로 기준점/서명
  되어 삭제나 편집이 감지 가능; 가능한 곳에서 한 번만 쓰는/WORM 저장.
- **부인 방지**: 각 엔트리는 인증된 행위자 아이덴티티(실행기 또는 승인자)와 모드(shadow/강제 적용)
  를 기록하여 액션을 나중에 부인할 수 없음.
- 모든 액션은 다음에 링크: 트리거 이벤트, 결정한 티어, 인용된 규칙/정책, 리스크 결정(auto/HIL),
  승인자(HIL인 경우), 멱등성 키, 롤백 참조.
- **보존**: legal-hold 지원과 함께 정의된 불변 보존 윈도우; 기록은 윈도우 경과 전에 정리 불가.
- 이 저장소의 감사 데이터는 고객-비종속; 실제 환경 기록은 포크의 런타임 저장소에만 있고 여기
  커밋되지 않음.
- [shadow 전용 MSCP 결정 맥락](mscp-operational-profile-ko.md#차용한-메커니즘)은 최초 불변 상태
  기록과 함께 내용 다이제스트 및 민감 정보를 제외한 감사 항목 하나를 기록합니다. 소유자 관측이
  누락되거나 충돌하면 보류하고, 재현 과정에서 기존 기록을 대체할 수 없습니다. 이 변환 결과는
  정본 런타임 읽기 경로 없이 승인, 실행 또는 운영 근거를 만들지 않습니다.

## 위협 모델 (STRIDE)

Browser-only 근거는 실행기 신원나 호스트 파일 시스템 mount가 없는 별도의 credential-free
런타임을 사용합니다. Exact HTTPS 출처 정책, 연결별 DNS revalidation, restricted egress,
GET/헤드 interception, visual 및 텍스트 민감정보 제거, 시크릿 canary, prompt-injection 검사, 내용 해시,
추가 전용 보관 기록이 하나의 실패 시 차단 경계를 구성합니다. 브라우저 내용은 항상
신뢰할 수 없는이며 액션을 approve하거나 execute할 수 없습니다. [브라우저 근거 수집](../interfaces/browser-evidence-ko.md)을
참고하세요.
Operator 역할은 허용된 페이로드 없는 작업 공간 메타데이터와 고정된 스냅샷 전체 보류 집계
하나만 조회할 수 있습니다. 산출물 테이블 또는 내부 허용 view는 조회할 수 없습니다. 보류
출력에는 개수만 포함되며, 보관 이동은 하나의 정확한 `actor`, 작업, 다이제스트, 신뢰 및 권한
없음 감사 일치가 있을 때만 나타납니다. 모호하거나 잘못된 일치는 `sequence` 또는 상관관계
식별정보를 노출하지 않습니다.

이벤트 페이로드와 도구 출력은 **신뢰할 수 없는** ; 결정론적 검증기와 정책 재검사가 권위이며,
모델이나 이벤트 텍스트가 아님.
공급자 관측 실패는 허용 목록에 있는 기계 사유로만 서비스 경계를 통과합니다. 공급자 응답 원문은
Resource 상태로 저장하거나 Console에 반환하지 않습니다.

| STRIDE | 위협 | 완화 |
|--------|------|------|
| **Spoofing** | 위조된 이벤트 / 임퍼소네이트된 승인자 | 인증된(서명된) 이벤트 소스; MFA + 액션-바인딩 승인; federated 아이덴티티 |
| **Tampering** | 변조된 규칙/IaC, 주입된 아티팩트 | 서명 커밋, protected 브랜치, 서명/고정 아티팩트 + SBOM |
| **Repudiation** | 나중에 부인된 액션 | Hash-chain된 actor-attributed 추가 전용 감사 |
| **Info 공개** | 로그 또는 LLM 프롬프트를 통한 시크릿/PII 유출 | 민감정보 제거, no-secret-in-prompt, 암호화, egress allow-list |
| **DoS** | 이벤트 홍수 / 폭주 루프 / 예산 소진 | 비율/예산 상한, HIL로 circuit-break, 비상 정지 |
| **권한 상승** | 과광범위 또는 cross-domain 액션 | Per-domain 아이덴티티, JIT time-bound 스코프, cross-assumption 거부, no 자기 승인 |
| **프롬프트 주입** | 악성 페이로드가 T2 조종 | T2는 신뢰할 수 없는 취급; 검증기 + 정책 재검사가 권위 |

## 열림 Decisions

| 우선순위 | 결정 | 소유자 | 목표 |
|----------|------|--------|------|
| ~~P0~~ | ~~Executor-side 신원 대응~~ - **해결** in [신원 대응](#identity-mapping) | - | - |
| ~~P0~~ | ~~Risk-classification 정책 (auto vs HIL) and initial 정책 승인자~~ - **해결** in [risk-classification-ko.md](../decisioning/risk-classification-ko.md) | - | - |
| P1 | 정책 예외 워크플로 소유자와 SLA | TBD | 프로덕션 전 |
| P1 | 감사 앵커 주기, WORM 바인딩 및 운영 검증 | TBD | 프로덕션 전 |
| P1 | 비상 정지와 break-glass 런북과 드릴 스케줄 | TBD | 프로덕션 전 |
| P2 | 컴플라이언스 컨트롤 매핑(MCSB / CIS / SOC 2) 과 증거 수집 | TBD | 첫 강제 적용 이후 |
| P2 | 아이덴티티별 시크릿 로테이션 간격과 federation 커버리지 | TBD | 첫 강제 적용 이후 |

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 구현 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/architecture/security-and-identity.md) |
