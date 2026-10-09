# Managed-language verifier evaluation

This report records the bounded Java and C# verifier changes in catalog version 1.5.0.
Use it with the [machine-readable evidence](managed-verifiers-1.5.0.json) to distinguish
improved source and sink coverage from verified precision. No additional verifier is promoted.

## What changed

- **Java path traversal:** Recognize fully qualified `java.io` file constructors. Stop inferring
  return-value taint from unresolved helper calls with Opengrep's AST-backed
  `taint_assume_safe_functions` option. A missed helper flow means verification abstained,
  not that the helper or file access is safe.
- **C# sources and sinks:** Recognize uploaded `IFormFile.FileName`, `SqliteCommand`, typed
  `Process` and `ProcessStartInfo` command-property assignments, process-info initializers,
  `FileStream`, and fully qualified `System.IO.File.ReadAllBytes`.
- **Sanitizer scope:** `Path.GetFileName` cuts filename taint only for C# path traversal.
  It does not remove SQL delimiters or shell syntax, so it no longer sanitizes those classes.
- **Regression fixtures:** Add direct vulnerable flows, fixed values, typed numeric parameters,
  unrelated objects with similarly named properties, filename sanitization, and unresolved
  helper returns. Fixtures are FDAI-authored and are never compiled or executed.

Example: an uploaded filename reaches `Path.Combine` and `FileStream`, which now produce
observation-only verifier hits. The same filename through `Path.GetFileName` doesn't confirm
path traversal, but still confirms a direct SQL or shell flow.

## Development decisions and limits

Only `dev` labels informed development. The existing corpus and its labels were not changed.
The complete rule bytes were frozen before evaluating either candidate or baseline on `holdout`.

Java SQL false positives on `dev` come from implicit propagation through helpers with constant
branches or switches. Opengrep's open-source taint analysis does not establish their reachable
return flow. No installed Java AST library or existing FDAI Java AST-flow implementation was
available; Opengrep's AST dump is not a supported path-sensitive return-summary contract.
Implementing and validating such a parser boundary was outside this bounded repair.

A development-only experiment making *all* unknown Java SQL calls non-propagating removed all
14 Benchmark `dev` true positives along with its 8 false positives. It was rejected before the
freeze. Java SQL is unchanged; no helper name, benchmark name, label, or special guard was
added to a sanitizer.

For Java path traversal, adding qualified sinks without conservative helper handling produced
31 true positives and 18 false positives on Benchmark `dev` (precision 0.6327). The selected
handling retained 4 and 2 (precision 0.6667). Relative to that development-only coverage-matched
variant, 27 true positives were sacrificed to avoid 16 false positives. Relative to the shipped
1.4.0 rule, the final rule loses **no labeled true positive**, but adds **two dev false positives**
and lowers overall dev precision from 1.0 to 0.7143. This is a bounded coverage repair with
conservative helper handling, **not a solved path-sensitive verifier or a promotion claim**.

C# now detects all five existing dev labels, compared with two before the change. Its corpus
has no C# safe controls, so observed precision 1.0 does not establish general C# precision.
The two existing C# SQL holdout labels remain undetected. C# command injection and path
traversal have no holdout labels. No holdout source was inspected to repair those misses.

## Frozen evaluation

The baseline is commit `94bdfafbf5c6baa065f404c54181248d04e26448`. Both runs use corpus
`fdai.code-security.verifier-real@1.1.0`, with 710 dev and 681 holdout labels, and the existing
scanner image `fdai-code-security-scanner:local` with Opengrep 1.30.1. Source acquisition uses
the existing pinned cache only; the local evaluation guard rejects any git/network acquisition.
Every engine process runs in Docker with `--network none`, read-only source and rule mounts,
and the non-root source-owner identity.

The evidence binds the corpus, frozen rule bytes, Python verifier bytes, engine binary, image,
source tree identities, and identical scanned-input digests for baseline and candidate. It
records all 24 engine-process exits, stdout digests, scanned-file counts, and structured errors
without embedding third-party source code. Every labeled taint file was scanned or had an
explicit parser error. Unlabeled hits are recorded separately and never counted as precision.
The official Python evaluation path runs in process on both splits.

The following cells show **TP / FP / precision / recall**. `n/a` means the ratio has no
denominator, not a passing result.

| Verifier key | Dev | Holdout | Eligible |
|---|---|---|---|
| `fdai.verify.java.command-injection` | 2 / 0 / 1.0 / 0.0351 | 2 / 0 / 1.0 / 0.0290 | Yes |
| `fdai.verify.java.sql-injection` | 15 / 8 / 0.6522 / 0.1119 | 21 / 10 / 0.6774 / 0.1511 | No |
| `fdai.verify.java.path-traversal` | 5 / 2 / 0.7143 / 0.0633 | 1 / 0 / 1.0 / 0.0182 | No |
| `fdai.verify.csharp.command-injection` | 1 / 0 / 1.0 / 1.0 | 0 / 0 / n/a / n/a | No |
| `fdai.verify.csharp.sql-injection` | 2 / 0 / 1.0 / 1.0 | 0 / 0 / n/a / 0.0 | No |
| `fdai.verify.csharp.path-traversal` | 2 / 0 / 1.0 / 1.0 | 0 / 0 / n/a / n/a | No |
| `fdai.verify.js.command-injection` | 1 / 0 / 1.0 / 1.0 | 3 / 0 / 1.0 / 1.0 | Yes |
| `fdai.verify.js.code-injection` | 4 / 0 / 1.0 / 1.0 | 1 / 0 / 1.0 / 0.5 | Yes |
| `fdai.verify.js.sql-injection` | 6 / 0 / 1.0 / 1.0 | 1 / 0 / 1.0 / 0.25 | Yes |
| `fdai.verify.js.path-traversal` | 1 / 2 / 0.3333 / 1.0 | 0 / 0 / n/a / 0.0 | No |
| `python:command_injection` | 5 / 0 / 1.0 / 0.6250 | 3 / 1 / 0.75 / 0.4286 | No |
| `python:code_injection` | 12 / 0 / 1.0 / 0.75 | 4 / 0 / 1.0 / 0.6667 | Yes |
| `python:sql_injection` | 3 / 0 / 1.0 / 0.6 | 1 / 0 / 1.0 / 0.5 | Yes |
| `python:path_traversal` | 17 / 0 / 1.0 / 0.5312 | 16 / 1 / 0.9412 / 0.4706 | Yes |
| `python:unsafe_deserialization` | 8 / 0 / 1.0 / 0.8 | 10 / 0 / 1.0 / 0.9091 | Yes |

Both baseline and candidate report 12 Juice Shop parser warnings. Two labeled JS SQL locations,
`loginAdminChallenge_1.ts:18` and `loginAdminChallenge_4_correct.ts:15`, are `unsupported`.
They are excluded from the precision and recall denominators by the existing metric contract,
not silently counted as true negatives. All other labeled outcomes have unsupported count zero.
These are existing, unchanged limitations; an exit code of zero alone does not prove parser coverage.

The promotion gate remains precision at least 0.90 and at least one true positive in **both**
splits. The eight previously promoted verifiers still meet that gate. All four changed Java/C#
verifiers remain in observation mode (`shadow`) and cannot grant `verified` confidence.
Python command injection remains unchanged and in shadow; its holdout result was not used for tuning.

## Focused validation

The owning Python checks passed (77 tests), and all 10 verifier-rule engine tests passed:

```bash
PYTHONPATH="$PWD/services/core-control-plane/src" \
  .venv/bin/python -m pytest -q --no-cov \
  --basetemp="$PWD/.fdai/verifier-work/pytest" \
  services/core-control-plane/tests/core/security/code_findings/test_verifier.py \
  services/core-control-plane/tests/core/security/code_findings/test_managed_verifiers.py \
  services/core-control-plane/tests/core/security/code_findings/test_verifier_evaluation.py

TMPDIR="$PWD/.fdai/verifier-work" .fdai/verifier-work/opengrep \
  --test rule-catalog/code-security/rules/verify
```

Evaluation used the local recorded-observation wrapper around the existing `evaluate_verifiers`
entrypoint. The wrapper checks process completion, labeled-file coverage, frozen rules, and
scanned-input parity; it adds no runtime scanner behavior. Its per-split metrics are derived by
the existing `verifier_metrics` implementation. You can reproduce those metrics with the supported
`fdai-code-security evaluate-verifiers` command using this corpus, the same cached sources, and
an Opengrep executable in an offline container.

## Related docs

| To inspect | Read |
|---|---|
| Pinned public sources and original labels | [Verifier corpus](verifier-corpus.yaml) |
| Completion observations and baseline deltas | [1.5.0 evidence](managed-verifiers-1.5.0.json) |
| Promotion authority | [Verifier catalog](../verifiers.yaml) |
| Runtime boundary and remaining design | [Code Security Scanning](../../../docs/roadmap/operations/code-security-scanning.md) |
