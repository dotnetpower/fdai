---
title: Deep DB-DR 복원 훈련 런북
translation_of: db-dr-drill.md
translation_source_sha: 272aed706ff74cacddcf7c442ef14729a766254f
translation_revised: 2026-07-06
---

# Deep DB-DR 복원 훈련 런북

Phase-3 § Deep DB-DR 훈련을 위한 운영자 런북. 배송된
[`DbDrVerifier`](../../src/aiopspilot/core/verticals/db_dr_verifier.py)와
Azure 어댑터
([`AzureDbDrRestoreAdapter`](../../src/aiopspilot/delivery/azure/db_dr_restore.py))를
반복 가능한 운영 절차로 만듭니다. 훈련은 프로덕션 PostgreSQL Flexible Server에
대해 실행되지만 프로덕션 데이터는 절대 건드리지 않습니다. 복원은 훈련이 끝나면
자동으로 정리되는 **격리된 리소스 그룹**에 랜딩됩니다.

## 언제 실행하나

- **베이스라인 스케줄**: 월 1회.
- **스키마 마이그레이션 이후**: 사용자 노출 테이블을 변경한 마이그레이션은 7일
  이내 재실행.
- **복원 어댑터 변경 시**:
  [`src/aiopspilot/delivery/azure/db_dr_restore.py`](../../src/aiopspilot/delivery/azure/db_dr_restore.py)
  아래 어떤 커밋이든 재실행 트리거.
- **필요 시**: 인시던트 대응에서 최신 RPO/RTO 수치가 필요할 때.

## 전제 조건

1. 원본 Azure PostgreSQL Flexible Server 상태가 `Ready`.
2. 원본 서버에 비어 있지 않은 PITR 창구가 있음. `az postgres flexible-server show`가
   의도한 복원 시점보다 오래된 `backup.earliestRestoreDate`를 반환해야 합니다.
3. 운영자의 Azure CLI 프로파일이 배포 프로파일임 - `env -u AZURE_CONFIG_DIR`가 기본
   프로파일을 선택합니다. `az account show`가 포크에서 설정한
   `AIOPSPILOT_EXPECTED_SUBSCRIPTION_ID`와 일치하는 서브스크립션을 반환하는지 확인합니다.
4. 격리 리소스 그룹 이름이 서브스크립션에서 사용 가능하고 원본 리소스 그룹과
   충돌하지 않음. 훈련 스크립트가 매 실행마다 새 이름을 생성합니다.

## 단계

1. **복원 지점 선택.** PITR 창구가 확실히 커버하도록 과거 30분 지점을 씁니다.

   ```bash
   RESTORE_TIME=$(date -u -d '-30 min' +%Y-%m-%dT%H:%M:%SZ)
   echo "Restore point: $RESTORE_TIME"
   ```

2. **격리 리소스 그룹 생성.** 병렬 훈련이 충돌하지 않도록 훈련 타임스탬프를
   담은 이름을 씁니다.

   ```bash
   DRILL_RG="rg-aiopspilot-dr-drill-$(date +%Y%m%d-%H%M)"
   az group create -n "$DRILL_RG" -l koreacentral \
     --tags workload=aiopspilot purpose=dr-drill drill-ts=$(date +%Y-%m-%d)
   ```

3. **PITR 복원 트리거.** 타겟 서버 이름은 전역 고유 Azure 식별자이므로 이전
   훈련과 충돌하지 않도록 타임스탬프를 포함합니다.

   ```bash
   SRC_ID="/subscriptions/<sub>/resourceGroups/rg-aiopspilot-dev-krc/providers/Microsoft.DBforPostgreSQL/flexibleServers/psql-aiopspilot-dev-krc"
   TARGET="psql-aiop-drill-$(date +%m%d%H%M)"
   az postgres flexible-server restore \
     -g "$DRILL_RG" -n "$TARGET" \
     --source-server "$SRC_ID" \
     --restore-time "$RESTORE_TIME" \
     --no-wait
   ```

4. **서버가 `Ready` 상태가 될 때까지 폴링.** 작은 dev 데이터베이스는 보통
   15-40분 안에 복원이 끝납니다.
   [`AzureDbDrRestoreAdapter`](../../src/aiopspilot/delivery/azure/db_dr_restore.py)는
   기본 30분 예산 내에서 LRO 엔드포인트를 폴링합니다. 운영자용 등가 명령은
   다음과 같습니다.

   ```bash
   while [[ "$(az postgres flexible-server show \
       -g "$DRILL_RG" -n "$TARGET" --query state -o tsv 2>/dev/null)" \
       != "Ready" ]]; do
     echo "still provisioning: $(date +%H:%M:%S)"; sleep 60
   done
   ```

5. **무결성 검사 (결정론).** 복원된 서버에 접속해 `$RESTORE_TIME` 시점 원본
   스냅샷에 대해 row 수 + 체크섬을 비교합니다. 하나라도 불일치가 있으면 훈련
   실패입니다.

   상위의
   [`DbDrVerifier`](../../src/aiopspilot/core/verticals/db_dr_verifier.py)는
   [`IntegrityChecker`](../../src/aiopspilot/shared/providers/db_dr.py)
   Protocol seam을 소비합니다. 운영자용 등가 명령은 다음과 같습니다.

   ```bash
   psql "host=$TARGET.postgres.database.azure.com user=<admin> dbname=aiopspilot sslmode=require" \
     -c "SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY relname;"
   ```

   복원 지점에서 원본에 대해 기록된 같은 쿼리와 비교합니다. 불일치가 0인
   상태가 phase-3 exit gate입니다.

6. **앱 레벨 스모크 테스트.** 대표 읽기 전용 클라이언트를 복원된 서버로 향하게
   하고 경계된 스모크 슈트를 실행합니다. 사용자 노출 테이블당 쿼리 하나 + smoke
   스키마에 세션 쓰기 하나. 어떤 에러든 훈련 실패입니다.

7. **정리.** 격리 리소스 그룹을 삭제합니다. 어댑터의 `teardown` 경로는
   멱등적이므로 404는 "이미 사라짐"으로 유효합니다.

   ```bash
   az group delete -n "$DRILL_RG" --yes --no-wait
   ```

## 성공 기준

다섯 조건이 모두 성립해야 훈련 통과:

- 설정된 예산 내에 복원 완료 (상위 기본값 30분).
- 무결성 리포트에 불일치 0건.
- 스모크 리포트에 최소 1건의 검사가 있고 모든 검사 통과.
- 격리 리소스 그룹 삭제가 2xx (또는 재시도 후 404) 반환.
- 모든 단계가 감사 엔트리를 기록. 훈련은 감사 로그에
  `restore_started` / `restore_ready` / `integrity_passed` /
  `smoke_passed` / `teardown_complete` 이벤트가 모두 있을 때만 "완료"입니다.

## 실패 처리

- **복원이 예산 초과** -> 어댑터가 `restore_timeout` 이벤트를 발화. 운영자는
  마지막 LRO 상태 URL을 캡처하고 인시던트를 접수합니다. 정리는 여전히 시도합니다.
- **무결성 불일치** -> 훈련이 안전 방향으로 실패. 불일치 리포트가 인시던트의
  페이로드입니다. 엔지니어가 샘플을 확인하기 전까지 격리 리소스 그룹을 삭제하지
  마세요 (hold 태그 추가).
- **스모크 쿼리 실패** -> 무결성 불일치와 동일 처리. 실패 쿼리 + 응답 기록.
- **정리 5xx** -> 선형 backoff으로 재시도 (5회, 30초 간격). 여전히 실패하면
  on-call 페이지: 남겨진 격리 리소스 그룹은 비용이 발생하며 수동 정리가 필요합니다.

## 비용 참고

격리 Postgres 서버는 훈련 기간 동안 표준 Flexible Server 컴퓨트 + 스토리지
요금이 발생합니다. day-zero의 Burstable B1ms + 32GB 스토리지 티어에서는 시간당
소액이지만, 정리를 건너뛰면 누적됩니다. 워크로드 태그 `purpose=dr-drill`에 대한
알림으로 24시간 이상 남아 있는 stray 훈련 리소스 그룹을 잡습니다.

## 관련 문서

- [phase-3-integrated-loop-ko.md § Deep DB-DR (stateful - 전용 설계)](../roadmap/phases/phase-3-integrated-loop-ko.md)
- [security-and-identity-ko.md](../roadmap/security-and-identity-ko.md)
- [DbDrVerifier 모듈 docstring](../../src/aiopspilot/core/verticals/db_dr_verifier.py)
