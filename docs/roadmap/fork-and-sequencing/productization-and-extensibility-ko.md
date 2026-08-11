---
title: 제품화 및 확장성 계획
translation_of: productization-and-extensibility.md
translation_source_sha: 642f8365a9884de3b990aff1c73f65d8b2be0fd0
translation_revised: 2026-08-11
---
# 제품화 및 확장성 계획

이 문서는 FDAI의 cloud-operations control-plane 경계를 약화시키지 않으면서 설치, 운영, 확장,
복구를 쉽게 만드는 product 및 platform 기능의 순서를 정의합니다. 배포,
conversational 채널, 기능 번들, 모델 라우팅, 예약, security 진단,
developer 인터페이스를 아우르는 작업의 중앙 상태 매트릭스입니다.

> **아키텍처 경계:** FDAI는 thin 읽기 전용 콘솔과 통제된 ChatOps를 사용하는 headless
> cloud-operations 컨트롤 평면으로 유지됩니다. 새 인터페이스는 실행기 신원을 받지 않으며
> 모든 변경은 타입이 지정된 trust-router, risk-gate, 승인, 실행기, 감사 경로로 다시 들어갑니다.
>
> **구현 초점:** Azure가 유일한 구현 cloud 대상으로 유지됩니다. 프로바이더 중립적인 계약은
> 보존하지만 이 계획은 다른 cloud 어댑터를 추가하지 않습니다.
>
> **상태 규칙:** 실행 가능한 코드와 focused 테스트가 있을 때만 `구현됨`으로 표시합니다.
> `부분 구현`은 안전한 기반이 있지만 운영 전송 계층, 영속 어댑터, release
> 산출물의 exit 게이트가 남은 상태입니다. `계획됨`은 design-only 상태입니다.

## 한눈에 보는 설계

이 계획은 FDAI의 기존 아키텍처를 강화하는 경우에만 productization 기능을 채택합니다.
Install과 진단은 단순해지고, 채널은 실행 권한 없이 bidirectional이 되며,
확장은 arbitrary 코드를 부하하지 않고 기존 타입이 지정된 기능에 연결되고, background 작업은
영속 원장과 범위가 제한된 장애 조치를 갖게 됩니다.

| 우선순위 | 의미 | 승격 규칙 |
|----------|------|-----------|
| P0 | 필수 platform 기반 | 통합 또는 user experience를 넓히기 전에 완료 |
| P1 | 높은 가치의 operational experience | 의존하는 P0에 executable 게이트가 생긴 후 시작 |
| P2 | 조건부 확장 | 측정된 수요와 승인된 threat 모델이 있을 때만 시작 |
| 채택하지 않음 | FDAI 앱 형태와 충돌 | 아키텍처 결정 기록을 통해서만 재검토 |

## P0 platform 기반

| ID | 기능 | 상태 | Exit 게이트 |
|----|------------|------|-----------|
| P0-01 | 설치형 `fdaictl` 항목 지점 | 구현됨 | 출처 및 휠 항목 지점이 해석되고 결정론적 `version` 텍스트 및 JSON 통과 |
| P0-02 | Toolchain 및 Azure 계정 doctor | 구현됨 | 누락된 도구/auth가 테넌트, 계정, user 식별자를 출력하지 않고 실패 시 차단 |
| P0-03 | 안전한 로컬 onboarding 구성 | 구현됨 | 스키마로 검증한 gitignored JSON이 모드 `0600`, overwrite는 `--force` 필요 |
| P0-04 | 활성 Azure 대상 mismatch 가드 | 구현됨 | 구성된 및 활성 테넌트/구독 mismatch가 작업 흐름 제출 전에 차단 |
| P0-05 | Static 배포 preflight | 구현됨 | 결정론적 입력, Terraform 계획 JSON, 실제 운영 Azure Policy/할당량/신원/시크릿, hash-only 근거 및 실패 시 차단 오류를 사용하는 범위가 제한된 실행기 TLS egress 통과 |
| P0-06 | 원격 계획 제출 | 구현됨 | 대상 id를 전송 계층 산출물에 넣지 않는 doctor-gated plan-only 전달, exact-commit 가드, 비공개 변경할 수 없는 binary 계획, 정제된 메타데이터 상태, 다이제스트/만료, 범위가 제한된 정리 통과 |
| P0-07 | Exact-plan 적용 | 구현됨 | Protected 계획이 완전한 enforce-mode Policy/할당량/신원/시크릿 검사 커버리지 및 범위가 제한된 egress 근거를 요구하며 separate 변경할 수 없는 근거 다이제스트를 점유, approval-gated 적용, convergence, 이행, 상태, 증적 전에 복원하고 verify |
| P0-08 | Signed 배포 번들 | 구현됨 | Tracked 허용 목록, 결정론적 CycloneDX 빌드/보관, 외부 Ed25519 signing, double-build 바이트 비교, 검증기 round-trip, approval-gated 산출물, 선택적 GitHub release 게시 통과 |
| P0-09 | 로컬 security 감사 | 구현됨 | 고정된 발견 사항이 auth bypass, Entra 구성, 실행 플래그, 샌드박스 준비 상태, 구성 hygiene 포함 |
| P0-10 | Narrow security auto-fix | 구현됨 | Regular 파일 `0600` 및 상위 디렉터리 `0700` 변경만 허용 |
| P0-11 | Bidirectional 채널 계약 | 구현됨 | 범위가 제한된 `InboundTurn` 및 thread-preserving `OutboundResponse` 프로토콜 테스트 통과 |
| P0-12 | 채널 principal 및 멱등성 게이트웨이 | 구현됨 | 해결되지 않은 발신자와 중복 메시지 id가 도구 호출에 도달하지 않음 |
| P0-13 | Signed Slack-style 이벤트 유입 | 구현됨 | Timestamped HMAC, 재생 구간, bot-event 차단, 범위가 제한된 큐 통과 |
| P0-14 | 인증된 Teams-style 활동 정규화 | 구현됨 | 큐 admission 전 RS256 Bot 서비스 JWT/JWKS/대상/발급자/serviceUrl 검사 및 범위가 제한된 same-tenant aadObjectId-to-canonical-principal 연결 통과 |
| P0-15 | 운영 채널 발행기 및 경로 | 구현됨 | Standalone ASGI 런타임이 시크릿 참조를 해석하고 signed Slack 및 구체적인 Teams auth/발행기를 배선하며 게이트웨이 소비자 시작, 실패 시 차단 시작, 종료 경로/작업/채널/owned HTTP 정리 통과 |
| P0-16 | 변경할 수 없는 기능 번들 런타임 | 구현됨 | 알 수 없음 대상/프로바이더가 활성 컨테이너 변경 전에 fail |
| P0-17 | Trust-verified 확장 수명 주기 | 구현됨 | 다이제스트, 발행기 trust, 호스트 호환성, 매니페스트 동등성, 비활성화된 install, atomic activation 통과 |
| P0-18 | MCP 서버 등록 및 발견 | 구현됨 | Disabled-first 카탈로그, safe 엔드포인트 검증, non-invoking `tools/list`, 영속 revision-CAS 상태, 주기적 상태, healthy-only 라우팅, atomic admin 감사 통과 |
| P0-19 | 확장 및 스킬 supply-chain 정책 | 구현됨 | Domain-separated source-keyed Ed25519 검증, lifecycle-first 비활성화된 install, PostgreSQL raw 산출물/서명 상태, exact 개정 번호 CAS, restart-safe 확장/스킬 분리 통과 |
| P0-20 | 영속 스케줄러 전달 원장 | 구현됨 | Atomic 점유, publish/fail, stale-to-lost 조정, 재시도, 이행, 운영 배선 통과 |
| P0-21 | Invariant-safe T2 기본 장애 조치 | 구현됨 | 각 same-publisher 후보를 최대 한 번 시도, all-failed는 검토로 경로 |
| P0-22 | 타입이 지정된 외부 RPC 및 클라이언트 계약 | 구현됨 | Scoped 발견, strict HTTP 상관관계, SHA-256 PostgreSQL 점유/재생 CAS, 결정론적 compilable Python stub, built-in 도구 메서드, 명시적 standalone 운영 조립 통과 |
| P0-23 | 통제된 샌드박스 프로파일 | 구현됨 | Default-deny 명령, VM-task, MCP/도구, document-converter 프로파일이 구체적인 어댑터 경계에서 서버가 소유한 기능, 모드, 접미사, 시간 초과, workspace/네트워크, 바이트 상한을 적용 |
| P0-24 | Full release 검증 | 구현됨 | Approval-gated release가 clean-checkout full 및 productization 게이트, disposable pgvector 이행/통합 테스트, pinned 의존성 감사, clean-tree 확인, reproducible signed 번들 검증, 선택적 GitHub release 게시를 요구 |

## P1 operational experience

| ID | 기능 | 의존성 | Exit 게이트 |
|----|------------|--------|-----------|
| P1-01 | 고정된, beta, 개발 release 채널 | P0-08 | 구현됨: 채널을 매니페스트에 서명하고 atomic mode-0600 업그레이드/롤백 상태가 구성 바이트를 보존하며 채널, CLI 범위, 버전, 다이제스트, 이력 mismatch를 차단 |
| P1-02 | Portable 백업 및 복원 | P0-08 | 구현됨: 결정론적 허용 목록 보관이 secret-provider 값 또는 Terraform 상태를 읽거나 내보내기하지 않고 검증된 구성, opaque 참조, 감사 해시 메타데이터, consented user 맥락을 복구 |
| P1-03 | Guided 배포 onboarding | P0-02부터 P0-08 | 구현됨: 실패 시 차단 wizard가 로컬 적용 경로 없이 toolchain 및 대상 doctor, 비공개 구성, 실제 운영 preflight, plan-only 실행기 제출, 범위가 제한된 정제된 상태 post-check를 순서대로 실행 |
| P1-04 | Rich Teams 및 Slack 스레드 행동 | P0-15 | 구현됨: 범위가 제한된 벤더 중립적인 mention 및 exclusive 스트림/편집/reaction 의도가 fixed Slack 및 Teams API로 대응되고 capability-off 경로는 originating 스레드를 텍스트로 보존하며 accepted 전송은 타입이 지정된 벤더 확인 응답을 반환 |
| P1-05 | 채널 발신자 pairing 및 허용 목록 | P0-15 | 구현됨: atomic 영속 pending 상한 및 승인, expiring 다이제스트, 서로 다른 승인자, principal 해석, same-thread native 도전자 전달 |
| P1-06 | Cross-channel 운영자 신원 링크 | P1-05 | 구현됨: 같은 principal에 독립 승인된 발신자만 명시적 영속 링크를 만들며 서로 다른 principal은 병합되지 않음 |
| P1-07 | 멀티모달 근거 첨부 | P0-15 | 구현됨: 범위가 제한된 opaque 채널 첨부가 protected 인제스트를 통과해 citation-only `doc:` 참조가 되며 bitmap 근거는 metadata-only |
| P1-08 | Managed MCP 카탈로그 | P0-18 | 구현됨: add/갱신/활성화/비활성화/remove가 revision-CAS, audited, 허용 목록에 있는, health-checked, healthy-only, restart-safe |
| P1-09 | Portable 스킬 instruction | P0-19 | 구현됨: versioned strict Markdown 매니페스트, 발행기 trust, 도구 게이트, 에이전트 허용 목록, whole-block 프롬프트 예산 통과 |
| P1-10 | 스킬 제안 workshop | P1-09 | 구현됨: inert 초안, 권한 확인, 서로 다른 검토, 감사, dedupe, PostgreSQL state-CAS 영속성, trust-verified 비활성화된 승격 통과 |
| P1-11 | 런타임 도구 검색 및 describe | P0-18 | 구현됨: installed-only RBAC-filtered 검색, 결정론적 순위, non-invoking 서술자를 채널 동사 및 타입이 지정된 읽기 RPC로 제공 |
| P1-12 | 모델 상태, cooldown, 복구 상태 | P0-21 | 구현됨: role-agnostic 민감정보가 제거된 실패/복구/선택 전이를 PostgreSQL에 저장, 범위가 제한된 cooldown 및 장애 조치는 텔레메트리 실패 시에도 유지 |
| P1-13 | Operator-visible 모델 라우팅 | P1-12 | 구현됨: Settings > Models가 라우팅 컨트롤 또는 프로바이더 시크릿 없이 선택된 배포, 민감정보가 제거된 대체 경로 사유, cooldown, 복구 표시 |
| P1-14 | User-editable 영속 기억 화면 | 기존 운영자 기억 | 구현됨: 읽기 전용 Settings 화면이 출처 이력, 범위, 만료, supersession, 승인 노출, 편집은 approved HIL/ChatOps 작업 흐름 유지 |
| P1-15 | Memory compaction 및 승격 작업 흐름 | P1-14 | 구현됨: 근거에 기반한 후보, 서로 다른 검토, atomic 영속 승격, source-preserving 롤백, no 액션 권한 통과 |
| P1-16 | Expanded 예약 타입 | P0-20 | 구현됨: one-shot, 간격, IANA-timezone cron, 정규화된 event-exit 예약을 kind-qualified 결정론적 occurrence id와 함께 저장 |
| P1-17 | 스케줄러 실행 이력 API 및 콘솔 화면 | P0-20 | 구현됨: reader-role GET 패널 및 읽기 전용 콘솔 화면이 task-scoped 상태, 시도, 실패 종류, 고정된 커서 페이지 나누기를 노출 |
| P1-18 | Scheduled-run 격리 프로파일 | P0-23 | 구현됨: 영속 default-deny 프로파일이 세션/맥락/도구 상한 및 선택적 명령 샌드박스 id를 고정하고 모든 scheduled 페이로드가 프로파일 포함 |
| P1-19 | 타입이 지정된 웹훅 대응 | P0-22 | 구현됨: 인증된 서버가 소유한 scalar 대응이 허용 목록에 있는 이벤트/에이전트 대상을 고정하고 범위가 제한된 hashed 세션 키 도출, 잘못된 페이로드는 publish하지 않음 |
| P1-20 | OpenTelemetry 내보내기 도구 및 라우팅 전이 | 기존 텔레메트리 | 구현됨: secure 선택적 OTLP/gRPC 내보내기 및 범위가 제한된 고정된 구간/메트릭을 채널, 확장, 모델, 스케줄러, security 전이에 기본값 제공 |
| P1-21 | 공개 확장 authoring 키트 | P0-17부터 P0-19 | 구현됨: strict 템플릿/스키마, `fdaictl extension validate`, 보관 다이제스트, 호스트 호환성, disabled-first, mandatory security checklist 동시 제공 |
| P1-22 | 더 넓은 localization 커버리지 | 기존 i18n | 구현됨: 모든 새 CLI/채널/admin 표면이 English 대체 경로 또는 paired 카탈로그 사용, productization 게이트가 카탈로그 동등성, translation, punctuation 강제 |
| P1-23 | Heterogeneous 모델 엔드포인트 및 게이트웨이 계약 | P0-21 | 구현됨: 기능 연결이 Azure OpenAI 또는 자체 호스팅 프로바이더, direct 또는 APIM 경로, Azure 또는 OpenAI-v1 프로토콜, Entra 대상, 타입이 지정된 용량, feature, 검증된 출처 이력을 분리하며 코어 정족수 및 서술기 전송 계층이 연결을 실패 시 차단 방식으로 사용 |
| P1-24 | PTU-aware 용량 및 APIM 라우팅 | P1-23 | 구현됨: Standard TPM과 regional/global/data-zone PTU를 별도로 검증하고 실제 운영 모델 Capacities 발견 및 정확한 Terraform PTU 개수가 통과하며 선택적 existing-APIM 정책이 day-zero 인벤토리 변경 없이 Entra, managed-identity 백엔드, PTU-first 범위가 제한된 Standard spillover, 영속 경로 근거를 적용 |
| P1-25 | 모델 엔드포인트 발견 및 Settings 인벤토리 | P1-23 | 구현됨: installable 발견이 구체적인 Azure OpenAI 계정/배포 및 APIM API/백엔드/정책 상태를 검증하고 protected resolved 메타데이터에 연결을 atomic 병합하며 domain-separated signed GPU 등록을 지원하고 런타임 상태가 있는 정제된 읽기 전용 Settings 인벤토리를 변환 결과 |
| P1-26 | 선택적 code-assurance 패키지 | P0-17부터 P1-10 | 구현됨: 독립 휠이 범위가 제한된 읽기 전용 GitHub pull-request 코드/security 도구, exact-SHA 근거, 통제된 스킬, package-carried 도구 메타데이터, disabled-first 확장 activation을 제공하며 GitHub 쓰기 표면은 없음 |

공개 확장 키트는 `examples/extension-kit/extension-kit.template.json`에 있고 머신 스키마는
`rule-catalog/schema/extension-kit.schema.json`에 있습니다. 다음을 실행합니다.

```bash
fdaictl extension validate \
 --manifest extension-kit.json \
 --archive extension.zip \
 --host-version 1.0.0
```

검증은 offline입니다. Strict 매니페스트, 보관 SHA-256, 호스트 semantic-version 범위, unique
기능 id, disabled-first 상태, mandatory security 검토를 검사합니다. Dynamic 코드, embedded
자격 증명, direct 실행기 접근, 네트워크 installer, default-enforce 행동은 schema-level
실패입니다.

선택적 `extensions/code-assurance/` workspace 패키지는 FDAI 휠 밖에 유지됩니다. `Pull
requests: 읽기` 근거만 사용하고 파일 및 patch character를 제한하며 페이지 나누기 뒤 변경할 수 없는 base 및
헤드 SHA를 다시 확인하고 omitted patch를 불완전한 커버리지로 보고합니다. 두 도구와 스킬은
shadow 모드에서 시작합니다. Digest-bound `ExtensionPackage`는 비활성화된 상태로 설치되고 atomic
activation 전에 일반 publisher-trust 검사를 요구합니다. Activation은 검토 posting, 승인,
병합 또는 실행기 권한을 부여하지 않습니다.

런타임 trust는 별도의 `fdai.extension-signature.v1` 및 `fdai.skill-signature.v1` 페이로드 도메인을
사용합니다. 구성된 발행기 출처가 Ed25519 공개 키를 선택하고 signed 페이로드는 출처,
산출물 id, 버전, 보관 또는 raw-Markdown 다이제스트를 연결합니다. 검증된 산출물은
비활성화된으로 install되고 exact raw 바이트 및 detached 서명과 함께 PostgreSQL에 저장됩니다.
Revision-CAS 갱신은 동시 activation 또는 버전 replacement를 차단하며 durable-write
충돌은 후보 런타임 카탈로그를 반환하지 않습니다. 데이터베이스는 발행기 비공개 키를
저장하지 않습니다.

타입이 지정된 RPC side-effect 키는 PostgreSQL 저장 전에 SHA-256으로 해시됩니다. Atomic 삽입이 복제본
전체에서 하나의 요청을 점유합니다. Completed 응답 묶음은 호출자의 현재 요청 id로
재생되고 unexpected 실패는 side 효과를 재시도하지 않고 모호한 in-flight 점유를
남깁니다. 발견 서술자는 결정론적 Python 비동기 stub를 생성하며 정규화된 method-name
충돌 또는 malformed 서술자는 세대를 실패시킵니다. Standalone 운영 앱은
호출자 authorizer 뒤에 상태, built-in non-invoking 도구 발견, explicitly supplied 메서드만
mount하고 영속 PostgreSQL 점유 저장소를 기본으로 사용합니다.

## P2 conditional expansion

| ID | 기능 | 채택 조건 | 필수 guardrail |
|----|------------|-----------|----------------|
| P2-01 | 추가 messaging 채널 | 명확한 운영자 수요와 관리자 | P0 채널과 같은 principal, 멱등성, 스레드, trust 계약 |
| P2-02 | 로컬 모델 엔드포인트 | 측정된 disconnected 또는 data-residency 수요 | Approved 배포 경계, 모델 quality 하한, quality-gate 계열 collapse 금지 |
| P2-03 | Subscription-backed 모델 authentication | 승인된 신원 및 청구 모델 | Per-capability 자격 증명, cooldown 가시성, 런타임의 shared 운영자 토큰 금지 |
| P2-04 | 외부 assistant 기억 가져오기 | 이행 수요 | 미리 보기, 충돌 처리, 백업, 출처 이력, 자격 증명/대화 기록 가져오기 금지 |
| P2-05 | Conditional 스케줄러 watcher | State-change 트리거의 측정된 필요 | 읽기 전용 스크립트, strict 도구 상한, 시간 예산, state-size 상한, 별도 액션 페이로드 |
| P2-06 | Proactive 운영자 commitment | 승인된 알림 정책 | 명시적 명시적 선택, 만료, same-principal 범위, inferred 변경 금지 |
| P2-07 | OpenAI-compatible 읽기 인터페이스 | 클라이언트 interoperability 수요 | 읽기 전용 또는 proposal-only 범위, 실행기 bypass 금지, 명시적 auth 범위 |
| P2-08 | 추가 기억 백엔드 | 규모 또는 수집 근거 | One 정본, 결정론적 재구축, 테넌트 격리, measured 재현율 quality |

## 채택하지 않는 기능

다음 기능은 현재 FDAI 앱 형태에 맞지 않으며 incremental feature 작업으로 구현에
들어가지 않습니다.

- **일반 desktop 또는 mobile personal-assistant 애플리케이션:** Operator 콘솔은 thin 읽기
 표면으로 유지하고 ChatOps가 기존 업무 채널에서 운영자에게 도달합니다.
- **Wake-word, continuous 어조, camera, 위치, SMS-device, screen-control 노드:** Cloud-operations
 컨트롤과 관계없는 device-trust 도메인을 만듭니다.
- **일반 브라우저 또는 full-host computer 컨트롤:** FDAI는 프로바이더 API, policy-as-code,
 통제된 명령 카탈로그, 범위가 제한된 작업 실행기를 사용합니다. Operator의 로그인된 브라우저
 프로파일을 자동화하지 않습니다.
- **Arbitrary dynamic 코드/플러그인 로딩:** 확장은 검토된 타입이 지정된 번들을 등록합니다.
 컨트롤 평면 안에서 검토되지 않은 패키지를 download하고 실행하지 않습니다.
- **서로 신뢰하지 않는 테넌트를 위한 shared 게이트웨이 하나:** 각 customer 포크와 배포가
 자체 신원, 상태, 정책, 감사 경계를 유지합니다.
- **Console-issued privileged 액션:** Console은 읽기 전용으로 유지됩니다. Command는 CLI, ChatOps,
 PR 또는 인증된 제안 API로 들어와 standard 컨트롤 루프를 따릅니다.

## 제공 순서

1. P1 확장 중에도 모든 P0 배포 및 release 게이트를 강제 적용 상태로 유지합니다.
2. release/백업/onboarding, 채널 richness, 확장 및 스킬 UX, 모델 상태, 기억,
 예약, 웹훅, observability, authoring 키트 순으로 P1을 구현합니다.
3. 각 P2 항목을 측정된 운영자 demand, 비용, threat 모델에 대해 평가합니다.
4. 모든 새 액션은 자체 승격 게이트를 통과할 때까지 shadow 모드로 유지합니다.

## 검증

각 배치는 가장 좁은 executable 테스트를 먼저 실행한 다음 영향을 받는 subsystem 모음을
실행합니다. P0 항목은 해당되는 다음 공통 검사가 통과해야 완료됩니다.

```bash
uv run ruff check <changed-paths>
uv run mypy <changed-python-package>
uv run pytest <focused-tests> -q
bash scripts/quality/localization/check-translations.sh
bash scripts/quality/repository/check-punctuation.sh
```

release 배치는 clean 체크아웃에서 `scripts/verify.sh --all`도 실행하고 휠 및 배포
번들을 빌드하고 isolated 환경에 휠을 설치하고 서명을 검증하고 disposable
PostgreSQL 데이터베이스에서 이행 업그레이드 검사를 실행합니다. release 작업 흐름은 환경이
signing 키를 노출하기 전에 이 순서를 적용합니다. 별도 의존성 감사도 통과해야 하며
gated 번들 작업만 저장소 쓰기 권한을 받습니다.

Executable productization 게이트에는 `scripts/deployment/release/verify-productization.sh`를 실행합니다. 이 계획의
subsystem을 검사하고 Alembic 헤드가 하나인지 확인하고 휠을 빌드하고 isolated `uvx`
install로 `fdaictl version --output json`을 실행합니다. Full 저장소 게이트 또는 실제 운영 disposable
데이터베이스 이행 실행을 대체하지 않습니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| Cross-subsystem 구현 wave | [implementation-plan-ko.md](implementation-plan-ko.md) |
| Install 및 배포 administration | [../deployment/installable-deployment-cli-ko.md](../deployment/installable-deployment-cli-ko.md) |
| Conversational 채널 및 도구 | [../interfaces/operator-console-ko.md](../interfaces/operator-console-ko.md) |
| 기능 번들 및 DI 경계 | [../architecture/project-structure-ko.md](../architecture/project-structure-ko.md) |
| 모델 라우팅 및 mixed-model 제약 | [../architecture/llm-strategy-ko.md](../architecture/llm-strategy-ko.md) |
| 통제된 예약 및 프로세스 | [../decisioning/process-automation-ko.md](../decisioning/process-automation-ko.md) |
| Security 및 신원 | [../architecture/security-and-identity-ko.md](../architecture/security-and-identity-ko.md) |
