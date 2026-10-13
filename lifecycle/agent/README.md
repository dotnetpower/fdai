# Lifecycle agent

This package is the Lifecycle I0 skeleton of the in-cluster lifecycle agent described in
[Hub-Managed Lifecycle](../../docs/roadmap/deployment/hub-managed-lifecycle.md). It polls the
Lifecycle Hub, admits a signed Plan, verifies the signed Release and configuration package,
computes the change it would make, and reports the result. By default it never applies anything.
With `--apply`, it applies the Plan to one demo namespace, verifies the rollout, and rolls back
on failure, as described in [Apply mode](#apply-mode).

## Boundary

- No Azure client is imported. Only `kube.py` imports a Kubernetes client, and only `--apply`
  loads it, so a dry run performs no write. `tests/test_no_write.py` proves this statically and in
  a fresh interpreter.
- Only `hub_client.py` opens a network connection, and only outbound to the Hub. Plain HTTP is
  accepted only for a loopback Hub, because the Lifecycle I0 Hub has no authentication.
- The maximum effect envelope is derived locally. `--local-policy` sets the hard limit. The signed
  Release's `capabilities.<id>.maximum_mode` lowers each capability mode and drops any capability
  the Release doesn't name, and a `region` in the signed configuration narrows the regions. Neither
  signed input can widen the limit, and a Hub Plan can only narrow the result.
- Every report except a rejection carries a reason code, `exact_plan_digest` (`sha256:` and the hex
  SHA-256 of the decoded `signed_payload`), and a summary string with counts only. Entity ids, digests,
  installation identifiers, and secrets stay inside the installation. A rejection reports only its
  reason, with a `null` digest and an empty summary.
- Development test keys are generated outside the repository (#1947). Only public keys are read.

## Poll order

1. Read the current-state snapshot again, then fetch `GET /v1/installations/{installation_id}/plan`.
   A `204` means no Plan is pending.
2. Decode the signed bytes with `decode_canonical_plan_payload`. Undecodable bytes are dropped
   without a report, because no Plan id can be trusted.
3. Admit with `evaluate_plan_admission`. The expected audience is the installation id, and the
   expected source-state digest is the `digest` of the current-state snapshot. The Hub echoes the
   installation's reported digest into the Plan.
4. Refuse a sequence that the agent already rejected.
5. Verify the Release and configuration signatures over the exact file bytes. An unsigned input is
   rejected before any change is computed. The Release then passes the full manifest validation
   of `parse_runtime_release_manifest`, and the configuration package must resolve for the target
   Release through `resolve_configuration_layers` (`configuration_override_missing` otherwise).
   Each document's canonical JSON must hash to the digest that the Plan names, as the Hub computes
   it. Then the Plan envelope must fit the maximum derived from local policy and both signed inputs
   (`plan_envelope_exceeds_signed_maximum`).
6. Compute the dry-run change set. `entity_components` in the local policy names the Release
   components that each Entity runs. An Entity is unchanged only when it already runs the target
   Release id with exactly those components' images, created when it's absent, and updated
   otherwise. A Release without a named component is rejected (`release_component_missing`).
   Confirm that the change stays inside the Plan envelope.
7. Persist the outcome and the pending report (`attempt` and `reported_at`) in
   `<state-dir>/lifecycle-agent-state.json`, then send
   `POST /v1/installations/{installation_id}/plans/{plan_id}/reports`. A `503 concurrent_write`
   is retried up to three times after `Retry-After`. Any other failure resends the identical report on the next
   poll, which the Hub accepts as a duplicate, so `attempt` doesn't grow while the Hub is
   unreachable. Only a `409 report_conflict` makes the next poll start a new `attempt`. A reported
   Plan is not evaluated again.

A rejection blocks its sequence durably, except a retryable one: an input that is missing or
unreadable (`release_unavailable`, `configuration_unreadable`, and so on), or bytes that no
configured Hub key signed (`plan_signature_invalid`, `plan_payload_mismatch`). A retryable result
is evaluated again on every poll and reported again, with the next `attempt`, only when it changes.
So unauthenticated bytes can't block a later genuine Plan, and a file that syncs late doesn't hold
the Plan until it expires.

A poll holds an exclusive `flock` on `<state-dir>/.lifecycle-agent.lock` for its whole run. A second
poll that starts meanwhile stops at once with exit `1`, before it contacts the Hub. When the state
record limit is reached, retryable records are evicted before final results.

If the Hub serves other bytes under a Plan id that already holds a final result, the agent reports
nothing, logs `lifecycle_agent.plan_id_conflict`, and exits `1`.

## Inputs

| Option | Content |
|--------|---------|
| `--inputs-dir` | `releases/<digest>.json` (a runtime release manifest) and `configurations/<digest>.json` (`schema`, `environment`, `entity_overrides`), each with a raw Ed25519 signature over the file bytes in `<digest>.sig`. `<digest>` is the hex SHA-256 of the document's canonical JSON. |
| `--current-state` | The Hub's reported-state shape, rewritten by the agent in apply mode: `{"digest": "<64 hex>", "schema_revision": 15, "entities": {"<entity>": {"release_id": "1.4.0", "artifact_digests": ["sha256:..."], "health": "healthy"}}, "observed_at": "<RFC 3339>"}` |
| `--local-policy` | `{"schema": "fdai.lifecycle-local-policy.v1", "entity_ids": [...], "regions": [...], "capability_modes": {...}, "destructive_allowed": false, "max_duration_minutes": 60, "entity_components": {"core": ["core-control-plane"]}}`. Every Entity in `entity_ids` must name at least one component. Apply mode also needs `"component_images": {"core-control-plane": "<repository>"}`, a repository path without a tag or digest for every component. |

```bash
fdai-lifecycle-agent poll-once \
  --hub-url http://127.0.0.1:<port> --installation-id <installation-id> \
  --state-dir <state-dir> --hub-public-key <hub.pem> --hub-key-id <key-id> \
  --hub-key-epoch <epoch> --fencing-generation <generation> \
  --release-public-key <release.pem> --configuration-public-key <configuration.pem> \
  --inputs-dir <inputs-dir> --current-state <current-state.json> --local-policy <local-policy.json>
```

`--hub-key-id` is the id that the Hub writes into its Plans. For a `dev-keygen` key, it's `hub-` and
the first 16 hex characters of the SHA-256 of the raw public key.

The command prints one JSON result. It exits `0` when the poll finished and every required report
was accepted, `1` when the Hub or local state failed, a report didn't land, or the agent is halted,
and `2` for invalid configuration.

## Apply mode

Apply mode is the narrow demo path for one development namespace. It isn't the workload renderer
of #1946.

```bash
fdai-lifecycle-agent poll-once <options above> \
  --apply --kube-context <context> --namespace <namespace> --health-timeout-seconds 180
```

| Option | Content |
|--------|---------|
| `--apply` | Apply an admitted Plan. Without it, the poll is the dry run above. |
| `--kube-context` | The kubeconfig context to use. Required with `--apply`. |
| `--namespace` | The only namespace the agent reads or changes. Required with `--apply`. |
| `--health-timeout-seconds` | How long each rollout and each rollback has to complete. Default `180`. |

### What the agent applies

Each component of each Plan Entity becomes one Deployment and one Service named after the
component. The image is `<component_images repository>@<image_digest of the Release>`. Both objects
carry `app.kubernetes.io/managed-by: fdai-lifecycle-agent`, `fdai.io/entity`, and
`fdai.io/component`. The Deployment runs one non-root replica on port `8080` with a readiness probe,
and the Service exposes it on port `80`. The agent writes with Kubernetes server-side apply under
the field manager `fdai-lifecycle-agent`.

### Apply order

After step 6 of the poll order admits the Plan:

1. Render the objects and record the rollback target: the last verified-healthy version of each
   object, or nothing when the object didn't exist. An object that exists in the cluster without a
   recorded healthy version rejects the Plan (`rollback_target_unknown`).
2. Run the preflight: every object passes the scope guard, and the API server accepts a
   server-side dry run of each one.
3. Journal the Plan in `<state-dir>/lifecycle-agent-workload.json` and report `apply-started`.
   Nothing is applied until the Hub accepts that report.
4. Apply the objects. Each Deployment must reach its observed generation with `replicas`,
   `updatedReplicas`, `availableReplicas`, and `readyReplicas` all equal to the desired replicas
   before the health timeout.
5. On success, report `applied` (reason `applied`) with the next attempt and record the objects as
   the new healthy version. On a failed apply or rollout, restore the rollback target, deleting
   objects that didn't exist, verify it the same way, and report `rolled-back` (reason
   `apply_failed` or `health_check_failed`). The summary adds `"rollback": "verified"`.
6. Write the new state snapshot to `--current-state` and send it to
   `POST /v1/installations/{installation_id}/state`. The snapshot keeps every Entity, updates the
   Plan Entities on success, and has a newer `observed_at`. Its `digest` is the hex SHA-256 of the
   canonical JSON of the other fields, so the Hub can echo it into the next Plan.

Each step survives a restart. A journal that never touched the cluster applies once after a late
`apply-started` delivery, unless the Plan expired (`rejected`, reason `plan_expired`). A journal
interrupted during the apply is never applied again: the next poll rolls it back and reports
`rolled-back` with `apply_failed`. A finished journal only repeats its pending reports, and
until its report and snapshot land, the agent fetches no new Plan. A `409 stale_state` answer
ends the snapshot delivery, because a newer snapshot can't be replaced.

### Failed rollback

When the rollback fails or can't be verified in time, the agent reports `rolled-back` with the
original reason and `"rollback": "failed"` in the summary, and marks the Plan Entities `unhealthy`
in the snapshot. It writes `<state-dir>/lifecycle-agent-halt.json` and never retries the rollback.
Every later poll stops with outcome `halted` and exit `1` before it contacts the Hub. Repair the
namespace by hand, then remove the halt file.

### Safeguards

| Safeguard | How the agent meets it |
|-----------|------------------------|
| Stop condition | A failed apply or rollout stops the change and starts the rollback. |
| Tested rollback | The recorded healthy version is restored and verified like an apply. |
| Impact scope | One namespace, Deployments and Services only, and only agent-managed objects. The scope guard runs before every cluster call, and the adapter refuses any other namespace or kind. |
| Dry run | The change set stays inside the Plan envelope, and the API server accepts a server-side dry run. |
| Target lock | The poll's exclusive `flock` covers the whole apply. |
| Idempotency key | The Plan id and the report attempt. A Plan is applied at most once. |
| Two-phase audit | `apply-started` before the change, then `applied` or `rolled-back`. |

### Limits

- Demo scope only: one replica, a fixed template, and no Pod disruption budget, ConfigMap, Secret,
  or configuration values.
- The agent doesn't read the cluster to build the current state. It trusts `--current-state` and
  its own healthy record, so a change made outside the agent isn't detected, except that an
  unrecorded live object blocks the first apply.
- The rollback target is the agent's last verified rendering, not an arbitrary earlier Release.
- The Hub must accept the apply outcomes and the state endpoint described above.

## Not in Lifecycle I0

The local lifecycle authorization receipt, phase fencing, the full workload renderer (#1946),
Release roll-back protection, and envelope inputs from ownership evidence and the configuration
package belong to Lifecycle I1. Apply mode above is a demo path, not the Lifecycle I1 apply. The pure checks are imported from
`packages/deployment-cli` until they move to a shared lifecycle-contracts package (#1948).

## Testing

Run `PYTHONPATH=lifecycle/agent/src uv run python -m pytest -q --no-cov lifecycle/agent/tests`
from the repository root. Unit tests use an in-memory cluster.

`tests/test_kind_apply.py` runs v1, v2, and a broken v3 against a local kind cluster. It runs only
when `FDAI_LIFECYCLE_KIND_CONTEXT` names a `kind-` context and the `kind` command exists, so CI
and any other cluster skip it. It creates and deletes its own namespace, and the kind node pulls
`nginxinc/nginx-unprivileged` by digest:

```bash
kind create cluster --name fdai-lifecycle-demo
FDAI_LIFECYCLE_KIND_CONTEXT=kind-fdai-lifecycle-demo PYTHONPATH=lifecycle/agent/src \
  uv run --no-sync python -m pytest -q --no-cov lifecycle/agent/tests/test_kind_apply.py
```
 From `lifecycle/agent/`, `mypy --config-file pyproject.toml` checks the
sources and the tests in strict mode. The package isn't a uv workspace member. It runs in the root
development environment, which already provides its dependencies.
