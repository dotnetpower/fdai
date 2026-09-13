---
title: 경로 교차 안전장치 근거 Runbook
translation_of: cross-path-safeguard-evidence.md
translation_source_sha: adf0884e18fe410eba9191d47ec49a1796b5a284
translation_revised: 2026-09-13
---
# 경로 교차 안전장치 근거 Runbook

등록된 모든 실행 경로에 대해 하나의 고정 리비전에서 통제된 안전장치 근거와 독립 효과 근거를
보존합니다. 그래야 디스패치를 성공으로 취급하지 않고 FDAI-CONST-007을 조정할 수 있습니다.

이 Runbook이 설명하는 캠페인은 **아직 실행되지 않았습니다**. 현재 저장소에는 계약, 행렬, 관측 장치,
계획 전용 워크플로만 들어 있습니다. 실제 근거를 만드는 일은 별도 승인이 필요한 별개 활동입니다.

## 권한 경계

이 문서를 읽는 것만으로는 아무 권한도 생기지 않습니다. 아래 각 항목은 실행 시점에 명시적인 현재 사람
승인이 필요합니다.

- 고정 리비전 선택,
- 해당 리비전 푸시 및 필수 CI 실행,
- Core 또는 격리 Executor의 보호된 배포,
- 관리 리소스, 풀 리퀘스트, 이슈에 대한 실제 효과,
- 승격, 레지스트리 변경, 추적성 상태 변경.

승인자는 개시자와 다른 주체여야 합니다. 침묵은 결코 권한을 부여하지 않습니다.

## 근거 경계

- 디스패치, 브로커 수락, 프로바이더 영수증은 운영 성공이 **아닙니다**.
- 근거가 없거나, 오래되었거나, 충돌하거나, 검열되었거나, 사용할 수 없는 관측은 미상 보류입니다.
  재시도, 새 효과, 잠금 해제, 승격 중 어느 것도 승인하지 않습니다.
- 합성 근거는 실제 근거가 아닙니다. 계약은 `allow_synthetic_evidence`를 `false`로 두고, 검증기는
  합성 영수증을 거부합니다.
- 고정 리비전의 보호된 배포와 모든 자격 있는 셀의 독립 관측 보존을 마친 뒤에야 캠페인이
  `live_execution`을 주장할 수 있습니다.

## 사전 선언된 행렬

[`config/cross-path-safeguard-evidence.json`](../../config/cross-path-safeguard-evidence.json)은
실행 경로 넷, 오케스트레이션 출처 둘, 실행 장소 둘로 이루어진 16개 셀을 모두 선언합니다. 여덟 개는
자격이 있고 여덟 개는 구조적으로 거부됩니다.

| 셀 그룹 | 자격 | 이유 |
|---|---|---|
| Core 장소의 `pr_native`와 `tool_call` | 자격 있음 | Core가 PR 게시자와 도구 라우터를 소유합니다. |
| 두 장소의 `direct_api` | 자격 있음 | Core와 격리 Executor가 각각 프로바이더 디스패치를 소유할 수 있습니다. |
| 모든 `pr_manual` 셀 | 구조적 거부 | 출시된 어떤 ActionType도 `pr_manual`을 선언하지 않으며, `resolve_ceiling`이 최종 경로를 ActionType만으로 결정하므로 `strictest_execution_path`를 호출하는 프로덕션 코드가 없습니다. |
| 격리 장소의 `pr_native`와 `tool_call` | 구조적 거부 | 격리 Executor는 경로가 `direct_api`가 아닌 명령을 모두 거부합니다. |

구조적으로 거부된 셀은 이유와 근거를 함께 기록합니다. 조용히 빠뜨리지 않으며, 생산자를 지어내서
자격을 부여하지도 않습니다.

### 장소 배타성

`enable_isolated_executor_authority_cutover`는 게이트웨이 호출자 권한과 수직 실행 신원을 Core에서
격리 Executor로 옮깁니다. 따라서 하나의 배포 구성이 두 `direct_api` 장소를 동시에 담을 수 없습니다.
두 셀을 모두 다루려면 **같은** 고정 리비전을 두 번 보호 적용해야 하며, 리비전을 둘로 나누면 안 됩니다.

## 안전한 ActionType과 되돌리기

| 경로 | ActionType | 효과 | 되돌리기 | 독립 관측자 |
|---|---|---|---|---|
| `direct_api` | `ops.start-vm@1.0.0` | 기존 비프로덕션 VM 하나가 `running` 상태가 됨 | `ops.deallocate-vm@1.0.0` | 변경 게이트웨이를 호출하지 않는 신원으로 읽는 Azure VM 전원 상태 |
| `pr_native` | `ops.publish-change-summary@1.0.0` | 전용 비프로덕션 근거 저장소의 풀 리퀘스트 하나 | 풀 리퀘스트 닫기 또는 `pr_revert` | GitOps 기록 토큰과 구분되는 읽기 전용 토큰으로 읽는 GitHub 풀 리퀘스트 상태 |
| `tool_call` | `tool.open-incident-ticket@1.0.0` | 같은 근거 저장소의 이슈 하나 | 이슈 닫기 | 같은 읽기 전용 토큰으로 읽는 GitHub 이슈 상태 |

셀당 영향 한계는 리소스 하나입니다. 이 저장소를 대상으로 삼지 마십시오.

## 롤아웃 순서

Core 먼저, 그다음 격리 Executor. 둘 다 같은 커밋에 고정합니다.

1. 캠페인 리비전을 보호된 `main`에 올리고 `required` 체크가 통과했는지 확인합니다.
2. `container-supply-chain`으로 그 커밋의 증명된 이미지를 빌드합니다.
3. cutover를 끈 상태로 `service-deploy`를 통해 `core-control-plane`을 계획하고 적용합니다.
   Core 장소 레인을 실행합니다.
4. 같은 `commit_sha`로 `service-deploy`를 통해 `isolated-executor`를 계획하고 적용합니다.
5. `deploy-dev`로 권한 cutover를 적용하고 격리 장소 `direct_api` 레인을 실행한 뒤, 이전 cutover 값을
   복원하고 복원 결과를 확인합니다.
6. 번들을 조립하고 검증한 뒤 독립 검토를 요청합니다.

## 현재 실행 가능한 계획 전용 레인

```bash
uv run python scripts/quality/repository/validate-cross-path-safeguard-evidence.py
```

`cross-path-safeguard-evidence` 워크플로는 같은 검증기를 정확한 보호된 `main` 리비전에 대해 실행하고,
검증 영수증을 90일간 보존하며, 효과 실행이 구현되지 않았으므로 모든 `apply` 요청을 거부합니다.

## 번들 조립

```bash
uv run python scripts/quality/repository/build-cross-path-safeguard-evidence-bundle.py \
  --receipt-dir .fdai/evidence/cross-path-safeguard/ \
  --output .fdai/evidence/cross-path-safeguard-live.json \
  --campaign-id "<campaign id>" \
  --base-revision "<40자 커밋>"

uv run python scripts/quality/repository/validate-cross-path-safeguard-evidence.py \
  --bundle .fdai/evidence/cross-path-safeguard-live.json
```

빌더는 번들을 한 번만 기록하고, 중복 키, 예상 밖이거나 빠진 영수증 종류, 유한하지 않은 수, 다른
리비전에 고정된 영수증을 모두 거부합니다. 이어서 검증기는 자격 있는 모든 셀의 독립 관측과 모든 거부
분류에 대한 영수증을 요구합니다.

## 남은 작업

계약은 다음 항목을 잔여 작업으로 열거하며, 실제로 닫힐 때까지 그대로 남습니다.

- 고정 리비전이 아직 선택되지 않았습니다.
- 보호된 배포가 아직 수행되지 않았습니다.
- 독립 관측이 아직 디스패치 수명주기에 연결되지 않아, 캠페인이 관측 영수증을 자동으로 낼 수 없습니다.
- 관측 결과를 권한 축소에 쓰이는 A3-E `EffectEvidenceDisposition`으로 옮기는 다리가 없습니다. 두
  어휘는 현재 의도적으로 연결되어 있지 않습니다. 이 다리를 만드는 사람은 `missing`, `stale`,
  `conflicting`, `censored`, `unavailable` 같은 모든 미상 결과를 권한을 낮추는 처분으로 옮겨야
  합니다. 그중 하나라도 `pending`으로 옮기면 보류가 자율성을 유지한 능력으로 조용히 바뀝니다.
- `pr_manual`에는 도달 가능한 런타임 트리거가 없습니다.
- `tool_call` 강제 적용 바인딩에 Terraform 변수가 없습니다.
- 독립 검토가 아직 수행되지 않았습니다.

FDAI-CONST-007은 이 항목이 모두 닫히고 독립 검토에서 Medium 이상 미해결 발견이 없을 때까지
`partial`로 유지됩니다.
