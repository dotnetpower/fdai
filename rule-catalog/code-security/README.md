# Code-Security Catalog

This directory holds the versioned data that turns scanner findings into canonical code-security
issues and remediation packs. The deterministic code under
[`services/core-control-plane/src/fdai/core/security/code_findings/`](../../services/core-control-plane/src/fdai/core/security/code_findings/)
reads it through
[`fdai.rule_catalog.code_security`](../../services/core-control-plane/src/fdai/rule_catalog/code_security.py).
The design is in [Code Security Findings](../../docs/roadmap/operations/code-security-findings.md).

> This catalog grants no authority. It parameterizes severity, priority, grouping, and the diff
> guard. Remediation runs on developer machines under their own authority, and FDAI treats every
> returned status as a claim until a rescan verifies it.

## Files

| File | Purpose |
|------|---------|
| `weakness-classes.yaml` | CWE grouping, impact range, fix class, autofix eligibility, maximum depth, and guidance per weakness class. A CWE id belongs to at most one class. |
| `severity-rubric.yaml` | Deterministic fact table for severity. Unknown facts produce an explicit floor-to-ceiling range instead of a guess. |
| `priority-policy.yaml` | First-match rules over severity, confidence, exposure, and known exploitation. |
| `remediation-policy.yaml` | Pack limits, test path globs, forbidden paths, and diff-guard patterns. |
| `remediation-pack/` | The conversational prompt, coding-agent adapters, and pack README rendered into every pack. |
| `scanners.yaml` | Deterministic-lane scanner commands, success codes, and sandbox mounts. Deployments bind each scanner id to a host executable. |
| `rules/` | FDAI-authored Opengrep rules with positive and negative fixtures. `rules/verify/` holds taint-mode verifier rules. |
| `lenses.yaml` | LLM lens definitions: CWE scope, sink hints, and excerpt budgets for the off-path review. |
| `verifiers.yaml` | Deterministic weakness verifiers: per-class sinks, sanitizers, entrypoints, and validation guards that raise a confirmed issue to `verified`. |
| `evaluation/` | Labeled evaluation corpora: `synthetic-corpus.yaml` for `evaluate`, `verifier-corpus.yaml` (pinned public projects, fetched at evaluation time) for `evaluate-verifiers`. |

## Change rules

- Bump the file's `version` on any semantic change. Packs record the versions they used.
- CWE identifiers are referenced with attribution to The MITRE Corporation. Guidance text is
  FDAI-authored. Do not copy rule text from third-party rule packs.
- Template placeholders are `{{PACK_ID}}`, `{{PACK_DIR}}`, and `{{EXPIRES_AT}}`. An unknown
  placeholder fails rendering.
- An evaluation corpus declares `provenance: synthetic` or `curated`. Never add customer code,
  paths, or advisory data to the upstream corpus.
- Changing a verifier rule or the Python verifier requires re-running `evaluate-verifiers` and
  updating the `promotion` list in `verifiers.yaml` in the same change.
- Run the focused tests after a change:
  `uv run pytest -q --no-cov services/core-control-plane/tests/core/security/code_findings`.
