# Code Security Findings (Detected Issues) implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

The deterministic core for SARIF ingestion, severity, canonical issues, priority, fix groups,
signed remediation packs, the diff guard, result import, rescan verification, adjudication,
Heimdall review publication, notifications, sandboxed scanning lanes, and a synthetic evaluation
harness, and Python weakness verifiers are implemented and covered by focused tests. The
read-only Console view of review summaries is also implemented. The state-store pack registry and
its verdict and adjudication view are implemented as well. The capability stays
in shadow mode; passing focused tests does not promote it or prove a deployed path.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Code-security catalog and strict loader | implemented | `rule-catalog/code-security/`; `rule_catalog/code_security.py`; `test_catalog.py` | Weakness classes, severity rubric, priority policy, remediation policy, and pack templates fail closed on invalid data. |
| Bounded SARIF ingestion | implemented | `core/security/code_findings/sarif.py`; `test_sarif.py` | Byte, depth, result, location, and flow limits; path normalization; text sanitization; recorded drops. |
| Severity rubric, canonical issues, and priority | implemented | `severity.py`, `canonical.py`, `priority.py`; `test_severity.py`, `test_canonical.py` | One severity per root cause with explicit ranges; KEV and exposure affect priority only. |
| Fix groups and remediation pack rendering | implemented | `fix_groups.py`, `pack.py`; `test_pack.py` | Deterministic files and SHA-256 manifest, minimized mode, recorded omissions, standard-library helper. |
| Pack helper and diff guard | implemented | `pack_helper.py`, `pack_runtime.py`, `diff_guard.py`; `test_diff_guard.py`, `test_pack_helper_session.py` | Verify, scope, branch, guard, commit, rollback, and finish against a real git repository. |
| Result import and operator CLI | implemented | `result_import.py`; `delivery/code_security_cli.py`; `test_result_import.py`, `test_cli.py` | Results stay claims; `fixed_verified` is never produced by import. |
| Agent wiring and notifications | implemented | `review_signal.py`, `notify.py`; `shared/providers/code_security.py`; `agents/_framework/heimdall_code_security.py`, `agents/heimdall.py`; `config/notifications-matrix.yaml`; `core/notifications/messages.{en,ko}.json`; `delivery/code_security_publish_cli.py`; `tests/agents/test_code_security_drift.py`, `test_review_signal.py`, `test_cli.py` | Heimdall publishes a strict no-authority review package on `object.drift`; Forseti yields a `hil` verdict and Saga audits it. A2 and A4 routes fail closed when missing. The design's Huginn event path was replaced by this precedent (provider-schema drift) because Heimdall already owns review-required drift. |
| Console view of code-security reviews | implemented | `delivery/persistence/state_store_code_security_review.py`; CLI `publish-review --record-state` and `scan --record-state`; `fdai_operator_service/code_security_review_projection.py`, `runtime_projection_reader.py`, `families/operations/manifest.py`; `console/src/routes/code-security.tsx`; `tests/delivery/test_code_security_review_state.py`, `services/operator-service/tests/test_code_security_review_projection.py`, `console/src/routes/code-security.test.ts`, `console/tests/e2e/code-security-responsive.spec.ts` | Immutable per-revision review rows, fail-closed Operator projection with withheld-record gaps, reader-role `GET /code-security/reviews`, read-only Console route with no action controls. Pack records, verdicts, and adjudications are projected from the state-store registry at `GET /code-security/packs`. |
| Pack signing, revocation store, and export gate | implemented | `signing.py`, `ed25519_verify.py`, `export_gate.py`; `shared/providers/remediation_pack.py`; `delivery/code_security_signing.py`, `delivery/code_security_registry.py`; `config/code-security-agent-providers.yaml`; `test_signing.py`, `test_export_gate.py`, `test_cli.py`, `tests/delivery/test_code_security_adapters.py` | DSSE over the manifest, stdlib RFC 8032 verification in the helper, file-backed registry with revocation, fail-closed provider gate. `delivery/persistence/state_store_code_security_registry.py` adds the state-store registry for multi-host installations. |
| Scanning lanes, verifiers, and proof | in-progress | [Code Security Scanning ledger](code-security-scanning.md) | The deterministic lane, the off-path LLM lens lane, and Python weakness verifiers are implemented and tracked in their own ledger. Opt-in proof is not implemented. |
| Rescan verification and adjudication | implemented | `sarif_runs.py`, `receipts.py`, `verification.py`, `adjudication.py`; `delivery/code_security_review_cli.py`; `test_verification.py`, `test_cli.py` | Baseline receipts at export, coverage-equivalence gaps, root-cause matching across line shifts and advisory aliases, separation-of-duties adjudication, append-only review log. |
| Evaluation harness and corpora | implemented | `evaluation.py`; `rule-catalog/code-security/evaluation/synthetic-corpus.yaml`, `curated-advisories.yaml`; CLI `evaluate`; `test_evaluation.py` | Dedup pairwise precision and recall, detection precision and recall, severity range containment, exact agreement and weighted kappa with labeled facts, rerun stability, and line-shift rescan matching, with acceptance floors and a receipt. The corpus is synthetic and author-labeled; it proves wiring and reproducibility, not calibration. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-07 | implemented | Added the code-security catalog, deterministic core, remediation pack with standard-library helper and diff guard, result import, operator CLI, and owning design under #1966. | current change; `uv run pytest -q --no-cov services/core-control-plane/tests/core/security/code_findings` (110 passed, including regression tests for eight review findings on guard bypass, ref injection, quoted and subdirectory paths, SARIF globs, truncation priority, pack self-commit, and minimized paths); ruff and strict mypy on changed modules pass; helper session also run under Python 3.10. | Agent wiring, signing, export gate, scanning lanes, rescan verification, adjudication, and measured evaluation. |
| 2026-10-07 | implemented | Added Ed25519 DSSE pack signing with developer-side stdlib verification, a pack registry seam with a file-backed adapter and revocation, the coding-agent provider export gate, and CLI `revoke`, `public-key`, and registry-based `import-result`. | current change; `uv run pytest -q --no-cov services/core-control-plane/tests/core/security/code_findings services/core-control-plane/tests/delivery/test_code_security_adapters.py` (130 passed); ruff and strict mypy pass. | Agent wiring, notifications, scanning lanes, LLM lens lane, rescan verification, adjudication, and evaluation. |
| 2026-10-07 | implemented | Added coverage receipts from SARIF run metadata, baseline storage at export, coverage-equivalent rescan verification (`fixed_verified`, `still_present`, `inconclusive`), false-positive adjudication with separation of duties, and CLI `verify-fixes` and `adjudicate`. | current change; `uv run pytest -q --no-cov services/core-control-plane/tests/core/security/code_findings services/core-control-plane/tests/delivery/test_code_security_adapters.py` (143 passed); ruff and strict mypy pass. | Agent wiring, notifications, scanning lanes, LLM lens lane, and evaluation. |
| 2026-10-07 | implemented | Added the code-security review package, Heimdall `object.drift` publication through an injected projector, Forseti `hil` judgment and Saga audit coverage, localized A2 and A4 notification routes with fail-closed planning, and CLI `publish-review`. | current change; `uv run pytest -q --no-cov services/core-control-plane/tests/core/security/code_findings services/core-control-plane/tests/agents/test_code_security_drift.py services/core-control-plane/tests/agents/test_provider_schema_drift.py services/core-control-plane/tests/notifications` (457 passed); Heimdall-related agent tests (279 passed); ruff, strict mypy, agents import boundary, and catalog parity pass. | Scanning lanes, LLM lens lane, Console view, and evaluation. |
| 2026-10-07 | in-progress | Moved deterministic scanning-lane delivery to its own owner document and ledger, and implemented acquisition, the sandbox, the scanner catalog, the FDAI rule pack, and the scan job there. | current change; see `docs/roadmap-implementation/operations/code-security-scanning.md`. | LLM lens lane, CWE verifiers, opt-in proof, Console view, and evaluation. |
| 2026-10-07 | implemented | Added the offline evaluation harness, the synthetic labeled corpus with acceptance floors, the public `matches_rescan` matcher, and CLI `evaluate` with a receipt. | current change; `uv run pytest -q --no-cov services/core-control-plane/tests/core/security/code_findings` (186 passed, 1 skipped without a local rule engine); `python -m fdai.delivery.code_security_cli evaluate` passes every floor on 8 cases and 12 issues; ruff and strict mypy pass. | Curated corpus with post-cutoff advisories, holdout, and independent labels; Console view; CWE verifiers; opt-in proof. |
| 2026-10-07 | implemented | Added durable per-revision review rows with `--record-state` on `publish-review` and `scan`, the fail-closed Operator projection and reader-role `GET /code-security/reviews`, and the read-only Console **Evidence > Code security** route. | current change; `uv run pytest -q --no-cov services/core-control-plane/tests/delivery/test_code_security_review_state.py services/core-control-plane/tests/core/security/code_findings` (passes); `uv run pytest -q --no-cov services/operator-service/tests` (2956 passed; one Postgres replay test fails identically on the base commit because `FDAI_DATABASE_URL` is unset); `npm --prefix console run typecheck`; `npm --prefix console test` (all passed after route-count updates); `npx playwright test tests/e2e/code-security-responsive.spec.ts --project=desktop-chromium` (3 passed at 1440, 993, and 390 px with no document or main overflow). | Project fix verdicts and adjudications through a database-backed pack registry; curated corpus; opt-in proof. |
| 2026-10-07 | implemented | Added the state-store pack registry with revision compare-and-set review appends and a separate baseline row, `--registry state-store` on every pack command, the fail-closed `GET /code-security/packs` projection, and the Console remediation-pack table. | current change; `uv run pytest -q --no-cov services/core-control-plane/tests/delivery/test_code_security_state_registry.py services/core-control-plane/tests/core/security/code_findings/test_cli.py` (passes); real loopback PostgreSQL run kept four concurrent reviews and persisted revocation; `uv run pytest -q --no-cov services/operator-service/tests/test_code_security_review_projection.py services/operator-service/tests/test_operator_operations_family.py services/operator-service/tests/test_operator_service_full_composition.py services/operator-service/tests/test_operator_service_composition.py` (196 passed); `npm --prefix console run typecheck`; `npx playwright test tests/e2e/code-security-responsive.spec.ts --project=desktop-chromium` (3 passed). | Curated corpus; opt-in proof. |
| 2026-10-07 | implemented | Added the curated advisory corpus (20 cases, 21 real advisories published 2025-07 to 2026-09, independent GitHub-reviewed severity labels, `dev` and `holdout` splits, clean negatives), split metrics in `evaluate`, overlap-aware issue matching, and ecosystem-aware package identity after the corpus exposed duplicate issues for differently spelled PyPI names. | current change; `python -m fdai.delivery.code_security_cli evaluate --corpus rule-catalog/code-security/evaluation/curated-advisories.yaml` first failed with dedup recall 0.76 (5 false-split pairs), then passed every floor in both splits after the fix; the synthetic corpus still passes; `uv run pytest -q --no-cov services/core-control-plane/tests/core/security/code_findings services/core-control-plane/tests/delivery` (6575 passed). | Code-level cases with independent severity labels. |

### Remaining work

- [x] Publish scan reviews through Heimdall's owned drift topic, judge them in Forseti, and audit
  in Saga; focused agent tests prove ownership, validation before transport, and audit in the
  transition above.
- [x] Add A2 immediate and A4 digest notification routes that fail closed on a missing category
  and carry no code excerpts; notification tests pass in the transition above.
- [x] Add an Operator API projection and Console route over recorded scan reviews; Operator,
  Console unit, and responsive browser tests pass in the transition above without code excerpts.
- [x] Move the pack registry and review log to the state store and project fix verdicts and
  adjudications in the Console route; Operator, Console, and browser tests pass in the transition
  above without code excerpts.
- [x] Sign packs with a detached envelope, keep a server-side revocation store, and gate export
  on an approved coding-agent provider list; signature, revocation, and export-gate tests pass
  in the 2026-10-07 transition above.
- [x] Define `code-acquire` and `code-analyze` sandbox contracts and run the deterministic lane with
  FDAI-authored rules; egress-free and quota tests pass, tracked in the
  [Code Security Scanning ledger](code-security-scanning.md).
- [x] Validate the LLM lens lane live. The lane runs as an off-path worker inside the scan job, so
  no pantheon change was needed. The two-family live run kept only grounded locations and is
  recorded in the [Code Security Scanning ledger](code-security-scanning.md), which tracks lens
  precision on a curated corpus.
- [x] Implement coverage-equivalent rescan verification for `fixed_verified` and a false-positive
  adjudication workflow; tests that reject non-equivalent rescans pass in the transition above.
- [x] Build a curated evaluation corpus (post-cutoff CVEs, holdout, clean negatives, independent
  reviewer labels) for the implemented harness; the `curated` receipt passes in both splits in the
  transition above.
- [ ] Add code-level cases with independent severity labels to the curated corpus; exit with a
  receipt that measures severity agreement for code issues as well as dependencies.
