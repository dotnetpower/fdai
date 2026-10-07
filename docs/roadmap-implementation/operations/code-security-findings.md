# Code Security Findings implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

The deterministic core for SARIF ingestion, severity, canonical issues, priority, fix groups,
remediation packs, the diff guard, result import, and the operator CLI is implemented and covered
by focused tests, including an end-to-end helper session in a temporary git repository. Nothing
on this path is wired into the agent runtime, Console, or notifications yet, and no scanning lane
runs inside FDAI. Passing focused tests does not promote the capability or prove a deployed path.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Code-security catalog and strict loader | implemented | `rule-catalog/code-security/`; `rule_catalog/code_security.py`; `test_catalog.py` | Weakness classes, severity rubric, priority policy, remediation policy, and pack templates fail closed on invalid data. |
| Bounded SARIF ingestion | implemented | `core/security/code_findings/sarif.py`; `test_sarif.py` | Byte, depth, result, location, and flow limits; path normalization; text sanitization; recorded drops. |
| Severity rubric, canonical issues, and priority | implemented | `severity.py`, `canonical.py`, `priority.py`; `test_severity.py`, `test_canonical.py` | One severity per root cause with explicit ranges; KEV and exposure affect priority only. |
| Fix groups and remediation pack rendering | implemented | `fix_groups.py`, `pack.py`; `test_pack.py` | Deterministic files and SHA-256 manifest, minimized mode, recorded omissions, standard-library helper. |
| Pack helper and diff guard | implemented | `pack_helper.py`, `pack_runtime.py`, `diff_guard.py`; `test_diff_guard.py`, `test_pack_helper_session.py` | Verify, scope, branch, guard, commit, rollback, and finish against a real git repository. |
| Result import and operator CLI | implemented | `result_import.py`; `delivery/code_security_cli.py`; `test_result_import.py`, `test_cli.py` | Results stay claims; `fixed_verified` is never produced by import. |
| Agent wiring, Console, and notifications | not-started | Design only | Huginn event ingress, Heimdall exposure correlation, Forseti verdicts, Saga audit, A2 and A4 routes. |
| Pack signing, revocation store, and export gate | not-started | Design only | Detached signature, server-side revocation, approved coding-agent provider list. |
| Scanning lanes, verifiers, and proof | not-started | Design only | Acquisition and analysis sandbox contracts, deterministic lane execution, LLM lens lane, CWE verifiers, opt-in proof. |
| Rescan verification and adjudication | not-started | Design only | Coverage-equivalent rescan for `fixed_verified`; false-positive adjudication workflow. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-07 | implemented | Added the code-security catalog, deterministic core, remediation pack with standard-library helper and diff guard, result import, operator CLI, and owning design under #1966. | current change; `uv run pytest -q --no-cov services/core-control-plane/tests/core/security/code_findings` (110 passed, including regression tests for eight review findings on guard bypass, ref injection, quoted and subdirectory paths, SARIF globs, truncation priority, pack self-commit, and minimized paths); ruff and strict mypy on changed modules pass; helper session also run under Python 3.10. | Agent wiring, signing, export gate, scanning lanes, rescan verification, adjudication, and measured evaluation. |

### Remaining work

- [ ] Publish scan completion through Huginn as an `Event` with artifact digests, correlate exposure
  in Heimdall, and issue Forseti verdicts with Saga audit; exit when focused agent tests prove
  ownership, idempotency, and replay under #1966.
- [ ] Add A2 immediate and A4 digest notification routes that fail closed on a missing category
  and carry no code excerpts; exit with notification routing tests.
- [ ] Sign packs with a detached envelope, keep a server-side revocation store, and gate export
  on an approved coding-agent provider list; exit with signature, revocation, and export-gate
  tests.
- [ ] Define `code-acquire` and `code-analyze` sandbox contracts and run the deterministic lane with
  FDAI-authored rules; exit with egress-free and quota tests.
- [ ] Approve the pantheon design change for the LLM lens lane, then implement lenses with
  grounding verification and mixed-model review; exit with zero ungrounded locations on the
  evaluation corpus.
- [ ] Implement coverage-equivalent rescan verification for `fixed_verified` and a false-positive
  adjudication workflow; exit with tests that reject non-equivalent rescans.
- [ ] Build the measured evaluation corpus (post-cutoff CVEs, holdout, clean negatives) and record
  severity agreement and dedup precision and recall; exit with a recorded receipt.
