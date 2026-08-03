---
title: Deep DB-DR 복원 훈련 런북
translation_of: db-dr-drill.md
translation_source_sha: 6556736ad2eff2228a30f8a44a4288b9b8d1e2eb
translation_revised: 2026-07-31
---

# Deep DB-DR 복원 훈련 런북

Phase-3 § Deep DB-DR 훈련을 위한 운영자 런북. 이 리포지토리가 제공하는
[`DbDrVerifier`](../../src/fdai/core/verticals/resilience/db_dr_verifier.py)와
Azure 어댑터
([`AzureDbDrRestoreAdapter`](../../src/fdai/delivery/azure/db_dr_restore.py))를
반복 가능한 운영 절차로 만듭니다. 훈련은 프로덕션 PostgreSQL Flexible Server를
대상으로 실행되지만 프로덕션 데이터는 절대 건드리지 않습니다 - 복원 결과는
훈련이 끝나면 자동으로 정리되는 **격리된 리소스 그룹**에 배치됩니다.

## 언제 실행하나

- **기본 주기**: 월 1회.
- **스키마 마이그레이션 이후**: 사용자 노출 테이블을 변경한 마이그레이션은 7일
  이내 재실행합니다.
- **복원 어댑터 변경 시**:
  [`src/fdai/delivery/azure/db_dr_restore.py`](../../src/fdai/delivery/azure/db_dr_restore.py)
  아래 어떤 커밋이든 재실행을 유발합니다.
- **필요 시**: 인시던트 대응에서 최신 RPO/RTO 수치가 필요할 때 실행합니다.

## 전제 조건

1. 원본 Azure PostgreSQL Flexible Server 상태가 `Ready`입니다.
2. 원본 서버에 비어 있지 않은 PITR 윈도우가 있어야 합니다. `az postgres flexible-server show`가
   의도한 복원 시점 이전의 `backup.earliestRestoreDate`를 반환해야 합니다.
3. 운영자의 Azure CLI 프로파일이 배포 프로파일이어야 합니다 - `env -u AZURE_CONFIG_DIR`가
   기본 프로파일을 선택합니다. `az account show`가 포크에서 설정한
   `FDAI_EXPECTED_SUBSCRIPTION_ID`와 일치하는 서브스크립션을 반환하는지 확인합니다.
4. 격리 리소스 그룹 이름이 서브스크립션에서 사용 가능하고 원본 리소스 그룹과
   충돌하지 않아야 합니다. 훈련 스크립트가 매 실행마다 새 이름을 생성합니다.
5. 배포 entry point에서 `DbDrVerifier`에 복원, 무결성, smoke, 감사 어댑터를
  구성한 후 `verifier.run`을 CLI에 전달합니다. 명시적 runner 없이 upstream
  `main()`을 호출하면 Azure를 변경하기 전에 종료 코드 `2`로 중단됩니다.

  ```python
  from fdai.core.verticals.resilience.db_dr_drill_cli import main

  raise SystemExit(main(verifier.run))
  ```
6. 주입된 HTTP client는 Azure Resource Manager HTTPS origin을 origin-only `base_url`로
  사용합니다. Adapter는 동일 origin 또는 root-relative path의 LRO pointer만 허용합니다.
  Source는 canonical PostgreSQL Flexible Server ARM id이고 target resource-group, server 및
  region 값은 유효한 Azure path segment이며 restore timestamp는 timezone-aware여야 합니다.

## 단계

1. **복원 지점 선택.** PITR 윈도우가 확실히 커버하도록 30분 전 시점을 사용합니다.

   ```bash
   RESTORE_TIME=$(date -u -d '-30 min' +%Y-%m-%dT%H:%M:%SZ)
   echo "Restore point: $RESTORE_TIME"
   ```

2. **수동 절차용 격리 리소스 그룹 생성.** 병렬 훈련이 충돌하지 않도록 훈련 타임스탬프가
  포함된 이름을 사용합니다. Automated `AzureDbDrRestoreAdapter`는 `If-None-Match: *`로 이
  단계를 직접 수행하고 201 ownership result만 허용하며 existing group을 채택하지 않고
  차단합니다.

   ```bash
   DRILL_RG="rg-fdai-dr-drill-$(date +%Y%m%d-%H%M)"
   az group create -n "$DRILL_RG" -l koreacentral \
     --tags workload=fdai purpose=dr-drill drill-ts=$(date +%Y-%m-%d)
   ```

3. **PITR 복원 트리거.** 타깃 서버 이름은 Azure 전역 고유 식별자이므로 이전
   훈련과 충돌하지 않도록 타임스탬프를 포함합니다.

   ```bash
   SRC_ID="/subscriptions/<sub>/resourceGroups/rg-fdai-dev-krc/providers/Microsoft.DBforPostgreSQL/flexibleServers/psql-fdai-dev-krc"
   TARGET="psql-aiop-drill-$(date +%m%d%H%M)"
   az postgres flexible-server restore \
     -g "$DRILL_RG" -n "$TARGET" \
     --source-server "$SRC_ID" \
     --restore-time "$RESTORE_TIME" \
     --no-wait
   ```

4. **서버가 `Ready` 상태가 될 때까지 폴링.** 작은 dev 데이터베이스는 보통
   15-40분 안에 복원이 끝납니다.
   [`AzureDbDrRestoreAdapter`](../../src/fdai/delivery/azure/db_dr_restore.py)는
  기본 30분 예산 내에서 LRO 엔드포인트를 폴링합니다. Budget은 monotonic elapsed time을
  사용하며 configured sleep interval뿐 아니라 token 및 HTTP latency도 포함합니다. 운영자용 등가 명령은
   다음과 같습니다.

   ```bash
   while [[ "$(az postgres flexible-server show \
       -g "$DRILL_RG" -n "$TARGET" --query state -o tsv 2>/dev/null)" \
       != "Ready" ]]; do
     echo "still provisioning: $(date +%H:%M:%S)"; sleep 60
   done
   ```

5. **무결성 검사 (결정적).** 복원된 서버에 접속해 `$RESTORE_TIME` 시점 원본
   스냅샷에 대해 행 수와 체크섬을 비교합니다. 하나라도 불일치가 있으면 훈련은
   실패로 처리됩니다.

   상위(upstream)의
   [`DbDrVerifier`](../../src/fdai/core/verticals/resilience/db_dr_verifier.py)는
   [`IntegrityChecker`](../../src/fdai/shared/providers/db_dr.py)
   Protocol seam을 주입받아 사용합니다. 운영자용 등가 명령은 다음과 같습니다.

   ```bash
   psql "host=$TARGET.postgres.database.azure.com user=<admin> dbname=fdai sslmode=require" \
     -c "SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY relname;"
   ```

   복원 지점 기준으로 원본에 대해 기록해 둔 동일한 쿼리 결과와 비교합니다.
   불일치 0건이 phase-3 exit gate입니다.

6. **앱 레벨 스모크 테스트.** 대표적인 읽기 전용 클라이언트가 복원된 서버를
   바라보도록 설정하고 범위가 한정된 스모크 스위트를 실행합니다 - 사용자 노출
   테이블마다 쿼리 하나에 smoke 스키마에 대한 세션 쓰기 하나를 더합니다. 어떤
   에러든 훈련은 실패로 처리됩니다.

  모든 복원 스모크 스위트에 다음 사용자 컨텍스트 테이블을 포함합니다.

  - `conversation_record`와 `conversation_turn`
  - `user_preference`와 `user_memory_fact`
  - `conversation_policy`
  - `briefing_subscription`과 `briefing_run`
  - `workflow_definition`과 `workflow_binding`
  - `user_context_projection_delete_queue`

  행 수뿐 아니라 외래 키, 고유 제약 조건, 원자적으로 할당되는
  `conversation_record.next_turn_index` 값도 검증합니다. 삭제 큐에서는
  `leased_until` 이후 leased 행을 다시 claim할 수 있고 작업 완료 시 행이
  제거되는지 검증합니다.

7. **정리.** 격리 리소스 그룹을 삭제합니다. 어댑터의 `teardown` 경로는
  멱등적이므로 404 응답은 '이미 삭제됨'을 의미하며 정상으로 간주합니다. 202 response는 LRO
  pointer를 제공해야 하고 adapter는 이를 polling한 후 target group이 404를 반환하는지 검증한
  뒤 cleanup success를 보고합니다. Restore failure 또는 cancellation도 adapter가 직접 만든
  group만 제거합니다.

   ```bash
   az group delete -n "$DRILL_RG" --yes --no-wait
   ```

## 보존 및 백업 잔존 데이터

스케줄러는 90일이 지난 비활성 대화와 오래된 브리핑 실행을 live 데이터베이스에서
삭제하고, `expires_at` 시각이 도래한 memory fact를 삭제합니다. 같은 트랜잭션은
ontology object id를 `user_context_projection_delete_queue`에 기록합니다. 이후
스케줄러가 격리된 재시도와 제한된 backoff를 적용해 metadata-only projection을
삭제합니다.

PITR은 개인정보 또는 보존 삭제 이전의 데이터베이스 상태를 복구할 수 있습니다.
따라서 live store에서 삭제했다고 해서 보존된 모든 백업 복사본이 즉시 지워지는
것은 아닙니다. 프로덕션은 35일 geo-redundant PostgreSQL 백업 window를 유지하며,
그 이후 provider가 잔존 복사본을 만료시킵니다. 복원 서버 접근은 훈련 운영자로
제한하고 검증이 끝나면 격리된 복원을 바로 삭제하는 것이 좋습니다.

복원 서버에 스케줄러 또는 애플리케이션 프로세스를 연결하기 전에 다음 순서를
따릅니다.

1. 선택한 복원 지점을 확인하고 사용자 컨텍스트 삭제 이전 시점인지 기록합니다.
2. raw turn 또는 memory body를 로그나 증거 artifact에 노출하지 않고 위의 사용자
  컨텍스트 smoke check를 실행합니다.
3. 범위가 제한된 retention tick을 한 번 실행하고 projection deletion queue를
  비웁니다.
4. 서버가 서비스에 투입되기 전에 source row와 ontology metadata가 일치하는지
  확인합니다.

## 성공 기준

다음 다섯 조건이 모두 성립하면 훈련 통과입니다:

- 설정된 시간 예산 내에 복원 완료 (상위 기본값 30분).
- 무결성 리포트에 불일치 0건.
- 스모크 리포트에 최소 1건의 검사가 있고 모든 검사 통과.
- 최종 ARM resource id가 요청한 restored server와 정확히 일치하고 유효한 FQDN이 요청한 target
  server name으로 시작합니다.
- 격리 리소스 그룹 삭제가 2xx (또는 재시도 후 404)를 반환.
- 모든 단계가 감사 엔트리를 기록. 훈련은 감사 로그에
  `restore_started` / `restore_ready` / `integrity_passed` /
  `smoke_passed` / `teardown_complete` 이벤트가 모두 있을 때만 '완료' 상태입니다. 모든 phase와
  teardown record는 결정의 고유 `run_id`를 `correlation_id`로 사용하고 `experiment_id`는
  계획된 exercise를 계속 식별합니다. Phase idempotency key는 해당 run 안에서 고유해야 합니다.

`verification_passed`는 intermediate result입니다. `teardown_succeeded` 이후에만 final
`passed` 결정을 기록합니다. Teardown error는 `cleanup_failed`를 만들고 진단을 위해 primary
verification outcome을 보존하며 CLI에서 nonzero exit를 반환하고 cleanup이 검증될 때까지 leaked
resource를 owned incident로 유지합니다.

## 실패 처리

- **복원이 예산 초과** -> 어댑터가 `restore_timeout` 이벤트를 발생시킵니다.
  운영자는 마지막 LRO 상태 URL을 캡처하고 인시던트를 등록합니다. 그래도 정리는
  시도합니다.
- **Malformed successful LRO response** -> 인식된 string status가 없는 HTTP 200 poll은 implicit
  running state가 아니라 restore failure입니다. Operation reference를 보존하고 중단합니다.
- **무결성 불일치** -> 훈련이 안전 측으로 닫히며(fail-closed) 실패 처리됩니다.
  불일치 리포트가 인시던트의 페이로드입니다. 엔지니어가 표본을 확인하기 전까지
  격리 리소스 그룹을 삭제하지 마세요 (hold 태그 추가).
- **스모크 쿼리 실패** -> 무결성 불일치와 동일하게 처리합니다. 실패한 쿼리와
  응답을 기록합니다.
- **정리 408, 429 또는 5xx** -> bounded linear delay로 재시도합니다(기본 5회, 30초 간격).
  다른 4xx response는 즉시 실패합니다. 그래도
  실패하면 on-call 담당자를 호출합니다 - 남겨진 격리 리소스 그룹은 비용이
  발생하며 수동 정리가 필요합니다.

## 비용 참고

격리 Postgres 서버는 훈련 기간 동안 표준 Flexible Server 컴퓨트 + 스토리지
요금이 발생합니다. day-zero의 Burstable B1ms + 32GB 스토리지 티어에서는 시간당
요금이 소액이지만, 정리를 건너뛰면 누적됩니다. 워크로드 태그 `purpose=dr-drill`에
대한 알림을 걸어 24시간 이상 남아 있는 잔여(stray) 훈련 리소스 그룹을
감지합니다.

## 관련 문서

- [phase-3-integrated-loop-ko.md § Deep DB-DR (stateful - 전용 설계)](../roadmap/phases/phase-3-integrated-loop-ko.md)
- [security-and-identity-ko.md](../roadmap/architecture/security-and-identity-ko.md)
- [DbDrVerifier 모듈 docstring](../../src/fdai/core/verticals/resilience/db_dr_verifier.py)
