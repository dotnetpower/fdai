---
title: 다중 채널 알림 전달
translation_of: multi-channel-notification-delivery.md
translation_source_sha: ad262e29a2fbf5bdada701cb47b09bf803abc793
translation_revised: 2026-09-17
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
    "mode": "shadow",
    "trust_tiers": ["a2_operational_alert"],
    "auth_mode": "workload_identity"
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
- **바인딩 ID는 범위가 제한된 ASCII 머신 식별자입니다.** 길이는 1-128자이며 문자, 숫자, `.`,
  `_`, `-`만 사용할 수 있고 문자나 숫자로 시작합니다. 공백이나 경로 구분자는 사용할 수 없습니다.
- **모든 깊이에서 중복 JSON 키는 유효하지 않습니다.** 뒤에 나온 `mode`, `enabled` 또는 엔드포인트
  참조가 검토자가 확인한 값을 조용히 대체할 수 없습니다.
- **하나의 바인딩 맵에는 최대 64개 항목을 둘 수 있습니다.** 시작 시 더 큰 맵은 어댑터나 준비 상태
  행을 만들기 전에 차단됩니다.
- **설정이 불완전한 상태의 `enabled: true`는 시작을 실패시킵니다.** 절반만 설정된 채널은 전송
  시점에 건너뛸 채널이 아니라 배포 결함입니다.
- **`enabled: false`는 명시적 제외입니다.** 모든 대상 집합에서 제거되며 dispatch 기록에
  드러납니다.
- **`mode: "shadow"`는 전송 없이 렌더링하고 기록합니다.** Teams와 Slack shadow 바인딩에는
  엔드포인트나 HTTP 클라이언트가 필요하지 않습니다. `mode: "enforce"`는 공급자 엔드포인트가
  필요하며 기존 런타임 동작을 유지합니다. 이전 버전과의 호환성을 위해 `mode`를 생략하면
  `enforce`가 기본값입니다.
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

접수 경로는 서비스 경계를 넘으므로 소유권에 따라 분리합니다.

| 단계 | 소유자 | 책임 |
|------|--------|------|
| 공개 ingress | Operator Service | `X-FDAI-Timestamp`와 HMAC-SHA256 `X-FDAI-Signature` 검증, 본문 크기 제한, 중복 제거, 시도 기록 |
| 브로커 전달 | Operator Service | 스키마 검증을 통과한 `notification-delivery-receipt` envelope 한 건 게시 |
| 전달 상태 전이 | Core 컨트롤 플레인 | `delivered` 또는 `retryable_failed` 적용과 관찰 감사 기록 |

`POST /runtime/integrations/notifications/delivery-receipt`는 `audit_id`, `channel_id`,
`publication_result`, 선택적 프로바이더 메시지 id만 받습니다. 서명이 없거나 오래되었거나 크기
제한을 넘었거나 추가 필드를 담은 본문을 거부하고, 전달을 단언하지 않은 채 `202`로 응답합니다.
보고를 수락한 것은 그 보고의 효과가 아니기 때문입니다. 콜백 시크릿은 배포 환경이 소유하며 Console에
전달되지 않습니다.

Envelope는 기존 기본 물리 토픽에 multiplex되는 논리 토픽
`fdai.notifications.delivery-receipts`로 이동하며, 양쪽 모두 패키지에 포함된
`notification-delivery-receipt` 스키마로 검증합니다. 전달 상태를 쓰는 주체는 Core뿐입니다. Core는
`accepted` 하위 항목을 `delivered`로 승격하고, 보고된 실패를 `retryable_failed`로 되돌리며,
준비 및 완료 `notification.delivery.observed` 감사 단계로 변경을 둘러쌉니다. 전달이 `accepted`가
아닌 관찰은 이전 라우팅 결정을 덮어쓰지 않고 거부하여 dead-letter로 보냅니다.

**저장은 진단이며 활성화가 아닙니다**

Settings > Integrations는 설정을 위한 범위가 제한된 상용 클라우드 저장 및 테스트 흐름을
제공합니다. Owner는 현재 FDAI ID와 배포 설정에서 제공한 Microsoft 365 계정 힌트를 비교하고, 해당
계정을 복사한 다음 Power Automate를 열 수 있습니다. 서명된 URL을 붙여 넣으면 고정된 합성 카드 한
건을 전송합니다. Microsoft 365 테넌트의 인증, MFA, 동의, Team 및 Channel 선택은 명시적인 사용자
작업으로 유지합니다. 배포 환경은 버전이 지정된 Teams 엔드포인트 시크릿 하나만 쓸 수 있는 전용
Managed Identity를 사용합니다. 로컬 프로필은 Operator가 소유하는 루프백 레코드를 암호화하여
사용하며 PostgreSQL에 평문을 쓰지 않습니다. FDAI는 저장된 정확한 버전을 다시 읽고 URL
다이제스트를 확인한 후에만 테스트 카드를 전송합니다. Key Vault는 이전 시크릿 버전을 롤백용으로
유지합니다.

**저장과 테스트에 성공한 endpoint만으로는 아무것도 전달하지 않습니다.** 진단은 endpoint가
존재하고 카드를 수락한다는 사실만 증명합니다. 런타임 전달은 배포가 바인딩을 활성화할 때 시작하며,
런타임은 endpoint가 아직 초기 placeholder인 활성화된 바인딩을 거부합니다.

| 모드 | 활성화 입력 | Endpoint 출처 |
|------|-------------|---------------|
| 배포 | `enable_teams_notification_delivery`와 `teams_notification_binding` 객체 | 읽기 전용 권한으로 컨트롤 플레인에 주입하는 Key Vault 시크릿 참조 |
| 로컬 | `FDAI_TEAMS_NOTIFICATION_ACTIVATION` | 동일한 암호화된 Operator 소유 레코드를 전달 측 저장소로 읽음. 평문 파일이나 환경 변수 복제 없음 |

**저장된 URL은 암호에 준하며 절대 반환하지 않습니다.** 바인딩 조회는 메타데이터만 응답합니다.
`visible`, `configured`, `binding_version`, 관찰 시각, 그리고 해당 버전을 증명하는 영속 Operator
저장 기록이 있을 때의 `saved_at`입니다. Contributor, Approver, Owner 역할은 바인딩이 존재한다는
사실만 확인할 수 있고 값을 다시 읽을 수 없으며 Console은 입력값을 미리 채우지 않습니다. Owner는 새
URL을 제출하여 바인딩을 교체합니다. 영속 저장 및 테스트 기록에는 다이제스트, 바인딩 버전, 행위자,
요청 id, 프로바이더 상태, 준비 및 완료 메타데이터만 남습니다.

## 6. 이 설계가 넘지 않는 경계

- A1 승인은 인증된 Teams 경로를 유지합니다. 워크플로 웹훅은 승인자를 검증할 수 없으므로 승인 결정을
  전달하지 않습니다. 바인딩 파싱이 이를 강제합니다. 종류와 무관하게 알림 바인딩은
  `a2_operational_alert` 또는 `a4_digest`만 선언할 수 있으며 `a1_hil_approval`이나
  `a3_chat_command`를 주장하는 바인딩은 로드에 실패합니다.
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
| 8 | 인증된 Operator ingress와 스키마 검증 Core consumer | 서명된 콜백이 브로커를 거쳐 `accepted` 하위 항목을 `delivered`로 수렴 |
| 9 | 명시적 배포 및 로컬 활성화 | 활성화된 바인딩은 전달하고 저장만 되었거나 placeholder인 바인딩은 전달하지 않음 |

## 8. capability-state, presentation, shadow-delivery 계약

A2/A4 채널은 fan-out 아래에 한 단계 더 필요한 기반 계층이 있습니다: 상태(health)와 섞이지 않고
바인딩의 가용성을 설명하는 방법, 모든 renderer가 vendor 호출 전에 반드시 거치는 fail-closed
렌더링 경계, 그리고 명시적으로 승격되기 전까지 네트워크 전송이 전혀 없이 새 바인딩을 도입하는
방법입니다.

### 8.1 Capability-state

[`ChannelCapabilityState`](../../../services/core-control-plane/src/fdai/shared/providers/notifications/capability.py)는
`available`(이 프로세스가 관찰할 수 있는 전제 조건이 완비됨), `enabled`(운영자 선호), `configured`
(시작 시 검증된 구성), `mode`(`ChannelMode.SHADOW` 또는 `ChannelMode.ENFORCE`)를 분리합니다.
이는 [coding-conventions.instructions.md § Safety](../../../.github/instructions/coding-conventions.instructions.md#safety)가
모든 capability flag에 요구하는 그대로입니다. `ready`는
`available and enabled and configured`이며, `mode`는 그 자체로 자율성을 높이지 않습니다.
Composition은 여전히 §1과 동일하게 나머지 세 필드로 fan-out 대상 집합을 결정합니다.
`to_readiness_row()`는
[`integration_row`](../../../services/core-control-plane/src/fdai/delivery/integration_readiness.py)가
이미 만드는 것과 동일한 출처 귀속 형태를 렌더링하므로, capability-state 인스턴스와 Settings
readiness projection이 같은 채널에 대해 서로 다른 어휘를 보고할 수 없습니다. capability state를
생성하거나 읽는 동작은 I/O를 수행하지 않으며, 전송 시점 상태(health) 프로브가 결코 아닙니다(위 §2).
`channel_id`는 비어 있지 않아야 합니다 - 생성자는 설정이나 composition 결함이 조용히 해당 채널의
readiness row를 손상시키기 전에 빈 값을 거부합니다.

### 8.2 Presentation 경계

[`render_presentation`](../../../services/core-control-plane/src/fdai/shared/providers/notifications/presentation.py)은
모든 renderer가 포맷팅이나 provider 호출 전에 거치는 pre-render fail-closed 경계입니다. 다음을
잘라내거나 조용히 제거하지 않고 거부합니다:

| 조건 | 결과 |
|------|------|
| Metadata가 interactive-content 키(`actions`, `buttons`, `interactive` 등)를 지정 - 대소문자를 구분하지 않고 비교하므로 `Actions`나 `ACTIONS`도 `actions`와 동일하게 거부됩니다 | 거부됨 - A2/A4 메시지는 절대 approval button이나 executable link를 포함하지 않습니다(`channels-and-notifications.md § 3`) |
| Title, body, link, metadata **key 또는 value**가 제한된 `PresentationLimits` 값을 초과 | 거부됨 - 맞추기 위해 잘라내지 않습니다. key를 제한하지 않으면 value만 검사하는 검증을 우회해 과도하게 큰 payload를 밀반입할 수 있습니다 |
| link `url`이 절대 `https://` 링크가 아님(다른 어떤 scheme이든, `http://`, `javascript:`, `data:` 포함) | 거부됨 - executable하거나 암호화되지 않은 링크는 절대 허용하지 않습니다 |
| Title, body, link, metadata **key 또는 value**가 고신호 secret-like 패턴(bearer token, API key/secret/password 대입, 서명된 URL query parameter, private-key header, GitHub/Slack token 형태)과 일치 | 거부됨 |

거부는 `ChannelDeliveryError`의 하위 클래스인 `PresentationRejectedError`를 발생시키므로,
라우터는 이를 다른 실패한 전송과 동일하게 처리하고 다음 fallback 채널이나 제한된 재시도로
진행합니다 - 부분 전송이나 비-redaction 전송으로 확대되지 않습니다. 반환된
`NotificationPresentationEnvelope.metadata`는 일반 `dict`가 아니라 `MappingProxyType` view이므로,
renderer가 생성 이후 경계 artifact를 변경할 수 없습니다.

### 8.3 Shadow delivery

[`ShadowNotificationChannel`](../../../services/core-control-plane/src/fdai/core/notifications/shadow.py)은
`ChannelMode.SHADOW`에 있는 바인딩에 대해 composition root가 vendor 어댑터 대신 등록하는
`NotificationChannel`입니다. 이 채널의 `send`는 위의 presentation 경계를 통해 메시지를 렌더링하고
주입된 `ShadowDeliveryRecorder`를 통해 제한된 envelope를 영속적으로 기록합니다 - **네트워크 호출은
전혀 발생하지 않습니다**. `NotificationRouter`는 실제 어댑터와 동일하게 이 채널로 dispatch하며
`delivered=True`를 받습니다: shadow 채널의 완전한 계약상 의무(렌더링과 영속 로컬 기록)는 확인되지
않은 외부 약속 없이 이미 완료되었으며, 이는 헌법 원칙 7("새 capability는 shadow mode에서
시작합니다 - 판단하고 기록만 하며 실행하지 않습니다")과 일치합니다. `ChannelMode.ENFORCE`로의
승격은 등록된 어댑터를 교체하는 명시적 composition-root 변경이며, `ShadowNotificationChannel`
자체를 변경하지 않고, 라우터, fan-out 전달 저장소, 위의 단일 감사 항목 불변식은 변하지 않습니다.

`ShadowDeliveryRecord.record_id`는 무작위 값이 아니라 `channel_id`와 메시지의 `correlation_id`,
`audit_id`, `category`를 결정론적으로 해시한 값입니다 - `channels-and-notifications.md § 5`의 기존
"어댑터는 멱등 `send`를 구현해야 함" 계약을 충족합니다: `InMemoryShadowDeliveryRecorder`는 같은
`record_id`가 반복되면 아무 것도 하지 않으며, 운영용 durable recorder도 반드시 동일하게(예:
`record_id`를 key로 하는 upsert) 동작해야 합니다. `send`는 또한 naive(timezone 없는) `clock()`
결과를 기록 전에 `ValueError`로 거부하므로, `recorded_at`은 이 서비스가 기록하는 다른 모든
timezone-aware timestamp와 항상 비교 가능한 상태를 유지합니다.

[`test_channel_foundation.py`](../../../services/core-control-plane/tests/notifications/test_channel_foundation.py)의
집중 테스트는 다음을 증명합니다: 사용할 수 없는 provider도 여전히 정확히 하나의 감사 항목과 함께
결정론적 fallback에 도달함, shadow 상태의 provider가 네트워크 호출 없이 dispatch를 충족함, 거부된
presentation이 부분 콘텐츠를 전송하는 대신 결정론적으로 fallback함, 동일한 `audit_id`에 대한
반복된 fan-out `dispatch()` 호출이 이미 종료된 대상을 재전송하지 않으면서도 호출마다 정확히 하나의
감사 항목을 계속 기록함, 그리고 같은 `correlation_id + audit_id + category`로 직접 반복 호출한
`send()`가 정확히 하나의 항목을 기록하고 같은 `provider_message_id`를 반환함.

### 8.4 Teams와 Slack 공급자 렌더링

Teams와 Slack은 두 모드에서 동일한 순수 공급자 렌더러를 사용합니다. enforce 어댑터는 메시지를
`render_presentation`에 통과시키고 공급자 payload를 렌더링한 다음 전송을 호출합니다. shadow
어댑터는 같은 두 렌더링 단계를 수행하지만, 변경할 수 없는 공급자 payload를
`StateStoreShadowDeliveryRecorder`를 통해 저장하며 HTTP 호출을 수행하지 않습니다.

공급자에 더 엄격한 제한이 필요하면 공유 묶음보다 좁은 제한을 적용합니다.

| 공급자 | 공급자 payload 계약 |
|--------|---------------------|
| Teams | `fallbackText`와 `speak`, 의미 기반 심각도 라벨, 가운데 정렬된 `ExtraLarge` 제목을 포함하는 Adaptive Card 1.4 묶음, 제목 250자, 본문 3000자, 전체 payload 28 KB, 공급자별 텍스트 축약이 발생하면 `rendering: truncated` 사실 항목 |
| Slack | Block Kit 머리글과 섹션을 포함하는 심각도 색상 attachment, 머리글 150자, 섹션 3000자, 섹션당 사실 항목 최대 10개, 전체 페이로드 40 KB, 이스케이프 처리한 사실 값, 대화형 작업 블록 대신 읽기 전용 Markdown 링크 |

이 계층 구조는 공급자 고유 카드 패턴을 따르면서 동일한 정본 의미를 보존합니다.
두 렌더러는 `correlation_id`, `audit_id`, 정렬된 범위 제한 메타데이터를 보존합니다. 따라서 호출자는
`NotificationMessage`에 공급자별 필드를 추가하지 않고도 표준 인시던트 id와
`Huginn -> Forseti -> Thor -> Vidar` 책임 순서를 전달할 수 있습니다. 안정적인 shadow 기록은
일반 묶음과 정확한 공급자 JSON 바이트를 포함합니다. 메모리 기반 개발 기록기와 StateStore
기록기는 모두 같은 기록 ID에 다른 범위 제한 콘텐츠가 들어오면 실패합니다. 따라서 충돌한 최초
기록 근거를 덮어쓰거나 조용히 유지하지 않습니다. 또한 사용자 지정 렌더러가 자체 제한을
빠뜨리더라도 shadow 경계는 64 KiB를 넘는 렌더링된 공급자 페이로드를 차단합니다.

Slack은 연결 설정 실패를 unavailable로 분류하지만, 전송 이후 제한 시간 초과나 그 밖의 HTTP
오류는 공급자가 요청을 받았을 수 있으므로 ambiguous로 분류합니다. 라우터는 모호한 확인 결과를
다른 경로로 재시도하지 않습니다.

Slack webhook의 HTTP 200은 `delivered`가 아니라 `accepted`를 만듭니다. 독립적인 게시 관측만
공급자 수락을 전달 완료로 승격할 수 있습니다. 해당 관측 경로와 승격 근거를 검토하기 전까지
Slack 기능은 shadow에 머뭅니다.

Teams와 Slack 차단 오류에는 공급자 이름과 HTTP 상태만 남깁니다. 공급자 응답 본문은 신뢰할 수
없고 메시지 내용을 반사할 수 있으므로 폐기하며, 라우터 감사 텍스트에 포함하지 않습니다.

## 관련 문서

| 알고 싶은 내용 | 읽을 문서 |
|----------------|------|
| 카테고리, trust tier, 수신 대상, 지역화 | [channels-and-notifications-ko.md](channels-and-notifications-ko.md) |
| A3 대화 전송과 edge 런타임 | [production-a3-channel-runtime-ko.md](production-a3-channel-runtime-ko.md) |
| 영속 아웃바운드 대화 회신 | [durable-conversation-delivery-ko.md](durable-conversation-delivery-ko.md) |
| 아무도 응답하지 않을 때의 에스컬레이션 | [escalation-and-standing-authority-ko.md](../decisioning/escalation-and-standing-authority-ko.md) |
| 구현 상태와 증거 | [multi-channel-notification-delivery.md](../../roadmap-implementation/interfaces/multi-channel-notification-delivery.md) |
