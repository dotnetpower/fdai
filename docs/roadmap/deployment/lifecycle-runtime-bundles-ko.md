---
title: 애플리케이션 실행 묶음
translation_of: lifecycle-runtime-bundles.md
translation_source_sha: abfb9f5caef3a377ffc2c4c577ee7cfb7f6b6c1a
translation_revised: 2026-10-24
---
# 애플리케이션 실행 묶음

이 설계는 공통 Lifecycle Agent를 제한된 HTTP 시험보다 넓은 범위에 적용합니다.
앱마다 실행기를 추가하는 대신, 독립적으로 검토한 설치 내부 실행 묶음과 서명된 이미지를 입력합니다.

> **상태:** 로컬 구현과 집중 검증을 진행했습니다. 자세한 상태는 연결된 구현 기록을 참조하세요.
> FDAI 전체 설치를 검증했거나 실제 배포를
> 승인했다는 의미는 아닙니다.
>
> **범위:** 기존 namespace, 신원, 저장소, 설정 참조와 초기화된 데이터베이스가 필요합니다.
> 기반 시설 생성, 권한 부여와 스키마를 바꾸는 마이그레이션은 별도 배포·승인 절차를 유지합니다.

## 설계 요약

모든 앱에서 release 게시, 독립적인 catalog 승인, 등록, 소유권 확인, 서명된 설정,
Plan 검증, dry-run, 적용, 복구와 보고 순서를 동일하게 사용합니다.
앱별 차이는 제품 이름에 따른 코드 분기가 아니라 이미지와 비공개 검토 입력에 둡니다.

| 입력 | 생성 담당 | 소비자 | 신뢰 경계 |
|------|-----------|--------|-----------|
| `fdai.application-release.v1` | 공급자 | 두 Hub와 Agent | 기존의 제한된 HTTP 계약을 유지합니다 |
| `fdai.application-release.v2` | 공급자 | 두 Hub와 Agent | 서명된 불변 component 이미지이며 비공개 Pod 설정은 포함하지 않습니다 |
| `fdai.application-runtime-bundle.v1` | 고객 배포 담당 | Agent만 | namespace, 객체, 참조와 Pod 구성을 독립적으로 승인합니다 |
| `runtime_bundle_digest` | 고객 설정 서명 담당 | Agent | 서명된 설정이 검토한 내부 묶음을 고정하며, 묶음 자체나 권한을 공급하지 않습니다 |
| Native 생성 승인 | 고객 운영자 | Agent와 소유권 승인 경로 | 정확한 객체 종류·이름과 기존 UID 조건의 생성·복구 경계를 유지합니다 |

설치 내부 정책과 Hub 설치 설정이 각각 같은 product를 지정합니다. 비공개 묶음도
이를 지정합니다. 묶음, package나 Plan이 이 독립적인 지정을 바꿀 수는 없습니다.

## Release와 비공개 실행 계약

Release v2는 `product`, `release_version`, `source_commit`, `platform_tag`와 선택적인
설정·DB 스키마 정보를 유지합니다. `components`에는 이름을 가진 레코드 1-64개가 있으며,
각 레코드는 `image_digest`만 포함합니다. v1의 `workloads`와 달리 sidecar, 초기화
컨테이너나 주기 작업을 HTTP 서비스로 표현하지 않습니다. 알 수 없는 필드, 잘못된 이름·digest,
중복 JSON 키, 유한하지 않은 값과 기존 크기 제한 위반은 계속 차단합니다.

설치 내부 묶음은 형식, product, namespace와 크기가 제한된 객체 목록을 포함합니다.
각 객체는 Entity, 종류, 이름과 비공개 구성을 지정합니다. 지원 범위는 Deployment,
ClusterIP Service, 실행 범위가 제한된 CronJob, 범위가 제한된 HorizontalPodAutoscaler입니다. 일반·초기화 컨테이너는 저장소,
태그나 이미지 주소가 아닌 승인된 release component를 지정합니다. Agent는 기존의
독립적으로 승인된 Entity/component/저장소 대응 관계로 실제 이미지를 결정합니다.

묶음은 검토한 ServiceAccount, 자원 제한, non-root sidecar, 초기화 컨테이너,
기존 CSI/PVC/ConfigMap 참조와 임시 쓰기 디렉터리를 표현합니다.
namespace, 역할, 신원, Secret, PVC나 SecretProviderClass는 생성하지 않습니다.
환경 변수는 비밀이나 연결 값을 직접 담지 않고 참조를 사용합니다.
호스트 namespace·경로, 특권 컨테이너, 추가 capability, root 실행과 무제한 자원은 지원하지 않습니다.

선택한 각 Entity의 서명된 설정은 내부 묶음의 정확한 정규화 digest를 고정합니다.
묶음, 지정이나 스키마 호환성이 없거나 맞지 않으면 적용 전에 중단합니다.
참조 구문은 로컬에서 검증합니다. 구문 점검만으로 Secret, ConfigMap, PVC나 CSI 입력의
존재·접근 권한을 증명하지는 않습니다. 서버 승인과 범위가 제한된 준비 상태 확인에서
누락 입력이 드러납니다. 내용을 검사하기 위한 Secret 읽기 권한은 Agent에 부여하지 않습니다.
비공개 실행 구성은 설치 내부의 보호된 저장소에 보관하며 보고나 Hub 정보로 보내지 않습니다.
공개 설정은 참조 이름을 드러내지 않고 digest만 포함할 수 있습니다.

## 자동 확장 Deployment

HorizontalPodAutoscaler는 같은 Entity의 같은 이름 Deployment를 가리키는 제한된 객체입니다.
`minReplicas`와 `maxReplicas`는 1에서 10 사이이고, `Utilization` 목표(1~100)를 가진 `Resource`
지표(`cpu` 또는 `memory`)를 하나 또는 두 개 둡니다. behavior 정책, 사용자 지정·외부 지표, 묶음
밖의 대상은 거부합니다.

복제본 수는 autoscaler가 소유합니다. 따라서 autoscaler가 있는 Deployment는 `replicas`를 생략하고,
`replicas`를 생략한 Deployment는 autoscaler가 있어야 하며 둘 다 고정하면 거부합니다. 렌더러는
`scaleTargetRef`를 같은 이름의 Deployment에 묶고 Deployment 다음에 autoscaler를 적용합니다.
Deployment spec을 교체하는 업데이트는 live 복제본 수를 1로 되돌리지 않고 유지합니다. 롤아웃 확인은
컨트롤러가 보고한 복제본 수를 따르며 0일 때는 완료로 보지 않습니다. 네이티브 범위는
`autoscaled_components`로 autoscaler를 묶고, 비어 있으면 생략하므로 기존 범위 digest와 승인은
바뀌지 않습니다. Agent 역할에는 필요한 `autoscaling` `horizontalpodautoscalers` 동사만 추가합니다.

## 설치 binding

컨테이너 환경 변수는 정확히 하나의 출처를 가집니다. 기존 `valueFrom` 참조, 크기가 제한된 `value`
리터럴, 또는 `binding` 키입니다. `binding`은 설치 소유자가 같은 owner-only 로컬 정책의 비공개
`installation_binding` 객체(`format: fdai.installation-binding.v1`, 최대 128개 키의 맵)에 제공하는
값을 가리킵니다. 인프라 에이전트가 Terraform 출력에서 이 객체를 기록하며, 이 문서는 읽는 쪽만
소유합니다.

binding 키는 소문자 식별자입니다. 값과 리터럴은 출력 가능한 1~1024자이며 자격 증명처럼 보이면
안 됩니다. userinfo가 있는 URL, `Password=`, `AccountKey=`, `SharedAccessKey=`, PEM 헤더는 거부합니다.
자격 증명을 뜻하는 이름(secret, password, token, DSN, key, signing 등)의 변수는 Secret 참조만
받으며 리터럴이나 binding은 받지 않습니다. Agent는 묶음이 참조하지 않는 binding 키와 binding에
없는 참조 키를 정책 로드와 렌더에서 모두 거부하고, 고정된 메시지로 값을 노출하지 않습니다.

값은 렌더 시점에 일반 환경 값으로 풀리며 묶음에 포함되지 않습니다. 고정한 묶음 digest는 리터럴과
binding 키 이름을 포함하므로 참조를 바꾸면 pin이 바뀌고 설치 로컬 값을 바꾸면 바뀌지 않습니다.
configuration 키 출처는 여기서 구현하지 않았고 [#2471](https://github.com/dotnetpower/fdai/issues/2471)에
남아 있습니다.

## Native 소유권과 실행 동작

기존 native 범위의 직렬화 형태, digest와 Deployment/Service 집합은 그대로 유지합니다.
새로 승인한 범위에만 명시적인 추가 자원 레코드로 CronJob을 포함합니다.
`service_components`로 Service가 필요한 Deployment만 명시할 수 있어
작업자에 불필요한 Service를 만들지 않아도 됩니다. 생략하면 기존의 전체 Service 범위를 유지합니다.
이 레코드도 digest로 고정하며 release나 다운로드한 묶음에서 추론하지 않습니다.
확장된 비공개 범위를 모르는 구버전은 범위를 넓히지 않고 입력을 차단합니다.

모든 객체에 기존 anchor 소유권, 정확한 namespace, Entity 귀속, 최초 생성 전용 쓰기,
보존한 UID/resourceVersion 조건의 갱신과 UID 조건의 삭제를 적용합니다.
CronJob의 Pod 구성에도 Deployment와 같은 범위 격리 label을 넣습니다.
새 종류를 지원해도 기존 자원을 임의로 인수하거나 생성된 Job을 이름만으로 변경하지 않습니다.

묶음에서 만든 객체도 같은 비공개 영속 journal과 전송 대기 보고 저장소를 사용합니다.
서버 dry-run을 완료한 다음 실행 의도를 기록하고 `apply-started`를 보고합니다.
Deployment가 준비된 후 주기 작업을 활성화합니다. 주기 작업은 실행 기한,
동시 실행 차단과 재시도·기록 보존 제한을 갖습니다.
복구는 기록된 구성을 복원하고 새로 생성했다고 증명한 객체만 제거합니다.
생성 결과가 불분명하거나 복구에 실패하거나 부작용을 입증할 수 없으면 사람 검토로 넘깁니다.
활성화됐을 가능성이 있는 주기 작업의 복구에서는 보수적으로 일정을 정지하고 실행을 중단합니다.
현재 정지나 부재만으로 이전 작업이 실행되지 않았다고 증명할 수는 없습니다.
실행 구성을 복원해도 영속 작업 효과를 자동으로 되돌렸다는 의미는 아닙니다.

구성 설치와 Pod 준비 상태만으로 FDAI 탐지, inventory, 모델 연결이나 주기 작업의
운영 효과가 준비됐다고 판단하지 않습니다. 앱별 독립 관찰은 입력·근거 작업으로 남기며,
엔진이 운영 성공 증적을 만들어 내지는 않습니다.

## 설계 비판과 수정

| 초기 방안 | 문제 | 수정 결정 |
|-----------|------|-----------|
| HTTP 시험의 이름을 FDAI로 변경 | 이미지만으로 설정, 신원, sidecar와 주기 작업을 표현하지 못합니다 | 앱에 종속되지 않는 component 형식과 비공개 실행 계약을 추가합니다 |
| Hub Plan에서 임의 Kubernetes YAML 수락 | 공급자나 전송 경로가 설치 권한과 비공개 구성을 공급하게 됩니다 | 독립적으로 준비한 내부 묶음만 사용하며 서명된 설정은 이를 고정할 뿐 공급하지 않습니다 |
| 기존 v1 매니페스트에 필드 추가 | 기존의 엄격한 판독기와 HTTP 의미가 모호해집니다 | v2 이미지 component 계약을 분리하고 v1의 바이트·digest 동작을 보존합니다 |
| 호환성을 위해 root 이미지나 넓은 역할 사용 | 실행 구성을 표현하는 대신 보안·권한을 바꿉니다 | 제한된 Pod 보안과 기존에 승인한 신원을 유지합니다 |
| DB revision을 마이그레이션 권한으로 간주 | 실행 구성 복구로 임의의 영속 변경을 되돌릴 수 없습니다 | 같은 스키마만 지원하며 DB 준비·스키마 변경은 별도로 관리합니다 |
| CronJob 구성 설치를 작업 성공으로 간주 | 설치 정보로 운영 효과를 검증하지 못합니다 | 설치 범위를 보고하고 별도 작업·효과 근거를 요구합니다 |
| 새 묶음에 없는 객체 자동 제거 | 삭제와 실행 중인 작업의 효과에는 별도 승인·복구 설계가 필요합니다 | 지원하지 않는 구성 제거는 방치하거나 자동 삭제하지 않고 차단합니다 |

## 완료 기준

- [ ] 기존 HTTP v1과 legacy runtime 경로의 동작과 서명을 유지합니다.
- [ ] 두 Hub가 기존 catalog 경로로 v2 component release를 게시·가져옵니다.
- [ ] 같은 Agent 진입점이 제품별 코드 분기 없이 nginx와 FDAI 전체 형태의 입력을 처리합니다.
- [ ] 내부 묶음/product/namespace/component/digest 불일치를 변경 전에 차단합니다.
- [ ] 비공개 참조와 설정 값을 보고와 공개 정보에 포함하지 않습니다.
- [ ] 새 객체 종류에도 native 소유권, 충돌, UID 교체, 복구, 재시작과 중복 Plan 검증을 적용합니다.
- [ ] 실제 FDAI의 서비스, sidecar, 초기화와 주기 작업을 비공개 입력으로 표현하며,
  기존 기반 시설과 스키마 전제 조건을 명시합니다.
- [ ] 지원하지 않는 스키마 변경, 구성 제거나 입증하지 못한 복구는 실행을 차단합니다.
- [ ] 집중 타입·lint·동작 검증을 통과하며 실제 클라우드 검증은 별도로 유지합니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 구현 상태와 남은 작업 | [구현 기록](../../roadmap-implementation/deployment/lifecycle-runtime-bundles.md) |
| 담당자, 입력과 복구 | [배포 인수인계](../../runbooks/hub-lifecycle-deployment-handoff-ko.md) |
| 공통 절차와 소유권 | [Hub 관리 수명 주기](hub-managed-lifecycle-ko.md) |
| 매니페스트 게시와 회수 | [Release와 채널](lifecycle-releases-and-channels-ko.md) |
| 기존 운영자 단계 | [Hub 운영 안내](../../runbooks/hub-lifecycle-operator-guide-ko.md) |
| 기반 시설과 스키마 준비 | [소스 배포](source-deployment-ko.md) |
