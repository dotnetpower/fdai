---
title: Console Web 알림
translation_of: console-web-notifications.md
translation_source_sha: 839d7c8962b6053ebe9a5ef2680fb85426fd76f8
translation_revised: 2026-09-14
---

# Console Web 알림

이 문서는 클라이언트 로컬 `console-web` 알림 채널, 개인 선택 화면, 브라우저 기능 게이트,
로컬 전달 원장 및 알림 클릭 확인을 소유합니다. Core 알림 어댑터, 서버 측 구독 저장소 또는
실행 권한을 추가하지 않습니다.

## 범위와 소유권

`console-web`은 한 브라우저 프로필에서 로그인한 principal이 사용하는 인증된 Console 편의
채널입니다. Settings > Integrations가 정식 선택 화면이며 헤더 컨트롤은 같은 기본 설정을
공유하는 바로가기입니다.

기존 Teams, Slack, 이메일, 웹훅, paging 및 SMS A2/A4 바인딩은 조직에서 관리하는
channel-as-audience 경로로 유지합니다. 개인 Settings 섹션에서는 읽기 전용 통합 근거입니다.
Operator가 principal의 검증된 활성 endpoint를 변환하고 해당 전달 경로가 같은 선택을 사용할
때만 이후 개인 채널을 선택할 수 있습니다.

브라우저 채널은 정보 제공 전용입니다. 승인 또는 실행 권한을 부여하지 않으며 로컬 증적은 Core
`notification.delivery.observed`를 충족하지 않습니다.

## 기능과 선택

다음 조건을 모두 충족할 때만 채널을 사용할 수 있습니다.

- 페이지가 보안 컨텍스트입니다.
- Notifications API를 사용할 수 있습니다.
- Service Worker를 등록할 수 있습니다.
- Web Locks가 principal 범위 live-stream 리더 하나를 선출할 수 있습니다.

FDAI는 페이지를 불러올 때 권한을 요청하지 않습니다. 선택에는 명시적 사용자 동작이 필요합니다.
기본 설정은 인증된 principal 키로 현재 브라우저 프로필에 저장됩니다. 같은 문서의 사용자 지정
이벤트와 탭 간 storage 이벤트가 Settings와 헤더 컨트롤을 동기화합니다.

저장된 선택과 수신자 상태는 서로 다른 상태입니다. 워커 또는 리더 실패 시 선택은 유지되고 상태가
다시 시도로 바뀝니다. 필수 API가 없는 브라우저는 준비 상태 대신 채널 사용 불가를 표시합니다.

## 이벤트 허용

선택된 리더는 탭이 백그라운드에 있을 때 인증된 `GET /live/stream` 연결을 유지합니다.
`runtime-observed` 승인, 거부 및 실패 프레임만 허용합니다. 재생, 합성 개발, 출처 미확인 및
일반 성공 프레임은 거부합니다.

알림에는 현지화된 일반 텍스트, 범위가 제한된 불투명 이벤트 태그, claim 토큰 및 서버가 만든
동일 출처 인시던트 링크만 포함합니다. 원본 오류, 리소스 식별자, 승인 컨트롤 또는 실행 링크는
포함하지 않습니다.

## 전달 원장

principal 범위 브라우저 원장은 다음 규칙을 적용합니다.

- 이벤트 태그 하나를 5분 동안 중복 억제합니다.
- 시스템 알림 표시를 분당 5건으로 제한합니다.
- 증적을 최대 32개, 7일 동안 유지합니다.
- `showNotification()`이 완료된 뒤에만 표시를 기록합니다.
- 일치하는 태그와 예측 불가능한 128-bit claim 토큰이 있을 때만 확인을 기록합니다.

레거시 항목은 롤링 버전 중복 억제를 위해 `at` 타임스탬프 별칭을 유지합니다. 토큰이 없는 레거시
항목은 새로운 확인을 만들 수 없습니다. 표시 완료와 실패 전송 해제에는 현재 claim 토큰이
필요하므로 오래된 callback이 대체 claim을 변경할 수 없습니다.

표시 상태는 보존된 최신 전달에서 `대기`, `전송됨`, `전송 및 확인됨`으로 도출합니다. 이전
알림을 열어도 더 최신인 미확인 알림이 확인된 것처럼 보이지 않습니다. 유효한 클릭이 표시
callback보다 먼저 도착하면 두 타임스탬프를 원자적으로 기록하며 이후 표시 쓰기는 단조 상태를
유지합니다.

## 클릭 확인

모든 알림 클릭은 선택된 동일 출처 Console 창을 닫힌 형식의
`#fdai-notification-ack` fragment로 이동합니다. Fragment는 HTTP 요청이나 referrer에 포함되지
않습니다. Console은 mount 및 `hashchange` 시점에 fragment를 검증하고 제거한 뒤 태그와 토큰이
일치하는 principal 원장을 정확히 하나 찾습니다. 따라서 알림 생성 후 브라우저 계정이 바뀌어도
활성 principal에 잘못 귀속하지 않고 원래 원장으로 수렴합니다. 일치 항목이 여러 개면 fail-closed
처리합니다.

서비스 워커는 등록 scope 안의 제어된 창 client만 대상으로 봅니다. 하위 경로 배포에서 같은
origin의 관련 없는 창을 이동하지 않습니다. 이동 결과로 반환된 창을 활성화하고, 이동이 창을
반환하지 못하면 같은 검증된 대상을 엽니다. 응답 없는 `postMessage()` 호출을 확인 전달로
간주하지 않습니다.

## 실패와 복구

서비스 워커 등록과 준비 대기에는 각각 10초 제한이 있습니다. Timeout, 토큰 생성 실패, 저장소
실패 및 Web Locks 획득 실패는 명시적인 사용 불가 또는 다시 시도 상태가 됩니다. 어떤 실패도
전달을 조용히 활성화하지 않습니다.

현재 구현은 Push API 구독이나 서버 측 구독 저장소를 제공하지 않습니다. 브라우저가 완전히
종료되면 알림을 받지 않습니다. 닫힌 브라우저 Web Push에는 별도로 인증된 서비스, 암호화된 구독
저장소, 철회, CSRF 보호 및 전달 감사가 필요합니다.

## 검증

집중 테스트는 출처 허용, 권한과 기능 게이트, principal 격리, 중복 억제, 속도 제한, 보존,
레거시 호환성, claim fencing, 순서가 바뀐 callback, 계정 전환 확인, 모호한 토큰 거부, fragment
파싱, 워커 이동 및 리더 실패를 다룹니다. Console 빌드와 번들 예산 검사는 로드된 표현과 지연 로딩
표현을 검사합니다. 브라우저 검사는 Settings/헤더 동기화, 같은 문서 fragment 처리, 영문과 한글
라벨, 320px 레이아웃 및 200% 텍스트 확대를 다룹니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 전달 상태와 남은 작업 | [Console Web 알림 구현 원장](../../roadmap-implementation/interfaces/console-web-notifications.md) |
| 공유 채널 범주와 조직 라우팅 | [채널과 알림](channels-and-notifications-ko.md) |
| Console 모듈 소유권 | [Operator Console 모듈 지도와 경계](operator-console-module-map-ko.md) |
| Console 근거 동작 | [Console 근거와 복원력](console-evidence-and-resilience-ko.md) |
