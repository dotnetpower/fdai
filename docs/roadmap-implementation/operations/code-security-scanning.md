# Code Security Scanning implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

The deterministic lane, the off-path LLM lens lane, the Python weakness verifiers, and the
evidence-gated taint verifiers for JavaScript, Java, and C# are implemented and covered by focused tests, including real bubblewrap runs on a host that supports
unprivileged namespaces, an engine test-mode run of the rule pack, and a real `trivy` run inside
the sandbox. Nothing has run in a deployed environment, and the lens lane has no live model run.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Exact-commit source acquisition | implemented | `delivery/code_security_acquire.py`; `tests/delivery/test_code_security_scanning.py` | Verified commit id, read-only extraction without `.git`, environment-only credentials. |
| Bubblewrap scanner sandbox | implemented | `delivery/code_security_sandbox.py`; `tests/delivery/test_code_security_scanning.py` | No network, read-only source, tmpfs scratch, cleared environment, rlimits, bounded output, observed completion. Tests skip where bubblewrap namespaces are unavailable. |
| Scanner catalog and FDAI rule pack | implemented | `rule-catalog/code-security/scanners.yaml`, `rule-catalog/code-security/rules/`; `rule_catalog/code_security_scanners.py`; `test_scanner_catalog.py` | 22 CWE-classified rules with positive and negative fixtures. |
| Scan job and CLI | implemented | `delivery/code_security_scan_job.py`, `delivery/code_security_scan_cli.py`; `tests/delivery/test_code_security_scanning.py` | Observed completion and rule-pack digests flow into the receipt; Heimdall publication is optional. |
| LLM lens lane | implemented | `rule-catalog/code-security/lenses.yaml`; `rule_catalog/code_security_lenses.py`; `core/security/code_findings/lens.py`; `shared/providers/code_security_lens.py`; `delivery/azure/llm/code_security_lens.py`; `test_lens.py`, `tests/delivery/azure/test_code_security_lens_adapter.py`, `tests/delivery/test_code_security_scanning.py` | Deterministic selection, grounding, CWE filter, two-family quorum, budgets, inert hypotheses; mock-transport adapter tests only, no live model validation. |
| Python weakness verifiers | implemented | `rule-catalog/code-security/verifiers.yaml`; `rule_catalog/code_security_verifiers.py`; `core/security/code_findings/verifier.py`; scan job and CLI `export --verify-repository`; `test_verifier.py`, `test_cli.py`, `tests/delivery/test_code_security_scanning.py` | Intra-procedural flow-sensitive taint from entrypoint parameters and request attributes to catalog sinks for five classes, with sanitizers, validation guards, reachability, and exact revision; raises confidence to `verified` only. Precision on real code is not yet measured. |
| Taint verifiers and the promotion gate | implemented | `rule-catalog/code-security/rules/verify/`; `rule-catalog/code-security/evaluation/verifier-corpus.yaml`; `verifiers.yaml` `promotion`; `core/security/code_findings/verifier.py`, `verifier_evaluation.py`; `delivery/code_security_verifier_eval.py`; CLI `evaluate-verifiers`; `test_verifier.py`, `test_verifier_evaluation.py`, `tests/delivery/test_code_security_scanning.py` | Ten taint-mode rules for JavaScript and TypeScript, Java, and C#; only promoted verifiers grant `verified`. The 2026-10-07 receipt promoted 10 verifiers at precision 1.0 and kept JavaScript path traversal (precision 0.0 on 3 hits) and every rule without real-code evidence in shadow. |
| Deployed scan runner | not-started | Design only | A container image with pinned scanner binaries and offline databases, scheduled per repository. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-07 | implemented | Added exact-commit acquisition, the bubblewrap scanner sandbox, the scanner catalog, 22 FDAI-authored Opengrep rules with fixtures, misconfiguration and secret tag classification, the scan job with observed completion and rule-pack digests, and CLI `scan`. | current change; `uv run pytest -q --no-cov services/core-control-plane/tests/core/security/code_findings services/core-control-plane/tests/delivery/test_code_security_scanning.py` (passes, engine test skipped without a local engine); `uv tool run --from 'semgrep==1.*' semgrep --test --metrics=off rule-catalog/code-security/rules` (22/22 passed); real `trivy` 0.72.0 `config` run inside the sandbox completed and ingested 3 findings. | LLM lens lane, deployed scan runner, and evaluation. |
| 2026-10-07 | implemented | Added the off-path LLM lens lane: lens catalog, deterministic excerpt selection, tool-free strict-schema Azure OpenAI adapter, grounding and CWE verification, two-family quorum, budgets and lens notes, and scan job and CLI `--lens-model` integration. | current change; `uv run pytest -q --no-cov services/core-control-plane/tests/core/security/code_findings services/core-control-plane/tests/delivery/test_code_security_scanning.py services/core-control-plane/tests/delivery/azure/test_code_security_lens_adapter.py` (passes; engine test skipped without a local engine); ruff and strict mypy pass. | Live lens validation against two real model families, deployed scan runner, and evaluation. |
| 2026-10-07 | implemented | Added the Python weakness verifiers: verifier catalog, strict loader, AST taint analysis with sanitizers, validation guards, and reachability, scan job integration with verifier results in `receipt.json`, and CLI `export --verify-repository` for external SARIF. | current change; `uv run pytest -q --no-cov services/core-control-plane/tests/core/security/code_findings services/core-control-plane/tests/delivery/test_code_security_scanning.py services/core-control-plane/tests/delivery/test_code_security_adapters.py` (passes; engine test skipped without a local engine); ruff and strict mypy pass. | Verifier precision on a curated corpus, verifiers for more languages and classes, opt-in proof lane, live lens validation, and deployed scan runner. |
| 2026-10-07 | implemented | Added taint-mode verifier rules for JavaScript and TypeScript, Java, and C#, the real-code verifier corpus over five pinned public projects, CLI `evaluate-verifiers` with a receipt, and the catalog promotion gate so only measured verifiers grant `verified`. | current change; `uv tool run --from 'semgrep==1.*' semgrep --test --metrics=off rule-catalog/code-security/rules` (32/32 passed); `python -m fdai.delivery.code_security_cli evaluate-verifiers --engine semgrep` over NodeGoat, Juice Shop, WebGoat, dvcsharp-api, and pygoat: 10 verifiers promoted at precision 1.0 (Python recall 0.5 for command injection because one sink is behind a helper), JavaScript path traversal 0 of 3 correct and kept in shadow, 2 unparseable Juice Shop excerpts counted as unsupported; `uv run pytest -q --no-cov services/core-control-plane/tests/core/security/code_findings services/core-control-plane/tests/delivery/test_code_security_scanning.py` (passes, including the engine test). | Command injection evidence for JavaScript, Java, and C#; a held-out corpus; inter-procedural Python flows; opt-in proof lane; deployed scan runner. |

### Remaining work

- [ ] Build and pin a scan-runner container with Opengrep, gitleaks, osv-scanner, and Trivy plus
  offline databases, and run one scheduled scan in a development deployment; exit with a recorded
  scan receipt from that deployment.
- [x] Implement the LLM lens lane as an off-path worker with grounding verification and
  mixed-model review; tests that reject ungrounded locations pass in the transition above.
- [ ] Validate the lens lane against two real model families on a synthetic vulnerable
  repository under an explicit live-validation request; exit with a recorded receipt of calls,
  kept hypotheses, and rejected candidates.
- [x] Measure weakness-verifier precision per class on a curated corpus of real vulnerable and
  fixed code, and add verifiers for JavaScript and TypeScript, Java, and C#; every promoted
  verifier recorded precision 1.0 in the transition above, and unmeasured or failing verifiers
  stay in shadow.
- [ ] Promote the shadow verifiers (JavaScript path traversal and the command injection rules for
  JavaScript, Java, and C#, plus C# path traversal) with labeled real-code evidence; exit with an
  `evaluate-verifiers` receipt at precision 0.90 or higher for each.
- [ ] Add the opt-in proof lane (`code-build-prove`) that reproduces injection, path traversal,
  deserialization, and memory-safety findings in a disposable credential-free sandbox; exit with
  isolation and quota tests and one reproducible `proven` result on a synthetic repository.
