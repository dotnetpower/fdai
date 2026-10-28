---
title: 심층 DB-DR 복원 훈련 런북
translation_of: db-dr-drill.md
translation_source_sha: 898b3abd4ff105b4b81caf931f39f959d9180202
translation_revised: 2026-10-22
---

# 심층 DB-DR 복원 훈련 런북

이 운영자 런북을 사용해 단계 3의 심층 데이터베이스 재해 복구(DB-DR) 훈련을 수행합니다.
이 저장소에서 제공하는
[`DbDrVerifier`](../../services/core-control-plane/src/fdai/core/verticals/resilience/db_dr_verifier.py)와
전달 계층 소유
[`AzurePostgresRestoreAdapter`](../../services/core-control-plane/src/fdai/delivery/azure/db_dr_restore.py)를
사용해 반복 가능한 운영 절차를 수행합니다. 훈련은 프로덕션 PostgreSQL Flexible Server를
원본으로 사용하지만 프로덕션 데이터를 변경하지 않습니다. 복원 결과는 Terraform이 관리하는
**격리된 리소스 그룹**에 배치되고 훈련이 끝나면 임시 서버를 삭제합니다.

## 언제 실행하나

- **기본 주기**: 매월 1회 실행합니다.
- **스키마 마이그레이션 이후**: 사용자 노출 테이블을 변경한 마이그레이션은 7일
  이내 재실행합니다.
- **복원 어댑터 변경 시**:
  [`services/core-control-plane/src/fdai/delivery/azure/db_dr_restore.py`](../../services/core-control-plane/src/fdai/delivery/azure/db_dr_restore.py)
  경로에 변경을 반영하는 모든 커밋 이후에 다시 실행합니다.
- **필요 시**: 인시던트 대응에서 최신 RPO/RTO 수치가 필요할 때 실행합니다.

## 전제 조건

1. 원본 Azure PostgreSQL Flexible Server 상태가 `Ready`입니다.
2. 원본 서버에 특정 시점 복원(PITR)이 가능한 구간이 있어야 합니다. `az postgres flexible-server show`가
   의도한 복원 시점 이전의 `backup.earliestRestoreDate`를 반환해야 합니다.
3. 운영자의 Azure CLI 프로필은 배포 프로필이어야 합니다. `env -u AZURE_CONFIG_DIR`는
   기본 프로필을 선택합니다. `az account show`가 포크에서 설정한
   `FDAI_EXPECTED_SUBSCRIPTION_ID`와 일치하는 구독을 반환하는지 확인합니다.
4. Terraform이 격리 대상 리소스 그룹과 전용 DB-DR 신원을 만들었는지 확인합니다. 이 신원은
   원본 서버 Reader, 대상 그룹 범위의 PostgreSQL Flexible Management Service Contributor,
   ACR 이미지 가져오기, 상태 저장소 시크릿 읽기 권한만 받으며 실행기 신원이 아닙니다.
5. `FDAI_DR_DRILL_INTEGRITY_TABLES`에 작고 안정적인 테이블 1-16개를 지정합니다. 기본값은
   `alembic_version`입니다. 선택한 복원 간격에도 내용이 안정적인 애플리케이션 테이블만
   추가하세요.
6. 예약 실행 진입점은 `python -m fdai.delivery.db_dr_drill_cli`입니다. 전체 예행 실행은 토큰을
   요청하거나 Azure 또는 PostgreSQL을 변경하지 않고 원본, 대상, 테이블, 시크릿 바인딩을
   검증합니다.

## 단계

1. **복원 지점을 선택합니다.** PITR 가능 구간에 확실히 포함되도록 30분 전 시점을 사용합니다.

   ```bash
   RESTORE_TIME=$(date -u -d '-30 min' +%Y-%m-%dT%H:%M:%SZ)
   echo "복원 지점: $RESTORE_TIME"
   ```

2. **격리된 리소스 그룹을 사용합니다.** 자동 작업은 Terraform이 만든 전용 그룹을 사용하고 그 안에
  타임스탬프가 있는 서버를 만듭니다. 수동 절차에서는 원본 그룹과 다른 별도 그룹을
  만드세요.

   ```bash
   DRILL_RG="rg-fdai-dr-drill-$(date +%Y%m%d-%H%M)"
   az group create -n "$DRILL_RG" -l koreacentral \
     --tags workload=fdai purpose=dr-drill drill-ts=$(date +%Y-%m-%d)
   ```

3. **PITR 복원을 시작합니다.** 대상 서버 이름은 Azure 전역에서 고유해야 하므로 이전
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

4. **서버가 `Ready` 상태가 될 때까지 조회합니다.** 소규모 개발 데이터베이스는 보통
   15-40분 안에 복원이 끝납니다.
   [`AzurePostgresRestoreAdapter`](../../services/core-control-plane/src/fdai/delivery/azure/db_dr_restore.py)는
  기본 45분 예산 안에서 정확한 서버 리소스를 폴링합니다. 잘못된 형식, 실패, 취소 또는
  불완전한 응답은 안전을 위해 실패로 처리하고, 부분적으로 생성된 대상의 정리를 시작합니다.
  운영자가 같은 작업을 수행하는 명령은
   다음과 같습니다.

   ```bash
   while [[ "$(az postgres flexible-server show \
       -g "$DRILL_RG" -n "$TARGET" --query state -o tsv 2>/dev/null)" \
       != "Ready" ]]; do
     echo "still provisioning: $(date +%H:%M:%S)"; sleep 60
   done
   ```

5. **결정론적으로 무결성을 검사합니다.** 복원된 서버에 접속해 `$RESTORE_TIME` 시점 원본
   스냅샷에 대해 행 수와 체크섬을 비교합니다. 하나라도 불일치가 있으면 훈련은
   실패로 처리됩니다.

   업스트림의
   [`DbDrVerifier`](../../services/core-control-plane/src/fdai/core/verticals/resilience/db_dr_verifier.py)는
   [`IntegrityChecker`](../../services/core-control-plane/src/fdai/shared/providers/db_dr.py)
   프로토콜을 구현한 의존성을 주입받아 사용합니다. 운영자가 같은 검사를 수행하는 명령은 다음과 같습니다.

   ```bash
   psql "host=$TARGET.postgres.database.azure.com user=<admin> dbname=fdai sslmode=require" \
     -c "SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY relname;"
   ```

   복원 지점 기준으로 원본에 대해 기록해 둔 동일한 쿼리 결과와 비교합니다.
   불일치 0건이 단계 3의 완료 조건입니다.

6. **애플리케이션 수준 스모크 테스트를 실행합니다.** 대표적인 읽기 전용 클라이언트가
   복원된 서버에 연결되도록 설정하고 범위가 한정된 스모크 테스트를 실행합니다.
   사용자에게 노출되는 테이블마다 쿼리 하나를 실행하고, 스모크 테스트용 스키마에
   세션 쓰기 하나를 추가합니다. 오류가 하나라도 발생하면 훈련은 실패로 처리됩니다.

  모든 복원 스모크 테스트에 다음 사용자 컨텍스트 테이블을 포함합니다.

  - `conversation_record`와 `conversation_turn`
  - `user_preference`와 `user_memory_fact`
  - `conversation_policy`
  - `briefing_subscription`과 `briefing_run`
  - `workflow_definition`과 `workflow_binding`
  - `user_context_projection_delete_queue`

  행 수뿐 아니라 외래 키, 고유 제약 조건, 원자적으로 할당되는
  `conversation_record.next_turn_index` 값도 검증합니다. 삭제 큐에서는
  임대한 행을 `leased_until` 이후 다시 점유할 수 있고 작업 완료 시 행이
  제거되는지 검증합니다.

7. **정리합니다.** 임시 복원 서버를 삭제합니다. 어댑터의 `teardown` 경로는 멱등적이므로 404는
  이미 삭제된 정상 결과입니다. 삭제 요청이 수락되면 해당 서버를 정확히 조회해 404를 반환할
  때까지 기다린 뒤 정리 성공을 보고합니다. 복원이 실패하거나 취소된 경우에도 부분적으로
  생성된 서버의 삭제를 시도합니다. Terraform이 관리하는
  격리 그룹은 다음 훈련을 위해 유지합니다.

   ```bash
   az postgres flexible-server delete -g "$DRILL_RG" -n "$TARGET" --yes
   ```

## 보존 및 백업 잔존 데이터

스케줄러는 90일이 지난 비활성 대화와 오래된 브리핑 실행을 실제 운영 데이터베이스에서
삭제하고, `expires_at` 시각이 도래한 기억 사실을 삭제합니다. 같은 트랜잭션은
온톨로지 객체 ID를 `user_context_projection_delete_queue`에 기록합니다. 이후
스케줄러가 격리된 재시도와 제한된 재시도 대기를 적용해 메타데이터만 포함한 변환 결과를
삭제합니다.

PITR은 개인정보 또는 보존 삭제 이전의 데이터베이스 상태를 복구할 수 있습니다.
따라서 실제 운영 저장소에서 삭제했다고 해서 보존된 모든 백업 복사본이 즉시 지워지는
것은 아닙니다. 프로덕션은 지역 중복 PostgreSQL 백업을 35일간 보존하며,
그 이후 프로바이더가 잔존 복사본을 만료시킵니다. 복원 서버 접근은 훈련 운영자로
제한하고 검증이 끝나면 격리된 복원을 바로 삭제하는 것이 좋습니다.

복원 서버에 스케줄러 또는 애플리케이션 프로세스를 연결하기 전에 다음 순서를
따릅니다.

1. 선택한 복원 지점을 확인하고 사용자 컨텍스트 삭제 이전 시점인지 기록합니다.
2. 원본 대화 턴이나 기억 본문을 로그 또는 근거 산출물에 노출하지 않고 위의 사용자
  컨텍스트 스모크 검사를 실행합니다.
3. 범위가 한정된 보존 처리 주기를 한 번 실행하고 변환 결과 삭제 큐를 비웁니다.
4. 서버가 서비스에 투입되기 전에 출처 행과 온톨로지 메타데이터가 일치하는지
  확인합니다.

## 성공 기준

다음 여섯 조건을 모두 충족할 때만 훈련을 통과합니다.

- 설정된 시간 예산 안에 복원이 완료됩니다(업스트림 기본값 45분).
- 무결성 보고서의 불일치가 0건입니다.
- 스모크 보고서에 최소 1건의 검사가 있고 모든 검사를 통과합니다.
- 최종 ARM 리소스 ID가 요청한 복원 서버와 정확히 일치하고 유효한 FQDN이 요청한 대상
  서버 이름으로 시작합니다.
- 복원 서버 삭제가 수락되고 해당 서버를 정확히 조회한 결과가 404입니다.
- 모든 단계가 감사 엔트리를 기록합니다. 훈련은 감사 로그에
  `start` / `verification_passed` / `teardown_succeeded` / `passed` 이벤트가 모두 있을 때만
  완료 상태입니다. 모든 단계와
  정리 기록은 결정의 고유 `run_id`를 `correlation_id`로 사용하고 `experiment_id`는
  계획한 훈련을 계속 식별합니다. 단계 멱등성 키는 해당 실행 안에서 고유해야 합니다.

`verification_passed`는 중간 결과입니다. `teardown_succeeded` 이후에만 최종
`passed` 결정을 기록합니다. 정리 오류는 `cleanup_failed`를 만들고 진단을 위해 기본
검증 결과를 보존합니다. CLI는 0이 아닌 종료 코드를 반환하며, 정리가 검증될 때까지
정리되지 않은 리소스를 담당자가 지정된 인시던트로 관리합니다.

## 실패 처리

- **복원이 예산 초과** -> 어댑터가 복원 실패를 반환하고 검증기가 종료 결과를 기록하기 전에
  부분 서버 정리를 시도합니다.
- **잘못된 성공 응답** -> 인식 가능한 상태가 없는 HTTP 200 읽기는 암묵적인 실행 중 상태가
  아니라 복원 실패입니다.
- **무결성 불일치** -> 훈련은 실패 시 차단되고 구조화된 불일치를 감사에 보존한 뒤 복원 서버를
  삭제합니다.
- **스모크 쿼리 실패** -> 한정된 범위의 실패 검사 결과를 기록하고 서버를 삭제합니다.
- **정리 실패** -> `cleanup_failed`가 기본 결과를 보존하고 CLI는 0이 아닌 종료 코드를
  반환합니다. 담당자에게 알리고 해당 서버를 수동 삭제하세요. 격리 대상 그룹 자체는 의도적으로
  유지합니다.

## 비용 참고

격리된 PostgreSQL 서버에는 훈련 기간 동안 표준 Flexible Server 컴퓨팅 및 스토리지
요금이 발생합니다. 최초 구성인 Burstable B1ms + 32GB 스토리지 계층에서는 시간당
요금이 소액이지만, 정리를 건너뛰면 누적됩니다. 워크로드 태그 `purpose=dr-drill`에
대한 알림으로 남아 있는 복원 서버를 감지합니다.

## 관련 문서

- [phase-3-integrated-loop-ko.md § Deep DB-DR (stateful - 전용 설계)](../roadmap/phases/phase-3-integrated-loop-ko.md)
- [security-and-identity-ko.md](../roadmap/architecture/security-and-identity-ko.md)
- [DbDrVerifier 모듈 설명](../../services/core-control-plane/src/fdai/core/verticals/resilience/db_dr_verifier.py)
