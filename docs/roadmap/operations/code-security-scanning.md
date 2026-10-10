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
> promotion gate, the opt-in proof lane for Python, JavaScript, native, Java, and C#, local folder
> scans with reports, and Console scan requests for registered repositories are implemented. See the
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

### Prepared-source handoff

The acquire-to-scan boundary uses `prepare-scan` followed by
`scan --prepared-source DIR --prepared-digest SHA256`. Acquisition exports only the extracted
tree and a versioned manifest: alias, exact revision, tree id, source attribution, and a digest
over relative file names, executable bits, and contents. Keep the returned manifest digest
outside the scanner's writable volume. The scanner compares it with the manifest and checks the
tree before and after scanning. A changed tree, symlink, special file, `.git` directory, or
oversized input stops the prepared scan explicitly; nothing is silently omitted.

The prepared tree is read-only, contains no acquisition credentials, and can be mounted at a
different path in a credential-free scanner process. Prepared mode does not fetch source, enable
live lenses, publish to the bus, or write to the state store. It writes local reports, SARIF,
and receipts only. Existing local and combined worker scans keep their current behavior.

This handoff implements the first boundary of the proposed deployed runtime, not its complete
orchestration. A checksum binds input bytes; it does not attest scanner completion or make an
untrusted result authoritative. Independent completion evidence, the result-recording boundary,
minimum-permission state access, and Kata job orchestration remain deployment prerequisites.

### Deterministic result acceptance

Prepared deterministic scans retain immutable process observations in controller memory, apart
from scanner-writable artifacts. Before returning the candidate, the acceptance adapter replays
those captured stdout bytes through the existing SARIF ingestion, canonicalization, verifier,
coverage, and review pipeline with the controller's source identity and catalog bindings.
It rejects mismatched identities, unknown or duplicate scanners, missing observations,
inconsistent completion, and differences in findings or coverage. Candidate review and receipt
files are not read as acceptance evidence.

The recording adapter writes only a successfully rebuilt result. Model and dynamic-proof
promotions are not accepted through this deterministic adapter; local proof scans remain available.
For an existing revision, review conflict checks finish before issue-detail insertion, and an
existing detail row with a different review digest raises a conflict. A crash between the two
writes may leave detail absent, but never authorizes a conflicting review to fill it.

This is a local controller-owned observation contract, not remote attestation. Distributed Kata
execution still needs an authenticated observation transport, credentials isolated from the
scanner VM, restricted state access, and worker orchestration. Supplying observations copied
from an untrusted receipt does not satisfy the contract.

### Scanner process controls

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
Opengrep, gitleaks, OSV-Scanner, and Trivy. Opengrep is pinned by version and SHA-256. The Go-based
tools retain their scanner versions but rebuild authenticated, checksum-pinned upstream modules
with digest-pinned Go 1.27.2 and patched dependencies. Builds reject compiler or embedded-module
version drift. The glibc-based scanner image uses digest-pinned Azure Linux 3.0, an officially
supported .NET 10 operating system. CPython 3.13.16 retains its authenticated upstream source
checksum and is built against maintained distribution libraries; compilation, installation and
bytecode workers are bounded. The application is rebuilt from the current source and frozen
lock, not copied from a previous scanner image. No unused pip installer is shipped.
The file builds three targets:

- **`runtime` (default):** every scanner and the Python proof lane.
- **`prover-javascript`:** every scanner plus Python and the pinned Node runtime. It omits
  native compilation, Linux development headers, Java, and .NET because this explicitly
  selected profile does not provide those proof languages.
- **`prover`:** the same image plus Node.js, gcc with AddressSanitizer and
  UndefinedBehaviorSanitizer, OpenJDK 21, and the .NET SDK, pinned by SHA-512. `--prove` can then
  reproduce Python, JavaScript, native, Java, and C# issues. The image is glibc-based because the
  sanitizer runtimes don't support musl.

The full profile installs the exact signed `msopenjdk-21-21.0.12.1-1` package rather than
copying an unpackaged JDK tree. It retains the RPM inventory and verifies Java, javac and the
module image against the digest-pinned official JDK image before accepting the build.

The local wrapper keeps `--prove` on the full profile. Select the smaller profile explicitly
with `--prove-profile javascript`; this implies `--prove`, chooses the matching build target,
and reports its limited proof scope. Its image override is
`FDAI_CODE_SECURITY_JS_PROVER_IMAGE`; the full profile's existing override remains unchanged.
Other languages retain their scanner/verifier findings and are not dynamically proven in this
profile. No risk, approval, verifier-promotion, scanner binding, or sandbox control changes.

The JavaScript runtime uses the checksum-pinned official Node.js 24.21.0 LTS binary at
`/usr/bin/node`, with its license notices and an explicit check for bundled Undici 7.29.1.
It does not install the vulnerable Debian Node/Undici package group or an unused npm installer.
Changing this runtime requires positive, negative, timeout, and no-source-mutation proof checks;
remaining Debian and execution-venue kernel findings stay separate from this repair.

The prover also carries `/usr/share/fdai/node-runtime.cdx.json`, generated from the trusted
runtime's reported versions and the exact executable SHA-256. Its CycloneDX scope is explicitly
`embedded-npm-only`: Acorn, Amaro, and Undici have NPM identifiers; other reported fields remain
unassessed metadata. Packaging this inventory lets the normal image scan discover those
statically embedded NPM components. Inspect its scoped contents separately as a cross-check:

```bash
container=$(docker create "$PROVER_IMAGE")
docker cp "$container:/usr/share/fdai/node-runtime.cdx.json" node-runtime.cdx.json
docker rm "$container"
trivy sbom --exit-code 1 --severity MEDIUM,HIGH,CRITICAL node-runtime.cdx.json
```

Run the unchanged image scan as well. A passing scoped SBOM check is not complete native-library,
kernel, full-image, or installation readiness evidence; the inventory is not an attestation.

### Supply-chain repairs and execution scope

Treat package/advisory matches as reported findings until their exact component scope is
reviewed. Image-package metadata does not establish which kernel a container or Kata VM runs.
Keep raw findings, any separate not-affected assessment, and execution-venue observations distinct.

The #2061 platform review rejected Debian 12 for the .NET 10 support gap and did not adopt the
Ubuntu candidate from a lower unmatched package count. The selected supported platform instead
requires recognized operating-system and language-package inventory, unchanged
`MEDIUM,HIGH,CRITICAL` checks, all scanner/proof capabilities and independent runtime evidence.
Missing coverage is not a zero-finding result; unsupported native-library coverage remains explicit.

Local development verification binds one exact image to UID, no-new-privileges, dropped
capabilities, default seccomp, read-only source, no scanner egress, resource limits and actual
positive/negative proof cases. Compiled proof programs require a private bounded executable
workspace; this does not require disabling seccomp or making the source writable. Local evidence
establishes only that selected development venue, not Azure installation or another venue's kernel.

Image build success does not prove supply-chain readiness. Scan all three exact built targets with
fresh vulnerability data, retain findings without available vendor fixes, and never report those
findings as resolved merely because the Go/Python dependency repairs pass.

The entrypoint has two steps:

1. `fdai-scan-runner prepare SOURCE_DIR` refreshes the Trivy and OSV offline databases into the
   cache. It's the only step that uses the network. A folder without a lockfile has no
   dependencies to scan, so OSV-Scanner's "no package sources" exit doesn't fail the step.
2. `fdai-scan-runner scan ...` binds every catalog scanner, the cache, and each proof toolchain
   the image carries, then runs the scan job. All scanners run inside the bubblewrap sandbox with
   no network, and the toolchains take effect only with `--prove`.

bubblewrap needs unprivileged user namespaces under the execution venue's approved security
policy. A namespace denial means that venue is unavailable, not a completed scan. The #2061
default-Docker admission probe was denied; its successful proof-harness tests do not qualify
the nested scanner there.

The separately qualified local scanner venue uses the exact image's exported files in the
existing host bubblewrap namespaces, a cleared environment, read-only source and image files,
unshared networking, no new privileges, and an observed user-service memory/process limit.
It does not disable Docker seccomp, AppArmor, or kernel controls. The existing Docker wrapper's
unconfined settings were not used or qualified by that receipt. Azure/Kata installation still
requires a selected target and its own evidence.

Example: on 2026-10-07 the image scanned OWASP NodeGoat at its pinned commit. All five scanners
completed in the sandbox and coverage was complete. The 423 raw scanner results became 202
canonical issues, 78 of them corroborated by more than one scanner and 3 `verified` by the
JavaScript code-injection verifier. That run also found and fixed three defects that host tests
couldn't reproduce:

- Opengrep rejects Semgrep's `--metrics` flag.
- gitleaks can't write its report through `/dev/stdout` inside the sandbox's user namespace.
- The tools' self-reported names (`Opengrep OSS`, and one `Trivy` for two modes) didn't match the
  catalog producers, so receipts lost the rule-pack digest.

Example: on 2026-10-09 the proof-lane tests ran inside the `prover` image under bubblewrap. Python,
JavaScript, native, Java, and C# fixtures were each `proven` at their fix sites, and their safe
counterparts stayed unproven. The first run showed that the sandbox binds the proof interpreter at
a fixed path without `/etc/ld.so.cache`, so the image links `libpython` onto the loader's default
path.

## CLI entrypoint

The core-control-plane package installs the `fdai-code-security` executable, which is the supported
CLI surface for every code-security command. A source checkout can invoke it with
`uv run --package fdai-core-control-plane fdai-code-security`; the scanner image installs the same
entrypoint in its virtual environment and its entrypoint wrapper uses it for scans and workers.
The module form (`python -m fdai.delivery.code_security_cli`) remains an implementation and test
path, not the user-facing installation contract.

## Local folder scans and reports

You can scan a folder on your machine and get a readable report without a running FDAI
deployment. Pass `--path` instead of `--repository` and `--revision`:

- **Committed code by default:** when the folder is the root of a git work tree, FDAI scans its
  exact `HEAD` commit, so uncommitted edits aren't part of the result.
- **Uncommitted snapshot:** `--include-uncommitted` scans the files git would track, tracked plus
  untracked without ignored files, or every regular file of a folder outside git. FDAI copies them
  into a content-addressed snapshot whose SHA-256 digest stands in for the revision. Symlinks are
  never followed, and size and file-count limits apply.
- **Report:** `--report DIR` writes `report.md`, `report.html`, and `report.json` with owner-only
  permissions. Each lists the decision, scanner coverage, counts, and one row per canonical issue
  with priority, severity, confidence, weakness class, CWE or advisory ids, fix-site location,
  and producers. It never includes source code, scanner messages, code flows, or secret values.
  `--report-locale ko` writes Korean labels.
- **Alias:** `--repo-alias` defaults to the folder name.

A snapshot has no commit, so it can't be the base of a remediation pack or of fix verification.
Commit first when you need either.

`scripts/operations/code-security-scan.sh FOLDER` runs the same scan in the scan runner image. It
builds the image and downloads the offline databases on first use, then scans with
`--network none`:

```bash
scripts/operations/code-security-scan.sh ~/src/payments-api --include-uncommitted --locale ko
```

Add `--prove` to also reproduce verified issues. The wrapper then builds and runs the `prover`
image target.

Example: a developer scans a checkout with one uncommitted file. All five scanners complete in the
sandbox, the uncommitted `draft.py` command injection appears next to the committed one, and the
report shows the lockfile advisories under their package name. No code text appears in the report.

## Repository scans from the Console

An operator can ask FDAI to scan a registered GitHub repository from the Console **Code security**
route. Heimdall is the accountable agent for the result. The request itself grants no authority:

1. **Registration:** an Owner registers an alias for an `owner/repository` location, plus a
   default ref (`HEAD`, the repository's default branch, when omitted) and exposure, from the Console (`POST /code-security/repositories`) or with
   `fdai-code-security repo-register`. Enable and disable toggle scanning. A Console change is a
   typed proposal (`code_security.repository_change`) that the worker applies before any scan.
   Every change uses compare-and-set and appends a Heimdall-attributed audit entry naming the
   requester. An alias can't be repointed at another location.
2. **Request:** a Contributor or Owner submits `POST /code-security/scan-requests` with an alias
   and an optional branch, tag, or commit. The Operator API validates the body and stores a typed
   proposal (`code_security.scan_request`) in its durable outbox. It doesn't scan or read
   repository state.
3. **Scan:** the bounded worker `fdai-code-security process-scan-requests` claims one pending
   request at a time with a lease, rechecks the requester role and the registration, resolves the
   ref to an exact commit, scans it in the sandbox, and records the review with trigger `console`
   and the request id. With a bus bound, Heimdall publishes the review on `object.drift`.
4. **Result:** the proposal closes as completed with a bounded summary (revision, decision, issue
   count, coverage) or rejected with a reason code. The Console lists requests and their status.

A successful `register` or `enable` change continues through one initial scan of the registered
default ref before the request closes. Registration remains an independently audited state change:
an initial scan failure does not erase the registration, and the terminal request result names the
scan failure so an operator can request a retry. A successful initial scan records the exact
revision, review digest, decision, issue count, coverage, and publication state in the same bounded
request result.

The Console follows the registry state when presenting this flow. With no registered repository,
it expands the Owner-only registration flow, omits the unavailable scan-request controls, and
connects Register, Scan, and Review as one visible sequence. The primary form accepts
`owner/repository` or an HTTPS GitHub URL, normalizes the URL before submission, and suggests the
alias from the repository name. Alias, default ref, and exposure remain editable under secondary
repository settings. After at least one repository exists, scan request becomes the primary task
and registration returns to a collapsed secondary disclosure. This presentation does not change
role checks, proposal semantics, or the worker's effect boundary.

The worker reads repository access from the deployment's GitHub App (`FDAI_GITHUB_APP_*`) or token
(`FDAI_GITOPS_TOKEN`) environment and narrows each token to the one registered repository with
read-only contents permission. Without credentials only public repositories can be scanned. The
request and scheduled workers remain bounded batches. A supervised code-security worker service
invokes the request batch every 5 seconds and the scheduled revision check every 5 minutes by
default; deployments can select bounded intervals without changing scan authority. Every cycle
writes a content-free heartbeat with the next request and schedule times. A missing or stale
heartbeat makes automation unavailable in the Console instead of leaving queued work looking
active. The AKS worker also updates a content-free local health file only after a durable heartbeat
write succeeds. Its readiness and liveness exec probes reject a missing or stale file with
thresholds derived from the request interval, without exposing an HTTP endpoint or credentials.
Each process uses a unique worker identity and renews its 60-second claim while scanning.
A replacement cannot steal an unexpired claim and recovers abandoned work only after the bounded
lease expires. The local full-stack supervisor runs the worker in the fixed
`fdai-code-security-worker` container. Its managed wrapper stops that exact container when the
supervisor terminates, and startup fails closed if the name is already owned, preventing stale
workers from accumulating across restarts. The scan runner image owns both the service and one-shot
commands.

Source acquisition resolves the remote ref, clones the exact commit into the private
content-addressed scan work root, removes `.git`, and makes the extracted tree read-only. The
Console never exposes that local path or source text. It shows the exact revision and review result
after recording, which is the operator's confirmation that the clone, scan, and review completed.
Git ref resolution and acquisition run outside the asynchronous coordinator loop so heartbeat and
claim renewal continue during a slow network fetch or archive extraction.

Automatic scans also produce two bounded, review-digest-bound presentation artifacts: a canonical
SARIF 2.1.0 document and a self-contained HTML report. They contain canonical issue metadata,
fix-site locations, severity floor and ceiling, deciding facts, scanner completion, coverage limits,
and counts, but no source code, scanner messages, code flows, credentials, or secrets. The worker records them immutably beside the issue
summaries. The authenticated Console can render either artifact for the exact repository revision;
an absent, oversized, malformed, or digest-mismatched full artifact is explicit, and the Operator
generates a clearly labeled summary-only HTML/SARIF view from the already validated issue summaries
without inventing paths or scanner coverage.

The Console uses the exact repository-relative fix-site path and line to build a GitHub blob link
pinned to the scanned commit. Operators inspect the actual code in the repository's own access
boundary. The full artifact can also retain at most seven exact-revision context lines around the
fix site, bounded per line and per finding. Secret-producing findings retain only the structural
assignment key and replace the value with a redaction marker; surrounding lines are omitted.
Other findings retain bounded text with control characters removed. FDAI never stores a whole
source file or an unredacted secret. Artifact schema 1.4 stores SARIF as compact JSON so whitespace
does not consume the 900 KB persistence envelope; it removes no finding, context line, redaction,
or recorded flow step. The Console formats that validated JSON for human-readable display.

The issue projection publishes a mutually exclusive display scorecard for determined Critical,
High, Medium, Low, and Informational findings plus a separate Needs review count for canonical
`undetermined` severity. Informational is a display triage bucket for canonical Low findings whose
deterministic priority is P4; it is not a new canonical severity. Needs review also reports the
number whose severity ceiling is Critical, High, Medium, or Low so uncertainty never becomes a
false determined count.

The [Knowledge GitHub connection](../../runbooks/knowledge-github-sources.md) can also register
a verified repository source, using either public read access or the deployment's read-only
GitHub App credential reference. Its repository provenance remains on the existing registration;
credential bytes never enter the stored record. A new Knowledge connection leaves scanning
disabled. An Owner separately enables scans, so Knowledge read access alone cannot request or
enable a scan. Disconnecting Knowledge does not revoke independently granted scan permission.

| Rejection reason | Meaning |
|------------------|---------|
| `request_malformed` | The stored body isn't the typed alias and ref |
| `requester_role_insufficient` | A scan requester had neither Contributor nor Owner, or a registration requester wasn't an Owner |
| `repository_not_registered` / `repository_disabled` | The alias can't be scanned or toggled |
| `repository_conflict` | A registration names an alias that's already bound to another location |
| `source_unavailable` | The ref, repository, or credential couldn't be resolved |
| `scan_failed` / `review_conflict` | The scan failed, or different findings exist for that commit |
| `attempts_exhausted` | The request was claimed more than three times |

### Scheduled scans

`fdai-code-security process-scheduled-scans --max-repositories N` scans the enabled registrations
in rotating alias order at their default refs with the same runner, credentials, and sandbox as the request
worker. It records each review with trigger `schedule` and no request id, and publishes it when a
bus is bound. Before scanning, the worker resolves the default ref and compares it with the last
successfully recorded revision for that repository. An unchanged revision records an `unchanged`
cycle outcome without running scanners or creating another review. A changed revision is scanned
by its exact commit id; only a successfully recorded review advances the durable revision
watermark. A failed check remains explicit and never appears as an unchanged or successful review.
Each repository ends as `published`, `unchanged`, `failed` with the request worker's
`source_unavailable`, `scan_failed`, or `review_conflict` reason, or `deferred` with
`schedule_capacity` when more repositories are enabled than the batch allows. One failure doesn't
stop the others, and the command reports `ok: false` when any scanned repository failed. The scan
runner image starts it with `fdai-scan-runner process-schedule`.

A durable cursor advances after each terminal repository attempt, including a failed attempt.
The next invocation resumes after that alias and wraps to the beginning. Bounded batches therefore
do not repeatedly scan only the first aliases while leaving later registrations deferred forever.
Run one schedule coordinator at a time, as required by the proposed `CronJob` concurrency policy.

Example: on 2026-10-09 a run with `--max-repositories 1` against a throwaway database scanned the
public OWASP NodeGoat registration at `HEAD`. It resolved commit `c5cb68a7` and recorded 202
issues with trigger `schedule`. A second enabled registration was reported `deferred`, and a
disabled one was skipped.

## Deployed scan runtime (proposed)

This runtime is partially implemented. The optional Kata scanner backend, authenticated process
observation, restricted database capabilities, and namespace/RBAC renderer pass focused tests.
No live deployed scanner run is claimed. The deployment must bind an exact cluster, immutable
image, dedicated Kata pool, shared source/cache storage, and controller identity first.

**Problem and revision.** Local bubblewrap needs unprivileged user namespaces. The deployed
backend instead runs each deterministic scanner directly in its own Kata pod VM, so it does not
request nested user namespaces or `Unconfined` profiles. `RuntimeDefault` seccomp, Restricted Pod
Security, read-only inputs/root filesystem, dropped capabilities, and no identity/secret mounts
remain required. Dynamic proof and live lens lanes are not enabled by this backend.

**Runtime.** On AKS, scanners run under
[Pod Sandboxing](https://learn.microsoft.com/azure/aks/use-pod-sandboxing) (Kata Containers), which
gives each pod its own lightweight VM and guest kernel:

- **Node pool:** a dedicated user pool with `os_sku = "AzureLinux"`,
  `workload_runtime = "KataVmIsolation"`, a generation 2 VM size with nested virtualization (for
  example, Dsv5), autoscaling from zero, and a `NoSchedule` taint so only scanner pods land there.
  Pod Sandboxing supports only Azure Linux and amd64, which FDAI's AKS profile already uses.
- **Scanner pod:** `runtimeClassName: kata-vm-isolation`, a toleration and node selector for the
  pool, user 65532, all capabilities dropped, no privilege escalation, and a read-only root file
  system. It retains `RuntimeDefault` seccomp. The host still runs the Kata shim, Cloud Hypervisor,
  and `virtiofsd` for each pod,
  and shared volumes are host-mediated, so the pod allows only `emptyDir` and the read-only volumes
  named below, never `hostPath`, and the node pool follows the AKS node image patch cadence.
- **Resources:** Kata sizes the pod VM from the pod memory limit, and the guest kernel and Kata
  agent consume part of it. Limits come from measured scanner peaks plus that overhead, and the
  job deadline includes a cold-start margin.

**Admission and observation.** The scanner namespace enforces Restricted Pod Security. The
controller verifies the installed Kata runtime class and the namespace's deny-all network policy
before creating a Job; additive ingress/egress allowance policies cause a denial. It observes the
exact Job UID and checks its pod's image, command, identity, mounts, resources and privileges
against the submitted contract. An extra init/ephemeral container, secret volume, image change,
or identity drift stops acceptance. Controller RBAC grants only scanner Job create/get/delete,
pod metadata/log reads, network-policy reads, and exact namespace/runtime-class reads. It grants
no secret access, pod exec, workload patching, or RBAC escalation.

**Credentials stay out of the scanner VM.** Kata protects the node, not the other processes in
the same pod VM. A scanner that escapes bubblewrap mustn't find a GitHub token, a database
credential, or open egress. Each run therefore splits into three steps:

1. **Acquire** (a `runc` pod with the worker's workload identity): claim the request or select the
   scheduled repository, mint a read-only installation token for that one repository, fetch the
   exact commit, and write the extracted tree to a per-run volume.
2. **Scan** (one Kata pod per scanner): mount that tree, the rule pack, and vulnerability cache
   read-only. The controller captures bounded stdout through the authenticated Kubernetes log
   API. The pod has no service-account token, secret mount, shared output write mount, or egress.
3. **Record** (the `runc` pod again): validate the output against the exact commit, record the
   review in the state store, publish it on `object.drift`, and close the request.

Both workers can select this split with `--scanner-runtime kata --state-access restricted`.
Their local default remains the existing combined bubblewrap path. The in-cluster API uses the
controller's service-account token and TLS CA only outside the scanner VM. Bounded stdout and the
pod's terminated process exit code enter deterministic result acceptance; scanner-supplied
completion claims never govern coverage. After reading logs by pod name, the controller reads
that pod again and verifies its UID and terminated process state have not changed, so stdout
from a replacement cannot be bound to the original execution. API errors are not retried, Jobs have active and
no-progress deadlines, and cleanup deletes only the exact UID. Private attempt journals retain
preflight/dispatch/observation failures that occur before a review exists. A worker that loses
its proposal claim cannot report a completed or rejected terminal result.

`render-scanner-runtime` produces the namespace, deny-all policy and minimum observer RBAC.
It does not create a cluster, node pool, identity, database, or storage. The controller namespace
must differ from the scanner namespace. Installation must supply RWX source storage shared by
the acquisition/recording controller and the read-only scanner mounts, and a separate read-only
cache snapshot. The dedicated pool uses `fdai.io/code-security-scanner=true` as its label and
`NoSchedule` taint.

`render-scanner-workers` additionally produces the controller namespace/service account and
the Console-request and registered-repository CronJobs. Jobs are suspended unless you explicitly
pass `--enable-jobs`. Both schedules use five-field UTC cron, `concurrencyPolicy: Forbid`,
no automatic retry, a bounded active deadline, the pinned scanner image, and
`--scanner-runtime kata --state-access restricted`.

Supply distinct controller and scanner PVC references for source and cache. PVCs are
namespace-scoped: matching names do not share data. The installer binds each namespace's
claims to the same respective backing store before enabling jobs. Source storage must be
writable by controller user 65532; both controller and scanner cache mounts use the same
digest-named snapshot read-only. No volume or secret values are fabricated by the renderer.

The existing controller Secret supplies `dsn`. A ConfigMap supplies `bootstrap-servers`, so
accepted reviews are wired to the bus rather than silently running without a publisher.
An optional GitHub App Secret supplies `client-id`, `installation-id`, and `private-key`;
without it only public registered sources are available. These are reference names, not
credentials passed as CLI arguments. Neither renderer creates Secrets, grants database role
membership, chooses an Azure target, or applies cluster resources.

Example: render suspended worker resources after installation has supplied the referenced
volumes, role-scoped Secret and broker ConfigMap:

```bash
fdai-code-security render-scanner-workers \
  --controller-namespace scan-controller --controller-service-account scan-controller \
  --scanner-namespace code-security \
  --image example.invalid/scanner@sha256:<64-hex-digest> \
  --controller-source-pvc controller-source --scanner-source-pvc scanner-source \
  --controller-cache-pvc controller-cache --scanner-cache-pvc scanner-cache \
  --cache-subpath snapshots/<64-hex-cache-digest>/cache \
  --state-secret scan-state --broker-config-map scan-broker \
  --request-schedule "*/5 * * * *" --scan-schedule "0 2 * * *"
```

Example worker binding (replace names and the digest with the selected deployment's values):

```bash
fdai-code-security process-scan-requests \
  --state-access restricted --scanner-runtime kata \
  --scanner-namespace code-security \
  --scanner-image example.invalid/scanner@sha256:<64-hex-digest> \
  --scanner-source-pvc scan-source --scanner-source-mount /work \
  --scanner-cache-pvc scan-cache --scanner-cache-subpath cache --cache-dir /cache
```

The same bindings apply to `process-scheduled-scans`. Source acquisition and recording retain
their normal credentials in the controller. Per-run source and rule-pack handoffs expose only
their named read-only subdirectories to each scanner, and rule-pack digests are checked before
and after execution. Before starting the engine, the image-owned `verify-scanner-input` bootstrap
also checks source, rule-pack, and cache bytes from the actual scanner mounts against controller
digests. A mismatched PVC or snapshot therefore cannot be accepted as the requested input.
Cleanup API failure stops the attempt but retains the independent process outcome and its stdout
digest in a private journal; TTL is a recovery backstop, not a success-shaped cleanup fallback.
Deployment network-denial and guest-kernel isolation probes remain required;
unit tests and Kubernetes metadata alone do not establish live isolation.

**Vulnerability cache.** A separate preparation job refreshes the Trivy and OSV databases through
the deployment's egress firewall, which allows only those database hosts. It publishes a
versioned snapshot atomically and keeps the last known-good one, so an upstream outage doesn't
stop scanning. `fdai-scan-runner prepare-snapshot SOURCE_DIR ROOT` refreshes in a private staging
directory, publishes a read-only digest-named generation under `ROOT/snapshots`, and atomically
updates `ROOT/current.json` only after preparation succeeds. Failed preparation does not replace
the current pointer. Bind the resulting `cache_subpath` and cache directory to the scanner
worker's read-only cache PVC. A digest binds the observed bytes; it does not prove database
freshness or package completeness, which still depend on provider metadata and scanner coverage.
Deployment firewall configuration and a scheduled preparation job remain installation inputs.

**State-store privilege.** Code-security records and the proposal outbox share the generic
`state_kv` table, so the worker does not receive table grants. The Core migration
`core_code_security_role_20261009` installs fixed-parameter `SECURITY DEFINER` functions and the
`fdai_code_security_worker` role. `process-scan-requests --state-access restricted` and
`process-scheduled-scans --state-access restricted` assume that role for every database connection,
including inherited adapter operations. The deployment grants role membership to its dedicated
worker login; missing membership or migration fails without falling back to Core.

The functions allow only code-security registration, review, issue-detail, and schedule keys.
Reviews and issue details are insert-only. The outbox functions claim and close only the two
code-security operation types with lease and claim-id checks. The audit functions expose the
current hash anchor, not audit payloads, and append only bounded Heimdall registration events
with no execution authority. State changes and audit appends remain one transaction.
Existing Core and Operator access is unchanged, so the Console keeps reading the same records.
Real validation-database tests prove unrelated state, raw table reads, broad audit access, and
other proposal operations are inaccessible, including through inherited adapter methods.

The legacy local binding remains `--state-access core` by default for compatibility. Deployed
isolated workers explicitly select `restricted`; this does not yet supply their Kata orchestration.

**Evidence and failures.** The record step wires the bus publisher explicitly. A job attempt that
fails before a receipt exists, during preparation, acquisition, or scheduling, writes a durable
attempt record, and `CronJob` failures raise the existing job alert. Microsoft Defender for
Containers doesn't assess Kata pods, so the image's vulnerability scan before publication is the
image control. The container supply chain publishes the `runtime` target, or `prover` when the
proof lane is enabled, and jobs reference it by digest.

**Cost and authority.** The pool scales to zero between runs, but each run starts a node, so a
deployment profile must opt in with a monthly cost ceiling above zero. Enabling the pool and the
jobs is a deployment change for an explicitly selected target. Delivery authorization doesn't
grant it.

**Exit evidence.** From one deployment:

- **Recorded runs:** one scheduled and one Console review, each published, each naming the runtime
  class, node pool, and cache snapshot.
- **Admission denials:** for a missing runtime class, a wrong namespace, a container-level or
  init-container override, an ephemeral container, and a legacy annotation.
- **Isolation probes:** the scanner pod can't reach any network or read an identity token or
  secret, and its source and cache mounts are read-only.

## LLM lens lane

The lens lane looks for weakness families that rules miss, such as missing authorization. It's
optional, runs off the agent hot path inside the scan job, and produces only inert hypotheses:

1. **Select deterministically:** walk the read-only source in sorted order, skip vendored,
   oversized, binary, and non-UTF-8 files, and pick bounded excerpts around lines that match a
   lens's sink hints in the [lens catalog](../../../rule-catalog/code-security/lenses.yaml).
2. **Ask several model families:** send each excerpt to every configured model as untrusted JSON
   data with line numbers, a strict JSON schema response, no tools, and a request byte ceiling.
3. **Verify in code:** keep a candidate only when the cited line is inside the excerpt, uses one
   of the lens's CWEs, and either matches a sink hint or assigns a variable that a later sink-hint
   line of the same excerpt uses as a whole word. Such a one-hop flow is anchored at that sink
   line, where SARIF producers place the fix site, so models that cite different lines of one flow
   meet at the same sink. No meaning is read from names or comments.
4. **Require a quorum:** emit an occurrence only when at least two distinct model families report
   grounded candidates within the line tolerance.

Kept candidates enter canonicalization in the `llm_lens` lane. They get `hypothesis` confidence,
so they can't reach alerting priorities on their own. They're corroborated only when a
deterministic or external producer reports the same root cause, and they become `verified` only
when a [weakness verifier](#weakness-verifiers) confirms the flow. With fewer than two model
families, the lane doesn't run. Budget exhaustion, model failures with their fixed reason counts,
and skipped files are recorded as lens notes in `receipt.json`. Those notes don't change deterministic coverage, because the
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

### Lens precision on real code

The operator CLI `evaluate-lens` measures hypothesis precision on
[`evaluation/lens-corpus.yaml`](../../../rule-catalog/code-security/evaluation/lens-corpus.yaml).
The corpus pins OWASP Benchmark for Java, whose maintainers label every test file with its category
and whether it's a real vulnerability. The command acquires the exact commit and takes the first ten
true and ten false files of each mapped category (command injection, path traversal, SQL injection)
in test-name order. It copies only those files into an owner-only scratch root and runs the lane
with only the matching lenses and unchanged prompts, hints, and limits. Every kept hypothesis is
labeled mechanically in the receipt: it's a true positive only when the file's category matches the
lens class and the file is a real vulnerability. `--dry-run` counts candidates and calls without
calling a model.

Measured, 2026-10-08, with `gpt-4.1-mini` and `gpt-4o`: 60 files produced 55 candidates and 110
calls with no errors. The lane kept 10 hypotheses, all for command injection: 5 true and 5 false
positives, precision 0.5 and recall 0.5. Each false positive is a file where a constant branch
(three files) or a list-index shuffle (two files) replaces the request value with a constant. Path traversal and SQL injection kept none: models cite the line that
builds the query or path, while grounding accepts only a sink-hint line, so 79 claims were
rejected as ungrounded. Lens hypotheses therefore stay inert until another producer or a verifier
confirms them.

Grounding then accepted the one-hop flow above. On a disjoint sample (`--sample-offset 10`, the
next ten true and ten false files per category) with the same two models, the strict rule kept 9
hypotheses (5 true, precision 0.556) with recall 0.5, 0, and 0 for command injection, path
traversal, and SQL injection. Flow grounding anchored 59 claims to their sink and kept 30 (15
true, precision 0.5) with recall 0.7, 0.4, and 0.4. Precision stays near 0.5, so lens
hypotheses remain inert.

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
   flow. An allowlist or validation guard on the value removes taint on both branches, including
   a fixed-substring check such as `'../' in name` on the value itself, but not on the arguments
   of a call that produces the checked container. A function-local list built from a literal is
   tracked element by element while it is only extended with `append` and shrunk with `pop` at a
   fixed index, so reading a clean element after a tainted one isn't a flow. Any other use of the
   list, or branches that disagree on its length, fall back to treating the whole list as tainted.
3. **Reachable:** the sink isn't after a `return` or `raise`, or in a branch that is never taken.
   The verifier folds `if`, conditional-expression, `while`, and `match` conditions built from
   literals and function-local names bound once to a literal, and analyzes every branch otherwise.
   An assignment made before `break` reaches the code after the loop, and `continue` re-enters
   the loop body.
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
intentionally vulnerable projects at exact commits, each in a `dev` or `holdout` split. Labels come
from each project's own documentation, such as Juice Shop's source annotations, lesson pages,
solution guides, and ground-truth files. OWASP Benchmark for Java and Python supply whole-file
labels from their `expectedresults` files, split by a hash of the test name. The operator CLI
`evaluate-verifiers` fetches each project at its commit, runs both verifier kinds without executing
project code, and measures every verifier as if promoted. It writes a receipt with per-verifier
precision and recall for each split. A verifier is promoted only when its precision meets the
corpus floor of 0.90 with at least one true positive in both `dev` and `holdout`, and the
promotion list in the verifier catalog must match that receipt. Every other verifier runs in
shadow: it records its hit as `verifier_in_shadow` and doesn't raise confidence.

Example: the 2026-10-08 receipt (corpus 1.1.0, 710 `dev` and 681 `holdout` labels) promotes five
verifiers: Java and JavaScript command injection, JavaScript code and SQL injection, and Python SQL
injection, each at precision 1.0 in both splits. Six verifiers promoted by the earlier receipt fell
back to shadow on held-out evidence. Java SQL injection measured about 0.6, because Benchmark's
constant branches and dead switches fool open-source taint mode. Python code injection, path
traversal, and unsafe deserialization measured 0.27 to 0.83, because the AST verifier ignores
early-return guards. Java path traversal and C# SQL injection had no held-out true positives.
Python command injection measured 0.75 on `holdout` and stays in shadow. The JavaScript path
traversal rule no longer treats a one-argument store lookup as tainted, but two safe Juice Shop
reads gated by a known-key lookup still keep it in shadow.

Example: the verifiers 1.3.0 receipt on the same corpus adds constant-condition folding and
fixed-substring guards, and returns Python code injection to promotion at precision 1.0 with 11
`dev` and 3 `holdout` true positives. No true positive was lost in either split. Python path
traversal rose to 0.90 on `dev` and 0.82 on `holdout`, and unsafe deserialization to 0.88 and 1.0,
so both stay in shadow.

Example: the verifiers 1.4.0 receipt (2026-10-09) adds element-sensitive list tracking, loop
`break` and `continue` flow, the `codecs.open` sink, and the narrower substring guard, all tuned on
`dev` only. It promotes Python path traversal (precision 1.0 on `dev` with 17 true positives and
0.94 on `holdout` with 16) and unsafe deserialization (1.0 in both splits with 8 and 10). Python
command injection measured 1.0 on `dev` and 0.75 on `holdout` and stays in shadow.

The managed-language 1.6.0 evaluation adds a generic Java AST constant-flow veto rather than
Benchmark-specific sanitizers. It recognizes provably constant local/control-flow/helper results,
keeps unknown flows unchanged, and removes only verifier evidence, not the base reported finding.
The same helper runs in evaluation, scan jobs, prepared-result acceptance, and repository-backed
pack export. It removed 13 Java SQL false positives without losing a true positive: precision is
0.8333 on `dev` (15 TP, 3 FP) and 0.9130 on `holdout` (21 TP, 2 FP). The rule remains in shadow.
The unresolved `dev` cases include a mutable map and reflection through classloader properties;
the latter cannot be treated as a known local pure method without further evidence. C# source,
sink and sanitizer corrections increased `dev` true positives from 2 to 5 with no false positives,
but the remaining held-out evidence still does not justify promotion.

Constant guard version 2 (catalog 1.7.0) additionally tracks exact locally constructed JDK
`HashMap` values at literal String keys and a final unconditional assignment in the same lexical
block. Aliases, escapes, custom map dispatch, unknown keys, or conditional mutation produce no
constant proof. Dev precision rises from 0.8333 to 0.8824 (15 TP, 2 FP); holdout stays 0.9130
(21 TP, 2 FP), with no true-positive loss. Java SQL remains in shadow because dev is still below
the 0.90 floor. Configuration-selected reflection is not assumed safe.

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

Proof output is untrusted JSON. Non-string issue identifiers or outcomes cannot consume a
target, interrupt later valid results, or raise confidence. A target without a well-formed
result remains `not_proven` with `no_result`.

Retransmission of the same normalized proof record is idempotent. Distinct valid outcome,
reason, or sink records for one expected target instead create a sticky, order-independent
`not_proven` result with `conflicting_results`; later repeats cannot restore proven confidence.
Other targets remain independent. Neither first-wins nor last-wins resolves conflicting evidence.

### Other proof languages

The lane picks a harness by fix-site extension, and a language runs only when the operator gives
its runtime with `scan --prove`:

- **JavaScript** (`--prove-node`): `fdai_prove.js` runs on Node.js in the same sandbox. Its loader
  replaces every package with an inert stub and `child_process`, `fs`, and `vm` with recording
  hooks, and `eval` and `Function` are hooks too. Each hook returns an inert stub, so the target
  keeps running past one sink. The harness calls every exported, registered, or
  constructor-assigned function whose source contains the fix-site line. A hit counts only when the
  caller's stack frame is the fix-site file and line, and the same class predicates as Python
  apply. Targets are JavaScript issues a promoted verifier confirmed.
- **Native C and C++** (`--prove-cc`): memory-safety issues have no deterministic verifier, so
  they're eligible when a deterministic or external producer reported them, never the LLM lens
  alone. `fdai_prove_native.py` finds the enclosing function and accepts only a buffer signature
  it can drive: a byte or char pointer with an optional length, or one string. It builds a driver
  and the target with AddressSanitizer and UndefinedBehaviorSanitizer and runs fixed input
  lengths. The issue is `proven` only when the sanitizer's first frame in the target file is the
  fix-site line. AddressSanitizer can't run under an address-space limit, so this run alone drops
  the sandbox `RLIMIT_AS`. The harness limits the compiler's address space and gives every run a
  CPU limit, `hard_rss_limit_mb`, a timeout, and truncated output.
- **Java and C#** (`--prove-java`, `--prove-dotnet`): these languages have no module loader to
  hook, so `fdai_prove_managed.py` rewrites a private copy of the fix-site file without moving any
  line. Every argument of a known command, query, or file-access call, and every value assigned to
  `FileName`, `Arguments`, or `CommandText`, passes through a recording hook first. The hook always
  returns an inert value of the same type, a path that can't exist, so a sink that still runs
  can't start a real program, open a real file, or send a real query. The harness compiles the copy
  alone with `javac` beside the given `java`, or with the SDK's Roslyn compiler under the given
  `dotnet`, then calls every method and constructor with the marker in each string, collection,
  and interface input. A hit counts only for a hook of the target's class, from a stack frame at the
  fix-site file and line, in the class predicate's shape. Only the argument that carries the class
  counts: the path of a file call, the query text, or a command's program and arguments read
  together. File contents and bound query parameters are made inert but never prove a finding.
  For command injection the program must be a shell and the value must reach the one argument it
  runs as its command (`sh -c`, `cmd /c`) after a separator. Only a single command-line string is
  split into words, and later arguments are positional parameters that the shell never parses. Constructing a `File`,
  `Path`, or `FileInfo` isn't a file access. A file that needs project dependencies doesn't compile
  alone and stays unproven with `compile_failed`. The harness runs on the sandbox's Python with the
  toolchain as its last argument; the toolchain must resolve inside the sandbox's read-only system
  mounts. Distribution JDKs link their `conf` files into `/etc`, so a Java run alone also mounts
  those `/etc/<name>` directories read-only. The .NET runtime keeps the sandbox address-space limit
  through a bounded GC heap and region range and single-mapped JIT memory.

On OWASP NodeGoat at its pinned commit, the three `eval` lines in `contributions.js` were proven in
the sandbox. Tests prove vulnerable JavaScript fixtures for command, code, SQL, and path flows and
a stack overflow in a C fixture, and require the safe counterparts (`execFile` with an argument
list, `Number`, a placeholder query, `basename`, and a bounds-checked copy) to stay unproven.
Java and C# fixtures prove shell command, string-built query, and concatenated file-path flows in
the sandbox, and require the safe counterparts (an argument list without a shell, a `grep -c`
argument without a shell, input passed as a shell positional parameter, a quoted argument-list
element, a parameterized query, a base name, and request text written to a constant path) to stay unproven with `canary_not_observed`. A hooked shell command
creates no file, a spinning class initializer is reported `timed_out`, and a C# file that needs a
NuGet package stays `compile_failed`. No public-project Java or C# result is recorded yet.

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
| Local folder isn't a repository root, is empty, or exceeds snapshot limits | Job stops; nothing is scanned |
| Console request for an unregistered or disabled alias, or an unresolvable ref | Request closes as rejected with a reason code |

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
Local scan tests cover committed-`HEAD` and snapshot acquisition, ignored files, symlink escapes,
ref resolution, and report escaping and localization; a real bubblewrap run scans an uncommitted
snapshot. Request tests cover registration, audit, body validation, and every rejection reason, and
a throwaway PostgreSQL database validated the proposal claim, completion, and Operator projections.
A live run against github.com registered `OWASP/NodeGoat` without a ref, resolved `HEAD` to its
default branch commit, completed all five scanners with complete coverage, and recorded 202 issues
with the request id.

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/operations/code-security-scanning.md) |
| Issues, severity, priority, and remediation packs | [Code Security Findings](code-security-findings.md) |
| LLM tiers and data residency | [LLM Strategy](../architecture/llm-strategy.md) |
| Tracking issue | [Issue #1966](https://github.com/dotnetpower/fdai/issues/1966) |
