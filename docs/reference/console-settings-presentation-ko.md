---
title: Console 설정 및 컴포넌트 표현
translation_of: console-settings-presentation.md
translation_source_sha: f5d9c205efa98344541b20a1fa4404724eb0055a
translation_revised: 2026-09-07
---

# Console 설정 및 컴포넌트 표현

이 참조 문서는 FDAI Console 설정과 정적 시안의 공유 컨트롤, IAM 단계, 컴포넌트 문서화 및
권한 경계를 정의합니다.

## 공유 컨트롤

Console 설정과 정적 시안은 Calm Slate 컨트롤 토큰과 표현 프리미티브를 공유합니다. 데스크톱 폼은
34 px 표준 컨트롤과 28 px 간소 작업을 사용하며 터치 대상은 44 px입니다. 브라우저 로컬 환경 설정,
계정 환경 설정, 배포 정책, 근거 및 권한은 시각적으로 구분하되 영속성이나 권한 부여 계약은
변경하지 않습니다.

## IAM 표현

`/settings/iam`은 경로가 소유하는 이중 언어 메시지와 반응형 스타일을 사용합니다. 검증된 FDAI
Owner 역할과 테넌트 관리자를 구분하고, 요청, 검토, 보호된 적용 및 새 검증을 별도 단계로
표시하며 운영 할당 검토를 Agent oversight에 연결합니다.

Console과 Operator API의 점진적 업그레이드 중에는 안전한 역할 및 기능 사실을 유지하고 누락된
디렉터리 메타데이터는 알 수 없음으로 표시합니다. IAM 응답 디코더는 초기 Console 번들을 늘리지
않고 첫 IAM 요청과 함께 로드됩니다.

## 컴포넌트 갤러리

정적 컴포넌트 갤러리는 `mocks/ui/assets/component-registry.json`에서 문서화된 컴포넌트 계약을
읽습니다. 범위가 제한된 각 카테고리 화면은 시안을 먼저 표시한 뒤 소유자, 원본, 상태, 사용 지침,
반응형 동작, 접근성 계약 및 제품 참조를 제공합니다.

레지스트리가 없거나 잘못되면 시안을 정규 컴포넌트로 추론하지 않고 문서화 상태를 차단합니다.
갤러리는 합성 표현 근거로 유지되며 Console, Operator API 또는 실행기 권한을 부여하지 않습니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| Operations 설계 | [Console 운영](../roadmap/interfaces/console-operations-ko.md) |
