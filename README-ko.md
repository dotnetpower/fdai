---
translation_of: README.md
translation_source_sha: fc6a315deb476eeb6469f246183ecf2cb832d0e8
translation_revised: 2026-07-22
---

# FDAI

**Forward Deployed Agents for Cloud Ops.** FDAI는 클라우드 안에 상주하는 자율
컨트롤 플레인입니다. Azure 이벤트를 지켜보다가 반복 가능한 것은 규칙과
정책으로 결정론적으로 해결하고, LLM 추론은 남은 소수의 모호한 케이스에만 사용합니다.
그래서 대부분의 운영은 사람 검토 없이 굴러갑니다.

무엇이 다른가: 3-tier 신뢰 라우터로 결정론 우선(T0 규칙 -> T1 유사도 재사용 -> T2 근거
LLM)이고, 자율 액션은 반드시 shadow 모드로 먼저 배포되며, 규칙 카탈로그는 스스로
갱신됩니다. 액션은 수정 PR로 전달되어 감사와 롤백이 git에서 자동으로 확보됩니다.

## 무엇을 얻을 수 있나

FDAI는 하나의 이벤트 기반 코어 위에 세 개의 초기 버티컬을 얹습니다. 다른 AIOps
도메인(posture management, SRE/SLO)은 같은 아키텍처에 맞으며 향후 범위입니다.

### Change Safety

제안된 모든 변경에 대해 규칙 카탈로그 기반 정책 게이트를 적용합니다. 각 후보는
policy-as-code(정책을 기계 판독 가능한 규칙으로 표현)에 대해 dry-run되고,
영향 범위가 명확히 제한되며, 저위험은 자동 병합되고 고위험은 사람 승인으로
라우팅됩니다.

예시: IaC PR이 public-egress NSG 규칙을 도입 -> 안전성 검토가 고위험으로 판정 ->
Teams에 사람 승인 카드 -> 승인자가 approve 클릭 -> executor가 수정 pull request를
병합하고 감사 엔트리를 기록.

### Resilience

예약된 재해 복구 훈련, DB DR 훈련, 영향 범위가 한정된 카오스 실험. 스케줄러가
주기를 담당하고, 안전성 검토가 범위를 담당하며, 감사 로그가 증거를 담당합니다.

예시: 야간 잡이 critical DB에서 PITR 갭을 발견 -> agent가 훈련 시간대 안에서
페어링된 복원 훈련을 스케줄링 -> RPO/RTO 목표에 대해 복원 성공 -> 감사 엔트리로
컴플라이언스 증거 확보.

### Cost Governance

지출 이상 탐지, 사이즈 최적화 권고, 저위험 하위집합(유휴 디스크 정리, 미사용 public
IP 해제, orphan NIC 제거) 자동 실행.

예시: 비용 이상 탐지기가 캐시 티어 과잉 프로비저닝에서 트리거 -> T0 규칙 매칭 ->
2주 동안 관찰 모드로 정확도 증명 -> 적용 모드 활성화 -> 롤백 경로를 갖춘 사이즈
최적화 수정 pull request가 나갑니다.

### Rule Catalog That Grows Itself

카탈로그는 스스로 최신 상태를 유지합니다. discovery loop가 업스트림 소스(WAF, MCSB,
CIS, Advisor, OPA/Gatekeeper, Checkov, tfsec, KICS, Trivy, kube-bench)와 운영
신호(승인 패턴, 관찰 정확도 드리프트, 오버라이드)를 관찰하여 새 규칙 / 개정 / 폐기
후보를 같은 quality gate로 제안합니다.

예시: 연속 3건의 관찰 모드 엔트리가 정상 트래픽에 대해 규칙 발동을 보임 -> discovery
loop가 드리프트를 플래그 -> 임계값을 강화한 개정 PR이 새 regression suite와 함께
도입됩니다.

## 여러분의 스택 전반에서 동작

- **Azure 리소스**: Azure Resource Manager를 통해 접근 가능한 모든 리소스와 그
  어댑터(Container Apps, PostgreSQL Flexible, Kafka 프로토콜의 Event Hubs, native
  secret binding을 통한 Key Vault).
- **GitOps 전달**: 모든 자율 액션은 수정 pull request(GitHub App 또는 Azure DevOps).
  감사와 롤백은 git에서.
- **ChatOps**: 사람 승인은 Teams Adaptive Cards. Slack, email, webhook, pager,
  SMS는 발신 전용 카테고리를 위한 플러그형 채널.
- **이벤트 버스**: Event Hubs Standard의 Kafka wire protocol. Native Azure
  신호(Activity Log, Resource events)는 Kafka 토픽으로 포워딩되어 코어는 Kafka만
  봅니다.
- **CSP-neutral 설계**: 클라우드 접근은 provider 어댑터(OPA로 policy-as-code,
  Terraform으로 infrastructure-as-code) 뒤에 있습니다. 클라우드 프로바이더
  중립(CSP-neutral)은 설계 원칙이며, Azure가 구현 대상이고 비-Azure 프로바이더는
  TBD입니다. 어댑터를 나중에 붙일 수 있도록 seam은 보존되어 있지만 배송 약속은
  아닙니다.

## 어떻게 동작하나

1. **Ingest**: 이벤트가 버스에 들어오면 `event-ingest`가 정규화·중복 제거하고 관련
   이벤트를 하나의 인시던트로 상관합니다.
2. **Route**: trust router(이벤트를 결정할 티어를 고름)가 가장 낮은 충분 티어를
   선택합니다. T0 결정론(규칙 판정) -> T1 lightweight 재사용(해결된 인시던트와의
   유사도) -> T2 추론(frontier LLM + verifier + mixed-model cross-check + policy
   근거 확인). T2 출력은 quality gate(모델 출력이 통과해야 하는 검사 세트)를
   통과해야 실행 자격이 생깁니다.
3. **Gate and act**: 안전성 검토가 자동 실행(`auto`), 사람 승인(`hil`), 판단 보류
  (`abstain`), 거부(`deny`)를 결정합니다. 자동 실행 자격이 있거나 승인된 액션은 수정
  pull request가 됩니다. 거절, 시간 초과, 판단 보류를 포함한 모든 종료 경로는 감사
  엔트리를 씁니다.

```text
event -> event-ingest -> trust-router -> T0 | T1 | (T2 -> quality-gate)
      -> risk-gate    -> auto | HIL | abstain -> executor -> delivery -> audit
```

## 여러분의 환경과 함께 성장

- **Day 1**: T0 규칙이 관찰 모드로 이벤트에서 돌아갑니다. 발견된 모든 문제는 감사
  엔트리를 남겨 "무엇을 했을지"를 보여줍니다.
- **Week 1**: 관찰 지표로 어떤 액션이 promotion gate를 통과하는지 확인. T1이
  해결된 인시던트 패턴을 재사용하기 시작하고, T2는 소수 비중을 유지.
- **Month 1**: 승격된 액션은 롤백 경로와 함께 자율 실행됩니다. discovery loop가
  여러분의 운영 신호(승인 패턴, 관찰 정확도 드리프트, 오버라이드)에서 카탈로그
  갱신을 제안하기 시작합니다.

오래 돌수록 T2 비중은 작아지고 자동 해결 비율은 높아집니다. 모든 목표는 측정된
베이스라인 위에서만 주장 가능합니다
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
| 단계별 배송 계획 (P0 -> P4) | [docs/roadmap/README-ko.md](docs/roadmap/README-ko.md) |
| 위험 분류 (auto vs 사람 승인 vs deny) | [docs/roadmap/decisioning/risk-classification-ko.md](docs/roadmap/decisioning/risk-classification-ko.md) |
| Shadow-then-enforce 승격 | [docs/user-guide/concepts/shadow-then-enforce-ko.md](docs/user-guide/concepts/shadow-then-enforce-ko.md) |

## 라이센스

Business Source License 1.1 (BSL 1.1)로 배포됩니다. 상업 사용은 별도 라이센스가
필요하므로 메인테이너에게 문의하세요. [LICENSE](LICENSE) 참고.
