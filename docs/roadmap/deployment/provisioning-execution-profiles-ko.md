---
title: Provisioning 실행 Profile
translation_of: provisioning-execution-profiles.md
translation_source_sha: 87c28a8af4f94ebd48591cb2023acc48b35da734
translation_revised: 2026-09-16
---
# 프로비저닝 실행 프로파일

이 문서는 계획된 `fdaictl` 배포판이 프로비저닝 호스트, connectivity 모드, 명령 전송 계층, 접근 경로를
선택하는 방법을 정의합니다. 또한 Terraform이 infrastructure 또는 역할 배정을 변경하기
전에 적용되는 사람 승인과 workload-identity 경계를 정의합니다.

> **범위:** Azure가 구현된 대상입니다. 이 프로파일은 Terraform 정본을 변경하거나
> 비공개 엔드포인트를 우회하는 로컬 대체 경로를 허용하지 않습니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| AKS 기본 배포와 후속 상세 비공개 네트워크 프로비저닝 | not-started | 아래 두 단계 계약이며 새로운 실행 검증 근거는 없음 | 일반 PC에서 미리 구축한 내부 인프라 없이 AKS 기본 흐름을 시작할 수 있습니다. API Server VNet Integration, 명시적 단계 선택, 기본 가동 검증, Console 네트워크 요청과 재개 가능한 보호 실행은 구현 및 전체 경로 검증이 필요합니다. |
| 읽기 전용 점검 및 프로파일 초기화 명령 | implemented | `packages/deployment-cli`, 집중 프로필, 대상, 도구, 제품화 검사 | 전용 배포판이 `fdaictl`을 등록하고 비공개 대상 연결 프로필을 쓰며 실행 호스트 근거가 있을 때까지 검토 상태를 반환합니다. |
| 관리 VM, 비공개 백엔드 및 수동 배포 호스트 | implemented | `infra/bootstrap/`, standalone 배포 모듈 및 집중 bootstrap 테스트 | 영속 VNet 호스트, workload identity, 비공개 상태, 정확한 계획 및 애플리케이션 적용이 GitHub Actions 없이 실행됩니다. |
| 신규 구독 로컬 조정기 | implemented | `fdaictl provision azure`, `fdai-up.sh`, 서명 키트, 기반 계층, Bastion, 관리 호스트, 승인, 라이선스, 마이그레이션 및 수렴 모듈과 라우팅된 수명 주기 테스트 | 하나의 `dev` 프로세스가 활성 Azure CLI 사용자에서 대상을 결정하고 상태 변경 전이를 직렬로 유지합니다. 대상 환경 배포에는 GitHub 전송 계층이 없습니다. 통제된 Azure 증적과 완전한 구독 보증 근거는 남아 있습니다. |
| 사전 빌드 OCI 배포 어플라이언스 사용 | in-progress | `run-deployment-appliance.sh`, 집중 스크립트 및 CLI 테스트 | 테넌트 프로비저닝은 release에서 게시하고 digest로 고정한 어플라이언스에서 공개 산출물 대체 경로 없이 수동 standalone 조정기를 시작할 수 있습니다. 통제된 아티팩트 오프라인 Azure 증적은 남아 있으며 테넌트 배포는 이미지를 만들지 않습니다. |
| Offline-kit 생성 및 검증 | validated | `fdai_deployment_cli.offline_kit`, 잠긴 릴리스 스크립트, 성공한 네트워크 격리 air-gap 훈련 | 서명 우선 검증, 정확한 파일, SBOM 커버리지, ABI/libc 연결, 비공개 스냅샷, 제공 wheel 설치가 통과합니다. |
| 안정 Network API 기반 Foundation 검색 | validated | PR #926, `deployment-v0.1.0-r4`, [이슈 #803 근거](https://github.com/dotnetpower/fdai/issues/803#issuecomment-5653340906) | 게시된 서명 번들로 West US 2의 모든 Foundation 입력 조회를 통과했습니다. 계획, 적용, 복구 또는 배포 준비 완료 주장은 만들지 않았습니다. |
| Temporary 공개 접근 정리 | not-started | 이 문서의 접근 선호 설정 계약 | 범위가 제한된 생성, 자동 정리, 정리 실패 시 불완전 상태 및 감사 종결을 입증하는 조립 명령이 없습니다. |
| Pinned TUF 루트 및 교대 | not-started | `docs/runbooks/offline-trust-ceremony.md` | 첫 루트 의식, 패키지 리소스, 클라이언트 초기화 및 교대 근거가 남아 있습니다. |
| 배포 후 검증 | in-progress | 관리 호스트 exact-plan 적용 증적, ACR 다이제스트 재확인, 마이그레이션, 상태 재확인, 두 번째 변경 없음 계획 및 라우팅된 수명 주기 테스트 | 구현은 존재하지만 완전한 CLI 기반 Azure 수명 주기와 아티팩트 오프라인 운영 증적은 아직 없습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-09-16 | not-started | AKS를 명시적인 기본 배포 대상으로 정하고, 선택한 피어링, 비공개 엔드포인트, 비공개 DNS, 비공개 클러스터 모드와 공개 접근 제거를 Console에서 시작하는 상세 프로비저닝 계획으로 옮겼습니다. 테넌트 프로비저닝은 미리 빌드하고 서명한 이미지만 사용하며 이미지를 빌드하거나 캡처하지 않습니다. | `current change`, 문서 및 배포 스킬 계약만 변경했으며 CLI, Console, Terraform 또는 Azure 효과는 주장하지 않습니다. | API 서버 서브넷과 공개 기본 구성을 구현하고 테넌트 이미지 builder를 제거하며 Console 네트워크 요청 상태와 보호된 실행을 추가한 뒤 기본 및 비공개 전환 증적을 보존합니다. |
| 2026-09-15 | not-started | 일반 PC에서의 시작을 정의하고 기본 서비스 배포와 후속 상세 프로비저닝을 분리했습니다. 선택하지 않은 고급 구성은 기본 배포 성공을 막지 않으며 정책상 필수 보안과 상태 보호는 해당 변경의 선행 조건으로 유지합니다. | 현재 설계와 배포 스킬 변경만 포함하며 새 CLI 명령, 스키마 필드, 플랫폼 지원이나 배포된 동작을 주장하지 않습니다. | 외부 PC에서 시작해 인증된 기본 서비스 상태에 도달하는 두 단계를 구현·검증하고, 재설치나 영속 상태 초기화 없이 선택한 기능을 추가합니다. |
| 2026-09-15 | in-progress | 기존 호스트 우선 배포를 명확히 했습니다. 현재 내부 VM이 조정기와 실행 역할을 함께 맡을 수 있으며 별도 VM, Bastion 또는 상태 이동을 일률적으로 요구하지 않습니다. 실제 연결·신원 문제와 설치기 연결 미구현을 구분합니다. | 현재 프로파일과 배포 스킬의 문서 변경이며 실행 경로 구현이나 Azure 검증을 주장하지 않습니다. | 공개 조정기가 적합한 현재 호스트 선택을 처리하도록 하고, 기존 백엔드 소유권과 완료된 변경을 보존하며, 불필요한 호스트 전송 없이 정확한 계획 실행과 독립 조회를 검증합니다. |
| 2026-09-13 | validated | 안정 Network API 수정을 포함한 `deployment-v0.1.0-r4`를 게시하고 실제 초안/공개 다운로드와 설치 바이트를 검증했으며, Azure 변경 없이 서명 번들의 West US 2 Foundation 검색을 통과했습니다. | PR #926, 소스 `c137aa104682a59b979f5f3554a06bf87c555b8e`, 전체 파일 트리가 같은 보호된 병합 `d312225c795ce9bb90022f37ebb7fd6f83a4d343`, CI `34755232779` 및 `34755464071` 성공, 압축 파일 SHA-256 `c7e8b3e99fd77534ad7e2b2321d2e677fb3fe316a946e4c58ef797d5682bbab5`, 격리 아티팩트 검사 11개, 서명 파일 304개, 일치하는 설치 파일 59개, 읽기 전용 호출 12건과 네트워크 접두사 일곱 개, [이슈 #803 근거](https://github.com/dotnetpower/fdai/issues/803#issuecomment-5653340906) | 기존 r1/r3 상태와 실행 주장은 변경하지 않았습니다. 명시적인 r4 출처 선택과 별도의 준비 컨텍스트가 필요하며, 정확한 계획 승인, 부분 이미지 복구, 온라인/오프라인 배포 수렴은 남아 있습니다. |
| 2026-09-13 | implemented | Azure CLI가 기존 리소스의 지역에서 지원하지 않는 Network API를 선택해 실패하던 Foundation 검색을 수정했습니다. 라우팅 테이블과 로컬 게이트웨이 상세 조회를 `2024-05-01`로 고정하고 목록 범위, 실패 처리, 승인 경계는 유지합니다. | `current change`, `test_genesis_network_api.py`, `test_genesis_network_layout.py`, `test_genesis_prepare.py` 32개 통과, Ruff, 형식, 엄격한 타입 검사 및 범위를 제한한 읽기 전용 공급자 검사 통과 | 대체 서명 키트의 게시와 검증이 남아 있으며 r3 원본 바이트는 유지합니다. 적용이나 복구는 수행하지 않았고 배포 수렴도 완료되지 않았습니다. |
| 2026-09-13 | validated | 추가 14회 라운드 전체를 포함한 `deployment-v0.1.0-r3`를 게시하고 설치했습니다. 운영 수정 아홉 건과 반증 후 회귀 테스트를 추가한 가설 다섯 건입니다. 보호된 PR 두 개가 병합됐고 정확한 소스의 main CI도 성공했습니다. | PR #918 및 #920, 소스 `3b4c088ea20d1d77770912394141847bf9940886`, CI `34746227767`, 압축 파일 SHA-256 `7b454ff37833d7f5c665fddb1f7954c99f8ebeda363c3a3d807f9707e4c6f82b`, 파일 304개/설치 내용 59개/이미지 여섯 개/지원 패키지 일곱 개/Terraform 루트 11개에 대한 무네트워크 검사 11개, 실제 공개 다운로드 및 네트워크를 차단한 온라인/오프라인 재개 검사 | 검토 범위에 확인된 Medium 이상 결함은 없으며 보존 복사본 누적은 Low입니다. Azure SKU 자격과 별도 승인을 거친 부분 이미지 복구/수렴은 막혀 있습니다. 프리릴리스는 명시적으로 선택해야 합니다. |
| 2026-09-13 | implemented | H14에서 이전 다운로드 기한의 버퍼 읽기 빈틈을 보완했습니다. 사용 가능한 데이터만 읽어 느린 스트림이 다음 전체 예산 검사 전에 여러 소켓 읽기로 큰 버퍼를 채우지 않게 합니다. | `current change`, 실제 `BufferedReader`와 가짜 원시 스트림으로 실패 재현, 지원되는 경우 `read1`을 사용한 뒤 집중 획득 테스트 통과 | 전체 기한을 넘는 시간은 진행 중인 소켓 읽기 한 번의 제한 이내이며 release 및 Azure 증적은 별도입니다. |
| 2026-09-13 | implemented | 새 비평 13회를 완료했습니다. 운영 수정 여덟 건과 실험으로 반증하고 회귀 테스트를 추가한 가설 다섯 건입니다. 범위를 한정한 최종 검토에서 획득, 시간 제한/전송, 승인 입력, 오류 표시에 확인된 Medium 이상 결함은 없습니다. | 커밋 `d8c4fa3a2`부터 `7e1f7a3f2`, 해당 변경 소유 회귀 테스트 379개 통과, 변경 소스 Ruff와 엄격한 타입 검사, 읽기 전용 검토 두 건 및 H13 반증 | 보존 복사본의 디스크 누적은 Low입니다. 하드닝한 버전의 게시와 Azure 이미지 복구/수렴은 남아 있으며 막힌 작업을 완료된 Low 문제로 취급하지 않습니다. |
| 2026-09-13 | validated | 통합 커밋 `74743842facfd3c986d3e069e2ae8e6714147bae`에서 개발 키트 `deployment-v0.1.0-r2`를 제작·게시하고 새 환경 설치, 실제 공개 다운로드, 두 오프라인 출처 형태에서 같은 아티팩트를 검증했습니다. | required CI `34741317737`, 이슈 #803 근거, 압축 파일 SHA-256 `4be041e244dfbcd3b69ea117f2c8a995ef14f2ae1188f55ad6ca00849c09e223`, 격리 검증 11개: 파일 300개, 설치 내용 48개, 이미지 여섯 개, 지원 패키지 일곱 개, Terraform 루트 11개 | 이 아티팩트는 후속 CLI 하드닝 13회 이전 버전입니다. Azure 적용이나 구독 준비 완료 증적은 만들지 않았습니다. |
| 2026-09-13 | implemented | 전송 예외는 만료 후에도 애플리케이션을 즉시 중단하고 터널 정리를 유지하며 후속 명령이나 준비 완료 증적에 도달하지 않음을 입증했습니다. | `current change`, 운영 코드 변경 없이 만료 전후 전송 실패 통합 회귀 테스트 통과 | 두 번째 만료 예외로 덮어쓰지 않고 원래 실패를 보존합니다. |
| 2026-09-13 | implemented | 소켓 제한 30초와 별도로 release 다운로드에 단조 시계 기반 15분 예산 하나를 적용하며 진행 상황으로 연장하지 않습니다. | `current change`, 이전에 통과하던 느린 소량 스트림이 거부되고 새 부분 다운로드만 삭제되는 테스트 및 획득 회귀 테스트 | 기존 압축 파일과 배포 상태는 보존하며 네트워크 재시도는 추가하지 않습니다. |
| 2026-09-13 | implemented | 실제 터미널을 요구하고 애플리케이션 확인 두 번과 사용자 조회를 최대 10분, 계획 만료, 호출 잔여 예산 중 가장 짧은 하나의 구간으로 제한합니다. | `current change`, 무제한 읽기 재현, 시간 초과/비대화형 입력 대조군, 공유 예산 및 기존 정확한 파괴적 승인 테스트 | 만료되거나 닫힌 입력은 승인을 부여하지 않고 자동 재시도도 하지 않습니다. |
| 2026-09-13 | implemented | 이미지 검토가 만료되어도 기존 실행 주장에 대한 검증만 허용하며 재선택, 재승인, 재적용은 하지 않음을 입증했습니다. | `current change`, 수동 및 자동 선택의 실행 주장/재개 회귀 테스트가 정확한 주장 바이트와 원래 적용 한 번을 보존함 | 완료된 효과의 검증일 뿐이며 부분 이미지 생성을 복구하지는 않습니다. |
| 2026-09-13 | implemented | Azure 신원 및 관리 호스트 입출력 예외를 출력 전에 정규화하고 원시 OS나 자식 프로세스 예외의 명령 인자와 비공개 경로 출력을 차단합니다. | `current change`, 합성 표식 노출 다섯 건 재현 및 집중 CLI/전송 회귀 테스트 | 안정적인 실패 분류만으로 이미 주장된 원격 효과의 완료 여부를 추론하지 않습니다. |
| 2026-09-13 | implemented | 명령, 표준 입력, 신원, 터널 정리를 바꾸지 않고 모든 애플리케이션 SSH/SCP 작업을 하나의 현재 기한으로 제한합니다. | `current change`, 전송 후 기반 리소스 단계의 시간 예산 오류 두 건 재현 및 직접 전송 회귀 테스트 | 만료되거나 실패한 적용은 검증으로만 재개하며 재시도나 승인을 추가하지 않습니다. |
| 2026-09-13 | implemented | 준비 전에 조정기의 시간 예산을 시작하고 Foundation 승인 대기를 현재 남은 시간으로 제한하며 Foundation 및 신원 작업 후 애플리케이션에 넘길 예산을 다시 계산합니다. | `current change`, 이전에 실패한 가짜 시계 회귀 테스트 세 개와 기존 조정기 테스트 | 각 애플리케이션 전송 작업도 남은 예산으로 제한해야 합니다. |
| 2026-09-13 | implemented | 최종 응답 후뿐 아니라 모든 리다이렉트 요청 전에 release HTTPS 호스트와 포트 허용 목록을 검사합니다. | `current change`, 금지된 대상 접촉 세 건 재현, 가짜 HTTP 전송과 허용된 CDN 대조군을 사용한 실제 urllib 리다이렉트 테스트 | 수정된 CLI를 게시해야 하며 허용 목록 확대나 실제 요청 재시도를 뜻하지 않습니다. |
| 2026-09-13 | implemented | 기존 오프라인 캐시가 출처 연결 기록 없이 명시적인 온라인 출처를 묵시적으로 수락하지 않음을 입증했습니다. | `current change`, 디렉터리 및 압축 파일의 모드 전환 회귀 테스트가 네트워크 요청 전에 중단되고 이전 바이트를 보존함 | 기본 버전의 이전 캐시 수락에도 전체 서명과 스냅샷 검증이 필요합니다. |
| 2026-09-13 | implemented | 로컬 디렉터리 획득은 이후 바뀐 원본 번들이 아니라 인증된 비공개 스냅샷을 실행하고 다음 재시도는 변경된 출처를 거부함을 입증했습니다. | `current change`, 운영 코드 변경 없이 출처 교체 회귀 테스트 통과 | 두 모드 모두에서 서명과 전체 스냅샷 검사를 유지합니다. |
| 2026-09-13 | implemented | 압축 파일 경로를 교체해도 추출기가 보유한 원본 디스크립터가 다른 파일을 가리키지 않음을 입증했으며 운영 코드는 바꾸지 않았습니다. | `current change`, 열린 inode 교체 회귀 테스트 통과 | 파일 내용 변경은 계속 서명과 스냅샷 검사로 검증합니다. |
| 2026-09-13 | implemented | 로컬 압축 파일과 디렉터리 재시도에서 보존된 정확한 스냅샷을 다시 검증하고 새 실행 복사본을 만들며 이전 근거를 보존합니다. | `current change`, 재현한 재시도 실패 두 건, 오프라인 재시도 및 변조 검사 네 개, 획득 경계 집중 테스트 | 새 CLI를 전달해야 하며 기존 부분 적용은 별도 승인을 거친 복구가 필요합니다. |
| 2026-09-13 | implemented | x64 macOS나 FreeBSD를 Linux로 취급하지 않고 두 아티팩트 획득 모드 모두에서 Linux가 아닌 POSIX 호스트를 먼저 차단합니다. | `current change`, 이전에 실패한 네 사례를 포함한 호스트 경계 회귀 테스트 다섯 개 | 수정된 CLI를 게시해야 하며 Azure 수렴 검증은 별도입니다. |
| 2026-09-12 | implemented | 대상 환경 프로비저닝을 manual 전송 계층으로 제한하고, 공개 CLI에서 workflow dispatch를 제거하고, 토큰 없는 관찰 전용 설치를 허용하고, OCI 배포 어플라이언스 진입점을 추가했습니다. | `current change`, 배포 CLI 계약, standalone 모듈, 어플라이언스 스크립트 및 집중 테스트 | 깨끗한 어플라이언스 하나를 빌드하고 연결 및 아티팩트 오프라인 Azure 배포 증적을 보존합니다. |
| 2026-08-14 | in-progress | 구현 원장을 도입했으며 이전 출처 이력은 재구성하지 않았습니다. 점검, 프로파일 영속성 및 offline 검증을 근거에 맞는 현재 상태로 바로잡았습니다. | 현재 변경과 구현 범위 표에 기재한 패키지 메타데이터, bootstrap 소스, release 스크립트 및 집중 작업 흐름 검사 | CLI 패키지를 만들고 offline 검증을 복원하며 trust 초기화를 완료한 뒤 전체 수명 주기를 검증해야 합니다. |
| 2026-08-29 | validated | 대상 연결 점검과 비공개 프로필을 추가하고 서명 offline 검증을 복원하며 제공 wheel 네트워크 격리 훈련을 완료했습니다. | `dd28b64d9` 이후 캠페인 커밋, 집중 검사, 성공한 `airgap-drill.sh` | 관리 호스트 Azure 실행을 완료하고 보호된 프로비저닝 후 증적을 보존해야 합니다. |
| 2026-09-05 | implemented | exclusive RCA reader identity apply와 검증 재개를 허용 목록 기반 bot 소유 요청으로 라우팅했습니다. downstream apply는 보호된 GitHub Environment에 계속 binding하며 변경 전에 보호된 `main`의 validator로 reviewer 정책을 검사합니다. | `current change`, 집중 deployment CLI, workflow 및 Environment 정책 검사 | 독립 승인 exact apply와 효과 증적을 하나 보존합니다. |
| 2026-09-05 | implemented | 실행 venue가 선택한 workload identity, 비공개 runner transport, scope별 lock, durable cursor fence 및 complete-reconciliation 권위를 보존하면서 읽기 전용 inventory change accelerator를 scheduled inventory 진입점에서 분리했습니다. | `current change`, inventory accelerator와 job 검사, strict mypy 및 강제 file-size gate | operating-instance owner가 추적하는 통합 change-feed timing 증적을 보존합니다. |
| 2026-09-06 | implemented | Exact image Container Apps rehearsal을 위해 positional `once` 또는 `loop` mode만 허용하는 설치형 inventory wrapper를 추가했습니다. Collection, projection, identity 또는 execution 권한을 바꾸지 않고 기존 CLI로 변환합니다. | `current change`, 집중 inventory CLI 테스트, strict mypy, package build 및 entrypoint 검색 | 운영 이력 certification 전에 exact image inventory projection refresh 증적 1개를 보존합니다. |
| 2026-09-06 | implemented | 보호된 OI-16 실행 profile에 deadline이 제한된 active generation projection release migration을 추가했습니다. Provider read를 수행하지 않고 이전 manifest와 journal fence를 보존하며 불완전하거나 변경된 content는 write 전에 차단합니다. | `current change`, 집중 replay CLI, projection, persistence, workflow 및 package 검사 | 보호된 dev campaign에서 성공한 exact release migration 증적 1개를 보존합니다. |
| 2026-09-11 | implemented | 서로 독립적인 로컬 아티팩트 경로, 기반 계층 입력 검색, 공급자 점검과 등록 요청, 정책 프로브 리소스 작업, 테넌트 디렉터리 읽기에 범위가 제한된 병렬 실행을 추가했습니다. 상태를 변경하는 적용, 승인, 정리, 인계, 저장소 쓰기, 보호된 애플리케이션 전이는 계속 직렬로 수행합니다. | `current change`, 집중 Genesis, 공급자 미러, 준비, Entra 및 제품화 테스트 | 경과 시간을 준비 상태 근거로 사용하지 않고 다음 exact-main 감독형 배포에서 시간 측정 근거를 보존합니다. |
| 2026-09-11 | implemented | GitHub Actions를 요구하지 않고 활성 `az login` 대상을 사용하는 online 및 아티팩트 오프라인 설치 패키지 배포를 추가했습니다. 완전한 서명 키트, GitHub 없는 관리 호스트, 정확한 애플리케이션 승인, 운영자 발급 또는 Trial 라이선스, 이미지 재확인, 활성화 전 마이그레이션 및 수렴 검사가 하나의 경로를 공유합니다. | `current change`, deployment CLI 및 Genesis 소스, strict mypy, 패키지 빌드와 새 환경 설치, 라우팅된 deployment 및 Genesis 테스트 | 깨끗한 스냅샷에서 완전한 서명 release 키트를 빌드하고 online 및 아티팩트 오프라인 Azure 수렴 증적을 보존합니다. |
| 2026-09-12 | implemented | 독립 실행형 배포에 대해 16회의 비평 및 하드닝 라운드를 완료했습니다. 전송 재사용은 정확한 서명 키트에 연결되고 trust root는 Ed25519를 요구하며 파괴적 plan은 두 번째 정확한 확인을 요구합니다. 모호한 apply는 검증으로만 재개하고 보존된 Foundation 및 Entra context를 정확히 확인하며 provider 대체 경로를 차단합니다. License, migration, image, revision 상태 및 변경 없음 효과는 독립적인 재확인이 필요합니다. | `current change`, deployment CLI, release builder, ShellCheck, strict mypy, 집중 package 및 Genesis 테스트, 독립적인 수정 후 비평 | 깨끗한 서명 키트를 빌드하고 다시 검증한 뒤 validation 상태를 높이기 전에 online 및 아티팩트 오프라인 Azure 수렴 증적을 보존합니다. |
| 2026-09-12 | implemented | 첫 번째 깨끗한 빌드가 해당 API 경계에 도달한 뒤 완전한 키트 런타임 메타데이터가 검증된 OCI manifest descriptor의 digest를 읽도록 수정했습니다. | `current change`, `build-standalone-deployment-kit.sh`, 깨끗한 로컬 OCI 및 Console 빌드 | 배포 전에 완전한 서명 키트를 다시 빌드하고 검증합니다. |
| 2026-09-12 | implemented | 첫 번째 실제 online 획득이 Azure 변경 전에 유효한 redirect를 거부한 뒤 GitHub의 정확한 공식 release asset CDN hostname을 HTTPS 허용 목록에 추가했습니다. Subdomain, credential, 기본값이 아닌 port 및 다른 모든 redirect host는 계속 차단합니다. | `current change`, 집중 downloader regression, 게시된 `deployment-v0.1.0` asset | Online 획득을 다시 실행하고 대상 연결 기반 Azure 수렴 증적을 보존합니다. |

### 남은 작업

- [x] 전용 CLI 패키지에 `provision inspect`와 `provision init`을 구현하고 무변경, mode-`0600`/`0700`, 덮어쓰기, symbolic link 및 안정적 JSON 테스트를 통과합니다.
- [x] 주입된 release 루트 뒤에 offline-kit 검증을 복원하고 서명 우선 확인, exact 파일 집합, no-follow 다이제스트, 호환성 및 한계 테스트를 통과합니다.
- [ ] Temporary 공개 접근 생성과 정리를 구현하여 정리 실패가 감사된 불완전 작업으로 남게 하고 CIDR, 기간, 인증, 롤백 및 멱등성 테스트를 통과합니다.
- [ ] TUF 루트 의식과 패키지 초기화를 완료하고 offline trust ceremony가 수락한 서명 루트 및 교대 근거를 남깁니다.
- [x] 깨끗한 스냅샷에서 완전한 서명 키트 하나를 빌드하고 다시 검증한 뒤 새 환경에 CLI를 설치하고 online 및 로컬 아티팩트 경로에서 같은 키트를 획득합니다. 근거: `deployment-v0.1.0-r2`와 위의 2026-09-13 아티팩트 기록입니다.
- [x] 후속 CLI 하드닝을 포함한 완전한 대체 키트를 게시하고 정확한 설치 아티팩트 검증을 반복합니다. 근거: `deployment-v0.1.0-r3`에 H01-H14가 포함되고 기본 설치 파일 59개가 모두 서명된 휠과 일치하며 이전 설치는 백업했습니다.
- [x] 안정 Network API 수정을 포함한 대체 서명 키트를 게시하고 검증한 뒤 해당 아티팩트에서 Foundation 검색을 확인합니다. 검색 성공을 배포 준비 완료로 취급하지 않습니다. 근거: `deployment-v0.1.0-r4`와 연결된 이슈 #803의 읽기 전용 검증 기록입니다. 기존 CLI 설치 파일 59개가 이미 서명된 휠과 일치하므로 교체하지 않았습니다.
- [ ] 전체 구독 준비 상태를 주장하지 않고 두 활성 로그인 모드의 대상 연결 기반 Foundation 및 애플리케이션 수렴 증적을 보존합니다.
- [ ] 별도 호스트를 불필요하게 만들거나 올바르게 보호된 기존 백엔드를 옮기지 않고 현재 VM에서 `existing-host` 실행을 검증하며, 신원·정확한 계획·재적용 금지·독립 조회 검사를 유지합니다.
- [ ] 사설 접근을 미리 설정하지 않은 일반 PC에서 기본 배포를 검증하고, 설치 식별자·기존 상태·Trial 시작 시점을 보존한 채 상세 프로비저닝을 진행하며, 선택 기능의 미설정 상태와 기본 서비스 상태를 구분합니다.
- [ ] API Server VNet Integration과 워크로드 및 API 서버 전용 서브넷을 포함한 AKS 기본
  프로파일을 만들고, 배포를 시작한 조정기에서 인증되고 제한된 공개 관리 접근을 검증합니다.
- [ ] 피어링, 비공개 엔드포인트, DNS, 비공개 클러스터 모드에 대해 `/provisioning` 네트워크
  의도, 평가, 정확한 계획 요청, 승인, 적용, rollback 및 독립 재확인 상태를 구현합니다.
- [ ] 테넌트 실행의 Docker, Buildx, ACR Tasks 및 VM 이미지 캡처 경로를 제거하고, 미리 빌드한
  서명 이미지 매니페스트와 배포된 digest 재확인을 요구합니다.
- [ ] release에서 게시하고 digest로 고정한 배포 어플라이언스 하나를 수락하고 SBOM, 출처 및
  내장 키트를 검증한 뒤 테넌트 프로비저닝에서 이미지를 만들지 않고 아티팩트 오프라인 Azure
  배포 증적을 보존합니다.

## 한눈에 보는 설계

프로비저닝은 네 가지 선택을 독립된 축으로 취급합니다. 명령은 먼저 근거를 평가하며,
`dev` 같은 환경 이름 또는 운영자가 휠을 설치한 머신에서 권한을 추론하지
않습니다.

| 축 | 지원 값 | 선택 규칙 |
|----|---------|-----------|
| Connectivity | `online`, `offline` | 제한된 TLS 검사를 통과한 후에만 online 출처를 사용하고, 그렇지 않으면 signed offline 키트를 요구합니다. |
| 실행 호스트 | `existing-host`, `managed-vm` | 적합한 private-network 호스트를 재사용하고, 적합한 호스트가 없으면 managed VM을 생성합니다. |
| 전송 계층 | `manual` | 대상 환경 배포는 항상 로컬 조정기와 Managed Host를 사용합니다. GitHub Actions는 release를 빌드하고 게시할 수 있지만 대상 환경을 계획하거나 적용할 수 없습니다. |
| 소유권 | `fdai-managed` | 승인 후 Terraform이 선언된 리소스와 역할 배정을 관리합니다. |

### 활성 로그인 기반 독립 실행형 배포

제품의 기본 경험은 일반 PC에서 기본 배포를 한 뒤 같은 설치에 상세 프로비저닝을 진행하는 것입니다.
현재 명령 이름이 `provision azure`라고 해서 기본 서비스 가동 전에 모든 고급 구성을 끝내야 하는
것은 아닙니다. 단계 분리는 아래 목표 계약이며 이번 문서에서 구현된 CLI 옵션이나 명령을 추가하지 않습니다.

설치 패키지는 `az login` 후 하나의 기본 구독 배포 경계를 지원합니다.

```bash
fdaictl provision azure --online
fdaictl provision azure --offline-kit /media/fdai/fdai-kit.tar
# 소스 checkout 편의 wrapper이며 online이 기본값입니다.
scripts/deployment/azure/fdai-up.sh
```

두 명령은 활성 Azure CLI 사용자 컨텍스트에서만 테넌트와 구독을 결정합니다. 소스 checkout,
Git remote, GitHub 계정, GitHub 저장소, required CI 검사, 저장소 변수, 저장소 비밀, 작업 흐름
dispatch 또는 GitHub runner 등록이 필요하지 않습니다. Online 모드는 각 리다이렉트에 접촉하기 전에 검증하는 제한된 HTTPS로
버전이 지정된 완전한 키트 하나를 다운로드합니다. Offline 모드는 같은 키트 형식을 로컬
경로에서 읽고 모든 공개 아티팩트 대체 경로를 차단합니다. 여기서 offline은 아티팩트가
오프라인이라는 뜻이며 선택한 Azure control plane 또는 Bastion 엔드포인트와 단절된다는 뜻은
아닙니다.

오프라인 재시도는 지정한 출처를 다시 읽고 보존된 스냅샷을 재검증하며 이전 상태를 교체하지 않고
새 실행 복사본을 사용합니다. 바이트가 바뀌거나 불완전하면 재시도를 중단합니다.
온라인 전송 진행 상황으로 전체 다운로드 예산 15분을 연장하지 않습니다. 소켓 읽기는 30초
제한을 유지하며 각 원시 읽기 사이에 사용 가능한 데이터를 반환합니다. 만료 시 새로 만든
부분 다운로드만 삭제하고 재시도하지 않습니다. 진행 중인 소켓 읽기로 전체 기한을 넘는 시간은 해당 읽기 한 번의 제한 이내입니다.

패키지는 키트와 별도로 release 및 bundle 검증 루트를 고정합니다. 완전한 키트에는 배포
bundle, Terraform과 OPA, provider mirror, runtime OCI archive, Console 콘텐츠, migration 지원
및 각 SBOM이 포함됩니다. Azure 변경 전에 서명, 정확한 파일 집합, 플랫폼, 소스 revision,
runtime 콘텐츠 검증을 완료합니다.
현재 관리 호스트 이미지와 완전한 키트 builder는 Linux x86_64를 지원합니다. 다른 호스트
운영체제나 아키텍처는 두 획득 모드 모두 시작 전에 차단하며 POSIX라는 사실만으로 Linux로 판단하지 않습니다.

Foundation 네트워크 검색은 안정 버전 Network API `2024-05-01`로 선택한 구독 전체의 기존
라우팅 테이블과 로컬 네트워크 게이트웨이를 읽습니다. 기존 리소스의 지역에서 지원하지 않을 수
있는 최신 버전을 Azure CLI가 자동 선택하게 두지 않습니다. 조회가 실패하면 검색을 중단하며
예약된 주소 범위를 누락하거나 공급자를 등록하거나 다른 버전으로 재시도하지 않습니다.

기본 배포는 미리 빌드하고 서명한 이미지 집합을 검증하고, API Server VNet Integration이 적용된
AKS 기반을 만들며, 기본 서비스 다섯 개를 배포합니다. 또한 배포에 연결된 라이선스를 설치하고
애플리케이션 활성화 전에 migration을 실행한 뒤 상태 검사와 두 번째 변경 없음 계획을 요구합니다.
테넌트 프로비저닝은 이미지를 빌드하거나 캡처하지 않습니다. 구독 정책이 첫 효과부터 비공개 접근을
요구하지 않는 한 기본 경로는 인증되고 제한된 공개 관리 접근을 유지합니다.

선택한 비공개 애플리케이션 백엔드, 비공개 레지스트리 경로와 비공개 서비스 엔드포인트는 후속 상세
프로비저닝 계획에 포함합니다. 조건을 갖춘 현재 VM은 `existing-host`로 조정기와 실행 역할을 함께
맡을 수 있습니다. 정책이 기본 배포부터 비공개 접근을 요구하면 해당 호스트 또는 최소
`managed-vm` 경로가 변경 전에 접근 가능성을 검증해야 합니다. 비공개 작업을 부적합한 호스트로
우회하지 않습니다.

모든 변경 checkpoint는 exact-plan 승인, 변경 전 불변 claim, 범위가 제한된 중지 및 정리 경로,
대상 lock, 안정적 멱등성 및 독립적인 효과 재확인을 유지합니다. 기본 standalone `dev` 경로는
각 exact plan마다 현재 로컬 사용자 승인 하나를 받습니다. Staging과 production은 구성된 독립
정족수와 승인된 실행 호스트를 계속 요구합니다.
Apply 결과가 모호하면 다음 호출은 변경 없음 plan과 권위 있는 재확인만 실행합니다. 보존된
claim으로 apply를 반복하지 않습니다. Foundation run, network/state handoff, Entra binding,
provider 구성 또는 서명 키트가 바뀌면 별도의 준비 context가 필요합니다.
호출 시간 예산은 준비 전에 시작합니다. 승인 대기와 애플리케이션 인계에는 현재 남은 시간을
사용하며 예산이 만료되면 다음 단계를 시작하거나 준비 완료 결과를 만들지 않습니다.
애플리케이션 확인에는 실제 터미널이 필요하며 두 확인 입력과 사용자 조회가 최대 10분의
한 구간을 공유합니다. 계획 만료나 호출 잔여 예산이 더 짧으면 그 시간으로 제한합니다.
`DeadlineTransport`는 기존 Bastion 명령과 파일 전송 각각을 같은 현재 예산으로 제한하고
입출력 후에도 만료를 검사합니다. 원래 터널은 자체적인 제한 시간 내 정리를 유지합니다.
신원 및 전송 실패에는 고정된 진단 메시지를 사용하며 원시 OS 및 자식 프로세스 예외의 명령
인자나 경로를 출력하지 않습니다. 효과 결과가 불명확하면 여전히 보존된 상태를 검토해야 합니다.

명령은 명시적 옵션 또는 문서화된 사용자 구성 경로에서 운영자 소유 mode-`0600` license issuer
key를 찾습니다. 키가 있으면 키를 복사하지 않고 배포 및 이미지에 연결된 token을 발급합니다.
미리 발급된 Trial token을 제공하면 같은 검증 및 전달 경로를 사용합니다. 둘 다 없으면 license
secret을 만들지 않고 관찰 전용 모드로 배포를 완료합니다. Token은 Bastion 표준 입력으로
전달되고 Managed Identity가 Key Vault에 기록합니다. 인자, Terraform 상태, portable 상태 또는
로그에는 포함되지 않습니다.

## 읽기 전용 검사

목표 명령은 초기화 계획을 만들기 전에 점검을 실행합니다.

```bash
fdaictl provision inspect --output json
```

점검은 로컬 Azure CLI, Terraform, 제한된 online 산출물 접근,
offline-kit 후보, Azure 워크로드 신원 엔드포인트를 검사합니다. `mutation_performed=false`,
필수 승인 정책과 정족수, 선택된 프로파일이 포함된 안정적인 JSON 계약을 반환합니다. 도구를
설치하거나 구성을 기록하거나 리소스를 생성하거나 실행기를 등록하거나 Terraform을
적용하지 않습니다.

결과는 다음 상태를 사용합니다.

| 상태 | 의미 |
|------|------|
| `ready` | 기존 호스트에 toolchain, 워크로드 신원, online 접근 또는 검증된 offline 키트가 있습니다. |
| `review` | Managed VM 또는 pinned 검증기가 없는 offline 키트에 운영자 검토가 필요합니다. |
| `incomplete` | 명시적으로 요청한 프로파일에 필수 의존성 또는 접근 경로가 없습니다. |

파일 존재만으로 trust가 성립하지 않습니다. Composition-injected pinned 검증기가 있으면 점검은
서명, 호환성, exact 파일, 다이제스트, 한계를 검사하고 non-secret 매니페스트 메타데이터만
반환합니다. Rejected 내용은 `incomplete`, 검증된 내용은 완전한 existing-host 프로파일을
`ready`로 만들 수 있습니다. 공개 루트 ceremony가 검증기를 패키지하기 전까지 목표 CLI는
offline 디렉터리를 `candidate` / `review`로 유지합니다.

## 프로파일 initialization

목표 초기화 명령은 명시적으로 결정된 값으로 검토한 프로파일을 저장합니다.

```bash
fdaictl provision init \
  --target-binding <sha256> \
  --connectivity online \
  --host existing-host \
  --transport manual \
  --access-method internal_ssh
```

대상 연결은 의도한 테넌트와 구독 쌍의 배포 로컬 다이제스트이며 원시 식별자가 아닙니다.
명령은 모든 `auto` 값을 거부하고 `.fdai/provisioning/profile.json`을 mode-`0700` 디렉터리
안에 파일 모드 `0600`으로 기록합니다. Offline 프로파일에는 `--artifact-source`가 필요합니다.
Temporary 공개 SSH에는 전체 주소 space보다 좁은 정본 출처 CIDR과 5-60분 접근
구간이 필요합니다. 대상 환경 배포 프로필은 `manual` 전송 계층만 허용합니다.

기존 대상은 `--force`를 명시하지 않으면 initialization을 차단합니다. Force는 symbolic
링크를 따라가거나 non-file 대상을 교체하지 않습니다. 프로파일 initialization은 Azure
리소스를 변경하지 않으며 JSON 출력에 `mutation_performed=false`를 기록합니다.

## 실행 호스트

### 기본 배포와 상세 프로비저닝

**설계와 검토:** 시작 전에 사설 인프라와 모든 운영 연동을 요구하면 설치 준비가 다시 설치의
선행 조건이 됩니다. 반대로 인증, 데이터 보호나 테넌트 필수 정책을 뒤로 미루면 안전하지 않은
기본 구성이 됩니다. PC의 Azure 내부 여부가 아니라 제품의 안전한 가동에 필요한 항목을 기준으로
단계를 나눕니다.

지원되는 CLI 실행 환경과 Azure 관리·신원 엔드포인트 접근이 있으면 일반 PC에서 배포를 시작할 수
있어야 합니다. 내부 VM, VPN, IMDS, PC에 연결한 Managed Identity나 미리 만든 Foundation은
모든 PC에 필요한 선행 조건이 아닙니다. 네이티브 운영체제 지원은 구현된 도구에 따르며, 지원되는
Linux 환경을 사용한다고 물리적 PC까지 Azure VM이어야 하는 것은 아닙니다.

| 단계 | 필요한 결과 | 이 단계의 선행 조건이 아닌 항목 |
|------|-------------|------------------------------|
| 기본 배포 | API Server VNet Integration, 워크로드 및 API 서버 전용 서브넷을 포함한 AKS Standard, 기본 서비스 5개와 필수 의존성, 영속 상태와 마이그레이션, 최소 워크로드 신원·RBAC, 인증된 Console URL, 제한된 공개 관리 접근, 독립적인 기본 상태 검증과 재시작 후 데이터 보존. | 비공개 엔드포인트, VNet 피어링, 비공개 DNS, 비공개 클러스터 모드, 전체 리소스 검색, 모델 용량 인증, 선택 연동·ChatOps, 조직별 정책, 운영 규모 튜닝이나 자율 실행 승격. |
| 상세 프로비저닝 | 기존 설치에 선택한 비공개 네트워크, 운영 범위, 모델, 연동, 정책과 용량을 추가하고 기능별 정확한 계획, 준비 상태와 승인을 검증. | 기본 구성 재설치, 검증된 리소스 재생성, 영속 데이터나 Trial 시작 시점 초기화. |

기본 배포에서는 대상·리전·런타임과 DB 선택·필수 비용 및 접근 결정만 수집하고 바뀌지 않은 선택은
재사용합니다. 최소 의존성과 구독의 필수 정책은 미룰 수 없습니다. 선택 설정은 사용할 수 없음으로
표시하며 가짜 상태나 근거로 대체하지 않습니다. [Trial 계약](installable-deployment-cli-ko.md#소스-출처와-trial)에
따라 기본 설치는 게시자 서명 키를 요구하지 않으며 이후 프로비저닝으로 Trial을 갱신하지 않습니다.

조정기는 PC에서 허용되는 관리 플레인 단계를 실행합니다. 기본 배포는 이후 네트워크 강화를 위한
구조를 예약하지만 시작 전에 PC 피어링, VM 신원 연결, 비공개 엔드포인트 생성 또는 Foundation
수동 구축을 요구하지 않습니다. 정책상 필요한 비공개 데이터 플레인 단계는 적합한 기존 호스트나
승인된 계획에 포함된 최소한의 설치기 관리 실행 경로를 사용합니다. 정책상 비공개여야 하는 서비스를
내부 실행 경로를 피하려고 공개하거나 기존 백엔드를 바꾸지 않습니다. 호스트 준비는 설치기의 작업이지
별도의 제품 단계가 아닙니다.

기본 Console 상태 검사가 통과하면 `/provisioning`에서 대상 피어 VNet, 주소 범위, 비공개 서비스,
DNS와 송신 정책을 수집할 수 있습니다. 브라우저는 내용 주소 기반 요청을 제출하며 배포 신원을
받거나 Terraform을 실행하지 않습니다. 보호된 실행기는 주소 겹침을 검증하고 정확한 계획을 만든
뒤 별도 사람 승인을 기다려 적용합니다. 공개 접근을 제거하기 전에 피어링, 경로, DNS, TLS, 신원과
엔드포인트 접근을 독립적으로 검증합니다. 효과가 불명확하면 검증만 재개합니다.

권위 있는 서비스 및 접근 검사가 통과한 뒤에만 기본 배포 성공을 보고합니다. 기본 서비스가
정상이면서 상세 프로비저닝은 미완료일 수 있으므로 `subscription_ready=false`만으로 기본 배포
실패로 보지 않습니다. 반대로 클러스터나 Console 화면만 있다고 기본 배포가 성공한 것은 아닙니다.
기존 결과 필드의 의미를 유지하고 새 단계별 계약은 구현 전에 정의합니다. 근거 없이 기존 전체
실행 증적을 기본 배포 성공으로 바꾸어 부르지 않습니다.

예: 노트북에서 기본 계획을 검토하고 서비스 검사 후 인증된 Console에 접속합니다. 이후 상세
프로비저닝에서 모델과 관리 리소스 범위를 설정하되 가동 중인 기본 구성을 다시 배포하거나 자율
실행 권한을 암묵적으로 부여하지 않습니다.

### 기존 호스트

조건을 갖춘 현재 내부 VM, 점프 서버 또는 배포 호스트에는 `existing-host`를 우선 사용합니다.
PC라고 부르거나 로컬 터미널을 사용한다고 외부 장비인 것은 아닙니다. 데스크톱 운영체제만으로
적합성을 추정하지 말고, 해당하는 경우 WSL의 Linux 도구를 포함해 실제 실행 환경을 확인합니다.
선택한 호스트에는 다음 조건이 필요합니다.

- 필요한 모든 비공개 엔드포인트에 대한 네트워크 및 비공개 DNS 도달 가능성.
- Azure CLI와 Terraform.
- 승인된 배포 역할이 있는 별도 워크로드 신원.
- Protected Terraform 백엔드와 계획 저장소에 대한 영속 접근.

수동 실행은 운영자가 이 호스트에서 `fdaictl`을 시작한다는 의미입니다. Terraform이
운영자의 interactive Azure 신원을 사용한다는 의미가 아닙니다. 필수 워크로드 신원이 없는 실행
호스트는 준비 미완료이지만, 조정기 역할만 하는 일반 PC까지 거부하지는 않습니다.
허용되는 경우 적절한 범위의 기존 배포 신원을 재사용하며,
현재 Foundation 실행이 만든 호스트나 신원만 요구하지 않습니다. 신원 연결, 역할 변경과 네트워크
변경에는 여전히 검토된 범위와 정확한 승인이 필요합니다.

**설계와 검토:** 별도 관리 VM은 구현 방식 중 하나이지 현재 VM이 부적합하다는 근거가 아닙니다.
반대로 Azure 내부라는 사실만으로 특정 비공개 엔드포인트 접근이 증명되지는 않습니다. 대상, DNS,
경로, TLS, 백엔드 접근 권한과 실행 신원을 각각 확인합니다. 직접 VNet 피어링이 없다는 사실만으로
승인된 다른 경로까지 없다고 판단하지 않습니다. 다른 호스트 생성을 일률적으로 요구하는 대신
실패한 검사와 최소한의 수정 사항을 보고합니다.

적합한 동일 호스트에서 조정기와 실행을 함께 수행하면 두 번째 장비로의 SSH/Bastion 연결이나
소스 전송은 필요하지 않습니다. Foundation 인계는 검증된 리소스 정보와 권위 있는 Terraform
상태를 이어받는 절차이며 리소스나 애플리케이션 데이터 이동을 뜻하지 않습니다. 올바르게 보호된
기존 백엔드는 재사용합니다. 실제 이행이 필요한 경우에는 정확한 승인과 단일 소유권 검증을 유지합니다.
설치기의 완료 기록이 없다는 이유로 완료된 적용을 반복하거나 증적을 만들어내지 않습니다.

기존 호스트를 선택할 수 있다고 모든 공개 조정기 경로가 이를 구현한 것은 아닙니다. 지원하지 않는
진입점이나 복구 증적 경로는 호스트 적합성과 별개인 설치기 미구현 사항으로 보고합니다.
이번 문서 변경으로 해당 구현이나 배포까지 완료됐다고 주장하지 않습니다.

### Managed VM

적합한 기존 호스트가 없거나 정책상 전용 배포 호스트가 필요한 경우 `managed-vm`을 사용합니다.
조정기가 외부에 있다는 이유만으로 적합한 기존 호스트를 교체하지 않습니다. VM은 영속하게 유지하지만
일반적으로 deallocate합니다. Protected 상태, 계획, 승인, 감사 기록은 비공개 저장소에
남으므로 VM을 시작, 중지 또는 다시 빌드해도 배포 권한이 변경되지 않습니다.

점검은 기존 호스트의 적합성을 먼저 평가하며 VM을 생성하지 않습니다. 초기화 계획 수립은 승인
전에 VM, 네트워크, 신원, 역할, 접근, 비용, stop, 정리 효과를 보여 줍니다.

## 접근 선호 설정

Managed-host 접근 순서는 다음과 같이 고정합니다.

1. 승인된 내부 SSH.
2. Azure Policy와 배포 프로파일이 허용하는 경우 temporary public-IP SSH.
3. Azure Bastion.
4. 감사되는 비상 경로인 Azure Run Command.

신규 구독 Genesis는 이 목록을 차례로 대체 시도하지 않습니다. `access_method=bastion`인
프로파일은 기반 계층이 만든 정확한 Standard Bastion 네이티브 터널을 선택합니다. 등록 자료는
SSH 표준 입력으로만 전달하며 상태 인계는 고정된 같은 호스트 키 경계를 사용합니다.

Temporary 공개 접근은 silent 대체 경로로 사용하지 않습니다. 계획에는 허용 목록에 포함된
출처 CIDR, 키 또는 certificate만 사용하는 SSH, 제한된 접근 구간, 공개 IP와 temporary
network-security 룰의 자동 제거가 필요합니다. `0.0.0.0/0`, password authentication,
persistent 공개 IP는 허용되지 않습니다. 정리는 연산 성공 기준의 일부입니다.
정리에 실패하면 연산은 불완전한으로 남고 감사 기록이 생성됩니다.

## Online 및 offline 전달

Online 전달은 공개 `fdai-deployment-cli` 패키지와 버전이 일치하는 완전한 서명 배포 키트를
사용합니다. 관리 호스트는 키트의 인증된 binary, provider, runtime image 및 migration wheel만
사용합니다.

목표 release 작업 흐름은 읽기 전용 작업에서 휠과 출처 분포를 한 번만 빌드하고 Python과
번들 버전이 일치하는지 검사합니다. 일치하는 signed 번들을 게시한 후에만 같은 산출물을
PyPI Trusted 발행으로 게시합니다. Publish 작업만 GitHub OIDC 권한을 받으며 장기
PyPI 토큰은 저장하지 않습니다.

공개 PyPI release 줄은 `0.1.0`에서 시작합니다. 기존 저장소 tag `v0.1.1`부터
`v0.1.12`까지는 pre-PyPI engineering 이정표이며 다시 작성하지 않습니다. 첫 공개 release는
정확한 게시 커밋에 `v0.1.0` tag를 생성합니다. `0.1.0`보다 높은 활성 pre-PyPI 번들
상태가 있는 installation은 fresh 공개 release 상태 또는 명시적 이행을 사용합니다.
`0.1.0`으로 semantic-version 업그레이드하는 것으로 처리하지 않습니다.

Disconnected 전달은 platform별 offline 키트에서 같은 `fdai` 휠과 명령 계약을
사용합니다. 키트에는 다음 항목이 포함됩니다.

- FDAI 휠과 모든 transitive Python 휠.
- Signed 배포 번들.
- Pinned Terraform binary와 프로바이더 mirror.
- OPA와 필요한 보조 로직 binary.
- SBOM, SHA-256 매니페스트, 서명, release trust 메타데이터.

전체 구성은 서명 배포 번들을 먼저 만든 뒤, 비공개 다이제스트 고정 서술자로 해당 번들의 정확한
바이트에 결속된 런타임 v2를 조립하고 외부 키트를 서명합니다. 독립적으로 사전 빌드한 런타임은
이미 같은 번들에 결속된 경우에만 계속 지원합니다.

Offline 모드는 PyPI, GitHub, 공개 Terraform 레지스트리 대체 경로를 차단합니다. 산출물 출처로
승인된 내부 mirror 또는 removable media를 사용할 수 있습니다. Installer와 `fdaictl`은 두
경우 모두 같은 pinned release 루트를 검증합니다.

목표 `verify_offline_kit` 구현은 매니페스트 파싱 전에 Ed25519 서명을 검사하고 exact CLI 및 platform
버전을 연결하며 symlink와 extra 파일을 거부합니다. 모든 파일 다이제스트를 스트리밍하고 휠,
signed 배포 번들, Terraform binary 및 프로바이더 mirror, OPA, SBOM을 요구합니다. release
루트 주입은 테스트, release construction, pinned 점검 조립에서만 사용합니다.
산출물 hashing은 no-follow 서술자 열림으로 경로 swap redirect를 막습니다. `fdaictl`은 `--release-root`
재정의를 제공하지 않습니다. 공개 루트가 휠에 pin될 때까지 점검은 `review`로
유지됩니다.

키트 내용을 **실행**하는 일은 그것을 **보고**하는 일보다 강한 증거를 요구합니다. `provision plan`은
키트의 Terraform 바이너리를 실행하므로, 운영자가 공급한 release 루트로 키트를 검증하고 검증이 실패하면
계획을 거부합니다. 두 경로 모두 산출물을 디렉터리 관례가 아니라 서명된 매니페스트에서 해석합니다.
Pinned 루트가 배포되면 `--release-root`는 계획 수립은 수락하고 점검은 여전히 수락하지 않는
재정의가 됩니다.

`build_offline_kit_manifest`는 그 검증기의 목표 release-side 역방향입니다. Staged 키트를 검증기와
동일한 검사로 읽으므로 symlink, 비정규 파일, 한계 초과 트리를 기술하는 대신 거부하며, 파일
목록을 운영자 입력이 아니라 단계에서 도출합니다. 단계에 없는 산출물 역할은 서명 이전에
실패하며, 동일한 내용을 두 번 빌드하면 서명 대상 바이트가 정확히 같습니다.
`scripts/deployment/release/build-offline-kit.py`는 검증기 모듈이 복원된 뒤 서명을 담당하도록
설계되어 있습니다. Operator가 보관한 Ed25519
비공개 키를 로드하고, 새 매니페스트를 쓰기 전에 오래된 서명을 제거해 중단된 실행이
그럴듯한 키트가 아니라 검증 불가 키트를 남기게 하며, 보고 전에 공개 release 루트로 재검증합니다.
비공개 키는 키트, 저장소, 로그 어느 곳에도 들어가지 않습니다.

### Trust 루트 및 교대

최종 offline 권한은 Python-TUF 7을 통해 The 갱신 Framework (TUF) 1.0을 사용합니다.
휠은 out-of-band trust 초기화로 initial signed `root.json`을 제공합니다. 루트 비공개
키는 offline에 보관합니다. CI는 targets, 스냅샷, 시각 메타데이터용 delegated online 키를
사용할 수 있지만 루트 비공개 키는 받지 않습니다.

클라이언트는 루트 메타데이터를 한 버전씩 갱신하고 각 new 루트가 old 루트와 new 루트 임계값을
모두 만족하는지 확인합니다. TUF 메타데이터 만료와 단조 증가 버전은 freeze, 롤백,
mix-and-match 공격을 방어합니다. 메타데이터 임계값과 키 ceremony는 release-security
정책이며 프로비저닝 적용의 one-person 승인과 독립적입니다.

현재 exact-content 검증기는 TUF가 대상을 인증한 이후 defense in 깊이로 유지됩니다.
Python-TUF 통합과 첫 루트 ceremony는 offline 루트를 만들고 CI 외부에 백업할 때까지
차단됩니다. 생성된 비공개 키를 커밋하거나 `fdaictl`을 통해 전달하지 않습니다.

## 승인 및 적용

Operator-initiated infrastructure 또는 role-assignment 적용에는 exact binary-plan 다이제스트에
연결된 인증된 사람 승인 한 명이 필요합니다. 실행기는 별도 워크로드 신원입니다. 계획이
변경되거나 만료되면 승인은 무효가 되며 적용은 `-auto-approve` 또는 caller-supplied
Terraform 인자를 허용하지 않습니다.

삭제, replacement, 역할 변경, state-backend 변경, temporary-access creation,
temporary-access 정리는 사람용 출력과 JSON 출력에서 별도로 강조합니다. 모두 같은
one-approver 프로비저닝 정책을 사용합니다. 이 배포 정책은 high-impact 자율
런타임 액션의 기존 정족수 룰을 낮추지 않습니다.

목표 수명 주기는 다음과 같습니다.

```text
inspect -> profile init -> bootstrap plan -> human approval -> exact apply
  -> access cleanup -> post-provision verification
```

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 설치 및 명령 계약 | [설치형 배포 CLI](installable-deployment-cli-ko.md) |
| Azure 인벤토리 및 초기화 리소스 | [배포 및 온보딩](deploy-and-onboard-ko.md) |
| 계획, release, 롤백 수명 주기 | [배포](deployment-ko.md) |
| 실행기와 human 신원 분리 | [보안 및 ID](../architecture/security-and-identity-ko.md) |
