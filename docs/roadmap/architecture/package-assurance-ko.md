---
translation_of: package-assurance.md
translation_source_sha: 3b4190862b6f610c0f937dabd9a12c9ba477c073
translation_revised: 2026-09-28
---

# 패키지 보증

이 문서는 FDAI Python 패키지의 최소 배포 계약을 정의합니다. 오프라인 패키지는 일반 로컬 pip
wheelhouse처럼 설치할 수 있으며, 설치 전에 private key로 만든 detached signature 하나만
추가로 검증합니다.

> **범위:** 이 계약은 Python 패키지 배포만 다룹니다. Azure 신원, Terraform 승인, 런타임 이미지,
> 데이터베이스 이행, 서비스 상태 및 배포 복구는 해당 배포 소유자가 관리합니다.
>
> **구현 원장:** 현재 제공 근거는
> [패키지 보증 구현 원장](../../roadmap-implementation/architecture/package-assurance.md)에서
> 추적합니다.

## 설계 개요

오프라인 패키지는 다음 파일만 포함합니다.

```text
package/
  INSTALL.txt
  requirements.txt
  SHA256SUMS
  SHA256SUMS.sig
  wheels/
    fdai_deployment_cli-<version>-py3-none-any.whl
    <dependency wheels>
```

서명자는 운영자가 보관하는 Ed25519 private key로 `SHA256SUMS`에 한 번 서명합니다. 신뢰하는
public key는 별도로 제공합니다. 패키지는 신뢰 의식, 산출물 프로필, 중첩 서명, SBOM 요구 사항,
출처 문서, 호환성 행렬, 런타임 권한 또는 배포 증적을 포함하지 않습니다.

## 빌드

다음 전용 빌더를 사용합니다.

```bash
scripts/deployment/release/build-signed-python-package.sh \
  --out /private/fdai-python-package \
  --signing-key /private/deployment-signing-key.pem
```

빌더는 Deployment CLI wheel을 만들고 잠긴 런타임 의존성을 `wheels/`에 다운로드한 다음 정렬된
checksum 목록 하나를 작성하고 서명해 tar 아카이브를 만듭니다. 서비스 이미지를 빌드하거나 Azure
배포 payload를 조립하지 않습니다.

서명 파일 두 개를 제외한 모든 포함 파일은 `SHA256SUMS`에 나열됩니다. `wheels/`에 wheel 파일이
아닌 항목이 있으면 빌더가 실패합니다. 서비스 계약처럼 잠긴 workspace 경로 의존성은 인덱스
해시가 없으므로 wheel로 빌드합니다.

## 검증 및 설치

pip를 실행하기 전에 서명과 checksum을 검증합니다.

```bash
cd package
openssl pkeyutl -verify -pubin \
  -inkey /private/trusted-package-signer.pub \
  -rawin -in SHA256SUMS -sigfile SHA256SUMS.sig
sha256sum -c SHA256SUMS
python -m pip install --no-index --find-links wheels -r requirements.txt
```

Python 버전, ABI, 플랫폼 wheel, 의존성 및 설치 검사는 pip가 담당합니다. 대상 인터프리터와 맞지
않는 패키지는 일반 pip 동작에 따라 설치되지 않습니다.

## 단일 패키지 제약

FDAI 패키지 보증이 요구하는 항목은 checksum 목록에 대한 유효한 detached Ed25519 signature
하나뿐입니다. 파일 해시는 서명 대상 콘텐츠 목록이며 별도 승인 체계가 아닙니다.

Private key는 저장소와 패키지 외부에 보관합니다. 패키지 설치는 Azure 접근, 실행 권한, 기능 사용
설정 또는 승인을 부여하지 않습니다.

## 제거한 제약

패키지 계층은 다음 항목을 더 이상 정의하거나 요구하지 않습니다.

- 보증 등급 또는 경계 분류
- connected, offline, appliance 산출물 프로필
- signed root 또는 TUF 의식
- 별도 release 및 bundle 서명
- SBOM 또는 출처 문서
- 호환성 매니페스트 또는 N-1 정책
- 전송 아카이브의 정확한 바이트 일치
- 패키지 최신성 또는 운영 근거
- wheelhouse 이외의 의존성 미러
- 런타임 승격, 승인, 신원 또는 효과 검증

소유자는 배포 또는 release 용도로 이러한 산출물을 계속 만들 수 있습니다. 그러나 패키지 설치의
선행 조건이 아니며 전역 패키지 검사에서 확인하지 않습니다.

## 패키지 목록

[`config/package-assurance.json`](../../../config/package-assurance.json)은 현재 이 signed
wheelhouse를 게시하는 Python 배포판만 나열합니다. 전체 작업 영역 목록이 아니며 내부 패키지는
항목이 필요하지 않습니다.

검사기는 Ed25519 서명 형식 선택과 각 배포판 경로의 `pyproject.toml` 이름 일치만 확인합니다.
그 밖의 항목은 pip와 패키지 관리자가 담당합니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 설치 후 배포 동작 | [설치형 Deployment CLI](../deployment/installable-deployment-cli-ko.md) |
| 런타임 및 Azure 산출물 제공 | [연결이 끊긴 배포](../deployment/disconnected-deployment-ko.md) |
| 패키지 구현 근거 | [패키지 보증 구현 원장](../../roadmap-implementation/architecture/package-assurance.md) |
