# Code Security Scanning implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

The deterministic lane is implemented and covered by focused tests, including real bubblewrap
runs on a host that supports unprivileged namespaces, an engine test-mode run of the rule pack,
and a real `trivy` run inside the sandbox. It has not run in a deployed environment.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Exact-commit source acquisition | implemented | `delivery/code_security_acquire.py`; `tests/delivery/test_code_security_scanning.py` | Verified commit id, read-only extraction without `.git`, environment-only credentials. |
| Bubblewrap scanner sandbox | implemented | `delivery/code_security_sandbox.py`; `tests/delivery/test_code_security_scanning.py` | No network, read-only source, tmpfs scratch, cleared environment, rlimits, bounded output, observed completion. Tests skip where bubblewrap namespaces are unavailable. |
| Scanner catalog and FDAI rule pack | implemented | `rule-catalog/code-security/scanners.yaml`, `rule-catalog/code-security/rules/`; `rule_catalog/code_security_scanners.py`; `test_scanner_catalog.py` | 22 CWE-classified rules with positive and negative fixtures. |
| Scan job and CLI | implemented | `delivery/code_security_scan_job.py`, `delivery/code_security_scan_cli.py`; `tests/delivery/test_code_security_scanning.py` | Observed completion and rule-pack digests flow into the receipt; Heimdall publication is optional. |
| LLM lens lane | implemented | `rule-catalog/code-security/lenses.yaml`; `rule_catalog/code_security_lenses.py`; `core/security/code_findings/lens.py`; `shared/providers/code_security_lens.py`; `delivery/azure/llm/code_security_lens.py`; `test_lens.py`, `tests/delivery/azure/test_code_security_lens_adapter.py`, `tests/delivery/test_code_security_scanning.py` | Deterministic selection, grounding, CWE filter, two-family quorum, budgets, inert hypotheses; mock-transport adapter tests only, no live model validation. |
| Deployed scan runner | not-started | Design only | A container image with pinned scanner binaries and offline databases, scheduled per repository. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-07 | implemented | Added exact-commit acquisition, the bubblewrap scanner sandbox, the scanner catalog, 22 FDAI-authored Opengrep rules with fixtures, misconfiguration and secret tag classification, the scan job with observed completion and rule-pack digests, and CLI `scan`. | current change; `uv run pytest -q --no-cov services/core-control-plane/tests/core/security/code_findings services/core-control-plane/tests/delivery/test_code_security_scanning.py` (passes, engine test skipped without a local engine); `uv tool run --from 'semgrep==1.*' semgrep --test --metrics=off rule-catalog/code-security/rules` (22/22 passed); real `trivy` 0.72.0 `config` run inside the sandbox completed and ingested 3 findings. | LLM lens lane, deployed scan runner, and evaluation. |
| 2026-10-07 | implemented | Added the off-path LLM lens lane: lens catalog, deterministic excerpt selection, tool-free strict-schema Azure OpenAI adapter, grounding and CWE verification, two-family quorum, budgets and lens notes, and scan job and CLI `--lens-model` integration. | current change; `uv run pytest -q --no-cov services/core-control-plane/tests/core/security/code_findings services/core-control-plane/tests/delivery/test_code_security_scanning.py services/core-control-plane/tests/delivery/azure/test_code_security_lens_adapter.py` (passes; engine test skipped without a local engine); ruff and strict mypy pass. | Live lens validation against two real model families, deployed scan runner, and evaluation. |

### Remaining work

- [ ] Build and pin a scan-runner container with Opengrep, gitleaks, osv-scanner, and Trivy plus
  offline databases, and run one scheduled scan in a development deployment; exit with a recorded
  scan receipt from that deployment.
- [x] Implement the LLM lens lane as an off-path worker with grounding verification and
  mixed-model review; tests that reject ungrounded locations pass in the transition above.
- [ ] Validate the lens lane against two real model families on a synthetic vulnerable
  repository under an explicit live-validation request; exit with a recorded receipt of calls,
  kept hypotheses, and rejected candidates.
