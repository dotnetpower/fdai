---
title: 다중 채널 알림 전달
translation_of: multi-channel-notification-delivery.md
translation_source_sha: 6882334dff0c0b18f28c9fc6cb7cb34667288bc4
translation_revised: 2026-08-31
---
# 다중 채널 알림 전달

이 문서는 하나의 운영 알림 또는 요약(digest)이 처음 수락한 채널에서 멈추지 않고 운영자가
활성화하고 설정한 **모든** 알림 채널에 도달하는 방식을 소유합니다. 또한 사용 중지된 Office 365
connector 전송을 대체하는 Microsoft Teams Workflows 웹훅 바인딩을 규정합니다.

> **범위:** `NotificationChannel`이 전달하는 A2 운영 알림과 A4 요약을 포함합니다. A1 승인
> (`HilChannel`)과 A3 대화(`ConversationChannelAdapter`)는 기존 계약을 유지하며 명시적으로
> 범위에서 제외합니다.
>
> **소유 경계:** [채널과 알림](channels-and-notifications-ko.md)이 카테고리, trust tier, 수신
> 대상 도출, 지역화에 대한 권위를 유지합니다. 이 문서는 그 아래의 전달 의미와 채널 바인딩
> 모델만 구체화합니다.

## 설계 한눈에 보기

현재 라우터는 `primary -> fallback[0] -> fallback[1]` 순으로 진행하다가 한 채널이 전달 성공을
보고하는 즉시 반환합니다. 그래서 Teams 채널, Slack 채널, 당직 메일함을 함께 운영하는 배포에서도
가장 먼저 정상 응답한 하나에만 도달합니다. 운영자는 이를 성공적인 failover가 아니라 알림 누락으로
받아들입니다.

Fan-out 전달은 단일 승자를 명시적인 대상 집합, 대상별 영속 전달 기록, 독립 재시도, 부분 성공을
보고할 수 있는 집계 결과로 대체합니다. Trust tier 검사, 편집(redaction) 규칙, 전체 실패 시
에스컬레이션 동작은 그대로입니다.

```text
notice
  -> resolve route (category -> trust tier + declared channels)
  -> compute target set (declared AND enabled AND configured AND trust-allowed)
  -> persist dispatch plan (frozen target snapshot)
  -> send to every target with bounded parallelism
  -> per-target durable state (accepted / delivered / retryable / ambiguous / abandoned)
  -> aggregate outcome + one audit entry
  -> escalate only when no target reached a human-visible channel
```

## 1. 대상 선정

알림은 서로 독립적인 네 조건의 교집합으로 전달됩니다.

$$
Targets = Declared \cap Enabled \cap Configured \cap TrustAllowed
$$

| 조건 | 의미 | 결정 위치 |
|-----------|---------|---------------------|
| `Declared` | 해당 카테고리의 route가 그 채널을 명시함 | 라우팅 매트릭스 |
| `Enabled` | 운영자가 채널을 켬 | 채널 바인딩 설정 |
| `Configured` | 필수 설정과 시크릿 참조가 시작 시 해석됨 | composition root |
| `TrustAllowed` | 채널이 메시지의 trust tier를 선언함 | 어댑터 계약 |

**레지스트리에 등록되었다는 사실만으로는 전달 자격이 생기지 않습니다.** 레지스트리에 있지만
route에 없는 채널은 대상이 아니므로, 어댑터를 추가했다는 이유로 거버넌스 요약의 수신 범위가
운영 채널까지 조용히 넓어질 수 없습니다.

빈 대상 집합은 조용한 성공이 아니라 설정 결함입니다. 이 경우 dispatch는
`no_eligible_channels`를 기록하고 사람 검토 대기열로 에스컬레이션하며 알림을 미해결로 남깁니다.

## 2. 채널 바인딩

채널 설정은 벤더별 암묵적 환경 변수 묶음에서 이름이 있는 바인딩 맵으로 바뀝니다. 그래야 한 배포가
여러 Teams 채널, 여러 웹훅, 여러 메일함을 동시에 운영할 수 있습니다.

`FDAI_NOTIFICATION_BINDINGS_JSON`은 이름이 있는 바인딩 맵을 전달합니다. 시크릿이 필요한 필드는
배포 시크릿 프로바이더가 채우는 환경 변수 이름만 지정합니다. JSON 자체에는 엔드포인트나 자격 증명
값을 넣지 않습니다.

```json
{
  "teams-ops-primary": {
    "kind": "teams_workflow",
    "enabled": true,
    "trust_tiers": ["a2_operational_alert"],
    "auth_mode": "workload_identity",
    "endpoint_env": "FDAI_TEAMS_OPS_PRIMARY_ENDPOINT"
  },
  "email-oncall": {
    "kind": "acs_email",
    "enabled": false,
    "trust_tiers": ["a2_operational_alert", "a4_digest"]
  }
}
```

규칙:

- **바인딩 id는 업스트림에서 placeholder입니다.** 엔드포인트 값, 테넌트 값, 채널 식별 정보는 배포
  시크릿 설정에 두며 이 저장소에는 두지 않습니다.
- **설정이 불완전한 상태의 `enabled: true`는 시작을 실패시킵니다.** 절반만 설정된 채널은 전송
  시점에 건너뛸 채널이 아니라 배포 결함입니다.
- **`enabled: false`는 명시적 제외입니다.** 모든 대상 집합에서 제거되며 dispatch 기록에
  드러납니다.
- **Trust tier는 바인딩 단위로 유지합니다.** 요약 전용 채널은 A2 호출 트래픽을 받지 않습니다.

### URL만 사용하는 초기 설정

Teams 대상 하나와 Slack 대상 하나를 사용하는 배포에서는 `FDAI_NOTIFICATION_BINDINGS_JSON`을
생략하고 엔드포인트 환경 변수만 설정할 수 있습니다.

| 환경 변수 | 기본 바인딩 id | 허용되는 트래픽 |
|-----------|----------------|-----------------|
| `FDAI_TEAMS_OPS_ENDPOINT` | `teams-ops-prd`, `teams-hil-prd` | A2 운영 알림 및 A4 요약 |
| `FDAI_SLACK_OPS_WEBHOOK_URL` | `slack-ops-prd` | A2 운영 알림 |

이 초기 설정은 합성된 바인딩 맵에 엔드포인트 값을 저장하지 않습니다. URL만으로는 워크로드 신원
설정을 제공할 수 없으므로 Teams 엔드포인트는 `anyone` 워크플로 인증 모드를 사용합니다. A1 사람
승인이나 A3 대화는 활성화하지 않습니다.

여러 대상, 서로 다른 trust tier 또는 Teams 워크로드 신원이 필요하면
`FDAI_NOTIFICATION_BINDINGS_JSON`을 사용하세요. 명시적 바인딩 맵이 우선하며 URL만 사용하는
기본값과 병합되지 않습니다.

### 가용성은 전송 시점 상태 확인이 아닙니다

이 설계는 전송마다 `is_ready()` 네트워크 확인을 수행하는 방식을 의도적으로 배제합니다. 프로바이더
장애는 대상 집합에서의 조용한 제거가 아니라 재시도를 동반한 전달 실패로 드러나야 합니다. 그렇지
않으면 운영자는 아무것도 보지 못했는데 감사 기록은 활성화된 모든 채널에 전달했다고 주장하게
됩니다.

| 상황 | 효과 |
|-----------|--------|
| 운영자가 비활성화 | 대상에서 제외하고 제외 사유를 기록 |
| 활성화했으나 설정이 유효하지 않음 | 시작 실패 |
| 활성화했고 전송 시점에 프로바이더 장애 | 대상 유지, 전달 실패로 표시하고 재시도 |
| dispatch 시작 이후 바인딩 변경 | 해당 dispatch가 종료될 때까지 고정된 스냅샷이 우선 |

## 3. Dispatch 계획과 채널별 전달

하나의 알림은 하나의 상위 dispatch 계획과 대상마다 하나의 하위 전달 기록을 만듭니다.

```text
dispatch:<audit_id>            targets = [teams-ops-primary, slack-ops, email-oncall]
  delivery:<audit_id>:teams-ops-primary
  delivery:<audit_id>:slack-ops
  delivery:<audit_id>:email-oncall
```

- 대상 집합은 **dispatch 생성 시점에 고정**하므로, 진행 중 설정을 수정해도 재시도가 최초 결정과
  달라지지 않습니다.
- 안정적인 하위 키는 `audit_id + channel_id`이며, 동일 원본 이벤트의 재전달을 채널 단위로 멱등하게
  유지합니다.
- 전송은 **제한된 병렬성**으로 수행하며, 한 채널의 예외가 다른 전송을 취소하지 않습니다.
- 실패한 하위 항목만 기존 시도 횟수 및 포기 한도 안에서 재시도합니다.
- 재시작 이후 복구는 종료되지 않은 하위 항목만 이어서 처리합니다.
- `accepted` 하위 항목에는 범위가 제한된 확인 기한이 있습니다. 기한이 지나면 자동으로 다시 보내지
  않고 `ambiguous`로 바꾸며, 인시던트 재처리 워커는 미종료 계획이 수렴할 때까지 계속 확인합니다.

채널별 상태:

| 상태 | 의미 |
|-------|---------|
| `pending` | 대상으로 선정되었고 아직 시도하지 않음 |
| `sending` | 한 워커가 시도를 임차(lease)함 |
| `accepted` | 프로바이더가 요청을 수락했고 사람에게 보였는지는 미확인 |
| `delivered` | 독립적인 관찰로 채널 게시를 확인함 |
| `retryable_failed` | 확정적 프로바이더 거부 또는 전송 실패이며 재시도 가능 |
| `ambiguous` | 전송 이후 확인 응답이 유실됨. 자동 재시도하지 않음 |
| `abandoned` | 시도 한도에 도달함 |

워크플로 트리거의 HTTP 성공은 요청 수락을 증명할 뿐 메시지 게시를 증명하지 않으므로 `accepted`와
`delivered`는 계속 구분합니다.

## 4. 집계 결과

| 결과 | 조건 | 후속 조치 |
|---------|-----------|-----------|
| `delivered_all` | 모든 대상이 종료 상태의 성공에 도달 | 없음 |
| `partially_delivered` | 하나 이상 성공하고 하나 이상이 미종료 또는 실패 | 실패한 하위 항목 재시도, 채널 상태 기록 |
| `failed_all` | 성공한 대상이 없음 | 사람 검토 대기열로 에스컬레이션 |
| `no_eligible_channels` | 대상 집합이 비어 있음 | 에스컬레이션하고 설정 결함으로 보고 |

부분 성공을 성공으로 올려 보고하지 않습니다. 또한 실패한 route를 사용하는 전달 실패 알림은 순환을
일으킬 수 있으므로 같은 A2 route로 다시 알리지 않고 채널 상태 지표와 인시던트 화면으로 드러냅니다.

라우터는 dispatch 호출마다 정확히 하나의 경로 감사 항목을 기록합니다. 이 항목에는 고정된 대상
목록, 현재 채널별 결과, 제외 사유가 들어갑니다. 이후 워크플로 콜백은 별도의
`notification.delivery.observed` 감사 항목을 기록하므로 추가 전용 감사 체인에서 이전 경로 결정을
수정하지 않습니다.

## 5. Teams Workflows 웹훅 바인딩

고전적인 Teams 수신 웹훅을 포함한 Office 365 connector는 2026-05-18부터 2026-05-22 사이에 순차적으로
비활성화되었습니다. 지원되는 대체 방식은 **When a Teams webhook request is received** 트리거로
시작하는 Power Automate 워크플로이며, 채널이나 채팅에 메시지 또는 Adaptive Card를 게시합니다.

**요청 계약**

- `POST`만 지원하며 `application/json`을 사용합니다.
- 본문은 Adaptive Card 봉투입니다. `type: "message"`와 함께 `attachments` 배열의 각 항목이
  `contentType: "application/vnd.microsoft.card.adaptive"`, `contentUrl: null`, `content`를
  포함합니다.
- 메시지 크기 상한은 28 KB입니다. 어댑터는 잘린 카드를 보내는 대신 프로바이더 호출 전에 실패로
  닫습니다.
- 초당 4건을 넘으면 조절(throttling)되므로 `429`는 제한된 지수 백오프를 사용합니다.

**인증**

| 트리거 모드 | FDAI 사용 | 요구 사항 |
|--------------|----------|-------------|
| `Anyone` | 로컬 검증과 짧은 전환 기간에만 사용 | `Authorization` 헤더를 보내면 요청이 실패함 |
| `Any user in my tenant` | 허용 | Entra bearer 토큰 |
| `Specific users in my tenant` | 배포 권장 | FDAI 알림 신원의 Entra bearer 토큰 |

배포는 FDAI 알림 managed identity를 허용 호출자로 등록하고 공용 클라우드 flow 서비스 audience인
`https://service.flow.microsoft.com/`에 대한 토큰을 요청합니다. 웹훅 URL은 시크릿 참조로 유지하며
평문 Terraform 변수나 로그 값으로 두지 않습니다.

**운영 제약**

- 워크플로는 팀이나 채널이 아니라 **사용자**가 소유합니다. 따라서 담당자가 조직을 떠날 때 고아
  흐름이 되지 않도록 FDAI가 사용하는 모든 워크플로에 최소 한 명의 공동 소유자를 지정해야 합니다.
- 메시지는 기본 Workflows 봇 신원으로 게시되며 봇 이름과 아이콘을 사용자 지정할 수 없습니다.
- Message Card 형식은 상호작용 버튼을 렌더링하지 않으므로 FDAI는 Adaptive Card를 유지합니다.

**효과 검증**

워크플로가 결과를 회신하기 전까지 `2xx`는 하위 항목을 `accepted`로만 종료합니다. `delivered`로
확정하려면 워크플로가 전달 id와 게시 결과를 담아 인증된 FDAI 접수 엔드포인트를 호출해야 합니다. 이
콜백에는 메시지 본문과 웹훅 URL을 담지 않습니다.

접수 처리기는 `audit_id`, `channel_id`, `publication_result`, 선택적 프로바이더 메시지 id만
받습니다. `X-FDAI-Timestamp`와 HMAC-SHA256 `X-FDAI-Signature`를 검증하고, 오래되거나 크기
제한을 넘은 요청을 차단하며, 결과를 `delivered` 또는 `retryable_failed`로 기록합니다. 준비 및
완료 관찰 감사 단계가 이 상태 변경을 둘러쌉니다. 콜백 시크릿은 배포 환경에서 관리합니다.

Settings > Integrations는 설정을 위한 별도의 일회성 상용 클라우드 진단을 제공합니다. Owner는
현재 FDAI ID와 배포 설정에서 제공한 Microsoft 365 계정 힌트를 비교하고, 해당 계정을 복사한 다음
Power Automate를 열 수 있습니다. 서명된 URL을 붙여 넣으면 고정된 합성 카드 한 건을 전송합니다.
Microsoft 365 테넌트의 인증, MFA, 동의, Team 및 Channel 선택은 명시적인 사용자 작업으로
유지합니다. Console은 URL을 즉시 지우고 API는 URL을 응답하거나 저장하지 않으며, 영속 진단
기록에는 URL 다이제스트와 준비 및 완료 메타데이터만 남깁니다. 진단 성공은 붙여 넣은 URL만
검증하며 배포 환경에서 관리하는 운영 바인딩을 업데이트하거나 증명하지 않습니다.

## 6. 이 설계가 넘지 않는 경계

- A1 승인은 인증된 Teams 경로를 유지합니다. 워크플로 웹훅은 승인자를 검증할 수 없으므로 승인 결정을
  전달하지 않습니다.
- A3 대화는 [운영 A3 채널 런타임](production-a3-channel-runtime-ko.md)이 설명하는 Operator 소유
  채널 edge를 유지합니다.
- Fan-out은 전달 범위만 바꿉니다. 자율성을 높이거나 편집 규칙을 완화하거나 낮은 신뢰 채널이 더 높은
  trust 카테고리를 받게 하지 않습니다.

## 7. 전달 순서

| 단계 | 작업 | 종료 증거 |
|------|------|---------------|
| 1 | 매트릭스 스키마에 채널 목록을 갖는 명시적 fan-out 전달 모드 추가 | 로더 테스트가 혼합 또는 알 수 없는 모드를 거부 |
| 2 | 채널 바인딩, 활성화, 시작 검증 | 활성화했지만 불완전한 바인딩에서 시작이 실패 |
| 3 | Dispatch 계획과 채널별 영속 기록 | 재시작 복구 테스트가 미종료 하위 항목만 재개 |
| 4 | 제한된 병렬성과 실패 격리를 갖춘 라우터 fan-out | 부분 실패 및 전체 실패 테스트 |
| 5 | 두 인증 모드를 지원하는 Teams Workflows 어댑터 | 스키마, 크기, 조절, 헤더 테스트 |
| 6 | Composition root에서 여러 바인딩 동시 연결 | 두 Teams 채널과 메일이 하나의 알림을 수신 |
| 7 | 전달 콜백과 `delivered` 승격 | 독립 관찰이 감사에 기록됨 |

## 관련 문서

| 알고 싶은 내용 | 읽을 문서 |
|----------------|------|
| 카테고리, trust tier, 수신 대상, 지역화 | [channels-and-notifications-ko.md](channels-and-notifications-ko.md) |
| A3 대화 전송과 edge 런타임 | [production-a3-channel-runtime-ko.md](production-a3-channel-runtime-ko.md) |
| 영속 아웃바운드 대화 회신 | [durable-conversation-delivery-ko.md](durable-conversation-delivery-ko.md) |
| 아무도 응답하지 않을 때의 에스컬레이션 | [escalation-and-standing-authority-ko.md](../decisioning/escalation-and-standing-authority-ko.md) |
| 구현 상태와 증거 | [multi-channel-notification-delivery.md](../../roadmap-implementation/interfaces/multi-channel-notification-delivery.md) |
