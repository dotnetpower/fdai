# Code Security Scanning implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

The deterministic lane, the off-path LLM lens lane, the Python weakness verifiers, and the
evidence-gated taint verifiers for JavaScript, Java, and C#, and the opt-in Python proof lane are
implemented and covered by focused tests, including real bubblewrap runs on a host that supports
unprivileged namespaces, an engine test-mode run of the rule pack, and a real `trivy` run inside
the sandbox. The scan runner image is built and validated locally. Nothing has run in a deployed environment;
the lens lane has one live two-family validation on a synthetic module.

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Exact-commit source acquisition | implemented | `delivery/code_security_acquire.py`; `tests/delivery/test_code_security_scanning.py` | Verified commit id, read-only extraction without `.git`, environment-only credentials. |
| Bubblewrap scanner sandbox | implemented | `delivery/code_security_sandbox.py`; `tests/delivery/test_code_security_scanning.py` | No network, read-only source, tmpfs scratch, cleared environment, rlimits, bounded output, observed completion. Tests skip where bubblewrap namespaces are unavailable. |
| Scanner catalog and FDAI rule pack | implemented | `rule-catalog/code-security/scanners.yaml`, `rule-catalog/code-security/rules/`; `rule_catalog/code_security_scanners.py`; `test_scanner_catalog.py` | 22 CWE-classified rules with positive and negative fixtures. |
| Scan job and CLI | implemented | `delivery/code_security_scan_job.py`, `delivery/code_security_scan_cli.py`; `tests/delivery/test_code_security_scanning.py` | Observed completion and rule-pack digests flow into the receipt; Heimdall publication is optional. |
| LLM lens lane | implemented | `rule-catalog/code-security/lenses.yaml`; `rule_catalog/code_security_lenses.py`; `core/security/code_findings/lens.py`; `shared/providers/code_security_lens.py`; `delivery/azure/llm/code_security_lens.py`; `test_lens.py`, `tests/delivery/azure/test_code_security_lens_adapter.py`, `tests/delivery/test_code_security_scanning.py` | Deterministic selection, grounding, CWE filter, two-family quorum, budgets, inert hypotheses; mock-transport adapter tests plus one live two-family validation on a synthetic module. |
| Python weakness verifiers | implemented | `rule-catalog/code-security/verifiers.yaml`; `rule_catalog/code_security_verifiers.py`; `core/security/code_findings/verifier.py`; scan job and CLI `export --verify-repository`; `test_verifier.py`, `test_cli.py`, `tests/delivery/test_code_security_scanning.py` | Intra-procedural flow-sensitive taint from entrypoint parameters and request attributes to catalog sinks for five classes, with sanitizers, validation guards, reachability, and exact revision; raises confidence to `verified` only. Precision on real code is not yet measured. |
| Taint verifiers and the promotion gate | implemented | `rule-catalog/code-security/rules/verify/`; `rule-catalog/code-security/evaluation/verifier-corpus.yaml`; `verifiers.yaml` `promotion`; `core/security/code_findings/verifier.py`, `verifier_evaluation.py`; `delivery/code_security_verifier_eval.py`; CLI `evaluate-verifiers`; `test_verifier.py`, `test_verifier_evaluation.py`, `tests/delivery/test_code_security_scanning.py` | Ten taint-mode rules for JavaScript and TypeScript, Java, and C#; only promoted verifiers grant `verified`. The 2026-10-07 receipt promoted 10 verifiers at precision 1.0 and kept JavaScript path traversal (precision 0.0 on 3 hits) and every rule without real-code evidence in shadow. |
| Opt-in proof lane | implemented | `delivery/code_security_prove.py`, `rule-catalog/code-security/prove/fdai_prove.py`; scan job and CLI `scan --prove`; `tests/delivery/test_code_security_prove.py`, `tests/delivery/test_code_security_scanning.py` | Python only; recording hooks, exploit-shaped payloads, and the scanner sandbox. Other languages have no proof harness. |
| Scan runner image | implemented | `services/core-control-plane/docker/code-security-scanner.Dockerfile`, `code-security-scanner-entrypoint.sh`; `tests/delivery/test_code_security_scanning.py` | Pinned Opengrep 1.30.1, gitleaks 8.30.1, OSV-Scanner 2.6.0, and Trivy 0.75.0 by SHA-256; built and run locally with Docker. |
| Deployed scheduled scan | not-started | Design only | A Container Apps job (or equivalent) that allows unprivileged user namespaces, with an offline-database refresh schedule, in a selected development deployment. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-10-07 | implemented | Added exact-commit acquisition, the bubblewrap scanner sandbox, the scanner catalog, 22 FDAI-authored Opengrep rules with fixtures, misconfiguration and secret tag classification, the scan job with observed completion and rule-pack digests, and CLI `scan`. | current change; `uv run pytest -q --no-cov services/core-control-plane/tests/core/security/code_findings services/core-control-plane/tests/delivery/test_code_security_scanning.py` (passes, engine test skipped without a local engine); `uv tool run --from 'semgrep==1.*' semgrep --test --metrics=off rule-catalog/code-security/rules` (22/22 passed); real `trivy` 0.72.0 `config` run inside the sandbox completed and ingested 3 findings. | LLM lens lane, deployed scan runner, and evaluation. |
| 2026-10-07 | implemented | Added the off-path LLM lens lane: lens catalog, deterministic excerpt selection, tool-free strict-schema Azure OpenAI adapter, grounding and CWE verification, two-family quorum, budgets and lens notes, and scan job and CLI `--lens-model` integration. | current change; `uv run pytest -q --no-cov services/core-control-plane/tests/core/security/code_findings services/core-control-plane/tests/delivery/test_code_security_scanning.py services/core-control-plane/tests/delivery/azure/test_code_security_lens_adapter.py` (passes; engine test skipped without a local engine); ruff and strict mypy pass. | Live lens validation against two real model families, deployed scan runner, and evaluation. |
| 2026-10-07 | implemented | Added the Python weakness verifiers: verifier catalog, strict loader, AST taint analysis with sanitizers, validation guards, and reachability, scan job integration with verifier results in `receipt.json`, and CLI `export --verify-repository` for external SARIF. | current change; `uv run pytest -q --no-cov services/core-control-plane/tests/core/security/code_findings services/core-control-plane/tests/delivery/test_code_security_scanning.py services/core-control-plane/tests/delivery/test_code_security_adapters.py` (passes; engine test skipped without a local engine); ruff and strict mypy pass. | Verifier precision on a curated corpus, verifiers for more languages and classes, opt-in proof lane, live lens validation, and deployed scan runner. |
| 2026-10-07 | implemented | Added taint-mode verifier rules for JavaScript and TypeScript, Java, and C#, the real-code verifier corpus over five pinned public projects, CLI `evaluate-verifiers` with a receipt, and the catalog promotion gate so only measured verifiers grant `verified`. | current change; `uv tool run --from 'semgrep==1.*' semgrep --test --metrics=off rule-catalog/code-security/rules` (32/32 passed); `python -m fdai.delivery.code_security_cli evaluate-verifiers --engine semgrep` over NodeGoat, Juice Shop, WebGoat, dvcsharp-api, and pygoat: 10 verifiers promoted at precision 1.0 (Python recall 0.5 for command injection because one sink is behind a helper), JavaScript path traversal 0 of 3 correct and kept in shadow, 2 unparseable Juice Shop excerpts counted as unsupported; `uv run pytest -q --no-cov services/core-control-plane/tests/core/security/code_findings services/core-control-plane/tests/delivery/test_code_security_scanning.py` (passes, including the engine test). | Command injection evidence for JavaScript, Java, and C#; a held-out corpus; inter-procedural Python flows; opt-in proof lane; deployed scan runner. |
| 2026-10-07 | implemented | Added the opt-in Python proof lane: a standard-library harness with import stubs, recording sink hooks, and class-specific exploit-shaped payloads, run in the bubblewrap sandbox for promoted verified issues, with results in `receipt.json` and `proven` confidence. | current change; `uv run pytest -q --no-cov services/core-control-plane/tests/delivery/test_code_security_prove.py services/core-control-plane/tests/delivery/test_code_security_scanning.py` (passes, including real sandbox runs where safe variants stay unproven); pygoat at its pinned commit: 9 of 9 verified issues proven in the sandbox. | Proof harnesses for other languages; deployed scan runner; live lens validation. |
| 2026-10-07 | implemented | Validated the LLM lens lane live against two model families in the FDAI development account, added `--lens-identity azure-cli` for local runs, and recorded the full lens report and kept hypothesis locations in `receipt.json`. | current change; `python -m fdai.delivery.code_security_cli scan --lens-model gpt-4.1-mini=... --lens-model gpt-4o=... --lens-identity azure-cli` on a synthetic Flask module with five planted flaws and three safe counterparts: 18 calls, 0 model errors, 9 candidates reviewed, 6 rejected as ungrounded, 7 grounded hypotheses kept covering all five planted flaws and no safe counterpart, 1 false-positive hypothesis (public search route flagged for missing authentication); `uv run pytest -q --no-cov services/core-control-plane/tests/delivery/test_code_security_scanning.py` (passes). | Lens precision on a curated real-code corpus; deployed scan runner. |
| 2026-10-07 | implemented | Added the pinned scan runner image and entrypoint, and fixed three defects its containerized run exposed: Opengrep's rejected `--metrics` flag, gitleaks output lost through `/dev/stdout` in the sandbox, and receipts keyed by tool-reported producer names instead of the catalog producer (scanner catalog 1.2.0, `trivy-config` producer `Trivy config`). | current change; `docker build -f services/core-control-plane/docker/code-security-scanner.Dockerfile` (image self-check passes); containerized `fdai-scan-runner prepare` then `scan --prove` on OWASP NodeGoat at `c5cb68a7`: 5 of 5 scanners completed in the sandbox, coverage complete, 423 raw results to 202 issues (78 corroborated, 3 verified), every receipt run bound to its catalog producer and rules version; `uv run pytest -q --no-cov services/core-control-plane/tests/core/security/code_findings services/core-control-plane/tests/delivery/test_code_security_scanning.py services/core-control-plane/tests/delivery/test_code_security_prove.py` (passes). | Deployed scheduled scan in a selected development deployment. |

### Remaining work

- [x] Build and pin a scan-runner container with Opengrep, gitleaks, osv-scanner, and Trivy plus
  offline databases; the containerized NodeGoat receipt is recorded in the transition above.
- [ ] Run one scheduled scan with the image in a selected development deployment whose runtime
  allows unprivileged user namespaces; exit with a recorded scan receipt from that deployment.
  This needs an explicit deployment authorization and target.
- [x] Implement the LLM lens lane as an off-path worker with grounding verification and
  mixed-model review; tests that reject ungrounded locations pass in the transition above.
- [x] Validate the lens lane against two real model families on a synthetic vulnerable
  repository under an explicit live-validation request; the receipt of calls, kept hypotheses,
  and rejected candidates is recorded in the transition above.
- [ ] Measure lens hypothesis precision on a curated real-code corpus; exit with a receipt that
  labels every kept hypothesis.
- [x] Measure weakness-verifier precision per class on a curated corpus of real vulnerable and
  fixed code, and add verifiers for JavaScript and TypeScript, Java, and C#; every promoted
  verifier recorded precision 1.0 in the transition above, and unmeasured or failing verifiers
  stay in shadow.
- [ ] Promote the shadow verifiers (JavaScript path traversal and the command injection rules for
  JavaScript, Java, and C#, plus C# path traversal) with labeled real-code evidence; exit with an
  `evaluate-verifiers` receipt at precision 0.90 or higher for each.
- [x] Add the opt-in proof lane (`code-build-prove`) for Python injection, path traversal, and
  deserialization findings in a disposable credential-free sandbox; sandbox tests and pygoat
  proofs pass in the transition above.
- [ ] Add proof harnesses for JavaScript, Java, and C#, and a memory-safety proof with sanitizers
  and fuzzing for native code; exit with one reproducible `proven` result per language.
