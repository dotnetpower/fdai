---
title: Deep DB-DR 복원 훈련 런북
translation_of: db-dr-drill.md
translation_source_sha: b5fb5493566abd44b3e545a128f529d033d68e89
translation_revised: 2026-07-11
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

## 단계

1. **복원 지점 선택.** PITR 윈도우가 확실히 커버하도록 30분 전 시점을 사용합니다.

   ```bash
   RESTORE_TIME=$(date -u -d '-30 min' +%Y-%m-%dT%H:%M:%SZ)
   echo "Restore point: $RESTORE_TIME"
   ```

2. **격리 리소스 그룹 생성.** 병렬 훈련이 충돌하지 않도록 훈련 타임스탬프가
   포함된 이름을 사용합니다.

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
   기본 30분 예산 내에서 LRO 엔드포인트를 폴링합니다. 운영자용 등가 명령은
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

7. **정리.** 격리 리소스 그룹을 삭제합니다. 어댑터의 `teardown` 경로는
   멱등적이므로 404 응답은 '이미 삭제됨'을 의미하며 정상으로 간주합니다.

   ```bash
   az group delete -n "$DRILL_RG" --yes --no-wait
   ```

## 성공 기준

다음 다섯 조건이 모두 성립하면 훈련 통과입니다:

- 설정된 시간 예산 내에 복원 완료 (상위 기본값 30분).
- 무결성 리포트에 불일치 0건.
- 스모크 리포트에 최소 1건의 검사가 있고 모든 검사 통과.
- 격리 리소스 그룹 삭제가 2xx (또는 재시도 후 404)를 반환.
- 모든 단계가 감사 엔트리를 기록. 훈련은 감사 로그에
  `restore_started` / `restore_ready` / `integrity_passed` /
  `smoke_passed` / `teardown_complete` 이벤트가 모두 있을 때만 '완료' 상태입니다.

## 실패 처리

- **복원이 예산 초과** -> 어댑터가 `restore_timeout` 이벤트를 발생시킵니다.
  운영자는 마지막 LRO 상태 URL을 캡처하고 인시던트를 등록합니다. 그래도 정리는
  시도합니다.
- **무결성 불일치** -> 훈련이 안전 측으로 닫히며(fail-closed) 실패 처리됩니다.
  불일치 리포트가 인시던트의 페이로드입니다. 엔지니어가 표본을 확인하기 전까지
  격리 리소스 그룹을 삭제하지 마세요 (hold 태그 추가).
- **스모크 쿼리 실패** -> 무결성 불일치와 동일하게 처리합니다. 실패한 쿼리와
  응답을 기록합니다.
- **정리 5xx** -> 선형 backoff로 재시도합니다 (5회, 30초 간격). 그래도
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
- [security-and-identity-ko.md](../roadmap/security-and-identity-ko.md)
- [DbDrVerifier 모듈 docstring](../../src/fdai/core/verticals/resilience/db_dr_verifier.py)
