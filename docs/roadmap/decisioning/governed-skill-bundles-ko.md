---
translation_of: governed-skill-bundles.md
translation_source_sha: 12d0c5ca3a34c9a108e77070ecca35748ca4a702
translation_revised: 2026-08-14
---
# 통제된 스킬 Bundles

통제된 스킬 번들은 이미 설치된 런타임 스킬의 ordered, 검토된 집합을 고정된 식별자 하나로
호출하게 합니다. 번들은 instruction만 compose합니다. 누락된 스킬을 install하거나 도구를 추가하고,
에이전트 허용 목록을 넓히며, 변경을 승인하거나 액션을 실행하지 않습니다.

> **범위:** 버전 1은 direct 스킬 구성원만 지원합니다. 중첩된 번들과 automatic 선택은
> 지원하지 않습니다. 수동 호출과 결정론적 작업 흐름 첨부는 명시적 입력입니다.

## Design at a glance

정본 JSON 매니페스트는 exact 구성원 버전, bundle-level 선행 조건, 선택적 범위가 제한된
instruction, 출처 이력, self-digest를 선언합니다. Detached 서명은 single-skill 및 확장
서명과 분리된 `fdai.skill-bundle-signature.v1` 도메인을 사용합니다. Install은 disabled-first입니다.

해석은 atomic합니다. FDAI는 번들 서명과 모든 구성원의 활성화된 상태, exact 버전,
발행기 trust, 본문 다이제스트, 도구 선행 조건, 에이전트 충족 여부를 다시 확인합니다. 하나라도 실패하면
고정된 거절 사유 하나만 반환하고 구성원 내용은 반환하지 않습니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 정본 매니페스트, 스키마, 서명 도메인, 변경 불가능 카탈로그 | implemented | `rule-catalog/schema/skill-bundle.schema.json`; `services/core-control-plane/src/fdai/core/skills/bundle_manifest.py`; `services/core-control-plane/src/fdai/core/skills/bundle_catalog.py`; `services/core-control-plane/tests/core/skills/test_bundle_manifest.py`; `services/core-control-plane/tests/core/skills/test_bundle_catalog.py`; `services/core-control-plane/tests/rule_catalog/schema/test_skill_bundle_schema.py` | focused test는 정본 바이트, 중복 및 알 수 없는 필드, 정확한 버전, 자체 다이제스트, 서명 분리, 비활성 우선 설치, 권한 비확장, 원자적 해석, 고정된 거절 사유를 다룹니다. |
| 감사되는 수명 주기 및 workshop 검토 | implemented | `services/core-control-plane/src/fdai/core/skills/bundle_lifecycle.py`; `services/core-control-plane/src/fdai/core/skills/bundle_workshop.py`; `services/core-control-plane/tests/core/skills/test_bundle_lifecycle.py`; `services/core-control-plane/tests/core/skills/test_bundle_workshop.py` | focused test는 변경 불가능 전이, 롤백 경로, 내용 없는 감사 이벤트, 자체 검토 차단, 반복 서명 검증, 비활성 승격을 입증합니다. |
| 런타임 해석, 프롬프트 변환, 재생 메타데이터, quality-gate 감사 직렬화 | implemented | `services/core-control-plane/src/fdai/core/skills/runtime.py`; `services/core-control-plane/src/fdai/core/prompts/skill_disclosure.py`; `services/core-control-plane/tests/core/skills/test_bundle_runtime.py`; `services/core-control-plane/tests/core/prompts/test_skill_bundle_disclosure.py` | focused test는 전체 구성원 로드, all-or-nothing 예산 및 신뢰 실패, 결정론적 번들 프롬프트 계층, 선택 및 거절 재생 레코드, 내용 없는 감사 메타데이터를 다룹니다. |
| 영속 산출물 codec, 격리된 산출물 종류, fail-closed 시작 재구성 | implemented | `services/core-control-plane/src/fdai/core/supply_chain/skill_bundle.py`; `services/core-control-plane/src/fdai/core/supply_chain/skill_bundle_loader.py`; `alembic/versions/20260720_0042_skill_bundle_artifacts.py`; `services/core-control-plane/tests/core/supply_chain/test_skill_bundle.py`; `services/core-control-plane/tests/core/supply_chain/test_skill_bundle_loader.py` | focused test는 결정론적 산출물 인코딩, 잘못된 archive 거부, 다이제스트 및 신원 검증, 활성 상태 복원, 중복 거부, fail-closed 재시작 동작을 다룹니다. 이 상태는 실제 데이터베이스 이행이나 배포된 재시작을 주장하지 않습니다. |
| Bragi 명령, 타입이 지정된 RPC, 읽기 전용 Console 점검 | in-progress | `services/core-control-plane/src/fdai/core/conversation/skill_discovery.py`; `services/core-control-plane/src/fdai/core/rpc/skill_discovery.py`; `services/core-control-plane/tests/core/rpc/test_skill_discovery.py`; `console/src/routes/skills.tsx`; `console/src/routes/skills.test.ts` | focused test는 읽기 범위 RPC 등록과 변경 control이 없는 fail-closed Console decoding을 입증합니다. 번들 RPC 연산 호출, Bragi 명령 직접 테스트, 세 화면 모두 하나의 권위 있는 운영 스냅샷을 사용함은 입증하지 않습니다. |
| 운영 composition 및 거버넌스가 적용된 런타임 근거 | in-progress | `services/core-control-plane/src/fdai/core/skills/runtime.py`; `services/core-control-plane/src/fdai/core/supply_chain/skill_bundle_loader.py` | 소스와 focused test는 구현 주장을 뒷받침하지만, 이행, 재시작 재구성, 번들 게시, 점검, 해석, 감사 동작을 하나의 배포 흐름에서 입증하는 거버넌스 적용 런타임 receipt가 없습니다. 따라서 어떤 행도 `validated`가 아닙니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-14 | in-progress | 이전 출처를 재구성하지 않고 구현 ledger를 도입했습니다. focused test로 뒷받침되는 매니페스트, 카탈로그, 수명 주기, workshop, 해석, 프롬프트, 재생, 산출물, 시작 loader 동작을 implemented로 기록하고 불완전한 전달 화면 근거와 배포된 런타임 검증을 분리했습니다. | `current change`; 구현 범위 표에 나열된 소스 및 focused test; route가 지정한 core suite (`51 passed`); `uv run pytest -q --no-cov services/core-control-plane/tests/core/rpc/test_skill_discovery.py` (`2 passed`); `npm --prefix console test -- --run src/routes/skills.test.ts` (`3 passed`) | Bragi 및 번들 RPC 연산 직접 coverage를 추가하고, 실제 영속 재시작과 운영 composition을 입증하며, `validated`를 주장하기 전에 거버넌스가 적용된 런타임 receipt를 수집합니다. |

### 남은 작업

- [ ] 목록, 설명, 로드, 거절 동작, 읽기 전용 control 경계를 다루는 Bragi 명령 및 타입이
	지정된 RPC 번들 연산 focused test를 추가한 뒤, Bragi, RPC, Console이 같은 권위 있는
	런타임 번들 스냅샷을 사용함을 입증합니다.
- [ ] 일회용 PostgreSQL 데이터베이스에 이행 `20260720_0042`를 적용하고 영속 설치,
	비활성화/활성화, 재시작 재구성, 변조된 레코드 거부 통합 테스트를 통과합니다.
- [ ] 운영 composition에서 서명된 스킬 재구성을 서명된 번들 재구성보다 먼저 연결하고,
	트래픽을 받기 전에 두 스냅샷을 모두 게시함을 입증하는 통합 테스트를 통과합니다.
- [ ] 범위 행을 `validated`로 변경하기 전에 영속 재시작, 운영자 점검, 원자적 프롬프트
	해석, 거절 감사, 재생에 대한 거버넌스 적용 런타임 근거를 수집합니다.

## 산출물 계약

공개 스키마는
[`rule-catalog/schema/skill-bundle.schema.json`](../../../rule-catalog/schema/skill-bundle.schema.json)입니다.
정본 파서와 도메인 모델은
[`core/skills/bundle_manifest.py`](../../../services/core-control-plane/src/fdai/core/skills/bundle_manifest.py)에 있습니다.

| 필드 | 계약 |
|-------|----------|
| `name`, `version` | 고정된 lowercase ID와 의미 번들 버전입니다. |
| `description`, `source` | Human 요약과 발행기 출처 이력입니다. |
| `members` | Exact `==MAJOR.MINOR.PATCH` 제약을 가진 ordered 1-16 스킬 참조입니다. |
| `allowed_agents` | 번들 허용 목록입니다. Effective 에이전트는 모든 구성원 및 런타임과의 intersection입니다. |
| `required_tools` | 완전한 declared 선행 조건입니다. 모든 구성원 도구를 포함해야 하며 도구를 권한 부여하지 않습니다. |
| `instruction` | 선택적 완전한 instruction이며 8 KiB 제한입니다. Truncate하지 않습니다. |
| `digest` | 다이제스트 자리를 제외한 정본 매니페스트 필드의 SHA-256입니다. |

알 수 없음 키, 중복 JSON 키, 중복 구성원, non-canonical 바이트, non-exact 버전, 다이제스트
mismatch는 trust 또는 카탈로그 변경 전에 파서 경계에서 실패합니다.

## 수명 주기 and 검토

`SkillBundleCatalog`는 변경할 수 없는이며 모든 연산은 새 후보 카탈로그를 반환합니다.

| 전이 | 필수 checks | Rollback |
|------------|-----------------|----------|
| Install | 정본 파서, self-digest, detached 발행기 서명, unique ID | 비활성화된 상태에서 uninstall합니다. |
| 활성화 | 모든 구성원이 installed, 활성화된, trusted, exact-version compatible, dependency-complete, agent-compatible | 같은 signed 매니페스트를 비활성화합니다. |
| 비활성화 | Installed 번들 | 같은 full 검증 후 re-enable합니다. |
| Uninstall | 번들이 이미 비활성화된 | 보존된 signed 매니페스트를 검토를 거쳐 reinstall합니다. |

`SkillBundleLifecycle`은 install, 활성화, 비활성화, uninstall의 내용이 없는 이벤트를 덧붙이기합니다.
Event는 행위자, 사유, 시각, ID, 버전, 다이제스트, before/after 상태를 기록하며 번들 instruction
또는 구성원 본문은 기록하지 않습니다.

`SkillWorkshop`은 별도 번들 제안 저장소를 통해 번들 propose, 검토, materialize, 비활성화된
승격을 제공합니다. 제안자는 self-review할 수 없습니다. 승격은 서명 검증을
다시 수행하며 번들을 활성화하지 않습니다.

## 해석 and 기능 intersection

해석기는 다음 순서로 검사합니다.

1. Stored 정본 바이트를 다시 parse하고 번들 서명을 재검사합니다.
2. 모호한 이름과 의존성 cycle을 찾습니다. Non-cyclic 중첩된 참조도 버전 1 범위 밖이라 거부합니다.
3. 번들, 구성원, requested 에이전트, known 에이전트, 런타임 도구 충족 여부를 intersect합니다.
4. Progressive 스킬 공개 trust 경로로 모든 구성원을 완전한 부하합니다.
5. Combined instruction/본문 예산을 확인한 뒤 모든 구성원을 함께 반환합니다.

해석기는 접두사를 반환하지 않습니다. 구성원 갱신, 비활성화, 제거, trust 실패는 다음
해석을 무효화합니다. 이미 해석된 변경할 수 없는 값은 이를 소유한 활성 대화에서
계속 재생할 수 있습니다.

## 프롬프트, 작업 흐름, and 재생

`SkillDisclosureRequest.selected_bundle_names`는 명시적 ID를 최대 2개 받습니다. 작성기는 번들을
순위하거나 auto-select하지 않습니다. 작업 흐름은 결정론적 입력에 같은 fixed ID를 첨부할 수 있습니다.

선택한 번들 하나는 완전한 번들 instruction과 ordered 완전한 구성원 본문을 포함한 하나의
`skill-bundle` 프롬프트 계층이 됩니다. `PromptReplayManifest.skill_bundle_records`는 번들
ID/버전/다이제스트, raw 매니페스트 SHA-256, 구성원 버전 및 본문/raw 다이제스트, 선택된/rejected 상태,
거절 사유를 보존합니다. Quality-gate 감사도 비공개 내용 없이 같은 메타데이터를 serialize합니다.

## 런타임 and 콘솔

운영은 번들 매니페스트를 `trusted_artifact.artifact_kind=skill_bundle`로 저장합니다. 이행
`20260720_0042`가 isolated 종류를 추가합니다. 시작은 signed 스킬을 먼저, signed 번들을 다음에
재구성하고 트래픽을 받기 전에 두 스냅샷을 하나의 `RuntimeSkillDisclosure`에 publish합니다.

Bragi는 `list_skill_bundles`, `describe_skill_bundle`, `load_skill_bundle`을 사용할 수 있습니다.
Exact 명령은 결정론적하게 실행되고 natural-language 턴에는 같은 스키마가 제공됩니다. 타입이 지정된
RPC는 같은 연산을 읽기 범위의 `skill_bundles.*`로 노출합니다.

읽기 전용 거버넌스 > Skills 패널은 구성원 순서, exact 버전, 의존성, 호환성, trust
recheck 상태, effective 충족 여부를 표시합니다. Install, 활성화, 검토, 승인, 실행 컨트롤은 없습니다.

## 실패 reasons

고정된 진단은 누락된, 비활성화된, version-incompatible, 신뢰할 수 없는, undeclared 의존성,
사용 불가 도구, disallowed 에이전트, 모호한 이름, cycle, 지원하지 않는 중첩, combined-budget 실패를
구분합니다. 거절 기록은 공개 ID와 다이제스트를 포함할 수 있지만 선택적 instruction, 구성원 본문,
참조 내용은 포함하지 않습니다.

## 검증

Focused 커버리지는 스키마/파서 동등성, signature-domain separation, 수명 주기 감사/롤백,
누락된/비활성화된/incompatible 구성원, no-widening intersection, cycle/모호함, member-update invalidation,
atomic 프롬프트 변환 결과, 재생/감사 직렬화, workshop 검토, 영속 재시작, Command Deck
호출, 타입이 지정된 RPC, 콘솔 디코딩을 포함합니다.
release 작업 흐름 액션 업그레이드는 정본 번들 바이트, detached 서명, 다이제스트 검증,
reproducibility 검사, 승인 경계를 보존해야 하며 산출물 전송 계층 구현만 변경할 수
있습니다.

## Related docs

| To learn about | 읽기 |
|----------------|------|
| Progressive single-skill 공개 | [프롬프트 조립](prompt-composition-ko.md#reviewed-runtime-skill) |
| 영속 trusted 산출물과 조립 | [Project Structure](../architecture/project-structure-ko.md) |
| 읽기 전용 운영자 점검 | [Operator Console](../interfaces/operator-console-ko.md) |
