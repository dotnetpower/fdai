---
title: Code Security Scanning
---

# Code Security Scanning

This document defines how FDAI scans source code itself. It covers how FDAI acquires the exact
revision, runs deterministic scanners in an isolated sandbox, and records honest coverage. The
results feed the canonical issue model, severity, priority, and remediation packs described in
[Code Security Findings](code-security-findings.md).

> **Scope:** Scanning reads code and produces evidence. It never edits the repository and never
> contacts the network after acquisition. It runs repository code only in the opt-in
> [proof lane](#proof-lane-opt-in), inside a disposable sandbox with recording hooks in place of
> every sink. Scanner findings are inert until the review flow and a person decide what to do.

> **Status:** The deterministic lane (acquisition, sandbox, scanner catalog, FDAI rule pack, scan
> job, and CLI), the off-path LLM lens lane, the Python and taint weakness verifiers with their
> promotion gate, and the opt-in Python proof lane are implemented. See the
> [implementation ledger](../../roadmap-implementation/operations/code-security-scanning.md).

## Design at a glance

A scan job turns one repository revision into SARIF (Static Analysis Results Interchange Format)
reports, a coverage receipt, canonical issues, and a review package for Heimdall:

![Design at a glance. The main stages are Acquire exact commit, Read-only source, Sandboxed scanners, SARIF per scanner, Coverage receipt, Canonical issues, Review package, Heimdall drift.](../../diagrams/generated/fdai-roadmap-operations-code-security-scanning-01.en.svg)

Example: an operator runs `scan` for commit `a1b2...` of `payments-api` with Opengrep and gitleaks
bound. FDAI fetches exactly that commit, extracts it read-only, and runs both scanners without
network access. It writes `opengrep.sarif`, `gitleaks.sarif`, and `receipt.json`. Because
`osv-scanner` isn't installed, coverage is marked incomplete and Heimdall publishes a
`coverage_incomplete` review instead of a clean result.

## Source acquisition

- **Exact commit:** the job fetches one commit by its full id into a private bare repository and
  verifies that the fetched commit equals the requested id.
- **No repository code at run time:** it extracts the commit's tree without `.git` into a
  content-addressed directory and removes write permission from every file.
- **Credentials:** an HTTP authorization header reaches git only through environment
  configuration. It never appears in argv, logs, or the extracted tree.
- **Bounds:** the archive size and the git timeout are limited, and failures stop the job before
  any scan.

## Scanner sandbox

Each scanner runs as one bubblewrap process with:

| Control | Setting |
|---------|---------|
| Namespaces | New user, PID, IPC, UTS, and network namespaces (`--unshare-all`), so there's no network |
| Source | The acquired tree, read-only at `/source` |
| Optional mounts | FDAI rule pack read-only at `/rules`; offline vulnerability database read-only at `/cache` |
| Writable paths | Private tmpfs `/scratch` and `/tmp` only |
| Environment | Cleared, then `HOME`, `TMPDIR`, and `PATH` only |
| Limits | CPU time, address space, and file size limits; a wall-clock timeout |
| Output | Standard output read up to the scanner's byte limit |

The sandbox observes completion itself. A run is complete only when the scanner exits with a
listed success code before the timeout and within the output limit. That observation overrides
anything the scanner claims in its SARIF, and a failed run marks the producer incomplete.

## Scanner catalog

The [scanner catalog](../../../rule-catalog/code-security/scanners.yaml) declares each
deterministic scanner's argv template, mounts, success codes, timeout, and output limit. The only
allowed placeholders are `{source}`, `{rules}`, and `{cache}`, and loading fails closed on
anything else.

| Scanner | Purpose | Needs |
|---------|---------|-------|
| `opengrep` | FDAI-authored taint and pattern rules | Rule pack |
| `gitleaks` | Hard-coded secrets (redacted in output) | Nothing |
| `osv-scanner` | Vulnerable dependencies from lockfiles | Offline OSV database |
| `trivy-config` | Infrastructure and container misconfiguration | Nothing |
| `trivy-vuln` | Vulnerable packages | Offline Trivy database |

FDAI doesn't redistribute these tools. A deployment binds each scanner id to an installed
executable. An unbound required scanner, a scanner without its offline database, a failed run,
and invalid SARIF each become a coverage limit.

## FDAI rule pack

The [rule pack](../../../rule-catalog/code-security/rules/) contains 22 FDAI-authored rules for
Python, JavaScript and TypeScript, Java, and Go. Each rule:

- carries exactly one CWE that maps to a weakness class, so its findings never land in
  `unclassified`;
- favors precision, flagging a sink only when untrusted data or an unsafe option is visible;
- has positive (`ruleid:`) and negative (`ok:`) fixtures that the engine's test mode checks.

No third-party rule text is copied, so the pack carries no third-party rule license. The fixtures
are deliberately vulnerable and never imported or executed. The Python fixture opts out of
repository lint with a file-level directive instead of a repository-wide exclusion.

## Coverage receipt

The job builds the receipt from SARIF run metadata and its own observations:

- **Completion:** observed by the sandbox, not reported by the scanner.
- **Full repository:** asserted for every scanner that completed, because each scans the whole
  extracted tree.
- **Rules version:** binds the scanner id, the tool version from SARIF, and, for rule-based
  scanners, a digest of the rule pack. A rule change therefore makes a later rescan
  non-equivalent unless the new version declares that it supersedes the old one.
- **Producer:** the catalog producer of the scanner FDAI ran, not the tool's self-reported
  name. Editions and modes report names such as `Opengrep OSS` or one `Trivy` for two scanners,
  which would otherwise detach the rules version and observed completion from the run.

The review is `coverage_incomplete` unless every required scanner was bound, completed, and
produced valid SARIF.

## Scan runner image

`services/core-control-plane/docker/code-security-scanner.Dockerfile` packages the scan job with
Opengrep, gitleaks, OSV-Scanner, and Trivy. Each binary is pinned by version and SHA-256, and the
base image is pinned by digest. The entrypoint has two steps:

1. `fdai-scan-runner prepare SOURCE_DIR` refreshes the Trivy and OSV offline databases into the
   cache. It's the only step that uses the network.
2. `fdai-scan-runner scan ...` binds every catalog scanner and the cache, then runs the scan job.
   All scanners run inside the bubblewrap sandbox with no network.

bubblewrap needs unprivileged user namespaces, so the container runtime must allow them. With
Docker, that means `--security-opt seccomp=unconfined --security-opt apparmor=unconfined`.

Example: on 2026-10-07 the image scanned OWASP NodeGoat at its pinned commit. All five scanners
completed in the sandbox and coverage was complete. The 423 raw scanner results became 202
canonical issues, 78 of them corroborated by more than one scanner and 3 `verified` by the
JavaScript code-injection verifier. That run also found and fixed three defects that host tests
couldn't reproduce:

- Opengrep rejects Semgrep's `--metrics` flag.
- gitleaks can't write its report through `/dev/stdout` inside the sandbox's user namespace.
- The tools' self-reported names (`Opengrep OSS`, and one `Trivy` for two modes) didn't match the
  catalog producers, so receipts lost the rule-pack digest.

## LLM lens lane

The lens lane looks for weakness families that rules miss, such as missing authorization. It's
optional, runs off the agent hot path inside the scan job, and produces only inert hypotheses:

1. **Select deterministically:** walk the read-only source in sorted order, skip vendored,
   oversized, binary, and non-UTF-8 files, and pick bounded excerpts around lines that match a
   lens's sink hints in the [lens catalog](../../../rule-catalog/code-security/lenses.yaml).
2. **Ask several model families:** send each excerpt to every configured model as untrusted JSON
   data with line numbers, a strict JSON schema response, no tools, and a request byte ceiling.
3. **Verify in code:** keep a candidate only when the cited line is inside the excerpt, matches a
   sink hint, and uses one of the lens's CWEs.
4. **Require a quorum:** emit an occurrence only when at least two distinct model families report
   grounded candidates within the line tolerance.

Kept candidates enter canonicalization in the `llm_lens` lane. They get `hypothesis` confidence,
so they can't reach alerting priorities on their own. They're corroborated only when a
deterministic or external producer reports the same root cause, and they become `verified` only
when a [weakness verifier](#weakness-verifiers) confirms the flow. With fewer than two model
families, the lane doesn't run. Budget exhaustion, model failures, and skipped files are recorded
as lens notes in `receipt.json`. Those notes don't change deterministic coverage, because the
lane is optional. Code text that tries to instruct the model can't add findings, since every
finding must pass grounding and quorum in code.

Deployments call models with the attached managed identity. For local development,
`--lens-identity azure-cli` uses the operator's existing `az` login instead. The receipt records
the full lens report (calls, errors, and candidates rejected as ungrounded, off-lens, or without
quorum) and every kept hypothesis location.

Live validation, 2026-10-07: `gpt-4.1-mini` and `gpt-4o` in the FDAI development account
reviewed a synthetic Flask module with five planted flaws and three safe counterparts. Across
18 calls with no errors, 6 ungrounded claims were rejected and 7 grounded hypotheses were kept.
Those covered all five planted flaws and none of the safe counterparts. One extra hypothesis,
missing authentication on a public search route, is a false positive that stays an inert
`hypothesis`.

Example: two model families both cite line 8, `Order.query.get(order_id)`, for
`missing-authorization` with CWE-639. FDAI keeps one `hypothesis` occurrence. The issue is
priority P3 until a person or another producer confirms it.

## Weakness verifiers

Weakness verifiers are the deterministic validate step. They run inside the scan job on the same
read-only tree, after canonicalization, and raise a confirmed issue to `verified` confidence. The
[verifier catalog](../../../rule-catalog/code-security/verifiers.yaml) lists, per weakness class,
the sinks to confirm and the sanitizers and validation guards to honor. Python covers command
injection, code injection, unsafe deserialization, SQL injection, and path traversal.

For each supported issue, the verifier parses the fix-site file without importing or running it.
It finds a catalog sink call on the fix-site line, following imports and aliases, and runs an
intra-procedural, flow-sensitive taint analysis over the enclosing function. The issue is
`verified` only when all of these hold:

1. **Attacker source:** the sink's dangerous argument comes from a parameter of an
   entrypoint-decorated function or a request attribute. Typed route converters and parameters
   annotated as numbers or UUIDs aren't sources. Local inputs such as command-line arguments
   aren't sources, because `verified` claims a network-reachable flow.
2. **No sanitizer:** no catalog sanitizer, such as `shlex.quote` or `os.path.basename`, cuts the
   flow. An allowlist or validation guard on the value removes taint on both branches.
3. **Reachable:** the sink isn't after a `return` or `raise`, or in a constant-false branch.
4. **Exact revision:** the issue and the acquired tree have the same commit.

Every other outcome leaves confidence unchanged and is recorded in `receipt.json` with a reason,
such as `no_sink_at_fix_site`, `argument_not_attacker_controlled`, `unreachable`, or
`unsupported_language`. Verifiers never lower confidence, change severity, or close an issue.
The analysis is conservative toward not verifying, so an unconfirmed issue isn't evidence of
safety. The operator CLI `export --verify-repository` runs the same verifiers on external SARIF,
such as MDASH results, against the exact acquired revision.

Example: Opengrep reports CWE-78 at `os.system(request.args['cmd'])` in a function. The verifier
finds the sink, traces the argument to `request.args`, finds no sanitizer, and marks the issue
`verified`. If the function first checks `cmd not in ALLOWED` and aborts, the issue stays
`reported`.

### Other languages and the promotion gate

For JavaScript and TypeScript, Java, and C#, FDAI-authored Opengrep taint-mode rules under
`rules/verify/` do the same job. Each rule declares request sources (Express `req`, servlet and
Spring request parameters, ASP.NET request collections and bound action parameters), sanitizers,
and the dangerous argument of each sink. The rules run with the rule pack in the scan job. An
issue is confirmed only when a deterministic-lane Opengrep or Semgrep occurrence from a verifier
rule sits in the same canonical issue, so external SARIF can't claim verification by naming a rule.

A verifier grants `verified` only after measured evidence promotes it. The
[verifier corpus](../../../rule-catalog/code-security/evaluation/verifier-corpus.yaml) pins public,
intentionally vulnerable projects (NodeGoat, Juice Shop, WebGoat, dvcsharp-api, and pygoat) at
exact commits. Its labels come from each project's own documentation, including Juice Shop's
source annotations and coding-challenge verdicts. The operator CLI `evaluate-verifiers` fetches
each project at its commit, runs both verifier kinds without executing project code, and writes a
receipt with per-verifier precision and recall. A verifier is promoted when its precision meets
the corpus floor of 0.90 with at least one true positive, and the promotion list in the verifier
catalog must match that receipt. Every other verifier runs in shadow: it records its hit as
`verifier_in_shadow` and doesn't raise confidence.

Example: the 2026-10-07 receipt promoted the Python verifiers for all five classes and the taint
rules for JavaScript code and SQL injection, Java SQL injection and path traversal, and C# SQL
injection, all at precision 1.0. The JavaScript path traversal rule matched three safe reads in
Juice Shop, where the path came from a server-side lookup or an existence gate, so it stays in
shadow. Rules without real-code evidence, such as the command injection rules, also stay in
shadow. The corpus informed rule development and samples are small, so it isn't a held-out
benchmark.

## Proof lane (opt-in)

The proof lane is the dynamic step: it reproduces a finding instead of reasoning about it. It's
off by default and runs only with `scan --prove`, only for Python issues a promoted verifier
already marked `verified`, and only for command injection, code injection, unsafe
deserialization, SQL injection, and path traversal.

A standard-library harness runs on the sandbox's system Python inside the same bubblewrap
sandbox as the scanners: no network, no credentials, a cleared environment, a read-only source,
and CPU, memory, file-size, and time limits. It imports the fix-site module, resolving
unavailable third-party imports to inert stubs, and replaces each sink with a recording hook
that never performs the real command, evaluation, deserialization, query, or file access. It then
calls the enclosing function with a class-specific payload in every request field and
parameter. The issue is `proven` only when the payload reaches the sink in an exploitable shape:

| Class | Payload | Proven when |
|-------|---------|-------------|
| Command injection | `x;` and a marker | A shell-aware lexer sees a command separator followed by the marker |
| Code injection | The marker | The evaluated text parses with the marker as a name, not a string |
| SQL injection | `x'` and the marker | The quote before the marker survives without escaping |
| Path traversal | `../../` and the marker | The traversal reaches the file operation intact |
| Unsafe deserialization | Encoded marker bytes | Attacker bytes reach the loader |

Quoting, escaping, parameterized queries, `basename`, or a failing import therefore leave the issue
`verified`. On pygoat at its pinned commit, all nine verified issues were proven. The test suite
runs the same harness against safe variants, including `shlex.quote`, `repr`, parameterized
`sqlite3`, and `basename`, and requires every one to stay unproven.

## Failure behavior

| Condition | Outcome |
|-----------|---------|
| Commit can't be fetched or differs from the request | Job stops; nothing is scanned |
| Scanner not installed or offline database missing | Coverage limit; review is `coverage_incomplete` |
| Timeout, output limit, or unexpected exit code | Run marked incomplete and truncated; its SARIF is ignored |
| Invalid SARIF | Coverage limit; producer marked incomplete |
| Unbounded or hostile SARIF content | Rejected or sanitized by [SARIF ingestion](code-security-findings.md#sarif-ingestion) |
| Fewer than two model families for the lens lane | Lens lane doesn't run; a lens note records why |
| Ungrounded, off-lens, or non-quorum model output | Discarded and counted in the lens report |
| Unsupported language or class, oversized, unparsable, or escaping file | Verifier result `unsupported`; confidence unchanged |
| Sink missing, sanitized, validated, or unreachable | Verifier result `not_verified` with a reason; confidence unchanged |
| Verifier hit from an unpromoted verifier | Result `not_verified` with `verifier_in_shadow`; confidence unchanged |
| Proof import failure, timeout, or no exploitable payload at the sink | Result `not_proven` with a reason; confidence stays `verified` |

## Verification

Focused tests cover catalog validation, rule-pack classification and fixture coverage, sandbox
command isolation, real bubblewrap runs (no writes to the source, no network interfaces,
truncation, timeout, and failure codes), exact-commit acquisition, and the scan job end to end.
The rule pack was validated with a Semgrep-compatible engine in test mode, with all 22 rules
passing. Lens tests cover deterministic selection, grounding, CWE filtering, quorum across
families, budget and failure reporting, and the adapter's tool-free strict-schema request through
a mock transport, without live model calls. Verifier tests confirm attacker-controlled flows for
every supported class, and reject parameterized queries, sanitizers, allowlist guards, typed
parameters, safe loaders, reassignment, unreachable sinks, local inputs, symlink escapes, and
revision mismatches. A real `trivy` binary ran inside the sandbox, and its SARIF went through ingestion.

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/operations/code-security-scanning.md) |
| Issues, severity, priority, and remediation packs | [Code Security Findings](code-security-findings.md) |
| LLM tiers and data residency | [LLM Strategy](../architecture/llm-strategy.md) |
| Tracking issue | [Issue #1966](https://github.com/dotnetpower/fdai/issues/1966) |
