---
title: 설치 Agent 구성 입력
translation_of: installation-agent-configuration.md
translation_source_sha: a89da3dd32841c2845b820cbe667bc30d51c72b5
translation_revised: 2026-10-21
---
# 설치 Agent 구성 입력

기존 설치 Agent로 서명된 v2 전체 구성 개정을 검증하고 비밀값을 읽지 않고 CSI 참조 보고를
검사할 수 있습니다. 이 가이드는 로컬 프로비저닝 입력을 설명하며 등록 절차, 배포 승인 또는
운영 신뢰의 증거가 아닙니다.

> **경계:** 소스와 로컬 합성 테스트를 구현했습니다. 실제 키 등록, 인증된 산출물 동기화,
> CSI 공급자 결합과 운영 수락은 별도 작업입니다. 기본 `poll-once`는 사전 실행이며
> 이 가이드는 `--apply`를 승인하지 않습니다.

## 선행 조건

- 독립적으로 프로비저닝한 Hub/Release 검증 키와 기존 로컬의 엄격한 정책이 필요합니다.
- 독립적으로 승인한 고객 구성 Ed25519 공개 키와 별도의 설치 X25519 비공개 키가 필요합니다.
  Ed25519 신원 키를 암호화 입력으로 사용하지 마세요.
- 기존 Hub 가져오기, 독립적인 범위/변경 승인과 활성화 경로에서 허용된 서명 Plan이 필요합니다.
  정확한 패키지 다이제스트는 로컬에서 유지한 활성 개정과 같아야 합니다. 패키지 서명이나
  로컬 파일만으로 이러한 승인이 입증되지는 않습니다.
- `configuration_schema`에 정확한 Release 버전과 정규 스키마 다이제스트가 포함된,
  허용된 서명 runtime v3 Release 매니페스트가 필요합니다. Release Hub 내보내기, 오프라인
  키트 또는 신뢰하지 않는 매니페스트 옆의 스키마 파일로 대체할 수 없습니다.

## 설치 로컬 입력 준비

기존 배포 비공개 파일 도우미를 사용해 현재 사용자 소유의 모드 `0700` 디렉터리와
모드 `0600` 단일 링크 파일에 비공개 입력을 보관하세요.
키나 복호화한 식별자는 Git, 명령 인자 값, 로그, 보고 또는 공개 출력에 넣지 않습니다.

`fdaictl configuration build`가 만든 원래 `fdai.lifecycle-configuration-file.v1`
컨테이너를 `--inputs-dir` 아래 `configurations/<package-digest>.json`에 놓습니다.
컨테이너에는 원래 v2 서명 페이로드와 분리된 서명이 들어 있으며 공개 키는 없습니다.
다이제스트는 컨테이너가 아닌 페이로드를 가리키고, 해당 디렉터리는 비공개입니다.
Release는 계속 `releases/<manifest-digest>.json`과 기존 `.sig` 형제 파일을 사용합니다.

독립적인 `--configuration-binding` JSON에는 정확히 다음 필드가 있습니다.

```json
{
  "format": "fdai.lifecycle-agent-configuration-binding.v1",
  "installation_id": "<installation-id>",
  "active_digest": "<exact-active-package-sha256>",
  "entity_bindings": {"core": "<independently-approved-64-hex-binding>"},
  "sealed_keys": ["endpoint"],
  "history": []
}
```

`entity_bindings`는 로컬 정책에서 이미 관리 중인 Entity 집합 전체를 일대일로 대응시킵니다.
Plan Entity ID는 64자 패키지 결합 ID가 아닌 기존 로컬 ID를 유지합니다.
이력은 순서대로 나열한 전체 선행 개정이며 최대 256개 패키지, 페이로드 16 MiB입니다.
각 선행 개정에는 `digest`, `configuration_key_file`(독립적으로 유지한 해당 개정의
Ed25519 공개 키 PEM 경로), `installation_key_digest`(원래 X25519 수신자 다이제스트)가
정확히 들어갑니다. 원래 선행 컨테이너도 같은 산출물 저장소에 놓습니다.
과거 신뢰는 수락한 바이트만 인증하며 현재 서명 권한을 부여하지 않습니다.

기존 `poll-once` 명령에 다음 옵션을 추가합니다.

```bash
--configuration-binding /private/approved-binding.json \
--installation-encryption-key /private/installation-encryption.pem
```

결합, 키 입력 또는 매니페스트 스키마가 없으면 `configuration_unavailable`을 반환하고
변경을 준비하거나 효과를 내지 않습니다. 잘못된 대체 입력은 차단합니다.
도우미는 패키지에서 키를 가져오거나 결합을 선택하지 않습니다.
기존 평면 `schema`/`environment`/`entity_overrides` 문서와 분리된 서명은 이 옵션 없이
계속 동작합니다. 별도의 정규 단일 Entity 패키지 v1은 v2 전체 개정이 아니며 자동 변환하지
않습니다.

## 렌더링과 비공개 상태

각 Entity를 따로 해석하며 구성된 모든 리전으로 기존 로컬 최대 범위를 좁힙니다.
기존 데모는 v2에서 복제본 1-3개를 지원하고 기존 데모 동작은 복제본 1개를 유지합니다.
동일 스키마 Operator 프로필은 기존 스키마 검사, 의존성 참조와 고정 리소스 한도를
유지합니다. 복호화한 식별자 중 지원되는 `operator_config_map_name` 참조만 렌더링에
전달됩니다. 다른 식별자는 인증하지만 이를 이용해 워크로드 필드를 만들지는 않습니다.
Entity는 네임스페이스, 이미지 저장소 또는 기능 모드를 선택할 수 없습니다.

Agent는 v2 준비 전에 비공개 상태 디렉터리를 요구합니다. 소유자만 접근하는 저널에는
롤백을 위해 렌더링된 참조 이름을 저장할 수 있습니다. 복호화한 엔드포인트/식별자 값은
보고, 상태 스냅샷과 로그에 들어가지 않습니다. 기존 Plan 허용 심사, 사전 실행, 2단계 보고,
롤백, 대상 잠금, 만료와 재시작 중복 방지는 계속 필요합니다.
로컬 테스트 통과는 설치 성공이나 비밀값 사용 가능성의 근거가 아닙니다.

## CSI 참조 보고 검사

명시적으로 결합한 출처만 검사합니다. `reference-status` 명령은 공급자 등록, RBAC 변경,
Secret 생성 또는 마운트된 파일 열기를 수행하지 않습니다.

```bash
fdai-lifecycle-agent reference-status \
  --references /private/csi-references.json \
  --kube-context <independently-selected-context> --namespace <exact-namespace>
```

비공개 JSON은 최대 32개 객체의 목록이며 각 객체에는 `CSIReference` 필드가 정확히
들어갑니다. 필드는 `entity_id`, `namespace`, `pod_name`, `pod_uid`, `class_name`,
`status_name`, `object_id`, `object_version`, `source_manager`입니다.
정확히 유지한 이름과 예상 Key Vault 비밀 버전을 제공하고 값은 제공하지 않습니다.
Pod의 Entity 레이블, UID, 클래스 볼륨과 상태 소유자가 일치해야 하며
SecretProviderClass 공급자는 `azure`여야 합니다.

범위가 제한된 어댑터는 기존 Kubernetes 전송 경로로 정확히 지정한 Pod,
SecretProviderClass, SecretProviderClassPodStatus만 읽습니다. 상태 리소스 버전,
예상 객체 버전, Pod UID, 읽은 시각과 드라이버 관리자의 갱신 시각을 명시합니다.
`binding_digest`로 대상 이름을 출력하지 않고 정확한 비공개 네임스페이스/Pod/클래스/출처
선택과 연결합니다. 고정 SDK 읽기 경로는 검색을 피하고 별도의 SDK 요청별 제한 시간인
10초를 유지합니다. 30초 예산은 각 읽기의 호출 전과 후에 확인하는 결과 수락 기한입니다.
기한과 같거나 늦게 완료된 읽기는 `unavailable`로 처리하고 추가 읽기나 재시도를 시작하지
않습니다. 실행 중인 요청을 강제로 중단하거나 명령 전체가 30초 안에 끝남을 보장하는
제한은 아닙니다. 진행 중인 요청은 기존 SDK 제한 시간에 따라 수락 기한 뒤에 돌아올 수
있습니다.
드라이버 시각이 없으면 `unknown`, 5분이 지나면 `stale`, 결합/버전이 충돌하면 `conflict`,
출처가 없거나 접근이 차단되면 `unavailable`입니다. `reported-mounted`와
`reported-unmounted`는 드라이버의 보고일 뿐 비밀값의 사용 가능성을 독립적으로 검증한
결과가 아닙니다. 픽스처나 파일 존재만으로 상태를 높일 수 없습니다.

## 다음 단계

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 정확한 호환성과 설계 비평 | [수명 주기 구성](../roadmap/deployment/lifecycle-configuration-ko.md#설치-agent-소비-경로-설계와-비평) |
| Plan 허용 심사와 운영 경계 | [Hub 관리형 수명 주기](../roadmap/deployment/hub-managed-lifecycle-ko.md) |
| 기존 CLI, 적용 안전장치와 선택적 테스트 | [Lifecycle Agent](../../lifecycle/agent/README.md) |
