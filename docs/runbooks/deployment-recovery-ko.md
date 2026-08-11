---
title: 배포 복구
summary: Protected plan 거부, offline kit 검증 실패 또는 runtime readiness 저하에서 안전하게 복구합니다.
translation_of: deployment-recovery.md
translation_source_sha: 3ebb98e79c8f6c2db322a04ccefe739ca68e7c25
translation_revised: 2026-08-11
---

# 배포 복구

Connected 또는 disconnected 배포를 안전하게 계속할 수 없을 때 이 런북을 사용합니다. 기존
머신 상태를 새 계획, 새 키트 또는 fresh 근거 복구 경로에 연결하며 signed 메타데이터를
수정하거나 준비 상태를 인위적으로 만들지 않습니다.

> **범위:** 이 절차는 customer-neutral입니다. 다운스트림 포크는 환경 값,
> 저장소 이름, 근거 위치, 소유자와 승인된 release 채널을 제공합니다.

## 담당과 진입 조건

- **Owner:** 계획과 키트 복구는 배포 운영자, 준비 상태 복구는 런타임 운영자가 담당합니다.
- **Approver:** 해당 환경의 지정된 배포 승인자입니다. 다른 계획 다이제스트 또는
 배포 맥락에는 기존 승인을 재사용하지 않습니다.
- **항목:** 결정 표의 고정된 신호 중 하나가 존재합니다.
- **영향 범위:** 한 번에 하나의 환경, protected 계획 id 또는 offline-kit 후보입니다.
- **최종 no-op:** 정제된 머신 근거에 연결할 수 없는 신호이면 적용을 제출하거나
 trust 자료를 교체하거나 소비자를 재시작하지 않습니다. 공백을 기록하고 검토로 전달합니다.

## 결정 표

| 신호 | 의미 | Stop 조건 | 안전한 복구 |
|--------|------|----------------|-------------|
| 계획 상태가 `planning`, `applying`, `applied`, `failed` 또는 `expired` | 계획이 새 exact 적용 대상이 아님 | 적용을 제출하지 않음 | 추가 배포가 필요하면 새 계획을 생성하고 승인 |
| `plan has expired` | Signed 적용 구간이 닫힘 | `expires_at`을 연장하거나 계획 id를 재사용하지 않음 | Doctor, preflight, 계획 생성을 반복 |
| 계획 맥락, 커밋, 번들, 출처, 근거 또는 binary 다이제스트 mismatch | 현재 의도가 protected 산출물과 다름 | 메타데이터를 수정하거나 다른 예상 다이제스트를 전달하지 않음 | 입력을 수정하고 새 protected 계획 생성 |
| 계획이 preflight에 차단된되거나 approved 실행기를 사용할 수 없음 | 필수 근거 또는 실행 경계를 사용할 수 없음 | 로컬 적용 금지 | 보고된 차단 요인을 해결하고 approved 실행기에서 새 계획 생성 |
| `fdaictl provision inspect`가 `4` 또는 `status=incomplete` 반환 | 필수 호스트, 신원, connectivity 또는 키트 근거 실패 | 프로파일에서 initialize 또는 deploy 금지 | 실패한 검사를 복구하고 다시 inspect |
| `artifact.offline-kit=fail` | 서명, 호환성, 매니페스트, 파일 집합 또는 다이제스트 검증 실패 | 거부된 키트 내부 파일을 복구하지 않음 | Pinned release 출처에서 전체 키트를 교체하고 다시 inspect |
| `artifact.offline-kit=candidate` | 키트가 있지만 pinned 검증기가 trust를 확립하지 못함 | 존재를 검증으로 취급하지 않음 | Packaged 공개 루트가 있는 release를 설치하거나 connected 경로 사용 |
| 시작 `decision=blocked` 또는 `/ready`가 `503` 반환 | Process-critical 근거가 실패한, 누락된, stale, timed out 또는 crashed | 소비자 또는 Pantheon을 수동 시작하지 않음 | 의존성을 복구하고 fresh 주기적 준비 상태 evaluation 대기 |
| 시작 `decision=degraded` | 프로세스가 reduced 권한으로 준비된 상태를 유지할 수 있음 | 보고된 `authority_ceilings`보다 높은 액션 금지 | 기능을 복구하고 fresh 보고에서 권한이 올라가지 않는지 확인 |
| 시작 근거가 누락된 또는 stale | 이전 관측이 더 이상 준비 상태를 증명하지 못함 | 결과, 시각, 만료 또는 state-store 기록 수정 금지 | 구성된 탐색이 fresh 근거를 생성하게 함 |

## Protected 계획 복구

1. 적용 전에 정제된 계획 기록을 읽습니다.

 ```bash
 fdaictl deploy 상태 \
  --repository <owner/repository> \
  --plan-id <plan-id> \
  --output json
 ```

2. `status`가 정확히 `ready`이고 현재 시간이 `expires_at` 이전이며 계획 다이제스트가 대상
 환경, 번들, 커밋, 백엔드와 실행기에 속하는 경우에만 계속합니다.
3. 만료 또는 mismatch가 있으면 읽기 전용 선행 조건을 다시 실행하고 새 계획을 제출합니다.

 ```bash
 fdaictl doctor --config <environment-config> --output json
 fdaictl deploy preflight \
  --input <preflight-input> \
  --environment-config <environment-config> \
  --output json
 fdaictl deploy 계획 \
  --config <environment-config> \
  --repository <owner/repository> \
  --bundle-digest <sha256> \
  --commit-sha <git-sha> \
  --output json
 ```

4. 새 계획 id와 다이제스트에 대한 승인을 받습니다. 거부된 계획의 승인을 이전하지 않습니다.
5. `fdaictl deploy apply`로 exact approved 계획만 제출합니다. Runner-side 검증은 binary
 계획, 출처 산출물, preflight 근거, 맥락, 커밋, 상태와 만료를 계속 일치시켜야 합니다.

Preflight 명령은 clear이면 `0`, 검토가 필요한 문제가 있으면 `2`, 배포 차단 요인이면 `3`으로
종료합니다. Exit 코드는 근거이며 보고를 우회할 권한이 아닙니다.

## 거부된 offline 키트 교체

1. 변경 없이 inspect합니다.

 ```bash
 fdaictl provision inspect \
  --connectivity offline \
  --host 기존 \
  --offline-kit <kit-directory> \
  --output json
 ```

2. Overall `status=ready`, exit `0`, `artifact.offline-kit=verified`를 모두 요구합니다. Exit `2`는
 검토, exit `4`는 불완전한입니다. `candidate`와 `not-configured`는 trust 결정이 아닙니다.
3. 검증이 실패하면 디렉터리를 근거로 격리합니다. 산출물 하나를 교체하거나
 매니페스트를 다시 쓰거나 서명을 재생성하거나 operator-selected trust 루트를 제공하지 않습니다.
4. Pinned release 출처에서 완전한 replacement를 가져옵니다. Packaged 공개 루트와 정확한 CLI
 버전 및 platform으로 검증합니다.
5. 점검을 다시 실행합니다. Replacement가 독립적으로 `verified`에 도달하고 필수 도구 및
 workload-identity 검사를 모두 통과한 뒤에만 계속합니다.

운영 공개 루트가 packaged되지 않았으면 중지합니다. Connected 경로를 사용하거나 release
trust 의식을 기다립니다. 테스트 키 또는 로컬 재정의는 운영 복구가 아닙니다.

## 런타임 준비 상태 복구

1. `/live`는 프로세스 생존에만, `/ready`는 처리 준비 상태에 사용합니다. 실제 운영 프로세스도
 차단된일 수 있습니다.
2. `runtime:startup-readiness:latest`를 읽습니다. `decision`, `missing_probe_ids`,
 `stale_probe_ids`, 각 결과의 `status`와 `failure_class`, `authority_ceilings`를 기록합니다.
3. `blocked`이면 런타임이 처리를 닫은 상태에서 해당 의존성을 복구합니다. 수명 주기
 게이트 밖에서 중복 작업을 만들 수 있으므로 소비자 또는 Pantheon을 수동 재시작하지 않습니다.
4. `degraded`이면 affected 기능을 보고된 상한 이하로 유지합니다. 특히 `/ready`의 HTTP
 `200`에서 배포 권한을 추론하지 않습니다.
5. 구성된 주기적 새로 고침을 기다립니다. 새로 관찰되고 만료되지 않은 탐색 결과만 누락된,
 stale, 실패한, 시간이 초과된 또는 crashed 근거를 해제할 수 있습니다.
6. 배포가 이미 시작되어 실패한 액션을 만들었다면 [인시던트 완화와 롤백](incident-mitigation-and-rollback-ko.md)
 절차로 전환합니다. 원래 상관관계 id와 멱등성 키를 보존합니다.

## 복구 훈련

승인된 non-production 범위에서 다음 훈련을 실행하고 정제된 출력을 보관합니다.

1. **만료된 계획:** 만료된 계획 고정본을 사용하거나 수명이 짧은 테스트 계획의 만료를 기다립니다.
 Exact 적용이 거부되고 적용 작업 흐름이 제출되지 않았는지 확인합니다. 새 계획을 생성하고 새로
 승인된 다이제스트만 진행되는지 확인합니다.
2. **Rejected 키트:** Signed 키트 산출물 하나의 disposable copy를 변조합니다. 점검이
 `artifact.offline-kit=fail`과 함께 `incomplete`를 반환하는지 확인합니다. Pinned 출처에서 전체
 copy를 교체하고 독립적인 검증 성공을 확인합니다. release 산출물을 in-place로 바꾸지 않습니다.
3. **준비 상태 loss:** 등록된 테스트 탐색 하나를 실패시킵니다. `blocked`가 `/ready`를 닫거나
 `degraded`가 해당 권한 상한을 낮추는지 확인합니다. 의존성을 복구하고 새로 고침을
 기다립니다. 복구를 얻기 위해 보고 또는 만료를 수정하지 않습니다.

## 근거와 완료

다음 정제된 산출물을 감사 기록에 첨부합니다.

- 거부된 계획과 replacement 계획의 id, 다이제스트, 상태, 만료, 작업 흐름 URL, 맥락 다이제스트.
- Provision 점검 스키마 버전, overall 상태, `artifact.offline-kit` 상태, 매니페스트
 다이제스트, 키트 버전, CLI 버전, platform, 파일 개수와 합계 바이트.
- Before-and-after 시작 결정, 탐색 id, 실패 등급, stale 또는 누락된 id, 권한
 상한, 관측 시간과 만료 시간.
- Approval 참조, 운영자 신원, 시각, 상관관계 id, 멱등성 키와 롤백 증적.

새 산출물 또는 fresh 근거가 original 검증기를 통과한 경우에만 복구가 완료됩니다. 수동
라벨, copied 상태, edited 시각 또는 successful 생존 응답은 완료가 아닙니다.
