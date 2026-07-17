---
title: 제품화 및 확장성 계획
translation_of: productization-and-extensibility.md
translation_source_sha: dbe2e24c902301a6efc8ba1e001b0d16965986af
translation_revised: 2026-07-17
---
# 제품화 및 확장성 계획

이 문서는 FDAI의 cloud-operations control-plane 경계를 약화시키지 않으면서 설치, 운영, 확장,
복구를 쉽게 만드는 product 및 platform capability의 순서를 정의합니다. Deployment,
conversational channel, capability bundle, model routing, scheduling, security diagnostics,
developer interface를 아우르는 작업의 중앙 상태 matrix입니다.

> **아키텍처 경계:** FDAI는 thin read-only console과 governed ChatOps를 사용하는 headless
> cloud-operations control plane으로 유지됩니다. 새 interface는 executor identity를 받지 않으며
> 모든 mutation은 typed trust-router, risk-gate, approval, executor, audit path로 다시 들어갑니다.
>
> **구현 초점:** Azure가 유일한 구현 cloud target으로 유지됩니다. Provider-neutral contract는
> 보존하지만 이 계획은 다른 cloud adapter를 추가하지 않습니다.
>
> **상태 규칙:** 실행 가능한 code와 focused test가 있을 때만 `구현됨`으로 표시합니다.
> `부분 구현`은 안전한 foundation이 있지만 production transport, durable adapter, release
> artifact의 exit gate가 남은 상태입니다. `계획됨`은 design-only 상태입니다.

## 한눈에 보는 설계

이 계획은 FDAI의 기존 architecture를 강화하는 경우에만 productization 기능을 채택합니다.
Install과 diagnostics는 단순해지고, channel은 execution authority 없이 bidirectional이 되며,
extension은 arbitrary code를 load하지 않고 기존 typed capability에 bind되고, background work는
durable ledger와 bounded failover를 갖게 됩니다.

| 우선순위 | 의미 | 승격 규칙 |
|----------|------|-----------|
| P0 | 필수 platform foundation | Integration 또는 user experience를 넓히기 전에 완료 |
| P1 | 높은 가치의 operational experience | 의존하는 P0에 executable gate가 생긴 후 시작 |
| P2 | 조건부 확장 | 측정된 수요와 승인된 threat model이 있을 때만 시작 |
| 채택하지 않음 | FDAI app shape와 충돌 | Architecture decision record를 통해서만 재검토 |

## P0 platform foundation

| ID | Capability | 상태 | Exit gate |
|----|------------|------|-----------|
| P0-01 | 설치형 `fdaictl` entry point | 구현됨 | Source 및 wheel entry point가 resolve되고 deterministic `version` text 및 JSON 통과 |
| P0-02 | Toolchain 및 Azure account doctor | 구현됨 | 누락된 tool/auth가 tenant, account, user identifier를 출력하지 않고 fail closed |
| P0-03 | 안전한 local onboarding config | 구현됨 | Schema-validated gitignored JSON이 mode `0600`, overwrite는 `--force` 필요 |
| P0-04 | 활성 Azure target mismatch guard | 구현됨 | Configured 및 active tenant/subscription mismatch가 workflow submission 전에 차단 |
| P0-05 | Static deployment preflight | 구현됨 | Deterministic input, Terraform plan JSON, live Azure Policy/quota/identity/secret, hash-only evidence 및 fail-closed error를 사용하는 bounded runner TLS egress 통과 |
| P0-06 | Remote plan submission | 구현됨 | Target id를 transport artifact에 넣지 않는 doctor-gated plan-only dispatch, exact-commit guard, private immutable binary plan, sanitized metadata status, digest/expiry, bounded cleanup 통과 |
| P0-07 | Exact-plan apply | 구현됨 | Protected plan이 complete enforce-mode Policy/quota/identity/secret check coverage 및 bounded egress evidence를 요구하며 separate immutable evidence digest를 claim, approval-gated apply, convergence, migration, health, receipt 전에 restore하고 verify |
| P0-08 | Signed deployment bundle | 구현됨 | Tracked allowlist, deterministic CycloneDX build/archive, external Ed25519 signing, double-build byte comparison, verifier round-trip, approval-gated artifact, optional GitHub Release 게시 통과 |
| P0-09 | Local security audit | 구현됨 | Stable finding이 auth bypass, Entra config, execution flag, sandbox readiness, config hygiene 포함 |
| P0-10 | Narrow security auto-fix | 구현됨 | Regular file `0600` 및 parent directory `0700` 변경만 허용 |
| P0-11 | Bidirectional channel contract | 구현됨 | Bounded `InboundTurn` 및 thread-preserving `OutboundResponse` protocol test 통과 |
| P0-12 | Channel principal 및 idempotency gateway | 구현됨 | Unresolved sender와 duplicate message id가 tool call에 도달하지 않음 |
| P0-13 | Signed Slack-style event ingress | 구현됨 | Timestamped HMAC, replay window, bot-event 차단, bounded queue 통과 |
| P0-14 | Authenticated Teams-style activity normalization | 구현됨 | Queue admission 전 RS256 Bot service JWT/JWKS/audience/issuer/serviceUrl 검사 및 bounded same-tenant aadObjectId-to-canonical-principal binding 통과 |
| P0-15 | Production channel publisher 및 route | 구현됨 | Standalone ASGI runtime이 secret ref를 resolve하고 signed Slack 및 concrete Teams auth/publisher를 wiring하며 gateway consumer 시작, fail-closed startup, shutdown route/task/channel/owned HTTP cleanup 통과 |
| P0-16 | Immutable capability bundle runtime | 구현됨 | Unknown target/provider가 active container 변경 전에 fail |
| P0-17 | Trust-verified extension lifecycle | 구현됨 | Digest, publisher trust, host compatibility, manifest parity, disabled install, atomic activation 통과 |
| P0-18 | MCP server registration 및 discovery | 구현됨 | Disabled-first catalog, safe endpoint validation, non-invoking `tools/list`, durable revision-CAS state, periodic health, healthy-only routing, atomic admin audit 통과 |
| P0-19 | Extension 및 skill supply-chain policy | 구현됨 | Domain-separated source-keyed Ed25519 verification, lifecycle-first disabled install, PostgreSQL raw artifact/signature state, exact revision CAS, restart-safe extension/skill 분리 통과 |
| P0-20 | Durable scheduler dispatch ledger | 구현됨 | Atomic claim, publish/fail, stale-to-lost reconcile, retry, migration, production wiring 통과 |
| P0-21 | Invariant-safe T2 primary failover | 구현됨 | 각 same-publisher candidate를 최대 한 번 시도, all-failed는 review로 route |
| P0-22 | Typed external RPC 및 client contract | 구현됨 | Scoped discovery, strict HTTP correlation, SHA-256 PostgreSQL claim/replay CAS, deterministic compilable Python stub, built-in tool method, explicit standalone production composition 통과 |
| P0-23 | Governed sandbox profile | 구현됨 | Default-deny command, VM-task, MCP/tool, document-converter profile이 concrete adapter boundary에서 server-owned capability, mode, suffix, timeout, workspace/network, byte ceiling을 적용 |
| P0-24 | Full release verification | 구현됨 | Approval-gated release가 clean-checkout full 및 productization gate, disposable pgvector migration/integration test, pinned dependency audit, clean-tree 확인, reproducible signed bundle verification, optional GitHub Release 게시를 요구 |

## P1 operational experience

| ID | Capability | 의존성 | Exit gate |
|----|------------|--------|-----------|
| P1-01 | Stable, beta, development release channel | P0-08 | 구현됨: channel을 manifest에 서명하고 atomic mode-0600 upgrade/rollback state가 config byte를 보존하며 channel, CLI range, version, digest, history mismatch를 차단 |
| P1-02 | Portable backup 및 restore | P0-08 | 구현됨: 결정론적 allowlist archive가 secret-provider value 또는 Terraform state를 읽거나 export하지 않고 validated config, opaque reference, audit hash metadata, consented user context를 복구 |
| P1-03 | Guided deployment onboarding | P0-02부터 P0-08 | 구현됨: fail-closed wizard가 local apply path 없이 toolchain 및 target doctor, private config, live preflight, plan-only runner submission, bounded sanitized status post-check를 순서대로 실행 |
| P1-04 | Rich Teams 및 Slack thread behavior | P0-15 | 구현됨: bounded vendor-neutral mention 및 exclusive stream/edit/reaction intent가 fixed Slack 및 Teams API로 mapping되고 capability-off path는 originating thread를 text로 보존하며 accepted send는 typed vendor acknowledgement를 반환 |
| P1-05 | Channel sender pairing 및 allowlist | P0-15 | 구현됨: atomic durable pending cap 및 approval, expiring digest, distinct approver, principal resolution, same-thread native challenge delivery |
| P1-06 | Cross-channel operator identity link | P1-05 | 구현됨: 같은 principal에 독립 승인된 sender만 explicit durable link를 만들며 distinct principal은 merge되지 않음 |
| P1-07 | Multimodal evidence attachment | P0-15 | 구현됨: bounded opaque channel attachment가 protected ingestion을 통과해 citation-only `doc:` ref가 되며 bitmap evidence는 metadata-only |
| P1-08 | Managed MCP catalog | P0-18 | 구현됨: add/update/enable/disable/remove가 revision-CAS, audited, allowlisted, health-checked, healthy-only, restart-safe |
| P1-09 | Portable skill instruction | P0-19 | 구현됨: versioned strict Markdown manifest, publisher trust, tool gate, agent allowlist, whole-block prompt budget 통과 |
| P1-10 | Skill proposal workshop | P1-09 | 구현됨: inert draft, authorization, distinct review, audit, dedupe, PostgreSQL state-CAS persistence, trust-verified disabled promotion 통과 |
| P1-11 | Runtime tool search 및 describe | P0-18 | 구현됨: installed-only RBAC-filtered search, deterministic ranking, non-invoking descriptor를 channel verb 및 typed read RPC로 제공 |
| P1-12 | Model health, cooldown, recovery state | P0-21 | 구현됨: role-agnostic redacted failure/recovery/selection transition을 PostgreSQL에 저장, bounded cooldown 및 failover는 telemetry 실패 시에도 유지 |
| P1-13 | Operator-visible model routing | P1-12 | 구현됨: Settings > Models가 routing control 또는 provider secret 없이 selected deployment, redacted fallback reason, cooldown, recovery 표시 |
| P1-14 | User-editable durable memory view | 기존 operator memory | 구현됨: read-only Settings view가 provenance, scope, expiry, supersession, approval 노출, edit는 approved HIL/ChatOps workflow 유지 |
| P1-15 | Memory compaction 및 promotion workflow | P1-14 | 구현됨: grounded candidate, distinct review, atomic durable promotion, source-preserving rollback, no action authority 통과 |
| P1-16 | Expanded schedule type | P0-20 | 구현됨: one-shot, interval, IANA-timezone cron, normalized event-exit schedule을 kind-qualified deterministic occurrence id와 함께 저장 |
| P1-17 | Scheduler run history API 및 console view | P0-20 | 구현됨: reader-role GET panel 및 read-only console view가 task-scoped status, attempt, failure kind, stable cursor pagination을 노출 |
| P1-18 | Scheduled-run isolation profile | P0-23 | 구현됨: durable default-deny profile이 session/context/tool ceiling 및 optional command sandbox id를 고정하고 모든 scheduled payload가 profile 포함 |
| P1-19 | Typed webhook mapping | P0-22 | 구현됨: authenticated server-owned scalar mapping이 allowlisted event/agent target을 고정하고 bounded hashed session key 도출, invalid payload는 publish하지 않음 |
| P1-20 | OpenTelemetry exporter 및 routing transition | 기존 telemetry | 구현됨: secure optional OTLP/gRPC export 및 bounded stable span/metric을 channel, extension, model, scheduler, security transition에 default 제공 |
| P1-21 | Public extension authoring kit | P0-17부터 P0-19 | 구현됨: strict template/schema, `fdaictl extension validate`, archive digest, host compatibility, disabled-first, mandatory security checklist 동시 제공 |
| P1-22 | 더 넓은 localization coverage | 기존 i18n | 구현됨: 모든 새 CLI/channel/admin surface가 English fallback 또는 paired catalog 사용, productization gate가 catalog parity, translation, punctuation 강제 |
| P1-23 | Heterogeneous model endpoint 및 gateway contract | P0-21 | 구현됨: capability binding이 Azure OpenAI 또는 self-hosted provider, direct 또는 APIM route, Azure 또는 OpenAI-v1 protocol, Entra audience, typed capacity, feature, verified provenance를 분리하며 core quorum 및 narrator transport가 binding을 fail closed 방식으로 사용 |
| P1-24 | PTU-aware capacity 및 APIM routing | P1-23 | 구현됨: Standard TPM과 regional/global/data-zone PTU를 별도로 검증하고 live Model Capacities discovery 및 정확한 Terraform PTU count가 통과하며 optional existing-APIM policy가 day-zero inventory 변경 없이 Entra, managed-identity backend, PTU-first bounded Standard spillover, durable route evidence를 적용 |
| P1-25 | Model endpoint discovery 및 Settings inventory | P1-23 | 구현됨: installable discovery가 concrete Azure OpenAI account/deployment 및 APIM API/backend/policy state를 검증하고 protected resolved metadata에 binding을 atomic merge하며 domain-separated signed GPU registration을 지원하고 runtime health가 있는 sanitized read-only Settings inventory를 projection |

Public extension kit는 `examples/extension-kit/extension-kit.template.json`에 있고 machine schema는
`rule-catalog/schema/extension-kit.schema.json`에 있습니다. 다음을 실행합니다.

```bash
fdaictl extension validate \
  --manifest extension-kit.json \
  --archive extension.zip \
  --host-version 1.0.0
```

Validation은 offline입니다. Strict manifest, archive SHA-256, host semantic-version range, unique
capability id, disabled-first state, mandatory security review를 검사합니다. Dynamic code, embedded
credential, direct executor access, network installer, default-enforce behavior는 schema-level
failure입니다.

Runtime trust는 별도의 `fdai.extension-signature.v1` 및 `fdai.skill-signature.v1` payload domain을
사용합니다. Configured publisher source가 Ed25519 public key를 선택하고 signed payload는 source,
artifact id, version, archive 또는 raw-Markdown digest를 binding합니다. Verified artifact는
disabled로 install되고 exact raw byte 및 detached signature와 함께 PostgreSQL에 저장됩니다.
Revision-CAS update는 concurrent activation 또는 version replacement를 차단하며 durable-write
conflict는 candidate runtime catalog를 반환하지 않습니다. Database는 publisher private key를
저장하지 않습니다.

Typed RPC side-effect key는 PostgreSQL 저장 전에 SHA-256으로 hash됩니다. Atomic insert가 replica
전체에서 하나의 request를 claim합니다. Completed response envelope은 caller의 현재 request id로
replay되고 unexpected failure는 side effect를 retry하지 않고 ambiguous in-flight claim을
남깁니다. Discovery descriptor는 deterministic Python async stub를 생성하며 normalized method-name
collision 또는 malformed descriptor는 generation을 실패시킵니다. Standalone production app은
caller authorizer 뒤에 health, built-in non-invoking tool discovery, explicitly supplied method만
mount하고 durable PostgreSQL claim store를 기본으로 사용합니다.

## P2 conditional expansion

| ID | Capability | 채택 조건 | 필수 guardrail |
|----|------------|-----------|----------------|
| P2-01 | 추가 messaging channel | 명확한 operator 수요와 maintainer | P0 channel과 같은 principal, idempotency, thread, trust contract |
| P2-02 | Local model endpoint | 측정된 disconnected 또는 data-residency 수요 | Approved deployment boundary, model quality floor, quality-gate family collapse 금지 |
| P2-03 | Subscription-backed model authentication | 승인된 identity 및 billing model | Per-capability credential, cooldown visibility, runtime의 shared operator token 금지 |
| P2-04 | 외부 assistant memory import | Migration 수요 | Preview, conflict handling, backup, provenance, credential/transcript import 금지 |
| P2-05 | Conditional scheduler watcher | State-change trigger의 측정된 필요 | Read-only script, strict tool cap, time budget, state-size cap, 별도 action payload |
| P2-06 | Proactive operator commitment | 승인된 notification policy | Explicit opt-in, expiry, same-principal scope, inferred mutation 금지 |
| P2-07 | OpenAI-compatible read interface | Client interoperability 수요 | Read-only 또는 proposal-only scope, executor bypass 금지, explicit auth scope |
| P2-08 | 추가 memory backend | Scale 또는 retrieval evidence | One source of truth, deterministic rebuild, tenant isolation, measured recall quality |

## 채택하지 않는 capability

다음 capability는 현재 FDAI app shape에 맞지 않으며 incremental feature 작업으로 구현에
들어가지 않습니다.

- **일반 desktop 또는 mobile personal-assistant application:** Operator console은 thin read
  surface로 유지하고 ChatOps가 기존 업무 channel에서 operator에게 도달합니다.
- **Wake-word, continuous voice, camera, location, SMS-device, screen-control node:** Cloud-operations
  control과 관계없는 device-trust domain을 만듭니다.
- **일반 browser 또는 full-host computer control:** FDAI는 provider API, policy-as-code,
  governed command catalog, bounded task runner를 사용합니다. Operator의 로그인된 browser
  profile을 자동화하지 않습니다.
- **Arbitrary dynamic code/plugin loading:** Extension은 review된 typed bundle을 등록합니다.
  Control plane 안에서 review되지 않은 package를 download하고 실행하지 않습니다.
- **서로 신뢰하지 않는 tenant를 위한 shared gateway 하나:** 각 customer fork와 deployment가
  자체 identity, state, policy, audit boundary를 유지합니다.
- **Console-issued privileged action:** Console은 read-only로 유지됩니다. Command는 CLI, ChatOps,
  PR 또는 authenticated proposal API로 들어와 standard control loop를 따릅니다.

## 제공 순서

1. P1 확장 중에도 모든 P0 deployment 및 release gate를 enforce 상태로 유지합니다.
2. Release/backup/onboarding, channel richness, extension 및 skill UX, model health, memory,
   scheduling, webhook, observability, authoring kit 순으로 P1을 구현합니다.
3. 각 P2 항목을 측정된 operator demand, cost, threat model에 대해 평가합니다.
4. 모든 새 action은 자체 promotion gate를 통과할 때까지 shadow mode로 유지합니다.

## 검증

각 batch는 가장 좁은 executable test를 먼저 실행한 다음 영향을 받는 subsystem suite를
실행합니다. P0 항목은 해당되는 다음 공통 check가 통과해야 완료됩니다.

```bash
uv run ruff check <changed-paths>
uv run mypy <changed-python-package>
uv run pytest <focused-tests> -q
bash scripts/check-translations.sh
bash scripts/check-punctuation.sh
```

Release batch는 clean checkout에서 `scripts/verify.sh --full`도 실행하고 wheel 및 deployment
bundle을 build하고 isolated environment에 wheel을 설치하고 signature를 검증하고 disposable
PostgreSQL database에서 migration upgrade check를 실행합니다. Release workflow는 Environment가
signing key를 노출하기 전에 이 순서를 적용합니다. 별도 dependency audit도 통과해야 하며
gated bundle job만 repository write permission을 받습니다.

Executable productization gate에는 `scripts/verify-productization.sh`를 실행합니다. 이 계획의
subsystem을 검사하고 Alembic head가 하나인지 확인하고 wheel을 build하고 isolated `uvx`
install로 `fdaictl version --output json`을 실행합니다. Full repository gate 또는 live disposable
database migration run을 대체하지 않습니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| Cross-subsystem implementation wave | [implementation-plan-ko.md](implementation-plan-ko.md) |
| Install 및 deployment administration | [../deployment/installable-deployment-cli-ko.md](../deployment/installable-deployment-cli-ko.md) |
| Conversational channel 및 tool | [../interfaces/operator-console-ko.md](../interfaces/operator-console-ko.md) |
| Capability bundle 및 DI seam | [../architecture/project-structure-ko.md](../architecture/project-structure-ko.md) |
| Model routing 및 mixed-model constraint | [../architecture/llm-strategy-ko.md](../architecture/llm-strategy-ko.md) |
| Governed schedule 및 process | [../decisioning/process-automation-ko.md](../decisioning/process-automation-ko.md) |
| Security 및 identity | [../architecture/security-and-identity-ko.md](../architecture/security-and-identity-ko.md) |
