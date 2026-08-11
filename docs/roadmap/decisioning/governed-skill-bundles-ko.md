---
translation_of: governed-skill-bundles.md
translation_source_sha: 1a8f62cebc15f7bbb0dd328aa0733be55f3a7b67
translation_revised: 2026-08-11
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
서명과 분리된 `fdai.skill-bundle-signature.v1` domain을 사용합니다. Install은 disabled-first입니다.

해석은 atomic합니다. FDAI는 번들 서명과 모든 구성원의 활성화된 상태, exact 버전,
발행기 trust, 본문 다이제스트, 도구 선행 조건, 에이전트 충족 여부를 다시 확인합니다. 하나라도 실패하면
고정된 거절 사유 하나만 반환하고 구성원 내용은 반환하지 않습니다.

## 산출물 계약

공개 스키마는
[`rule-catalog/schema/skill-bundle.schema.json`](../../../rule-catalog/schema/skill-bundle.schema.json)입니다.
정본 파서와 domain 모델은
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
