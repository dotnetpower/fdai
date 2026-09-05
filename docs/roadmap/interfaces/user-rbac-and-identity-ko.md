---
title: 사용자 RBAC와 Entra 아이덴티티
translation_of: user-rbac-and-identity.md
translation_source_sha: 3324e30235a40fcb8c113e17c738d5fe2074563c
translation_revised: 2026-09-05
---

# 사용자 RBAC와 Entra 아이덴티티

**사람 사용자** 가 콘솔, ChatOps, catalog-as-code 저장소에서 어떻게 인증되고 인가되고
감사되는가. 이 문서는 사람 아이덴티티 모델의 진실 원본입니다; 비-사람 아이덴티티(실행기
Managed Identity, GitHub App, Teams bot)는 여전히 [security-and-identity-ko.md](../architecture/security-and-identity-ko.md) 와
[deploy-and-onboard-ko.md](../deployment/deploy-and-onboard-ko.md) 가 관장.

*사람* 측면의 P0 blocker "최종 아이덴티티 매핑 (외부 IdP ↔ Entra ↔ Managed Identity)"
([security-and-identity-ko.md#open-decisions](../architecture/security-and-identity-ko.md#open-decisions))
을 해결; executor-측 매핑은 거기 선언된 대로 유지.

> RBAC(이 문서)은 *사람이 무엇을 조작할 수 있나*에 답한다. 별개의, 독립적으로 해석되는
> 축인 [agent-stewardship-and-handover-ko.md](agent-stewardship-and-handover-ko.md)는
> FDAI가 업무를 넘겨받은 지금 *15개 에이전트를 각각 누가 소유하나*(책임 + 에스컬레이션 +
> 인수인계)에 답한다. 한 사람이 보통 둘 다에 속하지만, 담당자라는 사실만으로는 RBAC
> 기능이 부여되지 않는다.

> 고객-비종속: 아래 모든 그룹 이름, 앱 registration 이름, GUID는 **자리 표시자** ;
> 포크가 구성으로 실제 값 공급
> ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 활동 관찰의 사람 및 workload identity 분리 | 구현됨 | `fdai_operator_service/activity_projection.py`, `test_activity_projection.py`, 이 문서의 인증된 관찰 계약 | 영속 현재 상태 활동은 hash된 correlation 참조만 전달하며 Reader bearer 게이트와 relay workload credential은 계속 분리되고 어떤 활동 행도 executor 권한을 얻지 않습니다. |
| Break-Glass 활성화 요청 경계 | 구현됨 | `services/operator-service/src/fdai_operator_service/families/iam/break_glass.py`; `capabilities.py`; `services/operator-service/tests/test_operator_break_glass_activation.py` | `POST /system/break-glass/activation`은 BreakGlass 전용 `activate-break-glass` 기능과 비어 있지 않은 인시던트 id 및 사유, 한도 안의 미래 오프셋 인식 만료 시각을 요구합니다. 감사 전용 projection만 기록하며 HIL 승인이나 executor identity를 부여하지 않습니다. 영속 활성화 저장소, TTL 적용, 사인인 알림은 배포 작업으로 남습니다. |
| 사람 승인 콜백 신원 | 구현됨 | `families/iam/hil_callback.py`, `hil_callback_authority.py`, `hil_decision_outbox.py`, `postgres_iam.py`, 집중 콜백, 영속성, Kafka, 워크플로 및 카나리 테스트 | Teams는 구성된 봇에 발급된 API 대상 OBO 토큰, 정확한 공급자-Entra 매핑, 별도로 구성된 그룹 연결 팀과 채널을 요구합니다. Slack은 브라우저 Entra 재인증과 구성된 워크스페이스 및 사용자-Entra OID 매핑을 요구합니다. 콜백 결정은 서명된 콜백 시각을 사용하고 제안 우선 영속화를 복구하며 영속 Operator 보낼 편지함을 통해 게시됩니다. BreakGlass는 기존 전역 기능에서 계속 사용할 수 있지만 사람 승인 권한은 부여하지 않습니다. |
| 로컬 Browser Entra 세션 복원력 | 구현됨 | `console/src/auth-session.ts`; `console/src/auth.ts`; focused Console 인증 테스트(`10 passed`)와 typecheck | MSAL Browser v4는 loopback origin에서만 암호화된 `localStorage`를 사용하고 배포 origin에서는 `sessionStorage`를 유지합니다. 시작 시, 30분마다, focus, visibility 또는 network 복구 뒤에 하나로 병합된 refresh를 실행합니다. Entra는 여전히 대화형 인증을 요구할 수 있습니다. |
| 알림 통합 구성 및 진단 | 구현됨 | `teams_workflow_binding.py`; `teams_workflow_diagnostics.py`; `families/iam/{capabilities,settings,manifest}.py`; 집중 바인딩, 진단 및 IAM 기능군 테스트 | Owner는 Teams 엔드포인트를 저장하고 테스트할 수 있습니다. Contributor, Approver 및 Owner는 `no-store` 응답으로 시크릿이 없는 바인딩 버전과 시각 메타데이터만 받으며 엔드포인트 값은 브라우저로 반환되지 않습니다. Reader와 BreakGlass에는 `visible: false`만 반환합니다. Slack은 일회성 테스트로 유지합니다. 모든 Teams 저장, 테스트 및 메타데이터 조회 감사 기록에는 URL을 넣지 않습니다. |
| 사용자별 비용 거버넌스 접근 | 구현됨 | `CostAccessGrant`, `CostDisclosureCeiling`, 비용 거버넌스 Operator 경로 및 집중 테스트 | Reader는 시간 검사와 배포 공개 상한을 적용하기 전에 principal, 목적, scope가 일치하는 최신 grant를 선택합니다. 서버는 직렬화 전에 `hidden`, `aggregate`, `masked` 또는 `detailed` 공개 정책을 적용하며, 권한은 패키지를 활성화하거나 액션을 승격할 수 없습니다. |
| IAM 관리 진단 및 요청 변환 결과 | implemented | `entra_directory.py`; `families/iam/iam_routes.py`; `postgres_iam.py`; `console/src/routes/settings-iam*`; 집중 Operator, Console 및 Browser 테스트 | Console은 FDAI Owner와 테넌트 관리자를 구분하고, 자격 증명을 사용할 수 있을 때 서버 측 읽기 전용 Graph 디렉터리를 사용하며, 승인이 멤버십을 변경했다고 주장하지 않고 영속 요청 및 검토 제안을 표시합니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-09-01 | implemented | ID 및 액세스 요청 계약을 복구하고, 명시적인 FDAI Owner 및 디렉터리 진단을 추가하고, 로컬 및 배포 자격 증명에 읽기 전용 Graph 디렉터리를 연결했으며, 오해를 일으키는 사용자 추가 문구를 실제 요청-검토-적용-검증 경계로 교체했습니다. | `current change`; `entra_directory.py`; `postgres_iam.py`; `settings-iam*.tsx`; 집중 Operator, Console, 카탈로그 및 Playwright 검사. | 자동 멤버십 변경을 주장하기 전에 배포된 Graph 읽기 증적을 보존하고 별도로 승격되는 할당-IAM 적용 워크플로를 완료합니다. |
| 2026-09-01 | 구현됨 | 암호화된 로컬 및 Key Vault 기반 Teams Workflows 엔드포인트 영속화와 Contributor, Approver 및 Owner용 감사된 `view-integration-secrets` 기능을 추가했습니다. Reader와 BreakGlass에는 바인딩 메타데이터를 제공하지 않습니다. | `current change`; `teams_workflow_binding.py`; `teams_workflow_diagnostics.py`; `families/iam/{capabilities,settings,manifest}.py`; 집중 Operator 테스트 53개 통과; Terraform 검증 통과. | Key Vault reveal 경로를 검증됨으로 주장하기 전에 배포 런타임 증적을 보존합니다. |
| 2026-08-28 | 구현됨 | Slack 진단 경로를 추가한 뒤 경로 팩터리와 일치하도록 고정된 IAM 기능군 매니페스트 순서를 수정해 경로 동등성 검사를 약화하지 않고 Operator API 시작을 복구했습니다. | `current change`; `families/iam/manifest.py`; 집중 IAM 기능군 매니페스트 테스트 통과 | 추가 경로 순서 작업은 남아 있지 않으며 배포된 공급자 증적은 별도로 유지합니다. |
| 2026-08-29 | 구현됨 | 목적과 범위로 제한되는 사용자별 비용 거버넌스 접근 및 서버 측 비승격 공개 정책을 추가했습니다. | `current change`; 서비스 계약, Operator 경로, 이행, 공개 정책 속성 및 조회 없음 테스트. | 접근 검토와 무단 공개가 없는 실제 캠페인 증적을 보존합니다. |
| 2026-08-28 | 구현됨 | 엄격한 엔드포인트 검증, 안전한 재시도 요청 id, 범위가 제한된 공급자 호출, 비밀 없는 영속 감사 메타데이터를 갖춘 Owner 범위 일회성 Teams Workflows 및 Slack 수신 웹후크 진단을 추가했습니다. | `current change`; `settings.py`; `teams_workflow_diagnostics.py`; `slack_webhook_diagnostics.py`; 집중 진단 테스트. | 운영 검증을 주장하기 전에 배포된 공급자 증적을 별도로 보존합니다. |
| 2026-08-13 | 구현됨 | 이전 출처 이력을 재구성하지 않고 구현 ledger를 도입했으며 영속 현재 상태 활동이 전달하는 범위 제한 identity를 기록했습니다. | 현재 출처와 `test_activity_projection.py`, 통과한 focused 영속성 및 projection 테스트 | 별도로 설계된 운영 Break-Glass 활성화 경계를 추가합니다. |
| 2026-08-15 | 구현됨 | BreakGlass 전용 기능, 인시던트 id, 사유, 한도 안의 미래 만료, 감사 전용 projection을 갖춘 `POST /system/break-glass/activation` 요청 경계를 추가했습니다. | `current change`; `services/operator-service/src/fdai_operator_service/families/iam/break_glass.py`; `pytest services/operator-service/tests` (308 passed, 1 skipped). | 배포에서 영속 활성화 저장소, TTL 적용, 사인인 알림을 연결합니다. |
| 2026-08-21 | 구현됨 | 배포 token 저장이나 API 검증을 바꾸지 않고 loopback 전용 영속 MSAL cache와 App 수명 주기가 소유하는 proactive refresh loop 하나를 추가했습니다. | `current change`; `console/src/auth-session.ts`; `console/src/auth.ts`; `console/src/app.tsx`; focused 인증 테스트 10개와 Console typecheck가 통과했습니다. 보존하지 않은 loopback Browser 검사에서 MSAL `sessionStorage` 항목 없이 두 번째 탭을 복구했고 startup refresh 한 번의 성공을 관찰했습니다. | runtime 검증을 주장하기 전에 webview 재생성 또는 야간 중단을 통과한 관리되는 Browser 증적을 보존합니다. |
| 2026-08-31 | 구현됨 | 콜백이 제공한 신원과 역할을 서버가 검증한 Teams 및 매핑된 Slack Entra 권한으로 교체했습니다. 콜백 문맥, 만료, 사유, 자기 승인 차단, 중복 처리, 첫 감사 시각 보존, 제안 우선 복구 및 영속 Kafka 게시가 이제 실패 시 차단됩니다. Teams 대상은 RBAC 그룹 id가 아니라 별도의 그룹 연결 팀과 채널에서 파생됩니다. | `current change`, 집중 Operator IAM, PostgreSQL, Kafka, 조립, 워크플로 승인 및 로컬 카나리 검사. | 토큰이나 테넌트 값을 저장하지 않는 통제된 배포 Teams OBO 및 브로커 수락 증적을 하나 보존합니다. |

### 남은 작업

- [x] 운영 Break-Glass 활성화 endpoint가 존재하며 인시던트 id, 사유, 한도 안의 미래 만료 시각을 요구하고 활성화 감사 근거를 기록하면서 런타임 HIL 승인이나 executor identity를 부여하지 않습니다. `services/operator-service/tests/test_operator_break_glass_activation.py`가 이를 증명합니다.
- [ ] 배포에서 영속 활성화 저장소, TTL 적용, 사인인 알림을 연결하고 관리되는 활성화 영수증 하나를 보존합니다.
- [ ] cache된 인증 artifact를 노출하지 않고 webview 재생성 또는 야간 중단을 통과한 loopback Browser 증적 하나를 보존합니다. Conditional Access 또는 MFA challenge는 대화형 인증 경계로 유지됩니다.

## 1. 상기하는 설계 원칙

세 안전 원칙이 이 설계를 관장; 아래 모든 선택이 이들을 보존:

1. **자기승인 없음** - 거버넌스 변경 요청자(PR 저자, HIL 트리거)는 승인자가 되어선 안 됨.
  CI + GitHub CODEOWNERS로 강제, 롤 분리로 아님.
2. **승인 ≠ 실행** - 사람은 작성, 검토, 승인하고 executor Managed Identity만 실행합니다.
3. **콘솔은 비특권 표면** - 범위가 제한된 요청을 제출할 수 있지만 executor identity를 받거나
   리소스를 변경하지 않습니다. 카탈로그 초안은 GitHub App PR을 사용합니다
   ([console-operations-ko.md](console-operations-ko.md)).

Operator Service는 token 검증과 server-owned App Role 해석 후에만 role을 serialize하며 browser payload는 이를 넓힐 수 없습니다. Core는 read 전에 principal-scoped purpose를 재검사하고 broker command identity는 executor 권한을 부여하지 않습니다.
계약은 ordinary role 4개와 고정된 topic만 허용하고 readiness에는 bridge worker 두 개가 모두 필요하며 transactional storage와 replay는 모든 projection을 request, principal, result digest에 bind합니다.

정확한 HIL 결정 재생은 결정과 정규화된 승인자 신원을 모두 보존해야 합니다. 다른 승인자가 같은
멱등성 키를 재사용하면 결정이 같아도 충돌로 처리합니다.

## 2. 롤 모델 (4티어 + Break-Glass)

Azure RBAC(읽기 담당 / 기여자 / Owner) 모델. 일상 4개 롤 + 하나의 분리된 break-glass
그룹. 롤은 **의도적으로 coarse-grained** - 차별화는 더 많은 롤 추가가 아니라 CI 검사,
CODEOWNERS 경로, 앱 레벨 정당화에서 옴.

| # | 롤 | Entra 보안 그룹 | 유사 | 가능 |
|---|-----|----------------|------|------|
| 1 | **읽기 담당** | `aw-readers` | Azure 읽기 담당 | 콘솔 조회: KPI 대시보드, 감사 로그, shadow 결과, HIL 큐 |
| 2 | **기여자** | `aw-contributors` | Azure 기여자 | 읽기 담당 + 초안 PR 작성 및 범위가 제한된 읽기 조사 시작 |
| 3 | **Approver** | `aw-approvers` | (검토자) | 읽기 담당 + 거버넌스 PR 리뷰/승인 + 런타임 HIL 요청 승인 + enforce 승격 / exemption / 재정의 승인 (고위험은 quorum - §5 참조) |
| 4 | **Owner** | `aw-owners` | Azure Owner | Approver + 비상 정지 트리거 + 런타임 설정, 환경 모델 바인딩 초안 및 Entra 그룹 멤버십 관리 + 인프라 IaC 적용 |
| - | **Break-Glass** | `aw-break-glass` | (별도 비상 계정) | Console 조회, 비상 정지, 비상 접근 권한 부여 기능만 가집니다. 런타임 HIL 승인 기능은 없으며 Owner의 superset이 아닙니다. |

**티어 추가 없이 모델을 안전하게 유지하는 규칙**

- 사용자는 여러 그룹에 소속 가능(예: 기여자와 Approver 모두), 하지만 **자기승인 없음**
  CI 검사가 여전히 자신의 PR 승인을 블록. 검사는 그룹 멤버십이 아니라 PR 저자 trailer와
  리뷰어의 Entra OID를 비교.
- **Break-Glass는 Owner 안에 중첩되지 않음.** 별도 관리 그룹; Owner 계정도 `aw-break-glass`
  에 없으면 break-glass 액션을 authorize하지 않음. 이는 Owner 계정이 손상되어도 영향 범위
  제한.
- **활성화 시 검증된 자격을 보존합니다.** 토큰 확인 과정은 기존 전역 비상 정지와 비상 접근
  기능을 위해 `BreakGlass` 역할을 보존합니다. 사람 승인 기능 매핑에서는 `BreakGlass`를
  제외하므로 콜백 경로가 비상 자격을 승인 권한으로 바꿀 수 없습니다.
- **현재 activation 경계.** `RoleResolver.activate_break_glass`는 인시던트 id와 future 만료를
  검증하는 pure activation 기본 요소입니다. `POST /system/break-glass/activation`이 그 앞의 요청
  경계로, BreakGlass 전용 `activate-break-glass` 기능과 인시던트 id, 사유, 한도 안의 미래 만료를
  요구하고 감사 전용 projection을 기록합니다. 호출 principal을 elevation하지 않으므로 토큰의
  BreakGlass 점유만으로는 여전히 HIL 승인 자격이 생기지 않습니다. persistent activation 저장소와
  TTL 적용 조립은 배포 작업으로 남습니다.
- **PIM은 선택**. 상류는 요구하지 않음. Entra ID P2 있는 포크는 just-in-time 활성화를 위해
  `aw-approvers` / `aw-owners` 위에 PIM을 얹을 수 있지만, 기본 모델은 P1에서 작동.

## 3. 페르소나 → 액션 매트릭스

| 액션 | 읽기 담당 | 기여자 | Approver | Owner | Break-Glass |
|------|:------:|:-----------:|:--------:|:-----:|:-----------:|
| 콘솔 조회 | ✓ | ✓ | ✓ | ✓ | ✓ |
| 범위가 제한된 읽기 조사 시작 | | ✓ | ✓ | ✓ | |
| 규칙 / 룰셋 초안 PR 작성 | | ✓ | ✓ | ✓ | |
| 할당 / exemption / 재정의 초안 PR 작성 | | ✓ | ✓ | ✓ | |
| 표준 거버넌스 PR 리뷰 + 승인 | | | ✓ | ✓ | |
| `audit → deny / remediate` 승격 승인 (quorum) | | | ✓ | ✓ | |
| Exemption 승인 (time-boxed) | | | ✓ | ✓ | |
| 재정의 승인 (수명이 긴 가능) | | | ✓ | ✓ | |
| 런타임 HIL 요청 승인 | | | ✓ | ✓ | |
| 런타임 HIL 요청 승인 (비상) | | | | | |
| 글로벌 비상 정지 트리거 | | | | ✓ | ✓ |
| 비상 스코프 접근 부여 | | | | | ✓ |
| 제한된 런타임 설정 관리 | | | | ✓ | |
| 환경 T1/T2 바인딩 초안 저장 또는 평가 | | | | ✓ | |
| 보호된 모델 바인딩 계획 요청 | | | | ✓ | |
| `aw-*` 그룹 멤버십 관리 | | | | ✓ | |
| 인프라 IaC 적용 (deployer) | | | | ✓ | |
| 실행기 Managed Identity 보유 | (절대) - MI는 비-사람 |||||

운영 API는 영속 명령 서비스가 연결된 경우에만 `POST /system/kill-switch`를
노출합니다. Owner 또는 externally activated BreakGlass 역할은 기능 검사를 통과하지만,
현재 운영 auth 조립에는 BreakGlass activation 경로가 없으므로 일반 토큰 해석에서
도달 가능한 emergency 호출자는 Owner입니다. 읽기 담당, 기여자, Approver는 호출할 수 없습니다.
이 엔드포인트는 콘솔 버튼이 아니며 실행기 신원을 사용하지 않고 개정 번호 상태 변경과
감사 항목을 원자적으로 기록합니다.

`manage-model-bindings` 기능도 Owner 전용입니다. 리비전이 있는 정책 초안과 권한 없는 평가 또는
문서 OCR 공급자 정책을 포함한 보호된 계획 요청을 허용합니다. Terraform 적용, 공급자 변경,
모델 호출, 승인 또는 실행기 권한을 부여하지 않습니다. Reader, Contributor, Approver 및
BreakGlass 역할은 OCR 정책을 저장하거나 계획을 요청할 수 없습니다. BreakGlass는 Owner 상위
집합이 아니며 이 기능을 상속하지 않습니다.

## 4. Entra ID 아티팩트

### 4.1 목표 App Registration

세 registration, 각각 자체 오디언스와 권한 표면. 분할이 SPA-발행 토큰이 백엔드 관리 스코프를
운반하는 것을 방지.

> 저장소는 제공된 테넌트, 대상, 클라이언트 및 역할/그룹 값을 소비합니다. 현재 Terraform은
> 이 registration이나 App 역할 배정을 프로비저닝하지 않습니다.

| App Registration | 타입 | 오디언스 | 노트 |
|------------------|------|---------|------|
| `fdai-console-spa` | SPA (PKCE, 시크릿 없음) | `fdai-api` 스코프 요청 | 콘솔 사인인만 |
| `fdai-api` | Web API | `api://<guid>` | 콘솔 + ChatOps 백엔드가 호출; **App Roles** (§4.4) 선언, 모든 요청의 `roles` 점유 검증 |
| `fdai-approval-bot` | Bot (Azure Bot 채널 registration) | `fdai-api` on-behalf-of Teams SSO | Adaptive 카드 HIL 승인 |

Redirect URI, tenantId, clientId는 **fork-provided** 이며 구성으로 주입.

### 4.2 보안 그룹 (slots)

상류가 slot 정의; 포크가 Entra `objectId` 값 공급. 시작 구성 검증이 필수 slot 누락 시
fail fast (deny-by-default).

```yaml
# shared/config schema (upstream slot definition)
rbac:
 entra:
 tenant_id: <fork-provided>
 groups:
  readers:  <objectId> # required
  contributors: <objectId> # required
  approvers:  <objectId> # required
  owners:  <objectId> # required
  break_glass: <objectId> # required (may be an empty group but must exist)
```

그룹 명명(`aw-readers` 등) 은 권장 관례; 런타임에는 objectId만 소비됨.

### 4.3 Conditional 접근

CA는 Entra ID P1에서 가능(P2 불필요). 그룹별 권장 정책:

| 대상 그룹 | 요건 |
|-----------|------|
| `aw-approvers`, `aw-owners` | **Phishing-resistant MFA** (FIDO2 / Windows Hello for Business / cert-based); 텍스트/phone OTP는 **거부** |
| `aw-owners` | 추가로 **compliant device** 또는 hybrid Entra-joined 요구 |
| `aw-break-glass` | Named-location 제한, 전용 하드웨어 토큰, 지속 사인인 알림 |
| 모든 `aw-*` 그룹 | 레거시 인증 프로토콜 블록 |

### 4.4 App Roles (토큰 표면)

API는 **App Roles를 정본 토큰 표면으로 우선 사용**합니다. App Roles는 `fdai-api` 앱
registration에 선언되고 Enterprise Applications 뷰에서 `aw-*` 그룹에 할당되며 접근 토큰의
`roles` 점유로 전달됩니다. 이행 compatibility를 위해 `roles`가 비어 있고 inline `groups`
점유가 사용 가능한 경우 `RoleResolver`는 구성된 objectId 대응을 대체 경로로 사용합니다.
Group-overage 토큰에는 이 대체 경로가 불가능하므로 FDAI App 역할이 반드시 필요합니다.

| App 역할 값 | 할당 대상 (Entra 보안 그룹) |
|-------------|--------------------------|
| `Reader` | `aw-readers` |
| `Contributor` | `aw-contributors` |
| `Approver` | `aw-approvers` |
| `Owner` | `aw-owners` |
| `BreakGlass` | `aw-break-glass` |

App Roles를 정본 표면으로 쓰는 이유:

- **테넌트 간 이식 가능.** App 역할 값은 코드에 정의된 상수; 그룹 `objectId` 는 테넌트마다
  다름. 포크는 코드가 아니라 그룹 할당을 변경.
- **Groups-overage 실패 없음.** 200개가 넘는 그룹에 속한 사용자의 토큰은 기본으로
  `groups` 점유를 생략하지만 `roles` 점유는 영향을 받지 않습니다. Overage 토큰에 FDAI
  App 역할이 없으면 API는 principal을 조용히 미할당 처리하지 않고 구성 오류로 실패 시 차단합니다.
- **앱-스코프 최소권한.** App Roles는 `fdai-api` 에만 적용; 손상된 토큰의 영향
  radius를 넓히기 위해 다른 곳에서 재사용될 수 없음.

그룹 멤버십은 **관리 표면** 유지(Owners가 Entra Portal로 멤버 추가/제거); App Roles는 API가
보는 **토큰 표면**.

## 5. 거버넌스 액션 강제 (CI + CODEOWNERS)

Coarse 롤은 PR과 API 레이어에서 **quorum + justification + 저자≠승인자** 검사로 안전하게
만들어짐:

> **구현 상태**: 런타임 기능 검사, `RoleEnforcer.no_self_approval`, risk-gate quorum을
> 구현했습니다. CI는 이제 exact-head GitHub PR, commit, review, Check Run 사실을 구성된 trusted
> verifier App이 발급한 Entra principal bundle과 결합합니다. Trusted attestation이 없으면 실패
> 시 닫힙니다. 정족수 2와 제안자, 공동 작성자 및 커미터 분리는 강제 적용 승격, 예외,
> 재정의 및 A1 라우팅에 적용됩니다. 해당 App 배포, 초안 생성 시 사람 OID trailer 기록 및
> 완전한 `@aw-approvers` CODEOWNERS 구성은 남아 있습니다.

### 5.1 목표 CODEOWNERS (단일 승인자 그룹, 경로-기반 리뷰어 카운트)

```
# CODEOWNERS
rule-catalog/rules/**    @aw-approvers
rule-catalog/assignments/**  @aw-approvers
rule-catalog/exemptions/**   @aw-approvers
rule-catalog/overrides/**   @aw-approvers
```

모든 거버넌스 PR은 최소 하나의 `@aw-approvers` 리뷰어 필요. CI가 **diff 컨텐트** 에 기반해
그 요건을 올림:

| Diff 패턴 (CI 감지) | 필요 승인 (`@aw-approvers`) |
|--------------------|---------------------------|
| 규칙 텍스트 또는 룰셋 변경 | **1** |
| 할당 파라미터 변경 (효과 승격 없음) | **1** |
| 할당 `effect` 승격 `audit → deny / remediate` | **2 (quorum)** |
| Exemption 생성 / 갱신 | **2 (quorum)** |
| 재정의 생성 / 수정 | **2 (quorum)** |
| A1 기본 / 대체 경로 변경 | **2 (quorum)** |

Quorum-2는 "elevated 승인자" 그룹 도입 없이 구체화된 shadow→enforce 승격 게이트
([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)).

### 5.2 목표 CI 검사 (상류 제공, 포크 설정)

- **저자-아님-승인자**: PR 저자의 Entra OID trailer(§6)와 모든 리뷰어의 Entra OID 파싱;
  어떤 리뷰어의 OID가 저자 OID와 같으면 실패.
- **저자-롤-검사**: PR 저자의 토큰(초안 PR 생성 시 캡처)은 `Contributor` 또는 상위 롤
  (`Approver`, `Owner`)을 포함하는 `roles` 점유를 운반해야 함. 롤은 draft-생성 시점에 PR
  trailer에 스탬프되어 CI가 리뷰 시점에 Entra를 재쿼리하지 않음.
- **Justification-존재**: 고위험 diff(위 quorum-2 행)의 경우 PR description은 `N` 문자 이상의
  `Justification:` 블록을 포함해야 함(`N` 은 설정됨).
- **서명 커밋 / 서명 trailer**: 리뷰어 승인은 특정 PR head 커밋에 바인딩; 승인 후 force-push는
  무효화하고 리뷰 재요청.

### 5.3 앱 레벨 정당화 (런타임 사람 승인)

콜백은 `justification`을 필수로 하며 누락되거나 공백이면 `400`으로 차단합니다. 역할은 콜백
JSON이 아니라 검증된 API 토큰에서 파생합니다. Teams는 API 대상이 검증되고 구성된 승인 봇을
허가된 클라이언트로 갖는 토큰을 요구합니다. Slack은 브라우저 Entra 재인증과 비어 있지 않은
공급자 사용자-Entra OID 매핑을 요구합니다.
5개 Entra 그룹 id는 역할 배정에만 사용됩니다. Teams 콜백 대상은 별도로 구성된 그룹 연결
승인 대상의 `teams:<team-id>:<channel-id>`입니다. Teams 구성은 전부 구성하거나 전부 비워야
하며, Slack은 `slack:<workspace-id>`로 독립적으로 운영할 수 있습니다.

```jsonc
POST /hil/{approval_id}/decision
{"decision":"approve","justification":"verified rollback plan","channel":"teams","provider_actor_id":"<provider-user-id>","audience":"teams:<configured-team-id>:<configured-channel-id>","correlation_id":"<original-correlation-id>","idempotency_key":"<original-idempotency-key>","action_hash":"<original-action-hash>"}
```

## 6. 목표 아이덴티티 흐름: 콘솔 → 초안 PR → 감사

목표 흐름은 저장소 쓰기를 **GitHub App** 에 위임하여 콘솔의 비특권 경계를 보존하고 사용자의
Entra OID를 no-self-approval과 감사 상관관계 검사까지 전달합니다. 현재 `GitOpsPrAdapter`는 실행기가
생성한 교정 초안 PR을 게시하지만, 콘솔 draft-governance 엔드포인트, Entra OID trailer,
사람 OID와 GitHub 로그인 매핑 저장소는 구현되어 있지 않습니다.

![6. 목표 아이덴티티 흐름: 콘솔 → 초안 PR → 감사. 주요 단계는 Sign in (MSAL, PKCE), Draft change (JSON) + access_token, Validate token, extract roles claim, schema-check, CI-dryrun, createPR(branch, patch, meta{entra_oid, upn, role, ts, sig}), Signed commit (author=github-app, / trailer: Entra-Author-OID: ), append(actor=entra_oid, action=draft-pr-create, / pr_url, correlation_id)입니다.](../../diagrams/generated/fdai-roadmap-interfaces-user-rbac-and-identity-01.ko.svg)

- SPA는 절대 GitHub PAT를 보유하지 않음. 카탈로그로의 쓰기 접근은 GitHub App에만 속함.
- 커밋의 git 작성자는 GitHub App; 사람 사용자의 Entra OID는 커밋 trailer
  (`Entra-Author-OID: <guid>`) 와 PR 본문에 동승. CI가 그 trailer를 파싱.
- 사용자의 Entra OID ↔ GitHub 로그인 매핑은 `shared/providers/` 인터페이스 뒤에 포크가 저장.
  매핑 부재 → API가 초안을 `403` 으로 거부.

## 7. ChatOps 사람 승인 흐름

이것은 HIL 승인 홉의 아이덴티티 뷰. 그 뒤의 **채널 추상화** - 카테고리, 신뢰 티어, 벤더별
규칙, 대체 경로 정책 - 는 [channels-and-notifications-ko.md](channels-and-notifications-ko.md)
에 있음.

> **현재 경계**: Teams 대화 유입은 Bot Framework JWT와 동일 테넌트 주체 연결을
> 검증합니다. 그 다음 HMAC으로 묶인 콜백은 형식화된 결정을 기록하기 전에 API 대상 Teams
> SSO OBO 토큰, 구성된 봇 클라이언트, 매핑된 Entra 행위자, 구성된 팀-채널 대상 및 현재 App Roles를
> 검증합니다. Slack은 브라우저 Entra 재인증과 명시적 공급자 사용자 매핑 뒤에만 같은 콜백을
> 사용합니다.

![7. ChatOps 사람 승인 흐름. 주요 단계는 HIL request (action_hash, idempotency_key, ttl), Adaptive Card (Teams SSO), approve / reject + justification, POST /approvals (SSO on-behalf-of), Verify approver OID ∈ aw-approvers, / action_hash matches pending, / approver OID ≠ action originator OID, decision + audit entry (correlation_id), (approved) execute입니다.](../../diagrams/generated/fdai-roadmap-interfaces-user-rbac-and-identity-02.ko.svg)

- 현재 콜백은 시각, URL `approval_id`, 본문을 HMAC에 바인딩합니다. 레지스트리 또는 parked
  조정기는 이 식별자를 pending 항목과 대조하고 원래 `correlation_id`, `idempotency_key` 및
  액션 해시를 검사한 뒤 안전하게 재시도할 수 있는 최종 결정을 강제합니다. 서명된 시각은
  안정적인 `decided_at`이며 정확한 재시도는 첫 준비/완료 감사 시각을 보존합니다. Operator는
  게시 전에 결정 보낼 편지함을 영속화하고 브로커가 수락한 뒤에만 전달 완료로 표시합니다.
  게시 실패는 재시도 가능한 `503`을 반환합니다.
- 자기 승인 차단은 서버가 인증한 Entra OID와 pending 항목의 제출자 OID를 비교합니다.
  일반 인증은 기존 BreakGlass 동작을 유지하지만 사람 승인 기능 검사에서는 BreakGlass를
  제외합니다.

## 8. 감사 상관관계

목표 거버넌스 흐름은 네 시스템에 같은 `correlation_id`를 남겨 단일 결정을 종단으로
재구성합니다. Operator 콜백은 이제 수락, 거절, 만료 및 잘못된 시도에 대해 원래 상관관계,
해시된 행위자 참조, 권한 근거 및 결과가 포함된 정제된 준비 및 완료 레코드를 기록합니다.
Entra 사인인, GitHub PR 및 Core 감사를 아우르는 보존된 운영 근거는 배포 작업으로 남습니다.

| 소스 | 기록 내용 |
|------|----------|
| Entra 사인인 로그 | 누가 사인인, MFA 방법, 디바이스, 위치 |
| `fdai-api` 액션 로그 | 어떤 API 호출, `justification`, `entra_oid`, `correlation_id` |
| GitHub PR 이벤트 | PR 저자 trailer, 리뷰어 승인, CI 검사 결과 |
| `core/audit` | 최종 결정, 티어, 실행기 / 승인자 아이덴티티, 멱등성 키 |

상관 ID는 흐름의 첫 사용자-개시 액션에서 `fdai-api` 가 생성하고 GitHub(PR 본문),
Adaptive 카드, 코어 감사 쓰기 담당으로 전파.

## 9. 포크 vs 상류 분리

아래 표는 목표 소유권 분리입니다. 현재 상류에는 역할과 기능, Entra 검증기와 해석기,
RBAC 그룹 슬롯, IAM 요청 및 디렉터리 계약, 콜백 권한 경로, 거버넌스 PR CI와 교정 PR
어댑터가 있습니다. App registration 매니페스트 템플릿과 사람 OID-GitHub 로그인 대응
프로바이더는 아직 없습니다.

| 항목 | 상류 (이 리포) | 포크 |
|------|--------------|------|
| App registration 매니페스트 템플릿 (스코프, redirect URI 스키마) | ✓ | tenantId, clientId 값 |
| 구성 스키마의 Entra 보안 그룹 **slot** | ✓ | 각 slot의 objectId 값 |
| Conditional 접근 정책 **요건** (문서화로) | ✓ | tenant-측 정책 생성 |
| CODEOWNERS 템플릿 | ✓ | GitHub 팀 이름 매핑 |
| `entra-oid ↔ github-login` 매핑 **인터페이스** (`shared/providers/`) | ✓ | 실제 매핑 데이터 |
| Justification 필드 + CI diff-risk 분류기 | ✓ | `N` (최소 길이) 튠, 경로 패턴 |
| Break-glass 알림 채널 | ✓ (인터페이스) | 실제 채널 바인딩 |

## 10. 사인인 흐름 참조

§6와 §7의 흐름 뒤 구체 프로토콜 세부사항. 모든 타이밍 값은 권장; 포크는 Conditional 접근으로
튠.

### 10.1 콘솔 (SPA) - OIDC + PKCE 있는 권한 확인 코드

- **라이브러리**: MSAL.js v4 (`@azure/msal-browser`). 암묵적 흐름 없음.
- **테넌트**: 포크당 single-tenant (`accountsInHomeTenantOnly`); 게스트 접근은 Entra B2B
  초대 통해(§10.5).
- **Redirect**: 콘솔은 anonymous 표면 없음. 로드 시 MSAL에 유효 세션이 없으면 즉시
  `/authorize` 로 리다이렉트.
- **토큰 저장**: 배포 origin은 access, id, refresh artifact를 `sessionStorage`에
  유지합니다. 표준 loopback origin은 탭 또는 VS Code webview를 재생성해도 account cache를
  복구할 수 있도록 MSAL v4의 암호화된 `localStorage`를 사용합니다. 암호화 키는 세션에
  묶이며, Entra의 Keep Me Signed In이 적용되지 않으면 browser를 닫은 뒤 다시 사인인해야 할
  수 있습니다. 다른 origin은 영속 정책을 선택할 수 없습니다.
- **세션 갱신**: 하나의 App 수명 주기 owner가 시작 시, 30분마다, focus, visibility 또는
  network 복구 뒤의 token 획득을 하나로 병합합니다. token API는 계속
  `acquireTokenSilent`를 사용합니다. Entra가 interaction 필요를 보고하면 Console은 현재
  account hint를 사용해 redirect 하나를 시작합니다. token persistence는 Conditional Access,
  MFA, revoke 또는 non-sliding SPA refresh-token lifetime을 우회하지 않습니다.
- **자동 토큰 시간 제한**: 콘솔은 기본적으로 `acquireTokenSilent`를 최대 10초 동안
  기다립니다. 토큰 획득이 멈추면 현재 패널을 계속 로드 상태로 두지 않고 재시도 작업이 있는
  인증 오류를 표시합니다. 포크의 아이덴티티 정책에 다른 제한 시간이 필요한 경우
  `VITE_AUTH_TOKEN_TIMEOUT_MS`를 양의 정수로 설정할 수 있습니다.
- **만료된 API 세션**: 구성된 읽기 또는 인제스트 API가 `401`을 반환하면 현재 데이터 표면을
  닫고 전체 화면 로그인 복구 화면으로 전환합니다. 일반 읽기, 인증된 브리지 소유 대화 상태, 대화, 작업 흐름, 명령,
  SSE 스트림에 동일하게 적용하며 `GET /live/stream`, `GET /agents/stream` 및 영속 `GET /agents/activity`도 같은 Reader bearer 게이트를 사용하고 공유 Kafka 중계는 별도의 서버 측 워크로드 자격 증명을 소유합니다. 영속 현재 상태 활동은 재생 identity용 hash correlation만 유지하고 operator 질문이나 리소스 identity는 저장하지 않습니다.
  신원 프로바이더 요청과 `403` 접근 결정은 이 전환을 시작하지 않습니다. 하나의 shared fetch 관찰기가 overlapping 소유자, 멱등적 정리 및 다른
  소유자가 global fetch 함수를 교체한 뒤의 재설치를 지원하며, 정리는 해당 replacement를
  덮어쓰지 않습니다.
- **사인아웃**: `/logout?post_logout_redirect_uri=...` 이 콘솔 세션과 테넌트의 Entra 세션
  모두 클리어.

> **로컬 개발**: 로컬 로그인 선택기에서 dev bypass를 제공할 때 콘솔은 먼저 토큰 없이
> 코어 읽기 엔드포인트를 호출합니다. 이 탐색이 성공한 경우에만 현재 세션의 bypass를
> 저장합니다. `401` 또는 `403`이면 선택기를 유지하고 운영자에게 Entra 로그인을 안내하므로,
> 인증을 강제하는 로컬 API에 깨진 anonymous 세션으로 진입하지 않습니다.

![10.1 콘솔 (SPA) - OIDC + PKCE 있는 권한 확인 코드. 주요 단계는 navigate https://console./, /authorize (client_id=spa, scope=api:///access + openid, / response_type=code, PKCE), sign-in prompt, credentials, Conditional Access evaluate / (approvers/owners → phishing-resistant MFA), MFA challenge (if triggered), FIDO2 / WHfB response, /callback?code=..., /token (code + PKCE verifier), id_token + access_token(aud=api://) + refresh_token, GET /me + Authorization: Bearer, verify signature (JWKS), aud, iss, exp; / extract oid, upn, roles입니다.](../../diagrams/generated/fdai-roadmap-interfaces-user-rbac-and-identity-03.ko.svg)

### 10.2 API 토큰 검증

API는 다음처럼 모든 요청 검증(거부 by 기본값):

1. **서명** via Entra JWKS (`https://login.microsoftonline.com/<tenant>/discovery/v2.0/keys`).
2. **오디언스** 가 `api://<fdai-api-guid>` 와 같음.
3. **발급자** 가 포크의 테넌트 발급자 URL과 같음.
4. **만료 안 됨** (`exp`) 과 **not-before 유효** (`nbf`).
5. **역할 해석** - `roles` App 역할을 먼저 사용합니다. 이 점유가 비어 있고 inline `groups`
  점유를 사용할 수 있으면 구성된 objectId 대응으로 대체 경로합니다. Group-overage 토큰에
  App 역할이 없으면 실패 시 차단합니다. 어떤 known 역할도 해석되지 않으면 protected 엔드포인트는
  `403`을 반환합니다. `aw-readers`로 자동 프로비저닝하지 않습니다.
6. **안정 아이덴티티** 는 `oid` (Entra 사용자 objectId). `upn`/이메일은 정보성; 감사와
  자기승인 없음은 `oid` 사용.

1-4단계는 제네릭
[`EntraJwtVerifier`](../../../services/operator-service/src/fdai_operator_service/auth.py) (PyJWT +
`PyJWKClient`)가 upstream에서 구현; 5-6단계는
[`RoleResolver`](../../../services/core-control-plane/src/fdai/core/rbac/resolver.py)가 구현. 이 검증기는
customer-agnostic - 포크는 값만 env로 공급:

| Env var | 필수 | 기본값 | 용도 |
|---------|:----:|--------|------|
| `FDAI_ENTRA_TENANT_ID` | yes | - | 포크의 단일 테넌트; 발급자 + JWKS URI 파생. |
| `FDAI_API_AUDIENCE` | yes | - | `fdai-api` App ID URI (`api://<fdai-api-guid>`); 토큰 `aud` 가 이것과 같아야 함. |
| `FDAI_ENTRA_ISSUER` | no | `https://login.microsoftonline.com/<tenant>/v2.0` | v1-토큰 앱용 오버라이드 (`https://sts.windows.net/<tenant>/`). |
| `FDAI_ENTRA_JWKS_URI` | no | 테넌트의 `.../discovery/v2.0/keys` | 소버린 / 에어갭 클라우드용 오버라이드. |

JWKS는 지연 fetch 후 프로세스 내 캐시; 요청별 검증은 로컬 RSA 크립토라, 동기
`ClaimsVerifier` 계약이 이벤트 루프를 막지 않고 유지됨.

### 10.3 첫 사인인 (미할당 사용자)

유효한 Entra 자격증명 있지만 `aw-*` 그룹 멤버십 없는 사용자는 콘솔에 도달할 수 있지만 어떤
기능도 얻어선 안 됨:

- Entra 인증 성공, `roles` 점유 비어 있음.
- API는 한 화면 메시지와 함께 `403` 반환: 그룹에 추가되려면 Owner에 연락.
- 역할이 필요한 엔드포인트는 `403`을 반환하고, role-optional `GET /iam/self`는 접근 필수
  화면에 필요한 self-service 변환 결과를 제공합니다. 전용 `sign-in-denied` 감사 이벤트는
  아직 구현되어 있지 않습니다.

### 10.4 ChatOps (Teams) 사인인

Teams SSO OBO 승인에 대한 목표 계약은 다음과 같습니다:

- Adaptive 카드 "Approve"/"거부" 클릭은 Teams SSO 토큰과 함께 봇에 도달.
- 봇은 Teams 토큰을 `fdai-api` 오디언스 토큰으로 교환하는 **On-Behalf-Of (OBO)**
  플로우 실행.
- API 검증(§10.2)은 동일; `roles` 점유는 `Approver` 또는 `Owner` 를 포함해야 함. 할당 없는
  첫 Teams 사용자는 같은 `403` 메시지.

### 10.5 게스트 (Entra B2B) 사용자

외부 협업자는 **Entra B2B 초대** 로 온보딩, 포크 테넌트에 게스트 `oid` 생성. 권장 포크 정책:

- 게스트는 `aw-readers` 에 추가될 수 있고 - justification과 함께 - `aw-contributors`.
- 게스트를 `aw-approvers`, `aw-owners`, `aw-break-glass`에 추가하지 않는 것이 좋습니다. 저장소는
  현재 이 사람 역할 정책을 검사하는 초기화 구성원 검사를 제공하지 않으므로 포크의 Entra
  관리 프로세스에서 강제해야 합니다.
- Conditional 접근 정책은 게스트와 멤버에 균일 적용.

### 10.6 프로그래매틱 접근 (로컬 dev, CI)

사람 사용자는 절대 PAT나 장기 시크릿을 보유하지 않음:

- **Azure-backed 로컬 콘솔**: `FDAI_OPERATOR_API_LOCAL_ENTRA=1`이 정본 interactive 개발
  모드입니다. 브라우저는 Entra로 로그인하고 API는 운영과 동일하게 JWT 서명, 발급자,
  대상, lifetime, App 역할을 검증합니다. 서버의 Azure CLI 세션은 Microsoft Graph, Azure
  Resource Graph 및 로컬 Azure OpenAI 서술 같은 Azure 어댑터에만 단기 토큰을 제공하며 브라우저
  principal을 대체하지 않습니다. Event Hubs 토큰 refresh는 변경 가능한 Azure CLI 기본값 계정이 아니라
  준비된 런타임 테넌트와 구독에 고정됩니다. App 역할이 없는 principal에는 접근 요청 페이지가 표시되고,
  bearer 토큰이 없으면 실패 시 차단합니다. Full-stack 준비 단계는 두 개의 고정 loopback 출처를
  구성된 SPA 등록에 안전하게 재시도할 수 있는 방식으로 동기화합니다. 테넌트가 다르거나 Graph
  권한이 부족하면 sign-in 후 redirect가 깨진 상태로 남지 않도록 시작을 중단합니다.
- **CLI principal 대안**: 브라우저 로그인이 필요하지 않을 때
  `FDAI_OPERATOR_API_LOCAL_AZURE_CLI=1`과 `VITE_LOCAL_AZURE_CLI_AUTH=1`은 현재 CLI 사용자를 고정된
  로컬 역할 상한으로 변환 결과합니다. 이는 명시적 대안이며 정본 full-stack 프로파일이
  아닙니다.
- **Synthetic 고정본**: 익명 권한 부여, static 사용자, 시드 감사 기록 및 시나리오 재생은
  pytest의 `app(test_fixtures=True)`에서만 사용할 수 있습니다. Interactive 개발 데이터 원본이
  아닙니다.
- **직접 API 클라이언트**: 개발 테넌트의 전용 `fdai-api-dev` 오디언스로 범위가 지정된
  토큰을 요청합니다. 10.2절의 표준 서명, 오디언스, 발급자, 만료, App 역할 검사가 그대로
  적용됩니다.
- **CI**: 워크로드 신원 federation (OIDC), [deployment-ko.md](../deployment/deployment-ko.md) 에서
  이미 필수. GitHub Actions와 Azure DevOps 모두 지원.
- **PAT는 금지**. CI의 시크릿 검사가 우발적 커밋 블록
  ([coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)).

### 10.7 Break-Glass 사인인

- Break-glass는 **전용 계정** (사람의 개인 계정 아님), 물리적 보관하의 하드웨어 FIDO2 키로
  저장.
- 모든 사인인에 대한 break-glass 알림과 상승된 감사 기록은 배포 운영 계약입니다. 운영 API는
  활성화 요청을 기록하는 `POST /system/break-glass/activation`을 제공하며, persistent activation
  저장소와 알림 조립은 배포 작업으로 남고 저장소가 구성되지 않으면 엔드포인트는 차단됩니다.
- `BreakGlass` 권한은 `RoleResolver.activate_break_glass`로 별도 활성화되어야 합니다.
  활성화된 `BreakGlass`만으로 비상 정지와 비상 접근 권한 부여 기능을 가질 수 있으며
  `Owner`와 `BreakGlass`를 동시에 요구하지 않습니다.
- Break-glass 자격증명 로테이션과 드릴 주기는
  [security-and-identity-ko.md](../architecture/security-and-identity-ko.md) 에 선언.

## 11. 콘솔 설정 및 액세스 요청

Settings 활동 bar 그룹은 콘솔의 클라우드 권한을 넓히지 않고 일곱 개의 안정적인 경로를
제공합니다.

| 경로 | 목적 |
|------|------|
| `/settings/general` | 브라우저 로컬 표시, 언어, 모션 및 답변 검증 환경 설정입니다. |
| `/settings/models` | 해결된 T1/T2 모델, 라이프사이클 및 지연 시간 근거, 로그인 사용자의 T1 서술기 선호, 런타임 상태를 변경하지 않는 distinct-publisher T2 카탈로그 초안 빌더입니다. Interactive 로컬은 테넌트 식별자, 엔드포인트 또는 자격 증명을 복사하지 않고 준비된 resolved-model 산출물에서 이 화면을 materialize합니다. |
| `/settings/runtime-policies` | 허용 목록된 런타임 정책의 정제된 환경, 영속 재정의 및 effective 값을 표시합니다. Interactive 로컬은 준비 상태를 추론하지 않고 검증된 준비 환경에서 진단과 구성된 통합 상태를 materialize합니다. 읽기 담당은 조회하고 Owner는 개정 번호 및 감사 검사를 통해 업데이트합니다. |
| `/settings/memory` | 프로바이더가 등록된 경우 영속 운영자 지침을 표시하고, 그렇지 않으면 명시적인 사용 불가 상태를 표시합니다. |
| `/settings/iam` | 로그인 principal, App 역할, 유효 기능, 참조된 사용자 및 액세스 요청입니다. |
| `/settings/integrations` | ID, 전달 및 운영자 채널 연결의 읽기 전용 상태입니다. |
| `/settings/diagnostics` | Operator API 엔드포인트 및 인증 세션 진단입니다. |

`/settings`는 `/settings/general`의 호환성 별칭으로 유지됩니다. Settings는 하단 탐색
그룹이므로 선택하면 이전 도메인 메뉴를 남기지 않고 다른 운영자 도메인과 같은 Explorer
패턴을 엽니다.

### 11.1 IAM 변환 결과

`GET /iam`은 서버가 검증한 principal, 고정된 다섯 역할 정의, 유효 기능 합집합, 명시적인
FDAI Owner 권한, 디렉터리 가용성, 요청 및 공급자 변경 경계를 반환합니다. Azure 구독,
Entra 테넌트 또는 애플리케이션 관리자 역할이 FDAI Owner를 의미하지는 않습니다.
`GET /iam/access-requests`는 해당 principal이 볼 수 있는 요청을 반환합니다.
접근 요청 ID는 Owner에게만 표시됩니다. 읽기 담당, 기여자 및 Approver 요청은 `403`을
받습니다. Users 및 접근 requests 탭은 잠금 아이콘과 함께 계속 표시되며, 탭을 선택하면
상호 작용을 무시하지 않고 즉시 접근 거부된 표면을 렌더링합니다. 역할이 없는 사용자는
role-optional `GET /iam/self` 변환 결과를 통해 자신의 요청만 봅니다.
역할이 할당된 principal의 `GET /iam/self`는 검증된 App 역할에서 콘솔 접근을 직접 도출하므로 access-request 변환 결과에 의존하지 않습니다. 역할이 없는 principal은 계속 해당 변환 결과가 필요하며, 사용 불가이면 어떤 접근도 얻지 못합니다.

Users 탭은 범위가 제한된 두 원본을 결합합니다. 검증된 로그인 principal과 표시 가능한
액세스 요청에 참조된 사용자를 보여줍니다. Owner는 `GET /iam/directory/users?q=...`를 통해
구성된 `HumanIdentityDirectory`를 검색하고 계정을 선택해 통제된 액세스 요청을 미리 채울
수도 있습니다. 로컬 실행은 서버의 Azure CLI 자격 증명을 사용하고 배포 실행은 Operator
Managed Identity를 사용합니다. 두 경로 모두 읽기 전용 Graph 바인딩이며 브라우저는
프로바이더 자격 증명을 받지 않습니다.

`GET /iam/directory/roster`는 FDAI 엔터프라이즈 애플리케이션의 실제 App Role 할당을
표시합니다. Entra 어댑터는 서비스 principal을 찾고 각 App Role ID를 역할 값에 매핑하며,
할당된 그룹의 모든 하위 멤버를 확장합니다. 직접 사용자 할당과 그룹에서 파생된 할당은
안정적인 대상 ID로 병합됩니다. Users 탭은 People 및 Groups를 필터링하지만 역할 요청은
활성 상태인 사람에게만 제공됩니다.

`HumanIdentityDirectory`는 cloud-provider-neutral 계약입니다. 각 어댑터는 안정적인
`provider`, `subject_id`, 사용자 이름, 표시 이름, 사용자 유형 및 활성 상태를 반환합니다.
Microsoft Entra ID가 구현된 어댑터이며 managed 신원 및 애플리케이션 권한
`User.Read.All`, `GroupMember.Read.All`로 Microsoft Graph `/users` 및 역할 그룹 멤버십을
사용합니다. AWS IAM 신원 Center와 Google
Cloud 신원 어댑터는 향후 범위입니다. 동일한 프로토콜을 구현하면 코어 서비스, API
페이로드 또는 콘솔을 변경하지 않고 추가할 수 있습니다.

API는 통제된 역할 요청을 수락하기 전에 구성된 프로바이더를 기록하고
`get_by_subject_id`로 대상, 사용자 이름 및 활성 상태를 확인합니다. 클라이언트가 제공한
프로바이더 라벨은 ID 백엔드를 선택하지 않습니다.

Agent oversight > 매핑 검토가 Owner 전용 할당 작업 영역을 담당합니다. ID 및 액세스는
다섯 번째 탭을 중복해서 만들지 않고 이 작업 영역으로 연결합니다.
`POST /iam/assignment-cases`는 정확한 활성
대상을 다시 검증하고 변경 불가능한 역할, 임무, 목표 및 사유 의도를 기록합니다. 리비전 기반
제출 및 검토 명령은 CAS를 사용합니다. `GET /iam/assignments`는 관측된 디렉터리 역할, 구성된 담당
체계 맵, 할당 케이스 및 인수인계 가용성만 조인합니다. 누락된 프로바이더 또는 인수인계 근거는
`null` 또는 `not_connected`로 유지하며 어떤 경로도 Graph 쓰기 프로바이더를 받지 않습니다.

일치하는 검토 후 담당 체계 병합이 끝나면 거버넌스 서비스가 멱등
`ops.apply-human-access` 요청 하나를 타입이 지정된 유입에 게시합니다. 런타임 전용 어댑터는
전용 관리 ID, 구성된 읽기 담당, 기여자, Approver, Owner 그룹 ID, 제한된 apply, verify,
롤백 호출을 사용합니다. BreakGlass, 동적 그룹, role-assignable 그룹, 임의 그룹 ID를
차단합니다. 이 경로는 별도 승격 전까지 관찰 전용입니다.

Interactive 로컬 모드는 synthetic 디렉터리로 대체 경로하지 않습니다. Microsoft Graph
어댑터는 서버의 Azure CLI 자격 증명을 사용해 FDAI 서비스 principal, 실제 App Role 할당,
모든 하위 그룹 멤버를 찾습니다. 따라서 별칭 검색, 역할 명단 및 접근
요청 대상은 로그인한 테넌트의 실제 데이터를 반영하며 프로바이더 자격 증명은 브라우저
외부에 유지됩니다. Offline 고정본 신원은 pytest 전용입니다.

### 11.2 통제된 요청 흐름

기여자 이상 역할은 다음 필드로 `POST /iam/access-requests`를 제출할 수 있습니다.

| 필드 | 규칙 |
|------|------|
| `idempotency_key` | 필수입니다. 동일한 의도로 재사용하면 기존 요청을 반환하고 다른 의도로 재사용하면 `409`를 반환합니다. |
| `identity_provider` | 클라이언트의 정보용 값입니다. API가 구성된 어댑터 이름을 기록합니다. |
| `target_subject_id` | 해당 프로바이더의 안정적인 계정 대상입니다. 마이그레이션 중에는 기존 `target_oid` 입력도 허용됩니다. |
| `target_username` | 검토를 위한 사람이 읽을 수 있는 이름 또는 UPN입니다. 권한 부여는 이 값을 신뢰하지 않습니다. |
| `operation` | `grant`, `revoke` 또는 `set`입니다. `set`은 행별 역할 dropdown 변경을 표현합니다. |
| `role` | `Reader`, `Contributor`, `Approver` 또는 `Owner`입니다. 일반 `BreakGlass` 요청은 차단됩니다. |
| `justification` | 20-2000자입니다. 요청 제안과 이후 Core 감사 전환에 저장됩니다. |

API는 검증된 토큰에서 요청자와 기능을 도출합니다. 각 요청을 안전하게 다시 시도할 수 있는
영속 Operator 제안으로 저장하고 완전한 요청 변환 결과를 Console에 반환합니다. 검토 결정은
별도의 영속 제안이며 자기 검토를 차단하고 원래 의도를 변경하지 않은 채 요청 변환 결과에
반영됩니다. 요청 검토는 안정적인 `request_id`를 직접 조회하므로 목록에 페이지 나누기가
적용된 뒤에도 이전 요청을 검토할 수 있습니다. 응답 상태는 `pending`입니다. 양식 제출은
요청을 승인하거나 Entra 그룹 멤버십을 변경하지 않습니다. Core 게시와 hash-chain 기반
`iam.access-requested` 및 `iam.access-reviewed` 기록은 별도의 전달 경계로 유지됩니다.

승인은 ChatOps 또는 거버넌스 PR 경로에 유지됩니다. 승인 후 Owner가 테넌트의 ID 관리
프로세스를 통해 허용 목록에 포함된 `aw-*` 그룹 변경을 반영합니다. 이 분리를 통해 브라우저,
Operator API 및 실행기 ID가 Microsoft Graph 멤버십 권한을 갖지 않도록 유지합니다.

### 11.3 역할이 없는 첫 로그인

FDAI App 역할이 없는 인증된 사용자는 운영자 shell에 진입하지 않습니다. 콘솔은 역할이
필요 없는 `GET /iam/self`를 호출하고 다음 항목을 포함한 접근 필수 화면을 렌더링합니다.

- 검증된 계정
- self-service로 사용할 수 있는 유일한 역할인 `Reader`
- 선택적 메시지
- 제출 후 현재 요청 ID 및 `pending` 상태
- 다시 확인 및 로그아웃 작업

`POST /iam/access-requests/self`는 검증된 토큰에서 대상 대상을 도출합니다. 동일 대상에
대한 `grant Reader`만 허용합니다. 브라우저 본문을 수정해도 다른 대상, 상위 역할 또는
철회 요청은 차단됩니다.

요청은 요청자, 프로바이더 대상, 역할 및 감사 상관관계와 함께 Settings > 신원 and
접근에서 Owner에게 표시됩니다. Owner는 IAM에서 justification과 함께 `approve` 또는
`reject`를 기록할 수 있습니다. API는 자기 승인을 차단하고 불변 요청과 별도로 결정을
저장하며 `iam.access-reviewed` 감사 항목을 기록합니다. 고위험 런타임 승인은 ChatOps와 기존
Approvals 표면에 유지됩니다. IAM 검토는 자율 작업을 승인하지 않습니다.

승인된 IAM 요청은 `approved` 상태이지만 다음 토큰에 역할이 포함되기 전에 프로바이더 측 그룹
할당이 여전히 필요합니다. 승인 principal과 할당 principal은 분리됩니다. 향후 프로바이더
자동화는 요청 또는 검토 계약을 변경하지 않고 승인된 변환 결과를 소비할 수 있습니다.

## 12. 열림 Decisions

- [ ] API가 `entra_oid ↔ github_login` 매핑을 감사와 같은 PostgreSQL(단일 저장소)에 저장할지
   별도의 포크 소유 아이덴티티 저장소에 저장할지.
- [ ] Diff-risk 티어별 정확한 `Justification` 최소 길이(현재 config-only).
- [ ] Owner가 Break-Glass 멤버도 될 수 있는지(기본: **아니오**; 포크 부트스트랩에서 CI로 강제).
- [ ] `aw-owners` 와 `aw-break-glass` 멤버십 로테이션 주기(수동 접근 리뷰 vs P2 Entra 접근
   Reviews).
- [ ] 콘솔의 "초안 변경" UI가 P1(변경 안전성만)에 실릴지 P3(3개 버티컬 모두)에 실릴지
   - [rule-governance-ko.md](../rules-and-detection/rule-governance-ko.md#open-decisions) 저작-UI 결정에 의존.
- [ ] 게스트 사용자가 `Contributor` 로 할당될 수 있는지 아니면 `Reader` 전용에만 머물러야
   하는지(§10.5 기본은 justification과 함께 기여자 허용).
- [ ] 콘솔 세션 최대 수명 값(Conditional 접근 설정); 기본 권장: idle 8시간, 절대 24시간.
