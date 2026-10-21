---
title: 로컬 구성 출판
translation_of: lifecycle-configuration-publication.md
translation_source_sha: 4e7e6400c9e43b92dd9207101a300deca516917b
translation_revised: 2026-10-22
---
# 로컬 구성 출판

이 문서는 명시적으로 선택한 구성 개정을 로컬에 출판하고 그 기록을 보존하는 방법을 정의합니다.
기존 패키지 생성기와 향후 보호된 병합 출판기 사이의 저장 경계를 보완하며, 로컬 산출물을
검토되거나 수락된 구성으로 간주하지 않습니다.

> **범위:** 출판 장소는 현재 운영자가 소유한 기존 모드 0700 디렉터리 하나입니다.
> 전역 원본 등록, Git 검토, Hub 수락 또는 실행 권한이 아닙니다.
> [수명 주기 구성](lifecycle-configuration-ko.md)이 패키지와 신뢰 계약을 소유합니다.

## 설계 요약

출판 장소 하나의 작업을 직렬화하고 보존한 전체 체인을 독립적으로 검증한 다음, 원래
암호문/서명과 증적을 저장합니다. 그 뒤 비공개 산출물 복사본을 만들고 다시 읽습니다.
재시도는 새로 암호화하거나 서명하지 않고 원래 바이트와 증적을 반환합니다.

## 입력 및 호환성

기존 단일 Entity 및 설치 전체 v1/v2 입력 계약, 독립적인 Ed25519 검증 키, X25519 수신자
키와 Release/스키마 입력을 사용합니다. 기존 `build`, `verify` 동작과
`fdai.lifecycle-configuration-file.v1` 바이트는 바뀌지 않습니다.

새 출판 경로는 소문자 16진수 40자로 된 명시적 개정 ID를 사용합니다. 이 형식이 Git 존재나
검토를 입증하지는 않습니다. 호출자는 출판 장소와 최초 출판 또는 예상 출판 체인 끝을
선택합니다. 로컬 체인은 Hub가 패키지를 수락했다는 주장이 아닙니다. 키를 검색, 변환,
발급 또는 등록하지 않습니다.

## 지속 상태 및 개인정보 보호

비공개 SQLite 원장은 원래 암호문/서명 바이트, 패키지/개정 식별 정보, 순서와 안정적인
증적 메타데이터를 보존합니다. 추가 평문 입력, 개인키나 비밀 값은 저장하지 않습니다.
산출물 복사본은 같은 비공개 장소의 모드 0600 파일입니다.

최대 패키지 256개와 보존 산출물 바이트 16 MiB를 지원합니다. 한도를 넘으면 자르지 않고
수락하지 않습니다. 원장 스키마 버전 1은 명시적입니다. 보존 스키마를 알 수 없거나
손상/누락된 경우 빈 체인으로 다시 만들지 않고 검토를 위해 보류합니다.

로컬 디렉터리 잠금 하나가 협력하는 작성자를 직렬화합니다. 대상, 실행 또는 출판 장소 간
잠금을 대신하지는 않습니다. 독립적으로 선택한 권위 있는 출판 장소와 검증된 백업/복원은
향후 자동 출판기의 선행 조건으로 남습니다.

## 커밋, 재시도 및 복구

| 단계 | 결과 | 결과가 불확실한 경우 |
|------|------|----------------------|
| 보존 상태 및 요청 입력 검증 | 기존 생성기/읽기 경로가 전체 이력과 정확한 재시도 입력을 검증합니다. | 이력을 보존하고 수락하지 않습니다. |
| 원래 패키지와 증적 커밋 | 지속적인 출판 식별 정보 하나를 기록합니다. | 재시도 전에 보존 근거를 확인합니다. |
| 비공개 산출물 생성 | 새 파일만 만들며 기존 복사본은 정확히 일치해야 합니다. | 충돌하는 복사본을 덮어쓰지 않습니다. |
| 독립적인 재조회 | 정확한 바이트와 독립적인 읽기 경로로 검증합니다. | 출판이 확인되지 않았다고 표시합니다. |

원장 커밋 후 산출물 생성 전에 프로세스가 중단되면 재시도는 다시 서명하지 않고 보존한
동일 바이트를 생성합니다. 원래 증적 시각과 식별 정보는 바뀌지 않습니다. 같은 개정의 입력
충돌, 키/맥락 불일치 또는 갈라진 이력은 명시적으로 수락하지 않습니다.
과거 개정을 재시도할 때는 현재 전체 체인을 독립적으로 검증한 뒤 보존된 이력 구간과
입력을 비교합니다. 과거 증적을 반환하더라도 출판 체인의 끝을 되돌리지는 않습니다.

읽기 전용 검사는 독립적인 공개 입력으로 보존 체인을 검증하고 원래 증적과 산출물 존재
여부를 보고합니다. 서명 키가 필요하지 않으며 산출물을 만들지 않습니다.
지우기, 삭제, 초기화, 회전 또는 파괴적 복구 명령은 제공하지 않습니다.
처리가 끝나지 않은 SQLite 트랜잭션 보조 파일이나 지원하지 않는 저장 모드가 있으면
검토를 위해 보류합니다. 검사는 SQLite 복구를 수행하거나 저널/공유 메모리 파일을 만들지 않습니다.

## 로컬 명령

기존의 빈 비공개 출판 장소와 독립적인 입력/키 파일을 선택합니다. 예를 들면 다음과 같습니다.

```bash
fdaictl configuration publish --state-dir /absolute/private/publications \
  --input /absolute/private/source.json --release-input /absolute/private/release.json \
  --configuration-key /absolute/private/configuration.pem \
  --installation-key /absolute/private/installation.pem \
  --signing-key /absolute/private/signing.pem --initial-publication --output json
```

후속 새 개정에서는 `--initial-publication` 대신
`--expected-publication-head <retained-package-digest>`를 사용합니다. 서명 자료 없이 검사합니다.

```bash
fdaictl configuration inspect-publication --state-dir /absolute/private/publications \
  --revision-id aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  --release-input /absolute/private/release.json \
  --configuration-key /absolute/private/configuration.pem \
  --installation-key /absolute/private/installation.pem --output json
```

결과는 보존 근거를 검증한 `verified`와 산출물을 다시 읽어 확인한 `publication_confirmed`를
구분합니다. 복사본이 없으면 복구하지 않고 `artifact_state: missing`과
`publication_confirmed: false`를 보고합니다. Git/전역 출판자 관련 주장은 미검증 상태로
유지하며, Hub/활성화/권한 플래그는 false로 유지합니다.

## 설계 검토 및 수정

- 파일 존재 여부만 확인하면 동시 암호화와 서로 다른 재시도 결과를 허용할 수 있습니다.
  검증, 커밋과 산출물 재조회 동안 기존 비공개 디렉터리 잠금을 유지합니다.
- 출판을 기록하기 전에 파일을 쓰면 중단 후 원래 결정을 잃습니다. 원래 바이트부터
  커밋한 뒤 그 바이트만 복구합니다.
- 로컬 원장이나 개정 형식의 문자열은 보호된 Git 검토나 전역 출판자 신원을 입증할 수
  없습니다. 이를 명시적으로 미검증 상태로 유지하며 가져오기나 활성화 권한을 부여하지 않습니다.
- 손상되거나 누락된 상태 파일은 새로 시작할 권한이 아닙니다. 빈 장소에서만 명시적 최초
  출판을 허용하며, 연결할 수 없거나 충돌하는 보존 산출물은 수락하지 않습니다.
- 쓰기 성공은 수락이나 운영 효과가 아닙니다. 재조회 후에만 로컬 출판을 보고하며 모호한
  실패 뒤에는 확인되지 않았다는 결과를 명시합니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 패키지, 이력, 봉인 및 독립적인 신뢰 | [수명 주기 구성](lifecycle-configuration-ko.md) |
| Hub 가져오기와 설치 경계 | [Hub 관리형 수명 주기](hub-managed-lifecycle-ko.md) |
| 제공 근거 및 남은 작업 | [구현 원장](../../roadmap-implementation/deployment/lifecycle-configuration-publication.md) |
