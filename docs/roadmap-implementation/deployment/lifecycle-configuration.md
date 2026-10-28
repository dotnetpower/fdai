# Lifecycle Configuration implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Local durable publication source | implemented | `current change`; #2363; [local publication owner](../../roadmap/deployment/lifecycle-configuration-publication.md) and its focused command: 211 passed; strict mypy (4 source files) and Ruff passed | A private bounded venue preserves original packages and receipts with read-only inspection and no head rewind. Protected-merge automation, authoritative venue selection, actual trust onboarding and installed effects remain open in #1823. |
| Installation Agent full-revision source consumer and CSI metadata adapter | implemented | `current change`; `lifecycle/agent/src/fdai_lifecycle_agent/{configuration_revision,configuration_rendering,reference_state,reference_cli}.py`, `inputs.py`, `agent.py`, `cli.py`, `kube.py`; focused #2338 command below; strict mypy and Ruff | Real canonical producer/CLI container reaches the supported Agent entry point and existing artifact/signature path. Independent local active digest, current and historical keys, X25519 input, exact Release/schema and one-to-one already-managed Entity mapping fence decryption/preparation. Existing per-Entity renderers, private journal and safeguards remain. Concrete exact-namespace CSI/Pod/provider reads report provenance/freshness only, never secret values or verified usability. No live key/provider binding, rollout, operational effect receipt or production trust is claimed. |
| Acceptance-time Entity scope for retained history | implemented | `current change`; `configuration_import_trust.py`; the focused historical-scope command below passed (43 cases); strict mypy (3 source files) and Ruff passed | An ancestor uses its original independently approved mapping and acceptance receipt, not today's managed Entity set. Current import/approval/activation/consumption still require the exact current managed set. Historical Release/schema admission remains unchanged and missing catalog entries hold. |
| Atomic signed-revision import and default configured consumption | implemented | `current change`; `lifecycle/hub/src/fdai_lifecycle_hub/configuration_import_*.py`, `configuration_consumer.py`, `store.py`, `remote_catalog.py`, `migrations.py`; exact #2336 commands below: 312 focused cases and 8 isolated PostgreSQL cases passed; strict mypy and Ruff passed | Real JWT scope request/independent approval, installation identity proof, current approved key/version, exact pinned Release/schema and managed Entity map, original ciphertext container, atomic receipt/head/audit, retry/restart/fork rejection, per-ancestor accepted key/receipt, issued Plan-to-import receipt and distinct change approval/activation. Default configured recomputation needs no candidate injection. Legacy raw configuration remains unchanged; no Agent delivery, same-Release action or production qualification is claimed. |
| Approved configuration public-key source bindings and consumption | implemented | `current change`; `lifecycle/hub/src/fdai_lifecycle_hub/configuration_keys.py`, `configuration_key_store.py`, `configuration_key_api.py`, `models.py`, `migrations.py`, `store.py`, `remote.py`, `remote_catalog.py`; #2333 focused command below passed (259 cases); strict mypy and Ruff passed | Real JWT-authenticated request and independent approval, enrolled identity and signer proofs, role-separated Ed25519/X25519 public keys, immutable version/predecessor records, expiry, replay/CAS and revocation. The actual planning/store/API seam resolves durable trust and pins pending Plans to it. Local-only synthetic evidence; actual onboarding, cross-key historical-chain import, atomic package import and production qualification remain open. |
| Full multi-Entity source revision production and consumption | implemented | `current change`; `lifecycle_configuration_entities.py`, `lifecycle_configuration_document.py`, `lifecycle_configuration_package.py`, `lifecycle_configuration_cli.py`; `lifecycle/hub/src/fdai_lifecycle_hub/{configuration,planning}.py`; focused #2331 checks below | One signed v2 revision binds every independently selected opaque Entity, exact Release version/manifest digest, canonical schema and authenticated identifier mapping. Actual library/CLI production and verification, installation-local decryption and the existing in-memory Hub planner are exercised. v1 remains explicit and compatible; no trust enrollment, durable Hub import, Agent delivery, CSI resolution or production eligibility is implied. |
| Release-bound configuration schema publication, admission and planning | implemented | `current change`; `runtime_release.py`, `lifecycle_configuration.py`; `lifecycle/release-hub/src/fdai_release_hub/store.py`; `lifecycle/hub/src/fdai_lifecycle_hub/{catalog_import.py,planning.py}`; focused 515-test selection and final 51-test publication hardening selection below passed; #2327 | Optional v3 metadata pins canonical annotated keys, schema format and exact Release version inside the existing manifest digest/signature. Registration/publication and independently pinned admission reject invalid schemas; the real planner blocks installation-schema mismatch. Legacy paths and unverified CLI eligibility remain unchanged. Production Release qualification is not established. |
| Configuration schema with axis and owner annotations | implemented | `current change`; `packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration.py`; `packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration_package.py`; focused package/validator/template selection below passed | Both builder and reader call the annotation validator. The reader requires an independently supplied trusted Release schema and sealed-key classification. Qualified production Release schemas remain separate work. |
| Configuration layers and override coverage | implemented | `current change`; `packages/deployment-cli/tests/test_lifecycle_configuration_package.py`; focused selection below passed | Actual package construction and reading validate all blocks, reject missing coverage and equivalent intervals, preserve most-specific selection, and reject sealed defaults. Hub/Agent transport integration remains open. |
| Configuration package, signing, and predecessor checks | implemented | #2325, #2336, #2363; `packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration_package.py`; focused selection below passed | Real detached Ed25519 signatures, unsigned/tampered rejection, ordered predecessor/fork/revision checks, exact retry bytes, durable atomic Hub import (#2336) and local publication custody (#2363). External customer protected-merge CI automation remains customer-owned. |
| Supported local configuration package CLI | implemented | `current change`; `packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration_cli.py`; `cli_parser.py`; `packages/deployment-cli/tests/test_lifecycle_configuration_cli.py`; focused 409-test selection and strict checks below passed; #2325 | `fdaictl configuration build` and `verify` reuse the canonical builder/reader. Independent file inputs, explicit empty-chain/retained-head assertions, private single-file no-clobber output and verified readback. Local success is not key admission, qualified Release eligibility, Hub import or deployment. |
| Sealed values | implemented | #2333, #2336, #2338, #2458 (`0d74a2637a`); `packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration_sealing.py`; builder/reader/decryption and connected-development Agent artifact tests passed | X25519/HKDF-SHA256/AES-256-GCM seals identifiers; signed persisted bytes contain ciphertext and digests, not plaintext values. The atomic source importer stores original ciphertext containers, and the installation-bound Agent verifies and decrypts plan-bound artifacts locally (#2338, #2458). Production multi-customer ceremony and legacy raw configuration deprecation remain separate. |
| Secret references | implemented | #1896, #2325, #2338, #2458 (`0d74a2637a`); `packages/deployment-cli/tests/test_lifecycle_configuration_package.py`; Agent CSI metadata adapter and #2338/#2458 tests passed | The builder rejects literal secrets before encryption/signing, the concrete CSI metadata adapter reports exact source/version/Entity and unavailable/unknown/stale/conflict/reported states without value reads, and #2458 exercises Secret-reference-only workload preparation. Production Key Vault CSI usability qualification remains tracked below. |
| Operational configuration transport | implemented | #2333, #2336, #2338, #2458 (`0d74a2637a`); `lifecycle/agent/src/fdai_lifecycle_agent/hub_artifacts.py`, `lifecycle/hub/src/fdai_lifecycle_hub/agent_artifacts.py`, `lifecycle/manager/`; `test_hub_artifacts.py`, `test_configuration_import.py` and connected westus3 AKS receipt | Installation-bound Agents fetch only the signed Release, active configuration and verified accepted predecessor chain named by their current eligible Plan, preserve Base64 Ed25519 signatures, verify both independently, and cache exact mode-0600 private inputs across polls. Siblings, successors and unrelated revisions remain unavailable. Production trust-root ceremony and full-FDAI topology qualification remain under #1821/#1824. |
| Customer repository template and key-custody runbook | implemented | `config/lifecycle-configuration-template/`; paired `docs/runbooks/lifecycle-configuration-key-onboarding.md`; `tests/integration/test_lifecycle_configuration_template.py` | Placeholders and pure-validator checks only. The runbook links the local CLI while retaining the stop before operational trust registration, qualified Release publication and Hub import. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-27 | implemented | Bound Agent history retrieval to the current Plan's retained configuration import and its verified accepted predecessor chain. This preserves an accepted but unactivated predecessor needed by a valid successor without exposing sibling, successor or unrelated revisions. | `current change`; `configuration_import_store.py`, `agent_artifacts.py`, `test_configuration_import.py`; `uv run pytest -q --no-cov lifecycle/hub/tests/test_configuration_import.py lifecycle/hub/tests/test_agent_artifacts.py` passed 41 cases; strict mypy and Ruff passed. | Deliver through protected merge, deploy the exact image, and complete the live #2468 full-topology Plan and independent readback. |
| 2026-10-26 | implemented | Extended the exact full-authority development recovery authorization to the first signed configuration scope and change. Same-Owner approval requires the recovered current identity, the audited same-Owner version-1 binding, the exact installation/operator/scope and an unexpired protected authorization. Durable recovery, key, scope and change audits preserve later verification; default, production and later key rotation still require independent approval. | `current change`; configuration import API/store/trust wiring and focused positive/default-independent tests. | Deliver through protected merge and use the bounded authorization for the live #2468 package activation. |
| 2026-10-26 | implemented | Added a fail-closed full-authority development recovery for one installation identity whose private key is unavailable, plus a first-binding-only same-Owner configuration approval exception fixed by protected Hub configuration. Exact replacement-key possession, installation/scope/operator/key/time bindings, no-open-Plan/no-existing-trust guards, audit idempotency and default independent approval remain enforced. | `current change`; recovery models/API/store/auth/infra paths; 33 focused key tests, 70 remote-auth tests, 118 adjacent API/store tests, one isolated PostgreSQL restart test and 48 Terraform tests passed; strict mypy, Ruff and Checkov passed. | Deliver through protected merge, then record one scoped live recovery and successful corrected runtime-bundle apply for #2468. Production and later rotations retain independent approval. |
| 2026-10-24 | implemented | Reconciled package signing/predecessor, sealed-value, secret-reference, and operational configuration transport scope rows after #2458 (`0d74a2637a`) delivered plan-bound Agent artifact transport, Base64 Ed25519 signature preservation, mode-0600 private input staging, and connected westus3 AKS configuration verification, and after all six #1823 candidate stories closed through #2325, #2327, #2331, #2333, #2336, #2338, and #2363. | `current change`; #1823, #2458 (`0d74a2637a`); `lifecycle/agent/tests/test_hub_artifacts.py`, `packages/deployment-cli/tests/test_lifecycle_configuration_package.py`, `test_lifecycle_configuration_cli.py`, `test_lifecycle_configuration_publication.py`, `lifecycle/hub/tests/test_configuration_import.py`, `test_configuration_keys.py`, `tests/integration/test_lifecycle_configuration_template.py`. | Production customer-key ceremony, production Release admission, and live Key Vault CSI operational usability remain tracked in Remaining work and parent #1821/#1824. |
| 2026-10-22 | implemented | Added a local durable publication seam without equating revision shape, original receipts or local locking with protected Git review, a global publisher, Hub acceptance or execution authority. | `current change`; #2363; `lifecycle_configuration_publication*.py`, shared artifact codec and focused owner command: 211 passed; strict mypy (4 files) and Ruff passed. | Parent #1823 remains partial: complete protected-merge publication, authoritative venue registration and actual onboarding/import/Agent/CSI qualification remain. |
| 2026-10-21 | implemented | Preserved configuration/key/history tables and APIs through the additive Hub revision-4 local-channel migration; no configuration approval or activation authority changed. | `current change`; #2361; `test_configuration_import_postgres.py::test_postgres_revision_two_upgrade_is_additive_and_preserves_legacy` now verifies revision 4 and unchanged legacy state; 193 focused configuration/native checks and an overlapping 153-case store/bootstrap/local-channel cohort passed. | Actual key onboarding, installed Agent delivery and operational qualification remain; schema 4 needs an explicit migration and compatible binary, not a destructive downgrade. |
| 2026-10-21 | implemented | Added explicit #2338 native module-entry proof after the earlier in-process evidence: producer `python -m fdai_deployment_cli` and Agent `python -m fdai_lifecycle_agent.cli` run as fresh processes over the existing bounded loopback Hub fixture, consuming a real canonical v2 container, independent private key/binding inputs and signed Release/Plan. Wrong-recipient input produces only a rejection audit report, with no admitted/apply-started report or workload journal. | `current change`; `test_configuration_process.py`, reused `test_configuration_entrypoint.py` fixture; two fresh-process cases passed, including durable replay, stdout/stderr privacy, process timeouts and server cleanup. Synthetic inputs and minimal generated child environment only; no dependency installation or actual Kubernetes call. | This proves source module-entry wiring, not actual Hub authentication/onboarding, installed-wheel qualification, real cluster effects, CSI operation or production trust. The existing kind process node remains needs-infrastructure and unexecuted. Parent owns protected delivery. |
| 2026-10-21 | implemented | Reproduced a #2338 completion-deadline defect through in-process public `reference-status` CLI execution: the final CSI read returning exactly at the deadline still produced `reported-mounted`. Added the same `>=` check after each source return, so late completion becomes unavailable without another request or retry. Kept the existing SDK request timeout; the acceptance budget does not interrupt in-flight requests or promise an absolute command wall time. | `current change`; `reference_state.py`, `test_reference_state.py`, paired installation Agent guide. The pre-fix equality case failed as expected; focused reference/legacy CLI/no-write selection passed (69 cases), including last representable tick before, exact equality, first representable tick after, earlier-read exhaustion, earlier unavailability and no retries. No actual Kubernetes call or cluster start. | Parent-owned protected delivery remains separate. Existing source-only onboarding/artifact/CSI binding and operational qualification boundaries are unchanged. |
| 2026-10-21 | implemented | Hardened #2338 legacy compatibility after the source consumer commit: malformed legacy bytes remain opaque until their detached signature is checked, preserving signature-missing/signature-invalid precedence and permanent malformed rejection instead of accidental retryable unreadability. Full-container trust checks remain unchanged. | `current change`; `lifecycle/agent/src/fdai_lifecycle_agent/inputs.py`, `lifecycle/agent/tests/test_configuration_entrypoint.py`; same focused command below passed (206 cases, 1 explicit opt-in kind skip), including three actual directory-adapter legacy rejection cases; strict mypy (13 files), Ruff and format passed. | Protected delivery remains parent-owned; operational key/artifact/CSI binding, rollout, independent effects and production qualification are unchanged open boundaries. |
| 2026-10-21 | implemented | Added #2338 installation-local full v2 revision consumption through the actual Agent CLI, original container protocol, independent signing/encryption/head/Entity/history inputs and exact manifest-bound Release schema. Connected per-Entity values and a supported decrypted reference to the existing renderers without bypassing admission, envelope, private journal, dry-run, reporting or recovery. Added concrete read-only CSI status transport and source-attributed unavailable/unknown/stale/conflict/reported states without Secret or mount reads. | `current change`; source/tests above and `docs/runbooks/installation-agent-configuration.md`; exact focused command below passed; strict mypy/Ruff passed. Synthetic keys, private files and mocked HTTP/Kubernetes mechanical transports only; no real DB, Azure, model, Kubernetes or Key Vault call. | Parent-owned protected delivery and exact-head CI remain separate. Actual key onboarding/readback, artifact synchronization, provider binding, Agent rollout, independently observed installation effects and production qualification remain open. Neither #1823 nor #1824 is complete. |
| 2026-10-21 | implemented | Reproduced an acceptance-time defect on the actual JWT/API/PostgreSQL path: managing an already enrolled Entity and independently approving a new full successor scope still failed because an ancestor was compared with today's managed set. Retained-history scope and package coverage now use the ancestor's immutable approved mapping. Current scope checks, installation proofs, approval/audit validity, key-version receipts and exact Release/schema admission remain unchanged. | `current change`; `configuration_import_trust.py`, `test_configuration_import_postgres.py::test_postgres_historical_scope_allows_new_independently_approved_managed_entity`; the regression failed before repair with `configuration_entity_scope_mismatch`, then the exact follow-up command below passed (43, no skips). It proves legal Entity management plus new independent approval succeeds; unapproved scope, substituted package bindings and old scope as current input fail. Missing historical catalog admission still holds. Strict mypy/Ruff passed. | Actual enrollment, deployed migration, Agent/CSI delivery and production qualification remain separate. This correction does not add Entity management or Release admission authority. |
| 2026-10-21 | implemented | Designed, critiqued and revised #2336 before persistent/public edits. Added independently approved installation-proven opaque Entity scope, bounded actual JWT signed-container import, atomic accepted receipt/head/audit, separate change approval/activation, additive schema 1/2-to-3 migration and the default durable configured consumer. Historical signatures retain their exact accepted key/version/approval receipt across rotation and expiry; revoked or unprovable history holds. Corrected SQLite savepoint transaction ownership after an audit-failure counterexample, without weakening PostgreSQL serialization. Issued Plans explicitly pin their import receipt so missing Plan/key/head provenance cannot fall back to the transient key-only seam. | `current change`; source/tests above; exact commands below passed (312 focused cases, 8 isolated PostgreSQL cases, no skips); strict mypy passed (15 source files), Ruff passed. Normal SignedEnrollment HTTP parsing, two PostgreSQL connections, rollback, restart/exact bytes, fork/predecessor/old revision, substitution/tamper, independent approvals, current versus historical key permission, missing receipt/key/head holds, privacy, recall/windows and legacy Plan preservation are exercised. | Actual enrollment, deployed migration/startup, operational Agent/CSI delivery and production qualification remain open. Activation selects an upgrade input only, not a same-Release action or execution/promotion authority. Protected publication is independently owned; this is local source evidence. |
| 2026-10-21 | implemented | Corrected the actual Hub consumer boundary: enrolled Entity IDs retain their existing maximum-63-character vocabulary, while v2 package bindings remain opaque 64-hex values. A transient candidate now requires an independent one-to-one mapping and exact installation binding; signed Plans retain the enrolled IDs. The prior test fixture's unsupported 64-character enrolled IDs no longer stand in for enrollment acceptance. | #2331; `current change`; the real signed-enrollment-to-planner regression failed before repair; `python3 scripts/automation/with-local-test-database.py uv run --no-sync pytest -q --no-cov --tb=short lifecycle/hub/tests/test_configuration_revision.py lifecycle/hub/tests/test_planning.py lifecycle/hub/tests/test_release_configuration_schema.py lifecycle/hub/tests/test_enrollment.py` passed (111, no skips); scoped strict mypy and Ruff passed. | This independent mapping is an explicit source-composition input, not durable mapping/key enrollment, ciphertext-only Hub import, Agent/CSI integration or production qualification. |
| 2026-10-21 | implemented | Added and critiqued the authority-neutral v2 full revision contract before source edits. Reused canonical layers, schema, signing, sealing and predecessor verification; bound exact Release manifest and independent opaque Entity selection; wired actual CLI and existing transient Hub planning consumption. Missing/extra/duplicate Entity coverage, crossing ambiguous intervals, schema/key/signature substitution, forks, gaps and superseded revision retries fail closed. | `current change`; task-owned source/tests listed above; `uv run --no-sync pytest -q --no-cov --basetemp=.fdai/test-2331-final packages/deployment-cli/tests/test_lifecycle_{configuration*,plan}.py lifecycle/hub/tests/test_{planning,release_configuration_schema,configuration_revision}.py tests/integration/test_lifecycle_configuration_template.py` passed (381); strict mypy/Ruff passed; #2331. | Independent key enrollment/rotation, atomic durable ciphertext-only Hub import, Agent transport/decryption, Key Vault CSI resolution and production Release qualification. This source slice does not close #1823 or any independent candidate. |
| 2026-10-21 | implemented | Routed only the lifecycle-configuration CLI source/tests to the existing Hub lifecycle owner, so the broad genesis route accepts their real owner without waiving documentation for unrelated provisioning changes. | `current change`; the real-manifest owner regression failed before routing repair; all 26 design-impact cases pass after repair, including refusal for unrelated `standalone_host.py`. The unchanged Hub PostgreSQL consumer cohort passed 2 cases on isolated loopback validation storage. The new package/sealing cohort passed 46 cases at 99.70% branch-inclusive coverage; the full focused package/resolver/template cohort passed 162. | These source and mechanical database checks do not implement atomic package import, independent installation key registration/rotation, Agent delivery/decryption, qualified schema, or CSI; #1823 remains open. |
| 2026-10-18 | implemented | Aligned the template with repository publication and localization boundaries: the tracked `config/` README stays English canonical, while onboarding and owner guides ship in the supported English/Korean `docs/` pairs. | `current change`; final template selection (10 passed); scoped mypy/Ruff; all 275 documentation translation pairs passed. The initial out-of-scope README translation advisory was repaired without changing the checker. | The same package signing, sealing, trust registration and Hub import work remains open. |
| 2026-10-18 | implemented | Published a placeholder-only customer repository template, focused pure-validator regressions and paired key-custody/onboarding prerequisite runbook. Corrected the owner document's stale claim that no validator exists without upgrading package delivery status. | `current change`; `uv run --no-sync pytest -q --no-cov tests/integration/test_lifecycle_configuration_template.py packages/deployment-cli/tests/test_lifecycle_configuration.py` (116 passed); scoped mypy and Ruff passed; #1823. | Implement and qualify the signed packager, predecessor/fork verification, sealing and Hub import. No operational key onboarding or deployment is claimed. |
| 2026-10-02 | not-started | Adopted the ledger with the accepted ADR-0003 design. No implementation exists. | `current change`; `docs/roadmap/deployment/lifecycle-configuration.md`, `docs/roadmap/architecture/decisions/0003-hub-managed-lifecycle-and-operator-governance.md`; design-route, roadmap-tracking, translation, punctuation, and link checks | Every item below |
| 2026-10-04 | implemented | Added a pure deployment CLI library for Release configuration schema annotations, deterministic layer resolution, deployability gating on matching Entity override blocks, and pre-signing literal secret-value rejection while allowing Key Vault references. | `current change`; `packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration.py`; `packages/deployment-cli/tests/test_lifecycle_configuration.py`; `uv run --project packages/deployment-cli pytest -q --no-cov packages/deployment-cli/tests/test_lifecycle_configuration.py` passed; `uv run --project packages/deployment-cli ruff check packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration.py packages/deployment-cli/tests/test_lifecycle_configuration.py` passed; `uv run --project packages/deployment-cli ruff format --check packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration.py packages/deployment-cli/tests/test_lifecycle_configuration.py` passed; `uv run --project packages/deployment-cli mypy --strict packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration.py` passed | Package signing, predecessor checks, sealing, Hub import, and the customer repository template remain open |
| 2026-10-04 | in-progress | Corrected the validator boundary: axis checks now allow only known non-authority ADR-0002 configuration axes, secret scanning rejects nested and malformed literal secret values, duplicate override ranges are ambiguous, and all override blocks are validated. Scope rows now state that these are pure validators not yet wired into a packager. | `current change`; `packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration.py`; `packages/deployment-cli/tests/test_lifecycle_configuration.py`; `uv run --project packages/deployment-cli pytest -q --no-cov packages/deployment-cli/tests/test_lifecycle_configuration.py` passed | Wire the validators into the future packager, then implement signing, predecessor checks, sealing, Hub import, CSI read paths, resolve-state reporting, and the customer repository template |
| 2026-10-21 | in-progress | Added a real offline signed package builder/reader and installation-only identifier encryption/decryption. Reproduced and fixed a sealed-default leak and comparator-order-equivalent override ambiguity. Reused the existing configuration document and validators without changing Hub/Agent transport contracts. | `current change`; `packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration_package.py`, `lifecycle_configuration_sealing.py`, `lifecycle_configuration.py`; `packages/deployment-cli/tests/test_lifecycle_configuration_package.py`; `PYTHONPATH=packages/deployment-cli/src uv run --no-sync pytest -q --no-cov --tb=short --basetemp=.fdai/issue-1823-pytest packages/deployment-cli/tests/test_lifecycle_configuration_package.py packages/deployment-cli/tests/test_lifecycle_configuration.py tests/integration/test_lifecycle_configuration_template.py` passed (162 tests); package/sealing branch coverage 99.70% (46 tests); legacy Agent configuration selection passed (6 tests); scoped strict mypy and Ruff passed; #1823 | Qualified Release binding, operational key enrollment/rotation, multi-Entity settings, CLI, atomic Hub import, Agent transport/decryption, CSI reference state, and candidate child-story closure evidence remain open. No issue exit criterion is withdrawn. |
| 2026-10-21 | implemented | Delivered the scheduled #2325 local CLI increment for #1823: real `fdaictl configuration build`/`verify`, separate verification and signing key files, independently supplied Release/schema/classification inputs, explicit accepted-chain assertions, a complete single-file signed container, no-clobber mode-0600 output and exact readback. Updated the EN/KO owner and key-custody runbook without relaxing operational publication stops. | `current change`; `packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration_cli.py`, `cli_parser.py`, `packages/deployment-cli/tests/test_lifecycle_configuration_cli.py`; `PYTHONPATH=packages/deployment-cli/src uv run --no-sync pytest -q --no-cov --tb=short --basetemp=.fdai/configuration-cli-final packages/deployment-cli/tests/test_lifecycle_configuration_cli.py packages/deployment-cli/tests/test_lifecycle_configuration_package.py packages/deployment-cli/tests/test_lifecycle_configuration.py tests/integration/test_lifecycle_configuration_template.py packages/deployment-cli/tests/test_cli_help.py packages/deployment-cli/tests/test_cli_help_hardening.py packages/deployment-cli/tests/test_cli_help_process.py` passed (409 tests); scoped Ruff check/format passed; `uv run --no-sync mypy --strict packages/deployment-cli/src/fdai_deployment_cli/lifecycle_configuration_cli.py` passed; strict parser/test checks with `--follow-imports=silent` passed. The unrestricted parser-import check exposed an unchanged `aks_service_update.py:29` baseline error, not repaired here. | Protected delivery/child closure remains with the delivery owner. Qualified production Release schemas, multi-Entity settings, operational signing/encryption key binding and rotation, atomic durable Hub import, Agent transport/decryption, Key Vault CSI state and installation acceptance remain open. No parent exit criterion is withdrawn. |

| 2026-10-21 | implemented | Delivered #2327's authority-neutral Release-schema increment: annotated schemas now travel inside actual v3 Release manifests through registration, persisted-draft revalidation, signing, independent pin/signature admission and real Hub planning. Rejected missing/blank annotations, unknown owners/metadata/axes, authority keys including nested values, format/version/digest mismatch, schema tampering and caller-key substitution. Kept legacy Releases readable and CLI production eligibility unverified. | `current change`; `uv run --no-sync pytest -q --no-cov --basetemp=.fdai/test-2327-focused lifecycle/hub/tests/test_release_configuration_schema.py lifecycle/hub/tests/test_release_hub_consumer.py lifecycle/hub/tests/test_planning.py lifecycle/release-hub/tests/test_release_hub.py packages/deployment-cli/tests/test_runtime_release.py packages/deployment-cli/tests/test_lifecycle_configuration.py packages/deployment-cli/tests/test_lifecycle_configuration_package.py packages/deployment-cli/tests/test_lifecycle_configuration_cli.py tests/integration/test_lifecycle_configuration_template.py tests/integration/scripts/test_design_doc_impact.py` passed (515); after final persisted-draft digest hardening, `uv run --no-sync pytest -q --no-cov --basetemp=.fdai/test-2327-publish-final lifecycle/hub/tests/test_release_configuration_schema.py lifecycle/release-hub/tests/test_release_hub.py lifecycle/hub/tests/test_release_hub_consumer.py` passed (51); scoped strict mypy and Ruff passed. | Production Release qualification/root ceremony, operational configuration-key enrollment/rotation, multi-Entity settings, atomic customer-package import, Agent transport/decryption, CSI reference state and parent #1823 closure remain open. No Azure, model, network validation, installation, authority change or remote delivery is claimed. |

| 2026-10-21 | implemented | Added #2333 source-only independently authenticated public configuration-key requests, approval, explicit rotation/revocation and retained version history on the existing enrollment lock/audit chain. The real configuration planning store resolves approved persisted keys, and pending Plans retain exact trust versions. Added explicit additive Lifecycle Hub migration 1-to-2 without changing Release Hub revision 1 or legacy enrollment. Reproduced crypto-provider acceptance of an identity-point signature and reject noncanonical, off-curve and small-order signing points at this new binding boundary. Missing configuration trust does not withdraw an existing legacy Plan. | `current change`; source and focused tests above; the exact command below passed 259 cases on isolated loopback PostgreSQL 5433; strict mypy and Ruff passed. The broad selected run first exposed an existing port-1 negative-connect test without a timeout; a process-local `PGCONNECT_TIMEOUT=3` bounded it without changing runtime configuration or weakening checks. | No real enrollment, deployed migration, atomic configuration-package/head import, cross-key historical-chain import, Agent/CSI integration, Azure/model use or production qualification. Protected delivery belongs to the parent issue outcome. |

Focused #2333 validation (passed: 259 tests; repeated on the clean immutable candidate with the
repository's strict defaults preserved and only coverage disabled):

```bash
PGCONNECT_TIMEOUT=3 python3 scripts/automation/with-local-test-database.py \
  .venv/bin/python -m pytest \
  lifecycle/hub/tests/test_configuration_keys.py \
  lifecycle/hub/tests/test_configuration_keys_postgres.py \
  lifecycle/hub/tests/test_enrollment.py \
  lifecycle/hub/tests/test_configuration_revision.py \
  lifecycle/hub/tests/test_hubs_postgres.py \
  lifecycle/hub/tests/test_remote_catalog.py \
  lifecycle/hub/tests/test_remote_auth.py \
  lifecycle/hub/tests/test_remote_bootstrap.py \
  lifecycle/hub/tests/test_api.py \
  lifecycle/hub/tests/test_store.py \
  lifecycle/hub/tests/test_database_inspection.py \
  -q --no-cov --tb=short --timeout=30 \
  --basetemp=.fdai/pytest-approved-keys-validated
```

Focused #2336 source validation (passed: 116 Hub cases plus 196 schema/package/CLI cases):

```bash
uv run --no-sync python -m pytest -q --no-cov --tb=short \
  --basetemp=.fdai/pytest-atomic-import \
  lifecycle/hub/tests/test_configuration_import.py \
  lifecycle/hub/tests/test_configuration_keys.py \
  lifecycle/hub/tests/test_configuration_revision.py \
  lifecycle/hub/tests/test_planning.py \
  lifecycle/hub/tests/test_remote_catalog.py
uv run --no-sync python -m pytest -q --no-cov --tb=short \
  --basetemp=.fdai/pytest-atomic-import-packages \
  lifecycle/hub/tests/test_release_configuration_schema.py \
  packages/deployment-cli/tests/test_lifecycle_configuration_package.py \
  packages/deployment-cli/tests/test_lifecycle_configuration_entities.py \
  packages/deployment-cli/tests/test_lifecycle_configuration_cli.py
```

Isolated PostgreSQL #2336 validation (passed: 8 cases, loopback port 5433 only):

```bash
python3 scripts/automation/with-local-test-database.py \
  uv run --no-sync python -m pytest -q --no-cov --tb=short \
  --basetemp=.fdai/pytest-atomic-import-pg \
  lifecycle/hub/tests/test_configuration_import_postgres.py \
  lifecycle/hub/tests/test_configuration_keys_postgres.py \
  lifecycle/hub/tests/test_hubs_postgres.py
```

The reviewed Starlette/AnyIO deprecation warning remains nonblocking. No dependency, marker,
strict-config or timeout policy was overridden.

Historical-scope follow-up validation (passed: 43 cases; the earlier commands above are unchanged):

```bash
python3 scripts/automation/with-local-test-database.py \
  uv run --no-sync python -m pytest -q --no-cov --tb=short \
  --basetemp=.fdai/pytest-historical-scope-validation \
  lifecycle/hub/tests/test_configuration_import.py \
  lifecycle/hub/tests/test_configuration_import_postgres.py \
  lifecycle/hub/tests/test_configuration_keys_postgres.py \
  lifecycle/hub/tests/test_hubs_postgres.py
```

Focused completion-deadline follow-up passed (69 local cases; no live tests selected):

```bash
.venv/bin/python -m pytest -q --no-cov --basetemp=.fdai/test-output/reference-deadline \
  lifecycle/agent/tests/test_reference_state.py \
  lifecycle/agent/tests/test_cli.py \
  lifecycle/agent/tests/test_configuration_entrypoint.py \
  lifecycle/agent/tests/test_no_write.py
```

Focused #2338 source checks passed: 203 cases for the initial consumer and 206 cases after
legacy rejection-precedence hardening, each with one explicit opt-in kind case skipped.
The selection includes actual locked Kubernetes SDK request serialization/deserialization with
only HTTP transport mocked. No live provider or database was used:

The earlier 206-case selector's full-revision producer-to-Agent test invokes both public
`main(args)` functions in process.
Its Agent CLI calls are dry runs with an injected Hub transport. Full-revision renderer/apply
checks separately invoke `LifecycleAgent` in process with a fake cluster; existing legacy CLI
apply checks also inject a fake cluster. Those earlier cases do not prove full-revision Agent `python -m`
or installed-binary process execution. The separate packaging CLI subprocess suite is not included
in this selector. Its no-write fresh-interpreter test invokes `Harness.poll`, not the Agent CLI.
The explicitly skipped node is
`lifecycle/agent/tests/test_cross_process_resumption.py::test_a_superseded_unreported_plan_is_abandoned_not_misapplied`.
It runs real Agent `python -m fdai_lifecycle_agent.cli poll-once --apply` processes only when
`FDAI_LIFECYCLE_KIND_CONTEXT` starts with `kind-` and the `kind` executable is available.
That test was not executed, and no live cluster or operational effect is claimed.

The later native module-entry check is separate from that earlier selector:

```bash
.venv/bin/python -m pytest -q --no-cov --basetemp=.fdai/test-output/native-configuration \
  lifecycle/agent/tests/test_configuration_process.py
```

It passed two cases using fresh producer and Agent processes and the existing loopback wire
fixture. The positive case also replays through another fresh Agent process without duplicate
reporting. The negative case preserves the existing rejection audit report rather than
manufacturing a no-report contract. The fixture does not establish operational authentication
or an actual cluster effect.

```bash
.venv/bin/python -m pytest -q --no-cov --basetemp=.fdai/test-output/configuration-agent \
  lifecycle/agent/tests/test_configuration_revision.py \
  lifecycle/agent/tests/test_configuration_entrypoint.py \
  lifecycle/agent/tests/test_reference_state.py \
  lifecycle/agent/tests/test_no_write.py \
  lifecycle/agent/tests/test_apply.py \
  lifecycle/agent/tests/test_cross_process_resumption.py \
  lifecycle/agent/tests/test_signatures_and_envelope.py \
  lifecycle/agent/tests/test_cli.py \
  lifecycle/agent/tests/test_agent.py \
  lifecycle/agent/tests/test_operator_workload.py \
  lifecycle/agent/tests/test_workload.py \
  lifecycle/agent/tests/test_kube.py
```

### Remaining work

- [x] Add pure validator coverage for axis and owner annotations, including rejection of an
  unannotated key, authority axes, and unknown axes.
- [x] Bind optional schemas to actual v3 Release publication, independent pinned admission and
  planner consumption; reject metadata/schema/version/signature mismatches and preserve legacy
  compatibility. #2327's history row records local evidence, not production qualification.
- [x] Add pure layer-resolution coverage for most-specific version-range selection and for a
  Release that isn't deployable without a matching override block.
- [x] Add the offline packager, and record tests that reject an unsigned package, a predecessor
  gap, and a forked revision, and that call the schema, layer, sealed-key, and secret-reference
  validators. The 2026-10-21 history row records the passing actual builder/reader checks.
- [x] Prove the new authenticated importer stores original ciphertext/public metadata and an
  installation decrypts with its own key; #2336 tests exercise both boundaries without changing
  existing legacy raw configuration storage.
- [x] Implement and exercise offline sealing and installation-only decryption with synthetic
  in-memory keys, including wrong-recipient and ciphertext-tampering rejection. Operational Hub
  persistence and enrollment binding are not implied.
- [x] Bind an installation-owned encryption public key through authenticated enrolled-identity
  proof and independent approval/rotation; #2333 source tests prove role separation, restart,
  replay/CAS rejection, revocation and actual planning consumption. No live ceremony is implied.
- [ ] Record actual customer-key onboarding and independent readback under an explicitly approved
  operational scope; source tests do not establish a trusted production installation.
- [x] Add atomic durable signed full-revision import, independently approved mapping/change,
  explicit activation and default configured consumption; #2336 records concurrent fork rejection,
  restart/exact retry, old-revision rejection, cross-key receipts and ciphertext storage evidence.
- [x] Connect full v2 configuration to the existing Agent artifact protocol, native CLI and
  per-Entity renderers with local decryption and negative substitution/privacy tests; #2338
  source evidence is recorded above and does not establish deployed trust.
- [x] Serve a current Plan's verified accepted configuration predecessor chain to its Agent while
  keeping siblings, successors and unrelated revisions unavailable.
- [ ] Record independently observed installation verification/decryption effects and an approved
  artifact synchronization binding without sending plaintext sealed identifiers through Hub.
- [x] Expose and exercise the supported local packaging and verification commands, including actual
  subprocess success, signature/schema/chain failures, pre-sign secret rejection, malformed input,
  private file boundaries, output privacy and preservation of existing output. The #2325
  implementation history row records the exact focused command and passing checks.
- [x] Implement the full multi-Entity source revision through the actual producer, verifier, CLI
  and existing Hub planner, with independent exact selection/Release checks and legacy compatibility;
  the #2331 history row records 381 passing focused cases.
- [x] Add the concrete bounded CSI metadata source adapter with exact Entity/Pod/source version,
  freshness and reported-only states without value reads; #2338 synthetic tests prove wiring only.
- [ ] Qualify production Release admission and bind actual Key Vault CSI reports to independent
  operational evidence without secret values; source status fixtures do not satisfy this boundary.
- [x] Deliver each remaining #1823 candidate through an existing or newly scheduled child issue
  with closure evidence, or record an explicit evidence-backed withdrawal (#2325, #2327, #2331,
  #2333, #2336, #2338, #2363, and #2458).
- [x] Record pure validator tests that a package containing a secret value is rejected before
  signing.
- [x] Publish a customer repository template and a configuration-key onboarding runbook that use
  placeholders only; their focused tests and explicit publication stop condition are recorded above.
