---
title: Hub 배포 인수인계
translation_of: hub-lifecycle-deployment-handoff.md
translation_source_sha: 07905bf7762019abc40b01f3c0e87906b52c5fcc
translation_revised: 2026-10-27
---
# Hub 배포 인수인계

이 점검표를 사용하면 엔지니어의 터미널 기록에 의존하지 않고 앱 배포를 반복할 수 있습니다.
담당자, 보존할 입력, 관찰 가능한 결과와 자동화할 수 있는 기계적인 단계를 정리합니다.

> **범위:** 제한된 nginx 실제 시험과 로컬 범용 실행기 테스트는 서로 다른 근거입니다.
> 이 변경으로 기존 Hub나 Agent에 실행 묶음 확장이 설치되지는 않습니다.
> FDAI 전체의 실제 클라우드 검증은 별도 작업입니다. 이 문서의 명령은 배포 권한을 부여하지 않습니다.

## 이 문서에서 다루는 내용

nginx와 FDAI의 순서는 같습니다. 기반 시설 준비, 이미지 게시, 독립적인 카탈로그 승인,
등록, 소유권 승인, 설정 서명, 입력 배치, Plan 승인, Agent 실행, 독립적인 결과 관찰 순서입니다.
앱별 데이터는 바뀌지만 실행 엔진과 신뢰 경계는 바뀌지 않습니다.

기존 명령과 API의 전체 설명은 [운영자 가이드](hub-lifecycle-operator-guide-ko.md)를,
확장된 입력 계약은 [실행 묶음](../roadmap/deployment/lifecycle-runtime-bundles-ko.md)을 참조하세요.
HTTP 매니페스트의 이름만 바꿔 FDAI 전체 구성을 대신하지 마세요.

## 이전에 수동으로 연결한 단계는 누가 담당하나요?

| 단계와 책임 담당자 | 필요한 입력과 작업 | 비공개로 보존할 내용과 완료 근거 | 자동화할 수 있는 부분 |
|-------------------|--------------------|---------------------------------|----------------------|
| 1. 고객 기반 시설 담당자 | 정확한 대상, 비용, 보존과 정리 계획 승인. 네임스페이스, 저장소, DB와 신원 준비 | 검토한 기반 시설 계획, 초기화된 스키마, 네임스페이스와 신원 참조 | 기존 기반 시설 도구로 참조를 생성할 수 있지만 자기 변경을 승인할 수는 없습니다 |
| 2. Hub 네트워크 담당자 | 운영자 접속, Agent의 Hub 접속, Lifecycle의 Release 카탈로그 접속을 각각 확인 | 승인한 원본 주소 범위, 아웃바운드 원본, 수신 규칙 관찰 결과와 두 제품의 빌드 신원 | DNS, 경로, 수신 규칙과 API를 각각 사전 점검합니다. 네트워크 차단을 역할 확대로 해결하지 않습니다 |
| 3. 고객 신원 담당자 | 사용자 로그인과 Agent 페더레이션·`Agent.Access`를 별도로 연결. 기존 신원 키 유지 | 정확한 앱·권한 범위 연결, 페더레이션 주체와 네임스페이스 ServiceAccount | 검토할 초기 설정 기록을 생성합니다. 관리자 역할이나 광역 Graph 권한은 부여하지 않습니다 |
| 4. 공급자 release 담당자 | 불변 이미지 빌드, 정확한 매니페스트 바이트 서명, 등록·게시와 회수 상태 관리 | 소스·이미지 해시, 서명 검증, 채널·카탈로그 리비전과 고정 해시 | 빌드·서명·게시 파이프라인을 사용합니다. 고객 승인을 대신하지 않습니다 |
| 5. 고객 카탈로그 승인자 | 게시자 키와 정확한 카탈로그 고정 해시를 독립적으로 확보. 승인 후 가져오기 | 수락한 키 ID, 리비전, 고정 해시, 최신성과 가져오기 결과 | 공개 정보를 자동 전달·비교합니다. 다운로드했다는 이유만으로 신뢰하지 않습니다 |
| 6. 고객 초기 설정 담당자 | 설치 ID와 키 보존, 새 등록 요청 제출, 별도의 사람 승인 확보 | 공개키 ID, 등록 결정과 영속 설치 신원 | 기존 등록 명령을 사용합니다. 중단 후 이어가는 UI 연결은 아직 필요합니다 |
| 7. 고객 소유권 승인자 | 정확한 native 객체 범위와 개발 전환에서 사용할 모든 기존 종류·이름·UID 검토. `bootstrap-slot` dry-run 후 승인한 anchor 생성 실행. 증명 제출 후 별도 승인 | 승인, 정확한 기존 객체 목록, 범위 해시, anchor UID와 서명된 증명을 비공개 저장소에 보존 | `bootstrap-slot`과 `submit-native-proof`를 사용합니다. 증명 생성이 소유권 승인이나 워크로드 인수는 아닙니다 |
| 8. 고객 실행·설정 담당자 | 비공개 묶음, 기존 참조와 이미지 저장소 검토. 서명된 설정에 묶음 해시 고정 | 소유자만 접근하는 내부 정책, 서명된 설정 바이트, 키 ID와 정확한 해시 | 스키마 검증과 해시 계산을 자동화할 수 있습니다. 안내형 비공개 묶음 편집기는 아직 없습니다 |
| 9. 설치본 입력 담당자 | 검증한 release·설정 문서와 분리된 서명 쌍 전달. 이미지 미러링 | 원자적으로 배치한 파일과 독립적인 서명·해시 검증 | `stage-inputs`를 사용합니다. Plan이 있다고 파일이 자동 전송되지는 않습니다 |
| 10. 고객 실행 승인자 | 명시적인 실행 구간, 현재 설정·제약과 정확한 Plan 승인 지정 | 승인자, 원본 상태 해시, Plan 만료 시각과 확인 문구 | 기존 양식이 ID·해시를 생성합니다. 승인은 사람이 합니다 |
| 11. 설치본 실행 담당자 | 영속 상태와 클러스터 내부 인증을 사용해 승인된 유한 Agent 실행 시작 | Agent 접속, 보고, 실행 기록, 정상 상태와 중단 표식 | 검토한 유한 Job 구성을 사용합니다. 등록만으로 상주 실행이 시작되지는 않습니다 |
| 12. 앱 담당자 | 예상 워크로드와 앱 효과 독립 관찰. 회수·보류 상태 별도 처리 | 설치 버전, 컨트롤러 준비 상태, 독립적인 앱 결과와 복구 결과 | 읽기 전용 점검과 시간순 기록을 자동화합니다. 전달 성공이나 Pod 존재를 운영 성공으로 바꾸지 않습니다 |
| 13. 고객 환경 담당자 | 승인한 임시 Job·자원만 제거. 합의한 클러스터·상태·신원 유지와 지속 비용 확인 | UID 조건의 부재 검증, 보존 자원 목록과 책임 담당자 | 정리 계획과 보존 요약을 자동화합니다. 복구 상태나 신원은 지우지 않습니다 |

카탈로그 정보, 서명된 입력 전달, 이미지 가용성과 Agent 실행 일정을 구분하세요.
하나를 완료해도 나머지가 완료되지는 않습니다. 정상 클러스터는 Agent 실행의 증거가 아닙니다.

## 비공개 실행 입력 예

다음은 Deployment와 내부 Service 하나를 표현하는 합성 예입니다.
기존 `fdai.lifecycle-local-policy.v1` 문서의 `runtime_bundle` 객체로 넣습니다.
현재 사용자 소유의 비공개 디렉터리 안에 단일 링크의 일반 파일로 보관하고 권한은 0600으로 설정합니다.
공개 release 매니페스트나 Hub 업로드가 아닙니다.

```json
{
  "format": "fdai.application-runtime-bundle.v1",
  "product": "example-web",
  "namespace": "example-test",
  "objects": [
    {
      "entity_id": "application",
      "kind": "Deployment",
      "name": "frontend",
      "spec": {
        "replicas": 1,
        "template": {
          "spec": {
            "serviceAccountName": "frontend",
            "automountServiceAccountToken": false,
            "securityContext": {
              "runAsNonRoot": true,
              "seccompProfile": {"type": "RuntimeDefault"}
            },
            "containers": [{
              "name": "frontend",
              "image_component": "frontend",
              "ports": [{"name": "http", "containerPort": 8080}],
              "readinessProbe": {"httpGet": {"path": "/healthz", "port": "http"}},
              "resources": {
                "requests": {"cpu": "100m", "memory": "128Mi"},
                "limits": {"cpu": "1000m", "memory": "512Mi"}
              },
              "securityContext": {
                "runAsNonRoot": true,
                "allowPrivilegeEscalation": false,
                "readOnlyRootFilesystem": true,
                "capabilities": {"drop": ["ALL"]}
              }
            }]
          }
        }
      }
    },
    {
      "entity_id": "application",
      "kind": "Service",
      "name": "frontend",
      "spec": {"ports": [{"port": 80, "targetPort": "http"}]}
    }
  ]
}
```

내부 정책에서 `product`, `entity_ids`, `entity_components`, `component_images`와 승인한
`native_scope_digest`도 지정합니다. Entity의 이미지 구성 요소 집합은 sidecar와 초기화
컨테이너를 포함합니다. 반면 native `components`는 Deployment 객체 이름입니다.
선택적인 `service_components`는 Service가 필요한 Deployment만 지정합니다.
생략하면 모든 Deployment를 사용해 기존 범위를 보존합니다.
`scheduled_components`는 CronJob 객체 이름을 명시합니다.
묶음의 전체 종류·이름 목록은 별도로 승인한 native 범위와 정확히 같아야 합니다.

비공개 내용을 표시하지 않고 묶음의 고정 해시를 계산하려면 설치한 Agent의 판독기를 사용합니다.

```bash
python -c 'import sys; from pathlib import Path; from fdai_lifecycle_agent.cli import load_local_policy; print(load_local_policy(Path(sys.argv[1]))["runtime_bundle"].digest)' "$LOCAL_POLICY"
```

계산한 `sha256:<hex>`를 선택한 각 Entity의 서명된 설정에 `runtime_bundle_digest`로 지정합니다.
v2 실행 경로는 설정 해석 결과에서 이 고정 해시와 선택적인 `region`만 수락합니다.
실행 설정과 연결 값은 사용되지 않는 설정 키나 환경 변수의 직접 값이 아니라,
미리 준비한 ConfigMap·Secret 참조에 둡니다.
비공개 구성이나 참조 이름이 바뀌면 새 고정 해시를 검토하고 다시 서명합니다.

공급자의 `fdai.application-release.v2`는 `workloads` 대신
`components.<name>.image_digest`를 사용합니다. 불변 이미지, 제품·버전·소스·플랫폼과
선택적인 기존 스키마 정보를 전달하며 비공개 구성은 포함하지 않습니다.
게시와 입력 배치에서는 정확한 바이트의 분리된 서명과 기존 정규화 해시 규칙을 유지합니다.

## 워크로드를 변경하지 않고 상태 재구성

`generate-runtime-bundle`은 번들 옆에 소유자만 읽을 수 있는 인계 파일 세 개를 기록합니다.

| 파일 | 용도 |
|------|------|
| `workload-handoff-inventory.json` | 승인한 각 객체의 digest로 고정된 Terraform 주소, 정확한 `namespace/name` import ID, 렌더링 digest |
| `workload-handoff.tfvars.json` | 인계 루트에서 사용할 전체 Deployment, Service, CronJob, HorizontalPodAutoscaler 맵 |
| `workload-handoff-commands.txt` | 최초 import, 변경 없음 확인, forget 전용 해제, 되돌리기 import, 마지막 변경 없음 확인 명령 |

보존한 워크로드 상태를 사용할 수 없을 때만 이 경로를 사용합니다. 새로운 비공개 절대 로컬
backend 경로 하나를 준비하고 생성된 모든 명령에서 같은 경로를 사용합니다. 계획 JSON과 증적을
소유자 전용으로 유지하도록 먼저 `umask 077`을 설정합니다. 정확한 비공개 kubeconfig와 context는
별도로 제공합니다. 적용하기 전에 모든 `terraform show -json` 출력을
`verify-workload-handoff-plan`으로 검토합니다.

첫 import 계획에는 정확한 import 레코드와 `no-op` 작업만 포함할 수 있습니다. 이 계획을 적용한
다음 Terraform 상세 종료 코드가 0이고 `zero-change` 검증을 통과하는 계획을 확인합니다. 해제
계획에는 같은 digest 고정 목록의 `forget` 작업만 포함할 수 있습니다. 모든 `removed` 블록은
`destroy = false`이므로 적용해도 실행 중인 객체를 삭제하지 않고 상태 소유권만 해제합니다.
계획에 생성, 수정, 삭제, 교체, drift, 이동한 주소, 지연된 변경, 승인하지 않은 import ID가 있으면
계속 진행하지 않습니다.

되돌리기 전에 Agent의 조정 해제 증적을 보존합니다. 같은 import 루트, 입력 파일, backend 경로를
다시 사용합니다. 정확한 되돌리기 import 계획을 검증하고 적용한 다음 두 번째 변경 없음 계획을
요구합니다. 이 증적이 있어야 설치의 Hub 소유 표시를 해제할 수 있습니다. 상태 파일을 직접
편집하거나 `terraform state rm`으로 대신하지 않습니다.

## 혼합 범위의 기존 객체를 정확히 인수

명시적으로 승인한 `full-authority-development` 네이티브 범위에서만 이 전환을 사용합니다.
`native-approval.json`의 `scope`는 그대로 유지하고 `existing_resources`를 종류와 이름 순으로
추가합니다. 각 항목에는 현재 객체에서 읽은 정확한 `kind`, `name`, Kubernetes `uid`만
기록합니다. 객체가 없거나 삭제 중이거나 다른 필드 관리자가 소유하거나 생성한 실행 묶음
밖에 있으면 목록에 넣지 않습니다. `existing_resources`에서 생략한 범위 객체는 모두
없어야 합니다.

먼저 `--apply` 없이 `bootstrap-slot`을 실행합니다. anchor는 계속 생성 전용으로 유지하면서
기존 UID와 부재 집합을 검증합니다. 기존 네이티브 상태가 있으면 다시 만들지 않고 보존된
anchor와 증명을 검증합니다. 운영자가 그 증명을 수락한 뒤 새 Hub Plan을 확보합니다.
서명된 Plan의 `ownership_digests`에는 같은 선언 다이제스트가 있어야 합니다. 이 연결이
없는 Plan은 인수를 수행할 수 없습니다.

같은 비공개 승인과 영속 상태로 범위가 제한된 Agent 적용을 실행합니다. 사전 검사는 리소스
버전과 원래 매니페스트를 보존하고 모든 인수를 서버에서 사전 실행합니다. Hub가
`apply-started`를 수락하면 Agent는 인수한 객체를 하나씩 체크포인트에 기록하고 UID를
네이티브 상태에 저장하며, 승인에서 없다고 선언한 객체만 생성합니다. 인수 증적을
보존하세요. 비공개 목록을 Hub로 보내지 않으면서 승인, 수락된 소유권 선언, Plan, 렌더링
객체, UID와 리소스 버전을 연결합니다.

실행이 중단되면 같은 상태와 승인으로 다시 시작합니다. Agent는 정확한 anchor 표시와 UID만
인식하고, 인수한 사양은 보존한 버전으로 롤백하며 아직 인수하지 않은 객체는 바꾸지
않습니다. 새 Plan에서 남은 집합을 재시도할 수 있습니다. UID 충돌, 다른 필드 관리자,
기존이라고 선언했지만 사라진 객체, 부재 집합에 새로 나타난 객체가 있으면 다시 관찰하고
승인해야 합니다. 네이티브 상태를 편집하거나 `kubectl`로 레이블을 패치하거나 바뀐 UID에
이전 승인을 재사용하지 마세요.

설치된 이전 Entity를 전환하려면 `transition-native-scope`를 실행하기 전에 별도의 Hub 전환
승인을 준비하고 받아야 합니다. 인증된 `--hub-url`과 정확한 `--hub-scope`를 지정합니다.
장애에 안전한 로컬 커밋이 끝나면 이 명령은 다이제스트로 고정한 증적, 새 빈 상태와 승인된
전체 종류/이름/UID 목록을 Agent 워크로드 신원으로 자동 제출합니다. 반환된 Hub 완료 증적이
있어야 성공입니다. 다음 Plan을 요청하기 전에 이 증적을 확인하세요.

로컬 커밋 뒤 Hub 전송에 실패하면 어느 상태도 편집하지 말고 일반 상태 엔드포인트로 새 상태를
따로 제출하지 마세요. 같은 `transition-native-scope` 명령과 입력을 다시 사용합니다. 로컬
재시도는 원래 로컬 증적을 반환하고, Hub의 정확한 완료 재시도는 원래 Hub 증적을 반환합니다.
신뢰할 수 있는 Hub 호스트는 범위가 제한된 복구를 위해 같은 비공개 완료 문서와 실행을 담당한
Agent principal을 지정해 `fdai-lifecycle-hub complete-native-transition`을 사용할 수
있습니다. 바뀐 바이트, 다른 신원, 열린 Plan이나 부분적인 Entity 관리 상태는 충돌입니다.
관리 해제, 상태 기록, 새 관리 설정을 나누어 쓰는 근거가 아닙니다.

완료된 전환을 밀리초 단위 이전 시각 생성기가 만들었다면 Plan을 요청하기 전에 변경할 수
없는 로컬 전환 증적과 보존된 Hub 완료 증적을 비교합니다. 모든 정규 상태 필드가 같고, 로컬
상태와 증적이 같은 밀리초 시각을 사용하며, Hub 완료 감사가 같은 순간의 더 늦은
1밀리초 이하 값을 보존하고, Hub 상태가 아직 이전 밀리초 다이제스트를 가진 경우에만 조정을
사용합니다. Entity, 범위, UID, 아티팩트 목록, 상태, 스키마 개정이 바뀌었거나 시각 차이가
1밀리초보다 크면 이 절차를 사용하지 않습니다.

1. 범위가 제한된 polling을 중지하고 Hub에 열린 Plan이 없으며 Agent에 보고하지 않은 Plan이나
   `prepared`/`applying` 저널이 없는지 확인합니다. 로컬 전환 증적, Hub 완료 증적, 네이티브
   승인, 설치 공개 키, Hub 공개 키와 current-state 경로를 보존합니다.
2. `fdai-lifecycle-agent prepare-native-transition-reconciliation`에 `--state-dir`,
   `--current-state`, `--native-approval`, `--hub-completion-receipt`,
   `--installation-public-key`와 소유자 전용 `--destination`을 지정해 실행합니다. 이 명령은
   Agent 상태 잠금을 사용하며 아무 상태도 변경하지 않습니다.
3. 비공개 요청을 인증된 운영자 신원으로
   `POST /v1/installations/{installation_id}/native-transition-state-reconciliation-approval`에
   제출합니다. 반환된 서명 승인을 보존합니다. `409`는 중지 조건입니다. 시각 허용 범위를
   넓히거나 어느 증적도 편집하지 않습니다.
   4단계를 시작하기 전에 승인이 만료되고 Agent가 현재 상태를 변경하지 않았다면 같은 근거,
   설치 공개 키, 만료된 `--expired-hub-reconciliation-approval`, 새 비공개 대상 경로를
   지정해 `fdai-lifecycle-agent prepare-native-transition-reconciliation-renewal`을
   실행합니다. 갱신 요청을 같은 승인 경로에 제출하고 새로 반환된 승인을 사용합니다.
   이전 승인이 만료됐지만 사용되지 않았고 현재 Hub 상태와 모든 Agent 근거 필드가 바뀌지
   않았으며 같은 운영자가 제출하고 열린 Plan과 기존 갱신이 없을 때만 Hub가 수락합니다.
   준비 명령은 보존된 로컬 조정 대기, 롤백 또는 완료 기록이 있어도 중단합니다. 유효하거나
   이미 사용한 승인은 갱신하지 않습니다.
4. 같은 상태, 네이티브 승인, Hub 완료 증적, 설치 공개 키, 정확한 Hub 키 ID/세대와 공개 키,
   반환된 `--hub-reconciliation-approval`, 인증된 `--hub-url`과 `--hub-scope`, 원래
   Kubernetes context 또는 클러스터 내부 신원을 사용해
   `fdai-lifecycle-agent reconcile-native-transition-state`를 실행합니다.
5. 명령에서 `reported_state_digest`와 `reconciliation_receipt_digest`가 모두 반환되어야
   합니다. 소유자 전용 롤백 및 조정 증적 파일을 확인합니다. 전환 증적, 네이티브 상태와
   워크로드 저널은 바이트 단위로 바뀌지 않아야 합니다. Hub에서 다시 읽은 결과와 로컬
   current-state의 전체 정밀도 시각 및 다이제스트가 같아진 뒤에만 다음 Plan을 요청합니다.

대기 상태를 쓴 뒤 명령이 중단되면 정확히 같은 입력으로 다시 실행합니다. 명령은 재시도하기
전에 보존한 current-state 바이트를 복원하며, 이미 커밋된 Hub 쓰기는 같은 결과를 반환하는
완료로 처리합니다. 바뀐 요청, 다른 Agent 신원, 동시 Hub 상태 변경, 교체된 UID, 변경된 증적
또는 서로 다른 이전 조정은 충돌입니다. 다른 복구를 시도하지 말고 조사해야 합니다.

## 보이지 않는 도우미 없이 실행하기

1. 기존 가이드에 따라 설치 신원을 등록하고 승인합니다. 불완전한 초기 설정을 고치려고
   설치 키를 다시 생성하지 않습니다.
2. 현재 유효한 비공개 native 승인을 준비합니다. `fdai-lifecycle-agent bootstrap-slot`에
   `--installation-id`, `--state-dir`, `--local-policy`, `--current-state`, `--native-approval`,
   `--installation-key`와 `--in-cluster` 또는 명시적으로 고른 `--kube-context`를 지정합니다.
   기본값은 dry-run입니다. 별도로 승인한 생성에서만 `--apply`와 `--proof-output`을 추가합니다.
   `submit-native-proof`로 공개 증명을 전달하고 사람 승인을 받습니다.
   혼합 전환에서는 위에서 설명한 정확한 `existing_resources` 목록을 포함합니다. Bootstrap은
   계속 anchor만 생성하며, 서명된 Plan 실행이 객체를 인수합니다.
3. 가이드의 `stage-inputs` 명령으로 서명된 입력을 배치합니다. 미러링한 이미지 해시도 확인합니다.
4. 유효한 새 Plan을 확보합니다. 기본 `poll-once`는 Kubernetes를 로드하거나 실행 의도 기록을
   만들지 않고 승인 조건만 검증합니다. Kubernetes 서버 dry-run은 아닙니다.
5. 승인한 네임스페이스, 영속 상태, `--hub-auth workload-identity`와 정확한 `--hub-scope`를
   지정해 `poll --apply --in-cluster`로 승인한 유한 실행을 시작합니다.
   기존의 필수 신뢰·입력·native 승인 인자도 지정합니다.
   `poll --help`에서 최대 반복 횟수와 총 실행 시간 제한을 확인합니다.
   적용 모드는 실행 의도 기록·보고·변경 전에 서버 dry-run을 수행합니다.
6. Agent 결과와 워크로드 결과를 독립적으로 다시 읽습니다.
   첫 응답을 잃었다는 이유로 다른 Plan을 발급하지 않습니다.
   같은 영속 실행 기록과 전송 대기 보고를 사용해 재개합니다.

기존 HTTP RBAC 구성은 CronJob 권한을 부여하지 않습니다. 주기 작업 묶음에는 별도로 검토한
네임스페이스의 `batch/cronjobs` Role이 필요합니다.
[선택적 구성 예](../../lifecycle/agent/deploy/scheduled-runtime-rbac.yaml)를 참조하세요.
Secret 읽기, 신원 변경이나 클러스터 전체 권한은 부여하지 않습니다.
이를 적용하는 것은 별도 권한 변경이며 이 문서가 조용히 수행하는 단계가 아닙니다.

## FDAI에서는 무엇이 바뀌나요?

승인한 입력만 바뀝니다. 제품 지정, 불변 이미지 집합, 비공개 실행 묶음, 참조, native 객체 목록,
서명된 설정의 고정 해시와 독립적인 효과 점검입니다.
기존 AKS 구성은 백엔드·Console Deployment, 선택한 내부 Service, ClamAV sidecar·초기화,
CSI·ConfigMap·PVC 참조와 범위가 제한된 주기 작업으로 표현합니다.
DB 기반 시설, 기존 실행 신원과 초기화된 동일 스키마 DB는 사전 준비 사항입니다.
스키마를 바꾸는 마이그레이션과 지원하지 않는 구성 삭제는 사람 검토로 넘깁니다.

합성 테스트는 공통 실행과 복구 동작의 근거입니다.
실제 FDAI 통합, 모델, inventory나 앱 상태가 Azure에서 통과했다는 뜻은 아닙니다.
별도 시험 전에 실제 참조와 앱 관찰 항목을 준비하고 검증하세요.
실제 입력에 지원하지 않는 자원·보안·권한 효과가 필요하면 제품 이름을 바꾸거나
권한을 넓혀 우회하지 말고 공백을 검토합니다.

## 실패, 중단과 보존

- 네트워크 수신 차단, API 401/403, 로그인 만료와 백엔드 실패를 구분합니다.
  수신 차단은 UI가 뜨기 전에 발생할 수 있습니다. 역할이 아니라 승인한 원본·네트워크 경로를 고칩니다.
- v2 이미지나 설정 적용 실패 시 안전하게 검증할 수 있으면 기록한 구성을 복원합니다.
  스키마 변경과 선택한 기존 정상 객체의 제거는 쓰기 전에 차단합니다.
- 활성화됐을 가능성이 있는 CronJob의 복구는 보류합니다. 실행 일정을 정지하고 제한된 구성을
  복원하되, 복구를 검증되지 않은 상태로 기록하고 후속 적용을 중단합니다.
  정지했거나 사라진 구성만으로 작업이 실행되지 않았다고 증명할 수는 없습니다.
  승인된 복구 전에 기존 작업과 영속 효과를 독립적으로 확인합니다.
  재시도만을 위해 중단 표식을 삭제하지 않습니다.
- native 생성 결과가 불명확해도 인수 권한은 생기지 않습니다. UID 근거와 대기 상태를 보존합니다.
  같은 설치 키와 상태로 재개하며 기존 객체를 이름만으로 덮어쓰지 않습니다.
  지원되는 개발 인수에는 정확한 로컬 종류·이름·UID 승인과 Hub가 서명한 소유권
  다이제스트가 필요합니다. 롤백은 이전 사양을 복원하면서 소유 표시를 유지합니다.
  별도의 조정 해제와 Terraform 가져오기 절차만 소유권을 되돌릴 수 있습니다.
- 환경 보존, 실행 일정, 로컬 native 승인 유효 기간과 Plan 만료는 서로 다른 한도입니다.
  AKS를 계속 켜 두어도 지속적인 무제한 변경 권한이 생기지는 않습니다.
- Agent 영속 저장소, 설치 신원과 정확한 근거를 보존합니다.
  정리에는 명시적인 대상·UID 목록과 독립적인 부재 확인이 필요합니다. 보존 기반 시설 비용도 확인합니다.

## 다음 단계

| 알아볼 내용 | 문서 |
|-------------|------|
| 지원되는 명령·API 순서 | [Hub 운영자 가이드](hub-lifecycle-operator-guide-ko.md) |
| 계약, 설계 비판과 구현 상태 | [애플리케이션 실행 묶음](../roadmap/deployment/lifecycle-runtime-bundles-ko.md) |
| 우선순위가 있는 UI·절차 개선 목록 | [운영 경험 개선](hub-lifecycle-operator-experience-ko.md) |
