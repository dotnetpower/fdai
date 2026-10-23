---
title: ADR-0004 개발 권한을 위한 로컬 격리 executor 주체
translation_of: 0004-local-isolated-executor-principal.md
translation_source_sha: 40d10f962f54606f8728f5bd4c599d2b3e3a1d3b
translation_revised: 2026-10-22
---
# ADR-0004: 개발 권한을 위한 로컬 격리 executor 주체

이 기록은 로컬 실행 venue가 [full-authority 개발 프로파일](../../decisioning/operator-governance-profiles-ko.md)을
위한 전용 executor 신원을 별도로 가질 수 있게 합니다. executor 신원은 Owner, Console, Core 프로세스와
분리된 상태로 유지됩니다.

## 상태

**제안됨:** 2026-10-22. 설계 전용입니다. 이 기록에 나온 코드, 구성, Azure 신원은 아직 구현되지 않았습니다.

## 배경

full-authority 개발 프로파일은 Owner 주체와 executor 주체가 서로 달라야 합니다. 현재는 배포된 런타임만
executor 신원을 가집니다.

- 선택 입력인 `--development-authority-profile`은 소스 AKS 배포에서만 허용되며, 이 배포는 관리형 워크로드
  ID에서 executor를 도출합니다.
- 로컬 격리 Executor는 `FDAI_ISOLATED_EXECUTOR_DEPLOYED=0`으로 실행되며 자체 Azure 주체가 없습니다. 로컬
  Console과 Operator API는 설계상 executor 신원을 받지 않습니다.
- 로컬 Azure 접근은 운영자의 Azure CLI 신원을 사용합니다. 이 신원이 Owner이므로 executor를 겸할 수 없습니다.

그 결과 실제 Azure 변경, 독립 효과 관측, 롤백이 필요한 검증은 모두 배포된 설치에서 해야 합니다. 프로덕션에는
맞는 규칙입니다. 그러나 Owner가 이미 통제하는 일회용 개발 범위에서는 프로비저닝에 몇 시간과 비용이 들고
수정 루프도 느려집니다.

## 결정

다음 조건을 **모두** 만족할 때에 한해 FDAI는 **전용 로컬 executor 주체** 하나를 로컬 격리 Executor
프로세스에 바인딩할 수 있습니다.

1. 선택된 승인 프로파일이 정확하고 현재 유효하며 만료되는 범위를 가진 `full-authority-development`입니다.
   `single-operator-production`을 포함한 프로덕션 프로파일은 로컬 executor 주체를 사용하지 않습니다.
2. 주체는 해당 프로파일을 위해 만든 전용 Microsoft Entra 서비스 주체입니다. Owner, 사람, observer, 다른
   설치와 공유하는 주체가 아니어야 합니다. 프로파일의 `executor_principal`이 이 주체의 object ID를 가리킵니다.
3. 자격 증명은 클라이언트 인증서입니다. 개인 키는 로컬에서 생성해 소유자 전용 권한으로 저장하고, 격리
   Executor 프로세스만 읽을 수 있습니다. 키는 저장소, 명령줄, 환경 변수, 로그, 채팅, 작업 출력에 나타나지
   않습니다. 클라이언트 비밀값은 허용하지 않습니다.
4. Azure 역할 할당은 프로파일 범위에 명시된 리소스 그룹으로 제한합니다. 각 할당은 등록된 `ActionType`에
   필요한 최소 역할만 가집니다. 구독 범위나 테넌트 범위 할당은 시작 시 실패합니다.
5. 인증서와 모든 할당은 프로파일의 `valid_until`보다 늦게 만료되지 않습니다. 만료, 프로파일 해제,
   readback 실패는 주체를 폐기합니다.

### 바뀌지 않는 경계

- Core, Operator API, Console은 공개 주체 식별자만 가집니다. 이 주체의 토큰은 격리 Executor만 얻습니다.
- executor는 기존 경로를 모두 마친 뒤에만 동작합니다. 스키마 검증된 버스 요청, 준비된 개발 바인딩, 정확한
  Owner 확인, 7가지 안전장치, 서버가 발급한 dry-run digest입니다. 이 주체는 승인, 승격, 모드 변경 권한을
  주지 않습니다.
- 독립 효과 관측은 별도의 읽기 신원을 사용합니다. executor는 자신의 효과를 관측할 수 없습니다.
- `FDAI_EXECUTION_VENUE=local`의 의미는 그대로입니다. [ADR-0002](0002-independent-runtime-axes-ko.md)의 증거
  프로파일, 액션 수명 주기, 사람 신원 축은 계속 독립입니다.

### 시작 시 검증

로컬 런타임은 다음을 live readback으로 증명하지 못하면 fail closed합니다.

- 주체가 존재하고 Owner 및 observer와 다릅니다.
- 역할 할당이 프로파일 범위와 등록된 액션의 부분집합입니다.
- 인증서 지문이 프로파일 기록과 일치하고 만료되지 않았습니다.
- 이 주체에 다른 자격 증명이 구성되어 있지 않습니다.

### 수명 주기

배포 CLI 명령이 주체를 생성, 교체, 폐기합니다. 생성 시에는 object ID, 지문, 범위 digest, 만료 시각만 비공개
영수증에 기록합니다. 폐기는 역할 할당을 먼저 제거한 뒤 주체를 비활성화하고 둘 다 readback합니다.

## 대안

| 선택지 | 결과 |
|--------|------|
| 배포 전용 executor (현재) | 프로덕션과 관리형 ID가 필요한 설치의 기본값으로 유지합니다. 기준 동작입니다. |
| Azure CLI 신원을 executor로 재사용 | 기각. Owner와 같아져 직무 분리가 사라집니다. |
| 클라이언트 비밀값 자격 증명 | 기각. 비밀값이 로그와 환경 변수에 새기 쉽습니다. |
| 로컬 Core가 배포된 development operations gateway를 호출 | 가능한 대안. 배포된 gateway와 Owner와 다른 호출자 신원이 필요해 배포를 없애지 못합니다. |
| 로컬 프로세스의 workload identity federation | 불가. 노트북 프로세스에는 증명 가능한 워크로드 신원이 없습니다. |

## 결과

- **긍정적:** 배포된 설치 없이도 개발 범위에서 변경, 효과 검증, 롤백 주기를 끝까지 실행할 수 있습니다.
- **부정적:** 로컬 키가 탈취되면 만료 전까지 프로파일 범위 안에서 동작할 수 있습니다. 제한된 범위, 짧은 만료,
  소유자 전용 키 파일, 프로세스 격리로 노출을 줄입니다.
- **운영:** Owner가 CLI로 주체를 생성, 교체, 폐기해야 합니다.
- **증거:** 로컬 주기는 개발 프로파일의 변경 경로를 증명합니다. 이슈가 명시적으로 요구하는 배포 관리형 ID
  증거를 대체하지 않습니다.

## 구현 단계

각 단계는 shadow 모드를 유지하며 자체 집중 테스트가 필요합니다.

1. 범위, 만료, 상호 구별성 검사를 포함한 로컬 executor 주체 기록의 계약과 검증기.
2. 비공개 영수증과 readback을 갖춘 배포 CLI 생성, 교체, 폐기 명령.
3. 격리 Executor의 인증서 자격 증명과 시작 시 readback 게이트.
4. 배포 경로와 같은 fail-closed 검사를 거치는 로컬 venue의 프로파일 선택.
5. 각 거부 사례의 집중 테스트: Owner와 executor 동일, 넓은 범위, 누락된 할당, 만료되었거나 불일치하는
   인증서, 추가 자격 증명, 프로덕션 프로파일.
