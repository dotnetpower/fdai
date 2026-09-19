---
translation_of: existing-container-apps-service-update.md
translation_source_sha: 8e86a7192cca23af0f8bb3416091593195a2292f
translation_revised: 2026-09-19
---
# 기존 Container Apps 서비스 업데이트

이 문서는 기존 개발 Azure Container Apps 설치에서 서비스 하나를 업데이트하는 정확한 플랜 복구
경로를 정의합니다. 공용 이미지 검증, 비공개 계획, 사람 승인, Managed Identity 실행, 롤백 및 효과
검증을 서로 다른 단계로 유지합니다.

> **범위:** 구현된 경로는 기존 `dev` Operator 서비스만 업데이트합니다. GitHub Actions 테넌트
> 배포를 복원하거나 런타임을 마이그레이션하거나 `initial-cutover`를 승인하지 않습니다.

## 설계 개요

공용 소스와 OCI 출처 확인에는 외부 조정기를 사용합니다. 비공개 Terraform 상태, Azure Resource
Manager readback, 저장된 플랜 적용 및 복구에만 적격한 내부 배포 호스트를 사용합니다. 이 경로는
`manual_operator_update.py`를 사용하며 Container Apps 이미지를 직접 업데이트하지 않습니다.

```text
외부 조정기: 이미지 증명 -> 콘텐츠에 결속된 증적 보존
내부 호스트: 입력 복원 -> 정확한 Terraform 플랜 검증 및 저장
활성 Azure 사용자: 호스트 밖에서 정확한 검토 승인
내부 호스트 UAMI: 실행 전 기록 -> 저장 플랜 적용 -> 검증 또는 롤백 revision 복사
```

## 입력 복구

호스트는 기존 Operator Container App과 공유 플랫폼 Terraform 출력을 읽습니다.
`recover_operator_tfvars.py`는 시크릿 값을 읽지 않고 현재 서비스 입력을 재구성합니다.

- **현재 서비스 상태:** 워크로드 신원, 시크릿이 아닌 환경 값, Key Vault 참조, probe, scale,
  태그, RBAC, callback 설정 및 롤백 이미지를 보존합니다.
- **플랫폼 소유권:** 현재 플랫폼 상태에서 Container Apps 환경, 레지스트리, Kafka, 리소스 그룹
  및 Cost Governance 가명화 시크릿 참조를 갱신합니다.
- **Peer 격리:** 복구 입력에서 별도 상태를 사용하는 채널 edge를 제외하고 주 Operator Container
  App만 대상으로 지정합니다. 다른 리소스 변경은 플랜 가드가 차단합니다.
- **안전한 차단:** 라이브 바인딩과 플랫폼 바인딩이 다르거나 신원이 없거나 시크릿 참조가 잘못됐거나
  현재 이미지가 digest에 고정되지 않으면 중단합니다.

## 정확한 플랜과 승인

공급자가 호스팅하는 GitHub 인증을 사용해 외부 조정기에서 `attest`를 실행합니다. 소유자만 읽을
수 있는 증적과 일반 대상 매니페스트만 감사 가능한 호스트 접근 경로로 전송합니다. 내부 호스트의
`plan`은 보호된 `origin/main`을 확인하고 정확한 배포 UAMI로 로그인한 뒤 기존 플랫폼과 서비스
backend를 초기화하고 리소스 하나에 대해 20분 동안 유효한 저장 Terraform 플랜을 만듭니다.

활성 Azure 사용자는 실행 호스트 밖에서 `approve`를 실행합니다. 승인은 Entra 사용자 object ID,
대상, 검토 digest, 플랜 digest 및 만료 시각을 결속합니다. 적용에는 서로 다른 배포 UAMI principal이
필요하며 소스, 대상, 플랜 바이트, 플랜 projection, 승인 또는 롤백 기준이 바뀌면 차단합니다.

수동 조정기는 배포 호스트의 Python 3.10 런타임을 지원합니다. UTC 기록은 복구 중에 더 새로운
인터프리터를 요구하지 않고 표준 라이브러리의 호환 표면을 사용합니다.

### 플랫폼 선행조건

기존 플랫폼 상태가 Cost Governance 가명화 키보다 오래된 경우
`manual_operator_platform.py`는 같은 `fdai-dev.tfstate` backend에 별도 저장 플랜을 준비합니다.
집중 Terraform root는 32바이트 임의 ID, Key Vault 시크릿 및 정확한 Operator
`Key Vault Secrets User` 할당에 대한 표준 count 주소를 선언합니다. 세 리소스 모두 표준 플랫폼
root와 같은 정의 및 주소를 사용하고 같은 AzureRM 및 Random 공급자 버전을 고정합니다.

플랫폼 가드는 세 create 작업만 허용하고 drift, deferred 변경, update, delete, replacement 또는
다른 주소를 차단합니다. 적용은 먼저 실행 전 기록을 쓴 뒤 정확한 시크릿 참조와 역할 할당을
독립적으로 읽습니다. 이 추가 선행조건은 상태를 앞으로만 진행합니다. 결과가 불명확한 적용은
권위 있는 검증을 위해 실행 전 기록을 유지하며 자동으로 반복하거나 삭제하지 않습니다. Operator
서비스 플랜은 선행조건 증적이 완료된 후에만 시작합니다.

## 적용과 복구

적용은 저장된 플랜으로 `terraform apply`를 호출하기 전에 소유자 전용 실행 전 기록을 씁니다.
성공하려면 이미지가 검토한 digest와 일치하는 새로운 ready revision이 필요합니다. 전달 또는
Terraform 종료만으로 성공으로 판단하지 않습니다.

적용이나 readback이 실패하면 캡처한 이전 revision을 새로운 revision으로 복사하고 복사된
revision이 캡처한 이미지로 ready 상태가 되는지 확인합니다. 실행 전 기록은 시도한 효과의 근거로
남습니다. 기존 실행 전 기록이 있으면 권위 있는 복구에서 불확실한 결과를 처리할 때까지 다른
적용을 차단합니다.

## 운영 종료 조건

집중 조정기 테스트, Ruff, 설계 라우트 검사 및 문서 검사가 통과하면 소스 구현이 완료됩니다.
운영 검증에는 정확히 병합된 소스, 검토된 플랫폼 선행 플랜과 서비스 플랜, 배포 이미지와 정상
revision readback, 변경되지 않은 peer 근거, 서비스 상태 및 인증된 Console Dashboard 확인이
추가로 필요합니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 런타임 선택과 상태 소유권 | [런타임 배포 프로파일](runtime-deployment-profiles-ko.md) |
| 비공개 호스트 배포 규칙 | [프로비저닝 실행 프로파일](provisioning-execution-profiles-ko.md) |
| 구현 진행 상황 | [기존 Container Apps 서비스 업데이트 구현](../../roadmap-implementation/deployment/existing-container-apps-service-update.md) |
