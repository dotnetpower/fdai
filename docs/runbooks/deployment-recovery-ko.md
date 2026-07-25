---
title: 배포 복구
summary: Protected plan 거부, offline kit 검증 실패 또는 runtime readiness 저하에서 안전하게 복구합니다.
translation_of: deployment-recovery.md
translation_source_sha: af3caf4fcc78b036cfbf6a41035b191f16355302
translation_revised: 2026-07-25
---

# 배포 복구

Connected 또는 disconnected 배포를 안전하게 계속할 수 없을 때 이 runbook을 사용합니다. 기존
machine status를 새 plan, 새 kit 또는 fresh evidence 복구 경로에 연결하며 signed metadata를
수정하거나 readiness를 인위적으로 만들지 않습니다.

> **범위:** 이 절차는 customer-neutral입니다. Downstream fork는 environment value,
> repository name, evidence location, owner와 승인된 release channel을 제공합니다.

## 담당과 진입 조건

- **Owner:** Plan과 kit 복구는 deployment operator, readiness 복구는 runtime operator가 담당합니다.
- **Approver:** 해당 environment의 지정된 deployment approver입니다. 다른 plan digest 또는
  deployment context에는 기존 승인을 재사용하지 않습니다.
- **Entry:** Decision table의 stable signal 중 하나가 존재합니다.
- **Impact scope:** 한 번에 하나의 environment, protected plan id 또는 offline-kit candidate입니다.
- **Terminal no-op:** Sanitized machine evidence에 연결할 수 없는 signal이면 apply를 제출하거나
  trust material을 교체하거나 consumer를 재시작하지 않습니다. Gap을 기록하고 검토로 전달합니다.

## Decision table

| Signal | 의미 | Stop condition | 안전한 복구 |
|--------|------|----------------|-------------|
| Plan status가 `planning`, `applying`, `applied`, `failed` 또는 `expired` | Plan이 새 exact apply 대상이 아님 | Apply를 제출하지 않음 | 추가 배포가 필요하면 새 plan을 생성하고 승인 |
| `plan has expired` | Signed apply window가 닫힘 | `expires_at`을 연장하거나 plan id를 재사용하지 않음 | Doctor, preflight, plan 생성을 반복 |
| Plan context, commit, bundle, source, evidence 또는 binary digest mismatch | 현재 의도가 protected artifact와 다름 | Metadata를 수정하거나 다른 expected digest를 전달하지 않음 | Input을 수정하고 새 protected plan 생성 |
| Plan이 preflight에 blocked되거나 approved runner를 사용할 수 없음 | 필수 evidence 또는 execution boundary를 사용할 수 없음 | Local apply 금지 | 보고된 blocker를 해결하고 approved runner에서 새 plan 생성 |
| `fdaictl provision inspect`가 `4` 또는 `status=incomplete` 반환 | 필수 host, identity, connectivity 또는 kit evidence 실패 | Profile에서 initialize 또는 deploy 금지 | 실패한 check를 복구하고 다시 inspect |
| `artifact.offline-kit=fail` | Signature, compatibility, manifest, file set 또는 digest 검증 실패 | 거부된 kit 내부 file을 복구하지 않음 | Pinned release source에서 전체 kit를 교체하고 다시 inspect |
| `artifact.offline-kit=candidate` | Kit가 있지만 pinned verifier가 trust를 확립하지 못함 | 존재를 verification으로 취급하지 않음 | Packaged public root가 있는 release를 설치하거나 connected path 사용 |
| Startup `decision=blocked` 또는 `/ready`가 `503` 반환 | Process-critical evidence가 failed, missing, stale, timed out 또는 crashed | Consumer 또는 Pantheon을 수동 시작하지 않음 | Dependency를 복구하고 fresh periodic readiness evaluation 대기 |
| Startup `decision=degraded` | Process가 reduced authority로 ready 상태를 유지할 수 있음 | 보고된 `authority_ceilings`보다 높은 action 금지 | Capability를 복구하고 fresh report에서 authority가 올라가지 않는지 확인 |
| Startup evidence가 missing 또는 stale | 이전 observation이 더 이상 readiness를 증명하지 못함 | Result, timestamp, expiry 또는 state-store record 수정 금지 | Configured probe가 fresh evidence를 생성하게 함 |

## Protected plan 복구

1. Apply 전에 sanitized plan record를 읽습니다.

   ```bash
   fdaictl deploy status \
     --repository <owner/repository> \
     --plan-id <plan-id> \
     --output json
   ```

2. `status`가 정확히 `ready`이고 현재 시간이 `expires_at` 이전이며 plan digest가 대상
   environment, bundle, commit, backend와 runner에 속하는 경우에만 계속합니다.
3. Expiry 또는 mismatch가 있으면 read-only prerequisite를 다시 실행하고 새 plan을 제출합니다.

   ```bash
   fdaictl doctor --config <environment-config> --output json
   fdaictl deploy preflight \
     --input <preflight-input> \
     --environment-config <environment-config> \
     --output json
   fdaictl deploy plan \
     --config <environment-config> \
     --repository <owner/repository> \
     --bundle-digest <sha256> \
     --commit-sha <git-sha> \
     --output json
   ```

4. 새 plan id와 digest에 대한 승인을 받습니다. 거부된 plan의 승인을 이전하지 않습니다.
5. `fdaictl deploy apply`로 exact approved plan만 제출합니다. Runner-side verification은 binary
   plan, source artifact, preflight evidence, context, commit, status와 expiry를 계속 일치시켜야 합니다.

Preflight command는 clear이면 `0`, 검토가 필요한 finding이면 `2`, deployment blocker이면 `3`으로
종료합니다. Exit code는 evidence이며 report를 우회할 권한이 아닙니다.

## 거부된 offline kit 교체

1. Mutation 없이 inspect합니다.

   ```bash
   fdaictl provision inspect \
     --connectivity offline \
     --host existing \
     --offline-kit <kit-directory> \
     --output json
   ```

2. Overall `status=ready`, exit `0`, `artifact.offline-kit=verified`를 모두 요구합니다. Exit `2`는
   review, exit `4`는 incomplete입니다. `candidate`와 `not-configured`는 trust decision이 아닙니다.
3. Verification이 실패하면 directory를 evidence로 격리합니다. Artifact 하나를 교체하거나
   manifest를 다시 쓰거나 signature를 재생성하거나 operator-selected trust root를 제공하지 않습니다.
4. Pinned release source에서 완전한 replacement를 가져옵니다. Packaged public root와 정확한 CLI
   version 및 platform으로 검증합니다.
5. Inspection을 다시 실행합니다. Replacement가 독립적으로 `verified`에 도달하고 필수 tool 및
   workload-identity check를 모두 통과한 뒤에만 계속합니다.

Production public root가 packaged되지 않았으면 중지합니다. Connected path를 사용하거나 release
trust ceremony를 기다립니다. Test key 또는 local override는 운영 복구가 아닙니다.

## Runtime readiness 복구

1. `/live`는 process liveness에만, `/ready`는 processing readiness에 사용합니다. Live process도
   blocked일 수 있습니다.
2. `runtime:startup-readiness:latest`를 읽습니다. `decision`, `missing_probe_ids`,
   `stale_probe_ids`, 각 result의 `status`와 `failure_class`, `authority_ceilings`를 기록합니다.
3. `blocked`이면 runtime이 processing을 닫은 상태에서 해당 dependency를 복구합니다. Lifecycle
   gate 밖에서 duplicate work를 만들 수 있으므로 consumer 또는 Pantheon을 수동 재시작하지 않습니다.
4. `degraded`이면 affected capability를 보고된 ceiling 이하로 유지합니다. 특히 `/ready`의 HTTP
   `200`에서 deployment authority를 추론하지 않습니다.
5. Configured periodic refresh를 기다립니다. 새로 관찰되고 만료되지 않은 probe result만 missing,
   stale, failed, timed-out 또는 crashed evidence를 해제할 수 있습니다.
6. Deployment가 이미 시작되어 failed action을 만들었다면 [incident 완화와 rollback](incident-mitigation-and-rollback-ko.md)
   절차로 전환합니다. 원래 correlation id와 idempotency key를 보존합니다.

## 복구 훈련

승인된 non-production scope에서 다음 drill을 실행하고 sanitized output을 보관합니다.

1. **Expired plan:** Expired plan fixture를 사용하거나 short-lived test plan의 expiry를 기다립니다.
   Exact apply가 거부되고 apply workflow가 제출되지 않았는지 확인합니다. 새 plan을 생성하고 새로
   승인된 digest만 진행되는지 확인합니다.
2. **Rejected kit:** Signed kit artifact 하나의 disposable copy를 변조합니다. Inspection이
   `artifact.offline-kit=fail`과 함께 `incomplete`를 반환하는지 확인합니다. Pinned source에서 전체
   copy를 교체하고 independent verification 성공을 확인합니다. Release artifact를 in-place로 바꾸지 않습니다.
3. **Readiness loss:** Registered test probe 하나를 실패시킵니다. `blocked`가 `/ready`를 닫거나
   `degraded`가 해당 authority ceiling을 낮추는지 확인합니다. Dependency를 복구하고 refresh를
   기다립니다. 복구를 얻기 위해 report 또는 expiry를 수정하지 않습니다.

## Evidence와 완료

다음 sanitized artifact를 audit record에 첨부합니다.

- 거부된 plan과 replacement plan의 id, digest, status, expiry, workflow URL, context digest.
- Provision inspection schema version, overall status, `artifact.offline-kit` status, manifest
  digest, kit version, CLI version, platform, file count와 total bytes.
- Before-and-after startup decision, probe id, failure class, stale 또는 missing id, authority
  ceiling, observation time과 expiry time.
- Approval reference, operator identity, timestamp, correlation id, idempotency key와 rollback receipt.

새 artifact 또는 fresh evidence가 original verifier를 통과한 경우에만 복구가 완료됩니다. Manual
label, copied status, edited timestamp 또는 successful liveness response는 완료가 아닙니다.
