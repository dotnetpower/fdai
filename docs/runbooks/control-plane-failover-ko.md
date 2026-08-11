---
title: 컨트롤 플레인 Regional Failover 및 Failback
summary: Split-brain execution이나 검증되지 않은 replay 없이 승인된 FDAI recovery plan 하나를 운영합니다.
translation_of: control-plane-failover.md
translation_source_sha: 7b0eec0af22385c79cfe0b88b3c974e685cf86b6
translation_revised: 2026-08-11
---

# 컨트롤 플레인 Regional 장애 조치 및 Failback

FDAI 컨트롤 플레인의 regional 장애 또는 예약된 regional 훈련에 이 런북을 사용합니다.
[컨트롤 플레인 재해 복구 설계](../roadmap/deployment/control-plane-disaster-recovery-ko.md)에
정의된 상태 순서, 기본 fencing, protected 배포, 상태와 이벤트 검증, 트래픽
전이 및 통제된 failback을 구현합니다.

> **범위:** 이 절차는 customer-neutral입니다. 다운스트림 배포가 지역, protected 환경
> 파일, 리소스 참조, 트래픽 프로바이더, 이벤트 복구 출처, 승인 프로바이더, 소유자 및
> 근거 위치를 제공합니다.
>
> **현재 업스트림 경계:** 업스트림은 alternate-region stack이나 트래픽 manager를
> provision하지 않습니다. 포크가 해당 기능을 연결하고 승인된 protected 계획을 만들지
> 않았다면 준비 상태에서 중단합니다. Laptop 또는 ad-hoc 로컬 `terraform apply`는 복구
> 경로가 아닙니다.

## 담당과 시작 기준

- **인시던트 commander:** Regional 시나리오와 장애 시작을 선언합니다.
- **Reliability 소유자:** RPO/RTO를 소유하고 훈련 또는 복구 결과를 수락합니다.
- **Operations 소유자:** 이 런북과 복구 환경 구성을 소유합니다.
- **Approver:** Action-bound 장애 조치 및 failback 승인을 인증합니다. 요청자는 같은
 전이를 승인할 수 없습니다.
- **실행기:** Protected 자체 호스팅 배포 실행기와 dedicated 복구 신원입니다.
- **영향 범위:** 하나의 계획 개정 번호, 하나의 복구 에포크 및 하나의 선언된 control-plane
 범위입니다.

장애가 인시던트 또는 승인된 훈련에 연결되고 현재 복구 계획이 `ready`인 경우에만
시작합니다. Temporary Azure 서비스 성능 저하, unhealthy 복제본 하나 또는 availability-zone
이벤트만으로 regional 장애 조치를 정당화할 수 없습니다.

## 필수 연결

통제된 운영자 환경에 다음 값을 기록합니다. 토큰이나 시크릿 값을 출력하지
않습니다.

```bash
export FDAI_REPOSITORY='<owner/repository>'
export FDAI_ENVIRONMENT_CONFIG='<recovery-environment-config>'
export FDAI_PREFLIGHT_INPUT='<recovery-preflight-input>'
export FDAI_BUNDLE_DIGEST='<lowercase-sha256>'
export FDAI_COMMIT_SHA='<40-character-git-sha>'
export FDAI_RECOVERY_PLAN_ID='<recovery-plan-id>'
export FDAI_RECOVERY_EPOCH='<positive-integer>'
export FDAI_READ_API_BASE_URL='https://<read-api-origin>'
```

Operator는 승인된 interactive 신원 흐름으로 `FDAI_OPERATOR_BEARER_TOKEN`을 얻고 프로세스
기억에만 유지합니다. 복구 구성은 기본과 복구 지역, 비공개 networking,
신원/RBAC, DNS, 상태 출처, 이벤트 출처, 트래픽 라우팅, 이미지 다이제스트 및 선택된 `restore`
또는 `warm` 프로파일을 제공합니다.

다음 연결이 하나라도 없으면 중단합니다.

- 승인된 numeric RPO/RTO와 fresh recovery-plan 개정 번호;
- 기본 fencing 연산과 독립적인 fence 탐색;
- 원격 Terraform 상태와 VNet-connected `[self-hosted, fdai-deploy]` 실행기;
- 복구 지역에서 사용 가능한 exact digest-pinned 이미지;
- 데이터베이스 복원 출처와 결정론적 무결성/smoke 검증기;
- 이벤트 복구 출처와 범위가 제한된 재생 구간;
- action-bound 승인 검증기와 추가 전용 `StateStore` CAS 연결;
- 신원, RBAC, 비공개 엔드포인트, 비공개 DNS, canary 및 트래픽 검증 탐색;
- 롤백 또는 state-forward 복구와 정리 소유자.

## 단계 1 - 확인과 동결

1. 현재 저장소 산출물과 운영 근거를 검증합니다.

 ```bash
 테스트 "$(git rev-parse 헤드)" = "$FDAI_COMMIT_SHA"
 python3 scripts/governance/check-arb-readiness.py --require-production-ready
 fdaictl doctor --config "$FDAI_ENVIRONMENT_CONFIG" --output json
 fdaictl deploy preflight \
  --input "$FDAI_PREFLIGHT_INPUT" \
  --environment-config "$FDAI_ENVIRONMENT_CONFIG" \
  --output json
 ```

2. 장애 시작, last successful canary, 최신 감사 체크포인트, 현재 이벤트 체크포인트,
 활성 프로세스 실행 및 in-flight privileged 액션을 기록합니다.
3. Owner 또는 Break-Glass principal로 global kill 전환을 활성화합니다.

 ```bash
 curl --fail --silent --show-error \
  -H "권한 확인: Bearer $FDAI_OPERATOR_BEARER_TOKEN" \
  -H 'Content-Type: 애플리케이션/json' \
  -d "{\"engaged\":true,\"사유\":\"Regional 복구 fence for 계획 $FDAI_RECOVERY_PLAN_ID\",\"request_id\":\"$FDAI_RECOVERY_PLAN_ID-fence-$FDAI_RECOVERY_EPOCH\"}" \
  "$FDAI_READ_API_BASE_URL/system/비상 정지"
 ```

4. 새 스케줄러 전달과 승인 전달을 중단합니다. 기존 액션 증적은 근거로
 유지하며 replacement 액션을 발행하지 않습니다.

## 단계 2 - 기본 fencing

1. Fork-bound 기본 fence를 실행합니다. Fence는 근거를 삭제하지 않고 이전 실행기,
 이벤트 소비자 및 트래픽 경로를 철회하거나 isolate합니다.
2. 독립 신원과 네트워크 경로에서 fence를 검증합니다. 근거에는 old 에포크, new 에포크,
 영향 신원/범위, 프로바이더 연산 증적 및 탐색 시간이 포함됩니다.
3. Non-mutating old-epoch 탐색을 한 번 시도합니다. 거부되어야 합니다. Old 에포크가 쓰기할 수
 있으면 계획을 `halted`로 옮기고 복구 compute를 시작하지 않습니다.
4. 영속 복구 조정기를 통해 `activating -> primary_fenced`를 저장합니다. Stale 저장소
 개정 번호, 검증되지 않은 승인, changed 근거 또는 CAS loss가 발생하면 중단합니다.

## 단계 3 - 복구 계획 및 provision

1. 새 protected 계획을 제출합니다. 복구는 일반 배포 계획이나 승인을 재사용하지
 않습니다.

 ```bash
 fdaictl deploy 계획 \
  --config "$FDAI_ENVIRONMENT_CONFIG" \
  --repository "$FDAI_REPOSITORY" \
  --bundle-digest "$FDAI_BUNDLE_DIGEST" \
  --commit-sha "$FDAI_COMMIT_SHA" \
  --output json
 ```

2. 반환된 계획 id, 다이제스트, 맥락 다이제스트, 작업 흐름 실행, 만료 및 복구 승인을
 recovery-plan 전이에 연결합니다. 만료된 또는 mismatched 산출물은 차단합니다.
3. 비공개 실행기에서 exact approved 계획만 적용합니다.

 ```bash
 fdaictl deploy 적용 \
  --repository "$FDAI_REPOSITORY" \
  --plan-id '<protected-plan-id>' \
  --output json
 ```

4. 작업 흐름의 post-apply 이행, 준비 상태, 상태 및 canary 검사가 통과해야 합니다. 해당
 검사 없는 successful Terraform 프로세스는 `runtime_started`가 아닙니다.

## 단계 4 - 상태 복원과 검증

1. 계획에 선언된 출처에서 PostgreSQL과 변경할 수 없는 산출물을 복원합니다. PostgreSQL
 geo-backup은 paired 지역에서 사용 가능한 최신 지점을 기록하며 원격 PITR을 주장하지
 않습니다.
2. 관리형 복원이 자동으로 복사하지 않는 네트워크, 비공개 DNS, 서버 매개변수,
 Entra/데이터베이스 역할, 경보, HA 및 복제본을 적용합니다.
3. 스키마, row-count, 체크섬, foreign-key, 보존 및 애플리케이션 smoke 검증을
 실행합니다.
4. 복원된 감사 해시 체인과 exact 체크포인트를 검증합니다. 결정 재생은 judge-only
 모드에서만 실행하며 재생 호출은 실행기에 도달할 수 없습니다.
5. 변경할 수 없는 근거 참조와 함께 `state_restored -> runtime_started -> audit_verified`를
 저장합니다.

## 단계 5 - 권한 없이 이벤트 복구

1. 소비자와 privileged 실행을 비활성 상태로 유지합니다.
2. 선언된 Event Hubs 복구 strategy를 검증합니다. 메타데이터 Geo-DR은 이벤트나 reusable
 오프셋을 복사하지 않으므로 이것만으로는 충분하지 않습니다.
3. 승인된 출처에서 범위가 제한된 재생 집합을 만듭니다. Original 이벤트 id, 멱등성 키,
 causal/리소스 정렬, 출처 시각 및 감사 체크포인트를 보존합니다.
4. 누락된, 중복, stale, malformed 또는 conflicting 기록을 기록합니다. 모호한
 기록은 human 검토로 보내며 조용히 폐기하거나 재생하지 않습니다.
5. 수락된 기록이 최종 감사 결과에 도달할 수 있고 measured 공백이 승인된 RPO 안에
 있을 때만 `event_recovery_ready`를 저장합니다.

## 단계 6 - 권한 전환과 서비스 검증

1. 새 복구 에포크와 소비자를 활성화합니다. Old 에포크가 계속 fenced인지 확인합니다.
2. Fork-bound 트래픽 전환을 적용합니다. 훈련은 isolated synthetic 트래픽만 전환합니다.
3. Protected 실행기에서 deployed canary를 실행합니다.

 ```bash
 cd infra
 rg="$(terraform 출력 -raw resource_group_name)"
 작업="$(terraform 출력 -raw canary_job_name)"
 테스트 -n "$작업"
 az containerapp 작업 시작 --name "$작업" --resource-group "$rg" >/dev/null
 실행="$(az containerapp 작업 실행 목록 --name "$작업" --resource-group "$rg" \
  --query 'sort_by([], &properties.startTime)[-1].이름' -o tsv)"
 az containerapp 작업 실행 show --name "$작업" --resource-group "$rg" \
  --job-execution-name "$실행" --query properties.상태 -o tsv
 ```

4. 시작 준비 상태, 감사 쓰기, Event Hubs produce/consume, 데이터베이스 읽기/쓰기,
 신원/RBAC, 비공개 DNS, 경보 전달 및 범위가 제한된 용량을 검증합니다.
5. Achieved RPO와 RTO를 측정합니다. 목표 breach는 exercise를 `halted`로 옮기거나
 인시던트를 unsuccessful 복구로 기록하며 passing average로 만들지 않습니다.
6. 모든 검사가 통과한 후에만 `traffic_shifted -> service_verified -> active_recovery`를
 저장합니다.

## Failback

Failback은 위 명령의 역순이 아니라 새 복구입니다.

1. 복구 지역을 정본으로 유지합니다. 대상, 목표, 산출물 또는
 procedure가 바뀌면 새 계획 개정 번호를 만듭니다.
2. 별도 action-bound failback 승인을 얻고 `failback_ready`를 저장합니다.
3. 활성 상태에서 대상을 재구축 또는 resynchronize합니다. Stale 기본 데이터베이스를
 시작하지 않습니다.
4. 대상 이미지 다이제스트, 네트워크, 신원/RBAC, 비공개 DNS, 상태 무결성, 이벤트 체크포인트,
 canary 및 용량을 검증합니다.
5. `failing_back`에서 새 에포크를 할당하고 활성 복구 실행기를 fencing한 뒤 거부를
 입증합니다.
6. 소비자와 트래픽을 전환하고 전체 서비스 검증을 실행하며 관측 구간이
 끝날 때까지 이전 활성 지역으로 롤백할 수 있게 유지합니다.
7. `primary_verified -> closed`를 저장하고 선택된 복구 프로파일을 다시 수립하며 검토된
 계획으로 temporary 리소스를 제거한 뒤 정리를 검증합니다.

## Stop 조건 및 롤백

다음 조건이 발생하면 계획을 `halted`로 옮기고 현재 reservation을 유지합니다.

- 기본 fence 또는 old-epoch denial을 입증할 수 없음;
- 승인, 계획 다이제스트, 이미지 다이제스트, 신원, RBAC, 비공개 DNS 또는 상태 근거 mismatch;
- 복원 무결성, 감사 해시 체인, 이벤트 완전성, canary, smoke 또는 용량 검사 실패;
- 시간 box, RPO, RTO, 영향 범위 또는 예산 초과;
- 롤백 실패 또는 영속 CAS 전이에서 다른 쓰기 담당이 승리.

트래픽 shift 전 롤백은 새 protected 계획을 통해 복구 런타임을 제거하거나 비활성화하고
인시던트 commander가 다음 단계를 결정할 때까지 기본을 fenced로 유지합니다. 트래픽 shift 후
롤백은 마지막 검증된 활성 에포크의 상태와 이벤트 체크포인트가 계속 권위 있는한 경우에만
해당 에포크로 돌아갑니다. 그렇지 않으면 새 계획 개정 번호에서 state-forward 복구를 사용합니다.

## 근거와 완료

하나의 계획 상관관계 기록에 다음 정제된 산출물을 첨부합니다.

- 계획 개정 번호, 저장소 개정 번호, 에포크, 장애 구간, 행위자, 승인 및 CAS 증적;
- 기본 fence와 stale-epoch denial;
- protected Terraform 계획/적용, 이미지/구성/프로바이더 다이제스트 및 작업 흐름 URL;
- 데이터베이스 복원 지점, 무결성, smoke, 감사 해시 체인 및 체크포인트;
- 이벤트 출처, 재생 구간, 개수, 공백, 중복, 충돌 및 최종 결과;
- 신원/RBAC, 비공개 DNS, 시크릿, 준비 상태, canary, 경보, 트래픽 및 용량 결과;
- approved와 achieved RPO/RTO, 롤백/failback 증적, 정리 및 잔여 risk.

복구는 restored 복구 프로파일과 accepted 근거가 있는 `closed`에서만 완료됩니다.
`active_recovery`는 복구 지역에서 서비스가 운영 중이라는 뜻이며 완료가 아닙니다.
