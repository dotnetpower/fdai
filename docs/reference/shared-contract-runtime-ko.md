---
title: 공유 계약 런타임
translation_of: shared-contract-runtime.md
translation_source_sha: 0bc5080eeb0171bc01a28087d6edc0316f834457
translation_revised: 2026-09-07
---

# 공유 계약 런타임

이 참조 문서는 `fdai_service_contracts`가 소유하는 의미 채널, 맥락 선택, 논리 토픽,
실행 장소, 호환성 및 이미지 계약을 설명합니다.

## 의미 턴 묶음

기존 Operator/Core 묶음의 버전 1.2는 범위가 제한된 semantic-turn 요청 하나와 근거에 묶인
최종 결과 하나를 추가합니다. 요청은 인증된 역할, 세션 정렬, 용도, 기한 및 멱등성을 고정합니다.
Answered 결과에는 정확한 release, 매니페스트, 계획, 실행 증적 및 근거 참조가 필요합니다.
SDK는 해당 필드를 폐기하는 대신 의미 downgrade to N-1을 거부합니다. 런타임 게시와 소비는
서비스 소유 구현으로 유지되며, Operator bridge는 서로 다른 최종 projection 토픽과 progress
토픽을 감독합니다.

Operator continuation 조회는 `request_id`로 결합하기 전에 결과 후보를 정확한 세션으로,
요청 후보를 정확한 outbox namespace와 principal로 제한하여 구체화합니다. 범위가 제한된 후보
집합은 lineage 검사를 유지하면서 PostgreSQL 조인이 관련 없는 `state_kv` 행으로 확장되지 않게
합니다.

## 맥락 선택

Semantic-turn 요청은 불투명한 서버 발급 토큰과 함께 타입이 지정된 화면 또는 리소스 그룹 선택을
보존합니다. Operator는 인증된 principal, 일반 소문자 역할 범위, 용도, 정확한 release, 출처 세대,
완전성 및 ID 집합에 대해 토큰을 해석한 뒤 선택 다이제스트를 다시 계산합니다. Core는 이를 사용해
`query.contextual_resources`의 정확한 `Resource.id` 범위를 컴파일합니다. 클라이언트가 위조하거나
다시 계산한 ID, 재시작 후 사라진 토큰 또는 범위 불일치는 principal 표시 컬렉션으로 대체하지 않고
타입이 지정된 사용 불가 결과가 됩니다. 어떤 맥락 필드도 승인 또는 실행 권한을 부여하지 않습니다.

명시적 발화 조건식은 토큰의 집합과 교집합하며, 불완전한 객체 전용 맥락 표는 answered claim이
되지 않고 의미 턴을 보류합니다. 이 보류는 맥락 리소스 계획에만 적용합니다. 범위가 제한된 다른
조회 표는 명시적 잘림 상태와 함께 계속 반환됩니다. 맥락 FunctionType은 불투명한 선택 토큰을
스칼라 스키마 입력으로 전달하고 객체 값인 조회 결과는 의존성 전용으로 유지합니다. 따라서
연결되지 않은 모델 노드는 특수 읽기를 호출할 수 없습니다.

Operator 인스턴스 변환 결과는 인증된 principal과 활성 세대에서 토큰을 발급하며, 잘린 변환 결과는
신원을 완전히 생략합니다. 공유 범위 다이제스트는 소문자 일반 역할(`reader`, `contributor`,
`approver`, `owner`)만 사용하고 `BreakGlass`는 거부합니다. 정확한 ID 조건식은 최대 128개씩
묶어 조회하고 이러한 객체 전용 읽기에서는 관계 구체화와 관계 완전성 검사를 생략합니다. Wire
계약은 보수적인 512개 ID 맥락 묶음을 허용하고 일반 ObjectSet과 저장소 상한은 1,000개로
유지합니다. 맥락 계약은 incident, screen 및 resource-group 신원을 혼합하는 입력을 거부하며,
정확한 선택 읽기는 출처 세대 증적을 보존합니다. 같은 512개 상한을 Operator/Core 스키마가 함께
적용하므로 과도한 클라이언트 맥락은 계획에 들어갈 수 없습니다. 범위가 제한된 의미 조회 JSON
묶음은 512개 ID 선택에 맞게 크기를 확보하면서도 일반 출력의 기존 행 및 바이트 상한은 제거하지
않습니다.

## 토픽과 실행 장소

SDK는 두 의미 채널이 하나의 물리 Event Hub를 공유할 때 사용하는 논리 토픽 표시와 결정론적 소비자
그룹 파생 규칙을 소유합니다. Core와 Operator는 서로 다른 어댑터, 코덱, 신원, 논리 토픽 및 오프셋
그룹을 유지하며 상대 서비스 구현을 가져오지 않습니다. 같은 계약은 대상 Terraform 상태가 새 출력을
아직 구체화하지 않았을 때 사용하는 정규 물리 토픽 기본값도 제공합니다.

SDK는 `notification-delivery-receipt` wire 스키마와 정규 논리 토픽도 소유합니다. Operator는 기존
multiplex 물리 토픽을 통해 관찰을 인증하고 게시하며, Core만 이미 수락된 전달에 관찰을 적용합니다.
이 계약은 알림 대상이나 실행 권한을 부여하지 않습니다.

SDK는 WARA shadow 평가 토픽과 Operator 소비자 그룹 ID도 소유합니다. Core는 권한이 없는 평가
결과를 이 토픽으로 발행하고 독립 Operator 서비스는 활성 컨트롤 전체가 정확히 포함됐는지 검증한
뒤 읽기 변환 결과를 교체합니다. 공유 계약에는 wire ID만 있으며 어느 서비스에도 공급자 읽기 또는
실행 권한을 부여하지 않습니다.

SDK는 실행 장소 계약도 소유합니다. `FDAI_EXECUTION_VENUE`를 해석하는 유일한 resolver와 장소가
선택하는 기능 플래그 표 하나입니다. 모든 프로세스가 같은 변수를 해석하고 독립 서비스는 Core
컨트롤 플레인을 가져올 수 없으므로 특정 서비스가 아니라 여기에 둡니다. `fdai/runtime/venue.py`는
이를 다시 내보내기만 하고 자체 바인딩을 선언하지 않습니다.

## 호환성과 이미지

서비스 분포 5개는 배포 가능한 `0.1.2` 이미지를 N-1, `0.1.3`을 N으로 사용합니다. 기존
contract-set `1.0.0`/`1.1.0` 매트릭스는 프로세스 간 호환성 경계로 유지합니다. 내용 기반 주소를
가진 실제 운영 근거는 정확한 서비스와 관측 종류도 연결하고 `observed=true`를 요구합니다.
다이제스트를 다시 계산해도 관측하지 않은 주장은 실제 운영 증적이 될 수 없습니다.

패키지 테스트 트리는 SDK 동작을 검증합니다. 서비스 간 N/N-1 및 토폴로지 검사는
[루트 통합 테스트](../../tests/integration/)에 유지합니다. 배포 가능한 서비스 이미지는 고정된
Alpine Python, OpenSSL, SQLite 및 util-linux 런타임 패키지를 공유합니다. 이미지 계약과 Trivy
게이트는 Dockerfile 6개 모두 알려진 차단 취약점이 없는 정확한 제공 버전을 유지합니다. 문서
워커는 자신이 소유한 Tesseract 언어 데이터와 OCR 의존성만 추가합니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 저장소 소유권 | [코드 맵](../roadmap/architecture/code-map-ko.md) |
| 공유 패키지 원본 | [서비스 계약](../../packages/service-contracts/src/fdai_service_contracts/) |
