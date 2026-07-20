---
translation_of: governed-skill-bundles.md
translation_source_sha: 20c8bc2d643a433f28368aa96bedb0a77b708692
translation_revised: 2026-07-21
---
# Governed Skill Bundles

Governed skill bundle은 이미 설치된 runtime skill의 ordered, reviewed set을 stable identifier 하나로
호출하게 합니다. Bundle은 instruction만 compose합니다. Missing skill을 install하거나 tool을 추가하고,
agent allowlist를 넓히며, 변경을 승인하거나 action을 실행하지 않습니다.

> **범위:** Version 1은 direct skill member만 지원합니다. Nested bundle과 automatic selection은
> 지원하지 않습니다. Manual invocation과 deterministic workflow attachment는 explicit input입니다.

## Design at a glance

Canonical JSON manifest는 exact member version, bundle-level prerequisite, optional bounded
instruction, provenance, self-digest를 선언합니다. Detached signature는 single-skill 및 extension
signature와 분리된 `fdai.skill-bundle-signature.v1` domain을 사용합니다. Install은 disabled-first입니다.

Resolution은 atomic합니다. FDAI는 bundle signature와 모든 member의 enabled state, exact version,
publisher trust, body digest, tool prerequisite, agent eligibility를 다시 확인합니다. 하나라도 실패하면
stable rejection reason 하나만 반환하고 member content는 반환하지 않습니다.

## Artifact contract

Public schema는
[`rule-catalog/schema/skill-bundle.schema.json`](../../../rule-catalog/schema/skill-bundle.schema.json)입니다.
Canonical parser와 domain model은
[`core/skills/bundle_manifest.py`](../../../src/fdai/core/skills/bundle_manifest.py)에 있습니다.

| Field | Contract |
|-------|----------|
| `name`, `version` | Stable lowercase ID와 semantic bundle version입니다. |
| `description`, `source` | Human summary와 publisher provenance입니다. |
| `members` | Exact `==MAJOR.MINOR.PATCH` constraint를 가진 ordered 1-16 skill reference입니다. |
| `allowed_agents` | Bundle allowlist입니다. Effective agent는 모든 member 및 runtime과의 intersection입니다. |
| `required_tools` | Complete declared prerequisite입니다. 모든 member tool을 포함해야 하며 tool을 grant하지 않습니다. |
| `instruction` | Optional complete instruction이며 8 KiB 제한입니다. Truncate하지 않습니다. |
| `digest` | Digest slot을 제외한 canonical manifest field의 SHA-256입니다. |

Unknown key, duplicate JSON key, duplicate member, non-canonical byte, non-exact version, digest
mismatch는 trust 또는 catalog 변경 전에 parser boundary에서 실패합니다.

## Lifecycle and review

`SkillBundleCatalog`는 immutable이며 모든 operation은 새 candidate catalog를 반환합니다.

| Transition | Required checks | Rollback |
|------------|-----------------|----------|
| Install | Canonical parser, self-digest, detached publisher signature, unique ID | Disabled 상태에서 uninstall합니다. |
| Enable | 모든 member가 installed, enabled, trusted, exact-version compatible, dependency-complete, agent-compatible | 같은 signed manifest를 disable합니다. |
| Disable | Installed bundle | 같은 full validation 후 re-enable합니다. |
| Uninstall | Bundle이 이미 disabled | 보존된 signed manifest를 review를 거쳐 reinstall합니다. |

`SkillBundleLifecycle`은 install, enable, disable, uninstall의 content-free event를 append합니다.
Event는 actor, reason, timestamp, ID, version, digest, before/after state를 기록하며 bundle instruction
또는 member body는 기록하지 않습니다.

`SkillWorkshop`은 별도 bundle proposal store를 통해 bundle propose, review, materialize, disabled
promotion을 제공합니다. Proposer는 self-review할 수 없습니다. Promotion은 signature verification을
다시 수행하며 bundle을 enable하지 않습니다.

## Resolution and capability intersection

Resolver는 다음 순서로 검사합니다.

1. Stored canonical byte를 다시 parse하고 bundle signature를 재검사합니다.
2. Ambiguous name과 dependency cycle을 찾습니다. Non-cyclic nested reference도 version 1 범위 밖이라 거부합니다.
3. Bundle, member, requested agent, known agent, runtime tool eligibility를 intersect합니다.
4. Progressive skill disclosure trust path로 모든 member를 complete load합니다.
5. Combined instruction/body budget을 확인한 뒤 모든 member를 함께 반환합니다.

Resolver는 prefix를 반환하지 않습니다. Member update, disable, removal, trust failure는 다음
resolution을 무효화합니다. 이미 resolve된 immutable value는 이를 소유한 active conversation에서
계속 replay할 수 있습니다.

## Prompt, workflow, and replay

`SkillDisclosureRequest.selected_bundle_names`는 explicit ID를 최대 2개 받습니다. Composer는 bundle을
rank하거나 auto-select하지 않습니다. Workflow는 deterministic input에 같은 fixed ID를 attach할 수 있습니다.

선택한 bundle 하나는 complete bundle instruction과 ordered complete member body를 포함한 하나의
`skill-bundle` prompt layer가 됩니다. `PromptReplayManifest.skill_bundle_records`는 bundle
ID/version/digest, raw manifest SHA-256, member version 및 body/raw digest, selected/rejected status,
rejection reason을 보존합니다. Quality-gate audit도 private content 없이 같은 metadata를 serialize합니다.

## Runtime and console

Production은 bundle manifest를 `trusted_artifact.artifact_kind=skill_bundle`로 저장합니다. Migration
`20260720_0042`가 isolated kind를 추가합니다. Startup은 signed skill을 먼저, signed bundle을 다음에
재구성하고 traffic을 받기 전에 두 snapshot을 하나의 `RuntimeSkillDisclosure`에 publish합니다.

Bragi는 `list_skill_bundles`, `describe_skill_bundle`, `load_skill_bundle`을 사용할 수 있습니다.
Exact command는 deterministic하게 실행되고 natural-language turn에는 같은 schema가 제공됩니다. Typed
RPC는 같은 operation을 read scope의 `skill_bundles.*`로 노출합니다.

Read-only Governance > Skills panel은 member order, exact version, dependency, compatibility, trust
recheck status, effective eligibility를 표시합니다. Install, enable, review, approval, execution control은 없습니다.

## Failure reasons

Stable diagnostic은 missing, disabled, version-incompatible, untrusted, undeclared dependency,
unavailable tool, disallowed agent, ambiguous name, cycle, unsupported nesting, combined-budget failure를
구분합니다. Rejection record는 public ID와 digest를 포함할 수 있지만 optional instruction, member body,
reference content는 포함하지 않습니다.

## Verification

Focused coverage는 schema/parser parity, signature-domain separation, lifecycle audit/rollback,
missing/disabled/incompatible member, no-widening intersection, cycle/ambiguity, member-update invalidation,
atomic prompt projection, replay/audit serialization, workshop review, durable restart, Command Deck
invocation, typed RPC, console decoding을 포함합니다.

## Related docs

| To learn about | Read |
|----------------|------|
| Progressive single-skill disclosure | [Prompt Composition](prompt-composition-ko.md#reviewed-runtime-skill) |
| Durable trusted artifact와 composition | [Project Structure](../architecture/project-structure-ko.md) |
| Read-only operator inspection | [Operator Console](../interfaces/operator-console-ko.md) |
