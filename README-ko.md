---
translation_of: README.md
translation_source_sha: a188a1243392a673660c25c354d239adade4c901
translation_revised: 2026-08-01
---

# FDAI

**Forward Deployed Agents for Cloud Ops.** FDAI는 클라우드 환경에서 동작하는 자율 운영
컨트롤 플레인입니다. Azure 이벤트를 감시하고, 반복 가능한 문제는 규칙과 정책으로
결정론적으로 해결하며, LLM 추론은 소수의 모호한 사례에만 사용합니다. 따라서 대부분의
운영 작업을 사람의 개입 없이 자동으로 처리합니다.

FDAI의 차별점은 3-tier 신뢰 라우터를 통한 결정론 우선 처리(T0 규칙 -> T1 유사 사례
재사용 -> T2 근거 기반 LLM 추론), 모든 자율 액션의 관찰 모드 우선 적용, 지속적으로
갱신되는 규칙 카탈로그입니다. 액션은 수정 PR로 전달되므로 Git에서 감사 이력과 롤백
경로를 함께 확보할 수 있습니다.

## 무엇을 얻을 수 있나요?

FDAI는 하나의 이벤트 기반 코어에서 세 가지 초기 운영 영역을 제공합니다. 다른 AIOps
영역(posture management, SRE/SLO)도 같은 아키텍처로 확장할 수 있으며 향후 범위에
포함됩니다.

### Change Safety

제안된 모든 변경에 규칙 카탈로그 기반 정책 게이트를 적용합니다. 각 후보는
policy-as-code(정책을 기계 판독 가능한 규칙으로 표현)를 기준으로 dry-run 검증을 거치고,
명확한 영향 범위 안에서 제한됩니다. 저위험 변경은 자동으로 병합하고 고위험 변경은
사람의 승인을 받도록 전달합니다.

예시: IaC PR이 public-egress NSG 규칙을 도입 -> 안전성 검토에서 고위험으로 판정 ->
Teams에 승인 카드 전송 -> 승인자가 승인 -> executor가 수정 pull request를 병합하고
감사 항목을 기록.

### Resilience

예약된 재해 복구(DR) 훈련, 데이터베이스 복구 훈련, 영향 범위가 제한된 카오스 실험을
제공합니다. 스케줄러는 실행 주기를 관리하고, 안전성 검토는 영향 범위를 제한하며,
감사 로그는 실행 결과를 증거로 보존합니다.

예시: 야간 작업이 중요 데이터베이스에서 PITR 공백을 발견 -> 에이전트가 지정된 훈련
시간대에 연계 복원 훈련을 예약 -> 목표 RPO/RTO를 충족하며 복원에 성공 -> 감사 항목으로
규정 준수 증거를 확보.

### Cost Governance

지출 이상 탐지, 용량 최적화 권고, 저위험 작업(유휴 디스크 정리, 미사용 public IP 해제,
orphan NIC 제거)을 자동으로 실행합니다.

예시: 비용 이상 탐지기가 과도하게 프로비저닝된 캐시 티어를 감지 -> T0 규칙과 일치 ->
2주 동안 관찰 모드에서 정확도를 검증 -> 적용 모드로 전환 -> 롤백 경로를 포함한 용량
최적화 수정 pull request를 생성.

### Rule Catalog That Grows Itself

카탈로그는 스스로 최신 상태를 유지합니다. discovery loop가 업스트림 소스(WAF, MCSB,
CIS, Advisor, OPA/Gatekeeper, Checkov, tfsec, KICS, Trivy, kube-bench)와 운영
신호(승인 패턴, 관찰 정확도 편차, override)를 관찰하고 새 규칙, 규칙 개정, 폐기 대상을
같은 quality gate에 제안합니다.

예시: 관찰 모드에서 정상 트래픽에 같은 규칙이 연속 세 번 발동 -> discovery loop가
정확도 변화를 감지 -> 임계값을 조정한 개정 PR을 새 regression suite와 함께 생성.

## 여러분의 스택 전체에서 작동합니다

- **Azure 리소스**: Azure Resource Manager를 통해 접근 가능한 모든 리소스와 그
  어댑터(Container Apps, PostgreSQL Flexible, Kafka 프로토콜의 Event Hubs, native
  secret binding을 통한 Key Vault).
- **GitOps 전달**: 모든 자율 액션은 수정 pull request(GitHub App 또는 Azure DevOps)로
  전달됩니다. Git에서 감사 이력과 롤백 경로를 관리합니다.
- **ChatOps**: 사람의 승인은 Teams Adaptive Cards를 통해 이루어집니다. Slack, email,
  webhook, pager, SMS는 발신 전용 알림을 위한 확장형 채널로 제공됩니다.
- **이벤트 버스**: Event Hubs Standard의 Kafka wire protocol. Native Azure
  신호(Activity Log, Resource events)는 Kafka 토픽으로 포워딩되어 코어는 Kafka만
  봅니다.
- **CSP-neutral 설계**: 클라우드 접근은 provider 어댑터(OPA로 policy-as-code,
  Terraform으로 infrastructure-as-code) 뒤에 있습니다. 클라우드 프로바이더
  중립(CSP-neutral)은 설계 원칙입니다. 현재 구현 대상은 Azure이며 비-Azure 공급자는
  추후 검토 대상입니다. 나중에 어댑터를 추가할 수 있도록 확장 지점은 보존하지만,
  제공 시점을 약속하지는 않습니다.

## 어떻게 작동하나요?

1. **Ingest**: 이벤트가 버스에 들어오면 `event-ingest`가 정규화·중복 제거하고 관련
   이벤트를 하나의 인시던트로 상관합니다.
2. **Route**: trust router(이벤트를 처리할 티어를 선택)가 문제를 해결할 수 있는 가장
  낮은 티어를 선택합니다. T0 규칙 기반 판정 -> T1 경량 재사용(해결된 인시던트와의
   유사도) -> T2 추론(frontier LLM + verifier + mixed-model cross-check + policy
  근거 검증). T2 출력은 quality gate(모델 출력이 통과해야 하는 검사 세트)를
   통과해야 실행 자격이 생깁니다.
3. **Gate and act**: 안전성 검토가 자동 실행(`auto`), 사람 승인(`hil`), 판단 보류
  (`abstain`), 거부(`deny`)를 결정합니다. 자동 실행 자격이 있거나 승인된 액션은 수정
  pull request가 됩니다. 거절, 시간 초과, 판단 보류를 포함하여 모든 종료 경로는 감사
  항목을 기록합니다.

```text
event -> event-ingest -> trust-router -> T0 | T1 | (T2 -> quality-gate)
      -> risk-gate    -> auto | HIL | abstain -> executor -> delivery -> audit
```

## 여러분의 환경과 함께 성장

- **Day 1**: T0 규칙이 관찰 모드에서 이벤트를 처리합니다. 감지된 모든 문제에 감사
  항목을 남기므로 실제로 변경하지 않고도 어떤 작업을 수행했을지 확인할 수 있습니다.
- **Week 1**: 관찰 지표를 통해 promotion gate를 통과할 액션을 확인합니다. T1은 해결된
  인시던트 패턴을 재사용하기 시작하고 T2는 낮은 비중을 유지합니다.
- **Month 1**: 승격된 액션은 롤백 경로와 함께 자동으로 실행됩니다. Discovery loop는
  운영 신호(승인 패턴, 관찰 정확도 편차, override)를 바탕으로 카탈로그 갱신을
  제안하기 시작합니다.

FDAI를 오래 운영할수록 T2 비중은 작아지고 자동 해결 비율은 높아집니다. 모든 목표는
측정된 기준선을 바탕으로 검증한 뒤에만 달성했다고 말할 수 있습니다
([goals-and-metrics-ko.md](docs/roadmap/architecture/goals-and-metrics-ko.md)).

## 시작하기

- **사용자 가이드**: [docs/user-guide/get-started-ko.md](docs/user-guide/get-started-ko.md)
- **상세 로드맵**: [docs/roadmap/README-ko.md](docs/roadmap/README-ko.md)
- **컨트리뷰터 규칙**: [.github/copilot-instructions.md](.github/copilot-instructions.md)

이 저장소는 범용이며 고객-비종속입니다. 고객별 커스터마이즈는 별도 포크에서 컴포지션
루트를 통해 배선됩니다
([generic-scope.instructions.md](.github/instructions/generic-scope.instructions.md)).

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| 컨트롤 루프와 3-tier 라우팅 | [architecture.instructions.md](.github/instructions/architecture.instructions.md) |
| 배포 토폴로지 (headless core + PR delivery + thin console + ChatOps) | [app-shape.instructions.md](.github/instructions/app-shape.instructions.md) |
| 모든 자율 액션의 안전 규칙 | [coding-conventions.instructions.md](.github/instructions/coding-conventions.instructions.md) |
| 단계별 출시 계획 (P0 -> P4) | [docs/roadmap/README-ko.md](docs/roadmap/README-ko.md) |
| 위험 분류 (auto vs 사람 승인 vs deny) | [docs/roadmap/decisioning/risk-classification-ko.md](docs/roadmap/decisioning/risk-classification-ko.md) |
| Shadow-then-enforce 승격 | [docs/user-guide/concepts/shadow-then-enforce-ko.md](docs/user-guide/concepts/shadow-then-enforce-ko.md) |

## 라이센스

Business Source License 1.1 (BSL 1.1)에 따라 라이선스됩니다. 상업적 사용에는 별도의
라이선스가 필요하므로 유지관리자에게 문의하세요. 자세한 내용은 [LICENSE](LICENSE)를
참조하세요.
