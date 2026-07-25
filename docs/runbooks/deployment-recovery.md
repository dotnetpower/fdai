---
title: Deployment Recovery
summary: Recover safely from protected-plan rejection, offline-kit verification failure, or degraded runtime readiness.
---

# Deployment Recovery

Use this runbook when a connected or disconnected deployment cannot continue safely. It maps the
existing machine statuses to a new-plan, new-kit, or fresh-evidence recovery path without editing
signed metadata or manufacturing readiness.

> **Scope:** This procedure is customer-neutral. A downstream fork supplies environment values,
> repository names, evidence locations, owners, and approved release channels.

## Ownership and entry criteria

- **Owner:** Deployment operator for plan and kit recovery; runtime operator for readiness recovery.
- **Approver:** The environment's designated deployment approver. A recovery does not reuse an
  approval for a different plan digest or deployment context.
- **Entry:** One of the stable signals in the decision table is present.
- **Impact scope:** One environment, one protected plan id, or one offline-kit candidate at a time.
- **Terminal no-op:** If the signal cannot be tied to sanitized machine evidence, do not submit an
  apply, replace trust material, or restart consumers. Record the gap and route it for review.

## Decision table

| Signal | Meaning | Stop condition | Safe recovery |
|--------|---------|----------------|---------------|
| Plan status is `planning`, `applying`, `applied`, `failed`, or `expired` | The plan is not eligible for a new exact apply | Do not submit apply | Produce and approve a new plan when another deployment is needed |
| `plan has expired` | The signed apply window closed | Do not extend `expires_at` or reuse the plan id | Repeat doctor, preflight, and plan creation |
| Plan context, commit, bundle, source, evidence, or binary digest mismatch | Current intent differs from the protected artifact | Do not edit metadata or pass a different expected digest | Correct the input and create a new protected plan |
| Plan is blocked by preflight or the approved runner is unavailable | Required evidence or execution boundary is unavailable | Do not apply locally | Resolve the reported blocker and create a new plan on the approved runner |
| `fdaictl provision inspect` returns `4` or `status=incomplete` | Required host, identity, connectivity, or kit evidence failed | Do not initialize or deploy from the profile | Repair the failed check and inspect again |
| `artifact.offline-kit=fail` | Signature, compatibility, manifest, file set, or digest verification failed | Do not repair files inside the rejected kit | Replace the entire kit from the pinned release source and inspect again |
| `artifact.offline-kit=candidate` | A kit exists but no pinned verifier established trust | Do not treat presence as verification | Install a release with the packaged public root or use the connected path |
| Startup `decision=blocked` or `/ready` returns `503` | Process-critical evidence is failed, missing, stale, timed out, or crashed | Do not manually start consumers or the Pantheon | Restore the dependency and wait for a fresh periodic readiness evaluation |
| Startup `decision=degraded` | The process can remain ready with reduced authority | Do not act above any reported `authority_ceilings` value | Restore the affected capability and confirm a fresh report raises no authority |
| Startup evidence is missing or stale | The prior observation no longer proves readiness | Do not edit results, timestamps, expiry, or state-store records | Let the configured probe produce fresh evidence |

## Recover a protected plan

1. Read the sanitized plan record before attempting apply:

   ```bash
   fdaictl deploy status \
     --repository <owner/repository> \
     --plan-id <plan-id> \
     --output json
   ```

2. Stop unless `status` is exactly `ready`, the current time is before `expires_at`, and the plan
   digest still belongs to the intended environment, bundle, commit, backend, and runner.
3. For any expiry or mismatch, rerun the read-only prerequisites and submit a new plan:

   ```bash
   fdaictl doctor --config <environment-config> --output json
   fdaictl deploy preflight \
     --input <preflight-input> \
     --environment-config <environment-config> \
     --output json
   fdaictl deploy plan \
     --config <environment-config> \
     --repository <owner/repository> \
     --bundle-digest <sha256> \
     --commit-sha <git-sha> \
     --output json
   ```

4. Obtain approval for the new plan id and digest. Never transfer approval from the rejected plan.
5. Submit only the exact approved plan through `fdaictl deploy apply`. Runner-side verification must
   still match the binary plan, source artifact, preflight evidence, context, commit, status, and
   expiry.

The preflight command exits `0` for clear, `2` for findings that need review, and `3` for a deployment
blocker. An exit code is evidence, not permission to bypass the report.

## Replace a rejected offline kit

1. Inspect without mutation:

   ```bash
   fdaictl provision inspect \
     --connectivity offline \
     --host existing \
     --offline-kit <kit-directory> \
     --output json
   ```

2. Require overall `status=ready`, exit `0`, and `artifact.offline-kit=verified`. Exit `2` means
   review; exit `4` means incomplete. `candidate` and `not-configured` are not trust decisions.
3. If verification fails, quarantine the directory as evidence. Do not replace one artifact, rewrite
   the manifest, regenerate the signature, or supply an operator-selected trust root.
4. Obtain a complete replacement from the pinned release source. Verify it with the packaged public
   root and the exact CLI version and platform.
5. Run inspection again. Continue only after the replacement independently reaches `verified` and
   all required tool and workload-identity checks pass.

If no production public root is packaged, stop. Use the connected path or wait for the release trust
ceremony; a test key or local override is not an operational recovery.

## Recover runtime readiness

1. Use `/live` only for process liveness and `/ready` for processing readiness. A live process can
   still be blocked.
2. Read `runtime:startup-readiness:latest`. Record `decision`, `missing_probe_ids`,
   `stale_probe_ids`, each result's `status` and `failure_class`, and `authority_ceilings`.
3. For `blocked`, restore the named dependency while the runtime keeps processing closed. Avoid a
   manual consumer or Pantheon restart, which can create duplicate work outside the lifecycle gate.
4. For `degraded`, keep every affected capability at or below its reported ceiling. In particular,
   don't infer deployment authority from an HTTP `200` on `/ready`.
5. Wait for the configured periodic refresh. Only a newly observed, unexpired probe result can clear
   missing, stale, failed, timed-out, or crashed evidence.
6. If a deployment already started and produced a failed action, switch to the
   [incident mitigation and rollback](incident-mitigation-and-rollback.md) procedure. Preserve the
   original correlation id and idempotency key.

## Recovery drills

Run these drills in an approved non-production scope and retain sanitized output:

1. **Expired plan:** Use an expired plan fixture or wait for a short-lived test plan to expire.
   Confirm exact apply is rejected and no apply workflow is submitted. Create a new plan and confirm
   only its newly approved digest can proceed.
2. **Rejected kit:** Tamper with a disposable copy of one signed-kit artifact. Confirm inspection
   returns `incomplete` with `artifact.offline-kit=fail`. Replace the whole copy from the pinned
   source and confirm independent verification succeeds. Never alter a release artifact in place.
3. **Readiness loss:** Fail one registered test probe. Confirm `blocked` closes `/ready`, or
   `degraded` lowers the matching authority ceiling. Restore the dependency and wait for refresh;
   don't edit the report or its expiry to obtain recovery.

## Evidence and completion

Attach these sanitized artifacts to the audit record:

- Rejected and replacement plan ids, digests, statuses, expiry, workflow URLs, and context digests.
- Provision inspection schema version, overall status, `artifact.offline-kit` status, manifest
  digest, kit version, CLI version, platform, file count, and total bytes.
- Before-and-after startup decisions, probe ids, failure classes, stale or missing ids, authority
  ceilings, and observation and expiry times.
- Approval reference, operator identity, timestamps, correlation id, idempotency key, and any
  rollback receipt.

Recovery is complete only when the new artifact or fresh evidence passes its original verifier. A
manual label, copied status, edited timestamp, or successful liveness response is not completion.
