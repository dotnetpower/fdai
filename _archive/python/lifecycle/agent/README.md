# Lifecycle agent

This package is the Lifecycle I0 skeleton of the in-cluster lifecycle agent described in
[Hub-Managed Lifecycle](../../docs/roadmap/deployment/hub-managed-lifecycle.md). It polls the
Lifecycle Hub, admits a signed Plan, verifies the signed Release and configuration package,
computes the change it would make, and reports the result. By default it never applies anything.
With `--apply`, it applies a bounded HTTP application or the legacy same-schema Operator profile to one
namespace, verifies the rollout, and rolls back on failure. See [Apply mode](#apply-mode).

The optional [private runtime-bundle extension](../../docs/roadmap/deployment/lifecycle-runtime-bundles.md)
uses `fdai.application-release.v2` component images for independently reviewed Deployment,
internal Service and bounded CronJob templates. It preserves the default dry run, native UID
fencing and same-schema boundary. See the [deployment handoff](../../docs/runbooks/hub-lifecycle-deployment-handoff.md)
for setup ownership, exact input pins, optional CronJob RBAC and unverified scheduled-effect holds.

## Boundary

- Azure identity is loaded only when workload federation is explicitly selected. It requests
  only the configured Hub API scope; no Azure management client, CLI credential, or client secret
  is used. The default dry run loads neither Azure nor Kubernetes. Only `kube.py` imports a
  Kubernetes client; explicit `--apply` or the read-only `reference-status` and `enroll`
  commands load it.
- `hub_client.py` opens outbound Hub connections. Explicit federation also contacts Entra through
  the identity SDK. Bearer transport requires an exact HTTPS origin and never follows redirects.
  Plain HTTP is accepted only for the unauthenticated loopback profile.
- The maximum effect envelope is derived locally. `--local-policy` sets the hard limit. The signed
  Release's `capabilities.<id>.maximum_mode` lowers each capability mode and drops any capability
  the Release doesn't name, and a `region` in the signed configuration narrows the regions. Neither
  signed input can widen the limit, and a Hub Plan can only narrow the result.
- Every report except a rejection carries a reason code, `exact_plan_digest` (`sha256:` and the hex
  SHA-256 of the decoded `signed_payload`), and a summary string with counts only. Entity ids, digests,
  installation identifiers, and secrets stay inside the installation. A rejection reports only its
  reason, with a `null` digest and an empty summary.
- Development test keys are generated outside the repository (#1947). Signing verification uses
  public keys. Optional full-revision decryption uses a separate private X25519 installation input.

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
   of `parse_lifecycle_release_manifest`, and the configuration package must resolve for the target
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
   unreachable. A `409 report_conflict` means that the attempt already contains different bytes.
   The Agent retains that attempt, halts before the next Hub fetch, and keeps any apply journal for
   operator reconciliation. It never invents a successor because the Agent-authenticated API
   doesn't expose the conflicting report. The agent retains a contiguous history of up to eight
   reports from attempt 1. A `409 report_attempt_gap` replays that history in order, including any
   earlier retryable rejection, until the Hub accepts the current report. A reported Plan is not
   evaluated again. Unknown or non-contiguous legacy report progress fails closed instead of
   guessing.

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
| `--artifact-source` | `directory` reads pre-staged files. `hub` downloads only the exact Release and active configuration named by the current Plan and requires workload-identity authentication. |
| `--inputs-dir` | For `directory`, contains `releases/<digest>.json` and `configurations/<digest>.json` plus raw Ed25519 `<digest>.sig` files. For `hub`, this is an optional private verified cache; omission uses `<state-dir>/artifact-cache`. |
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

## Application-neutral packages

`fdai.application-release.v1` declares an application `product` and named HTTP `workloads`.
Add the independently approved `product` to local policy and bind the same value in Hub Settings.
A missing or different product rejects the package; neither a Plan nor a signed manifest chooses
local authority. An omitted product retains only legacy runtime compatibility.
Map each already-owned Entity to its named components and approved image repositories.
Signed `port`, `health_path` and `replicas` reach the existing Deployment/ClusterIP Service renderer.
No application-specific flag, Entity kind, arbitrary template or permission is added.
Application packages reject `workload_profile` in flat and per-Entity configuration before rendering;
only a legacy runtime package can select the legacy Operator renderer and its schema-check Job.
Absent database metadata means schema revision zero, not permission to reset a database.
See the [package contract](../../docs/roadmap/deployment/lifecycle-releases-and-channels.md#application-package-contract)
for bounds. Ownership, dry run, independent rollout observation, rollback and durable replay guards
remain required; local synthetic tests are not installation evidence.

## Full signed configuration revisions and CSI reports

The actual `poll-once` entry point and `DirectoryArtifactStore` also consume unchanged
`fdai.lifecycle-configuration-file.v1` containers carrying complete signed v2 revisions.
Add independent private `--configuration-binding` and `--installation-encryption-key` inputs;
missing prerequisites hold the new capability without changing legacy flat artifact behavior.
The exact Release/schema, current active digest, already-managed Entity mapping, signature,
recipient, authenticated sealed coverage and complete historical key bindings are verified before
prepare. The package never supplies a trusted key. Decryption is installation-local.

Each Entity reaches the existing renderer with its own values. The v2 demo supports 1-3 replicas;
the Operator profile keeps the existing same-schema gate. Configuration cannot choose a namespace,
image repository, component ownership or capability mode. Rendered reference names can persist
only in private installation state, never reports or public output. Existing dry-run, approval,
fencing, expiry, report, rollback and restart safeguards remain required.

The explicit read-only `reference-status` command reads exact CSI/Pod/provider metadata through
the existing Kubernetes adapter. It reports source/version/Entity/freshness, never secret values.
`reported-mounted` is a driver report, not independent verification of secret usability. Missing
source bindings remain unavailable; fixtures cannot qualify a real Key Vault/CSI installation.

See [Installation Agent configuration inputs](../../docs/runbooks/installation-agent-configuration.md)
([Korean](../../docs/runbooks/installation-agent-configuration-ko.md)) for exact private formats,
compatibility, bounds and unavailable/stale/conflict states. No live onboarding, authenticated
artifact synchronization, Agent rollout or production trust is established by source tests.

## Apply mode

Apply mode defaults to the narrow demo path for one development namespace. The signed
configuration can instead select the [Operator profile](#same-schema-operator-profile) or the
independently pinned private runtime bundle. A full-authority development native approval may list
exact existing kind/name/UID objects for a mixed adoption-and-create Plan. The Hub-signed Plan must
bind the accepted native claim in `ownership_digests`; the Agent keeps names and UIDs private,
adopts only Terraform-owned fields, and creates only omitted objects that remain absent. See the
[deployment handoff](../../docs/runbooks/hub-lifecycle-deployment-handoff.md#adopt-exact-existing-objects-in-a-mixed-scope).

```bash
fdai-lifecycle-agent poll-once <options above> \
  --apply --kube-context <context> --namespace <namespace> --health-timeout-seconds 180
```

| Option | Content |
|--------|---------|
| `--apply` | Apply an admitted Plan. Without it, the poll is the dry run above. |
| `--kube-context` | Select one kubeconfig context, or select `--in-cluster`, with `--apply`. |
| `--in-cluster` | Use the Pod's projected Kubernetes identity and CA, without kubeconfig fallback. |
| `--namespace` | The only namespace the agent reads or changes. Required with `--apply`. |
| `--native-approval` | Independent local approval for the exact native scope and optional sorted existing kind/name/UID objects. |
| `--installation-public-key` | Enrolled installation public key used to verify the retained native proof. |
| `--health-timeout-seconds` | How long each rollout and each rollback has to complete. Default `180`. |

### Remote development preparation

Remote transport is opt-in and has local test evidence only. It doesn't modify an existing Hub,
register an application, grant a role, create an AKS cluster, or authorize workload application.
Use a separately approved Hub build that supports `auth.agent_principals`. Each entry binds
`installation_id`, `object_id` and `client_id` to one distinct application identity. The verified
token also needs `idtyp=app` and the `Agent.Access` application role. The role permits only that
installation's Plan GET/HEAD, state/report POST and pending-enrollment request routes, never
enrollment approval, catalog, operator approval or recomputation. Empty bindings retain denial by
default.

Select federation with `--hub-auth workload-identity --hub-scope api://<hub-api-id>/.default`.
The AKS workload-identity webhook supplies `AZURE_TENANT_ID`, `AZURE_CLIENT_ID` and
`AZURE_FEDERATED_TOKEN_FILE`. Its projected token has the token-exchange audience, not the
Kubernetes API audience. Kubernetes authentication still uses its own projected identity.
Don't supply token contents through command arguments, input files or logs.

Connected Agents can add `--artifact-source hub` instead of pre-staging signed inputs. Lifecycle
Hub serves only the Release and configuration digests in that installation's current eligible
Plan, after rechecking accepted catalog and configuration-import provenance. The Agent verifies
the original signatures and canonical digests before publishing a mode-`0600` private cache.
Subsequent polls reuse exact bytes. A missing or changed artifact remains a retryable hold and
doesn't reach Kubernetes.

The `poll` command accepts the same settings as `poll-once` plus `--max-polls` (default 30),
`--poll-interval-seconds` (15) and `--max-duration-seconds` (900). It bounds poll starts and
sleeps, stops on transport/authentication errors, rejected inputs and rollback, and logs only
outcome codes rather than receipt contents. An in-flight apply finishes its existing bounded
verification/recovery before the scheduling deadline takes effect; it isn't forcibly killed.
Each HTTP response is size-bounded and has a body deadline in addition to socket timeouts.

Before polling, stage each independently pinned signed input:

```bash
fdai-lifecycle-agent stage-input --kind release --digest <approved-canonical-digest> \
  --document <release.json> --signature <release.sig> --public-key <release-public.pem> \
  --inputs-dir <inputs-dir>
```

Use `--kind configuration` and the configuration public key for the other input. This offline
command verifies the exact bytes and canonical digest before atomic owner-only publication.
It never signs data or obtains trust from a key bundled with the download. Admission rechecks
both inputs and all existing semantic, expiry, replay and envelope constraints at every new Plan.

The [namespace RBAC template](deploy/namespace-rbac.yaml) binds a service account in
`fdai-agent-system` to a Role in the separate `fdai-nginx-dev` namespace. Its only permissions
are get/create/patch/delete on Deployments, Services and Jobs. It grants no Secrets, Pods,
exec, RBAC, node, namespace or cluster-admin access. The workload namespace enforces restricted
Pod Security. Discovery relies on the cluster's authenticated discovery access; don't add a
wildcard ClusterRole if discovery fails.

The [state PVC template](deploy/state-volume.yaml) reserves an Azure Disk claim in the Agent
namespace, outside its workload write scope. Mount it writable and keep `--state-dir` and
`--current-state` on that same volume; seed the initial current-state snapshot through the
approved operator setup before starting. Mount signed input directories, public keys and
local policy read-only. Use one Agent replica and a Recreate strategy with the ReadWriteOnce
volume. Don't substitute `emptyDir` or container-local storage for the replay floor, pending
reports, journal or current state. These are preparation templates, not an installed Agent
image or evidence that a cloud Pod can authenticate, mount storage or recover after eviction.

### Enrolling this installation

`fdai-lifecycle-agent enroll` lets the Agent submit its own enrollment request, so the operator no
longer carries a signed file. The Agent only proposes: the Hub records a pending request, and a
human still accepts it after comparing the installation key id out of band.

```bash
fdai-lifecycle-agent enroll \
  --installation-id <installation-id> \
  --installation-key <owner-only-private-key.pem> \
  --declaration <owner-only-declaration.json> \
  --namespace <workload-namespace> \
  --hub-url https://<hub-origin> \
  --hub-scope api://<hub-api-id>/.default
```

The command:

1. Loads the existing owner-only installation private key (`0600`, current UID, no symlink). It
   never generates, prints, exports or logs the key.
2. Derives Entities and reported state from the Agent's own namespace using the in-cluster
   identity only; there is no kubeconfig option or fallback. It makes two bounded read-only list
   calls (Deployments and CronJobs labelled `fdai.io/entity`), never reads Secrets, and refuses
   a continuation page instead of enrolling a partial view.
3. Reads the customer-owned settings and configuration from `--declaration`, a strict owner-only
   JSON file of at most 64 KiB. The Agent never invents a setting, and the file cannot carry
   `product`, `plan_duration` or `fencing_generation`.
4. Signs the payload with the shared `fdai_deployment_cli.lifecycle_enrollment` implementation,
   the same bytes `fdai-lifecycle-hub sign-enrollment` produces, and POSTs it with the workload
   identity token to `POST /v1/installations/{id}/enrollment-request`.
5. Prints only the installation id, installation key id, `pending` status and the submit-before
   time (the five-minute proof window).

The declaration uses this schema; any other field is rejected:

```json
{
  "schema": "fdai.lifecycle-installation-declaration.v1",
  "installation_id": "<installation-id>",
  "settings": {
    "channel": "stable",
    "version_range": ">=1.4.0 <2.0.0",
    "region": "korea-central",
    "allowed_regions": ["korea-central"],
    "windows": [
      {"start": "11:30:00", "duration": "PT1H", "timezone": "Asia/Seoul", "allows_downtime": false}
    ]
  },
  "configuration": {
    "schema": {},
    "environment": {},
    "entity_overrides": []
  }
}
```

Cluster-derived facts. A workload belongs to an Entity when it carries `fdai.io/entity`; the value
must be a Hub identifier. The Release id is the workload's canonical SemVer
`app.kubernetes.io/version` label, the schema revision is its `fdai.io/schema-revision`
annotation, artifact digests are its `@sha256:` image references, and health comes from
Deployment rollout status. A workload without a version label reports the explicit empty state
(`release_id: null`, health `unknown`). Mixed or non-canonical Release ids, an unobserved or
inconsistent schema revision for an installed Entity, a workload outside the namespace, an invalid
Entity id, more than 64 Entities, or no labelled workload stop the command before any Hub call.
Unlabelled workloads are invisible to enrollment.

Failure handling. Exit code `2` means nothing was sent (local input, key, cluster or identity
problem). Exit code `3` means the Hub answered with a refusal; `installation_exists` means a
pending, enrolled or rejected record already exists, so re-running is idempotent and changes
nothing. Exit code `4` means the delivery result is unknown. The command never retries
automatically after an uncertain result, because the Hub may have recorded the request; check the
Hub's pending enrollment list before running it again. Only an explicit `503 concurrent_write`,
which the Hub answers before committing, is resent by the shared transport.

The command needs a namespace-scoped `list` on Deployments and CronJobs in addition to the
existing `get`. The [enrollment read Role](deploy/enrollment-rbac.yaml) adds only that, and the
independent Lifecycle Agent Terraform root includes the same rule. The installation private key
and the declaration must reach the Pod's owner-only private state path outside Terraform; the key
never becomes a Terraform input. Local tests do not prove a cloud Pod can authenticate, list or
reach the Hub.

### What the agent applies

Each component of each Plan Entity becomes one Deployment and one Service named after the
component. The image is `<component_images repository>@<image_digest of the Release>`. Both objects
carry `app.kubernetes.io/managed-by: fdai-lifecycle-agent`, `fdai.io/entity`, and
`fdai.io/component`. The Deployment runs one non-root replica on port `8080` with a readiness probe,
and the Service exposes it on port `80`. The agent writes with Kubernetes server-side apply under
the field manager `fdai-lifecycle-agent`.

### Same-schema Operator profile

This development slice runs the actual signed `operator-service` image, not nginx. It preserves
the external Core, Kafka, and service-owned PostgreSQL dependencies instead of replacing them.
Select exactly one Plan Entity whose component set is `["operator-service"]`.

The resolved **signed configuration** contains these values:

```json
{
  "workload_profile": "operator-service-v1",
  "operator_config_map_name": "operator-config-v1",
  "operator_database": {"secret_name": "operator-database-v1"},
  "schema_database": {"secret_name": "schema-reader-v1"},
  "replicas": 1
}
```

Declare each key in the existing configuration package's `schema` with `x-fdai-axis` set to
`installation-path` and `x-fdai-owner` set to `customer`. Supply the values through its defaults,
environment, or matching version override. This is not a new Release manifest or catalog format.
Local policy `component_images` needs repositories for both `operator-service` and
`core-control-plane`; both image digests come only from the verified Release.

Prepare these dependencies outside the agent:

| Dependency | Requirement |
|------------|-------------|
| Namespace and service accounts | Dedicated namespace; existing `operator-service` and `fdai-schema-check` accounts. The profile mounts no Kubernetes token and creates no role binding. |
| ConfigMap | Versioned, retained, immutable configuration for the real Operator's authentication, broker/topics, product profile, and dependent services. No secret values. The profile fixes port `8000` and database role `fdai_operator`. |
| Operator Secret | Versioned, retained, immutable Kubernetes Secret, populated inside the installation by its secret provider. Key `FDAI_DATABASE_URL` connects as `fdai_operator`. |
| Schema-reader Secret | Same key, with read access to the legacy and five service migration version tables. No DDL or administrator privilege is needed. |
| Existing database | Already bootstrapped through the normal migration path, with authoritative catalogs present. The scalar schema revision and every legacy/service Alembic head match the candidate Release. |
| Core and broker | Real existing Core/event-bus bindings. This slice doesn't deploy them or manufacture their data. |

The agent never reads or journals Secret values. It retains only the reference names. Keep the
old ConfigMap and Secrets until the rollback window ends. Authentication/identity policy and
provider reach remain installation-owned; this profile does not provision federated identities,
Azure bindings, secret synchronization, or broker infrastructure.

Before switching the Deployment, the agent runs a bounded, non-retrying schema-check Job using
the signed Core image's existing migration tools. It compares the legacy head first, then the
service heads in `service-migrations/ownership.json` dependency order, in a read-only transaction.
It never upgrades, downgrades, stamps, or materializes a catalog. A new schema target is rejected
even without `--apply`; a missing or mismatched head fails before the Deployment switches.

After the Job succeeds, the Deployment starts `fdai-operator-service` on `8000`, probes
`/healthz`, and exposes only `operator-service-internal` as a ClusterIP Service. Pod labels
preserve the existing external Service selector `app.kubernetes.io/name=operator-service`.
The external Service, namespace, database, accounts, roles, and Terraform state stay untouched.
Server-side apply doesn't force field conflicts, and an unrecorded existing Deployment blocks
the apply rather than being adopted.

Readback requires the controller's latest healthy rollout and matching rendered spec fields.
The completed Job is deleted and its absence is observed before success. The journal retains the
last healthy Deployment and internal Service, not the transient Job. Failure restores those
objects without rerunning the Job or attempting a database downgrade. Process-loss recovery,
two-phase reports, exclusive locking, and halt-on-failed-rollback remain the existing apply path.
The Plan expiry is rechecked while waiting and before each forward workload write.

**Design critique and boundary:** Running unclassified migrations from today's v3 Release could
drop tables and invalidate rollback. This slice therefore checks an already migrated baseline
and rejects schema transitions. It is not the full vendor-signed workload-template contract,
three-signer installation binding, migration lease/expand flow, Terraform parity, adoption, or
production lifecycle authorization receipt. Full workload rendering remains incomplete.

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
| Impact scope | One namespace, agent-managed Deployments, internal Services, and schema-check Jobs only. The scope guard runs before writes, and the adapter refuses any other namespace or kind. |
| Dry run | The change set stays inside the Plan envelope, and the API server accepts a server-side dry run. |
| Target lock | The poll's exclusive `flock` covers the whole apply. |
| Idempotency key | The Plan id and the report attempt. A Plan is applied at most once. |
| Two-phase audit | `apply-started` before the change, then `applied` or `rolled-back`. |

### Limits

- The legacy demo remains one fixed replica. Full v2 Entity values and the Operator profile
  support 1-3 replicas with
  fixed resource bounds and reference-only configuration; neither path renders a Pod disruption
  budget, autoscaler, ConfigMap, or Secret.
- The agent doesn't read the cluster to build the current state. It trusts `--current-state` and
  its own healthy record, so a change made outside the agent isn't detected, except that an
  unrecorded live object blocks the first apply.
- The rollback target is the agent's last verified rendering, not an arbitrary earlier Release.
- The Hub must accept the apply outcomes and the state endpoint described above.
- If the Hub supersedes a Plan before the agent's `apply-started` report for it ever lands (for
  example because the Hub was briefly unreachable for writes), the agent abandons that Plan's
  local record once it fetches the superseding one. Nothing was ever applied for the abandoned
  Plan, and the superseding Plan gets its own independent, correctly numbered reports, but the
  abandoned Plan's `apply-started` record never resolves to `applied` or `rolled-back` locally.
  `tests/test_cross_process_resumption.py` drives this with two real `poll-once` processes
  against a real kind cluster and confirms the cluster and the superseding Plan stay correct.

## Not in Lifecycle I0

The local lifecycle authorization receipt, phase fencing, the full workload renderer (#1946),
Release roll-back protection, and envelope inputs from ownership evidence and the configuration
package belong to Lifecycle I1. The demo and Operator slice are not the full Lifecycle I1 apply.
The pure checks are imported from
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

`tests/test_cross_process_resumption.py` uses the same opt-in and the same cluster. It runs
`poll-once --apply` as two separate OS processes sharing one `--state-dir` against a real loopback
HTTP stub Hub, to check the on-disk journal and state files the way two separate agent invocations
actually see them, not an in-process harness.

From `lifecycle/agent/`, `mypy --config-file pyproject.toml` checks the
sources and the tests in strict mode. The package isn't a uv workspace member. It runs in the root
development environment, which already provides its dependencies.

For the Operator slice, run focused tests from the repository root:

```bash
python -m pytest -q --no-cov \
  lifecycle/agent/tests/test_operator_workload.py \
  lifecycle/agent/tests/test_schema_check.py \
  lifecycle/agent/tests/test_kube.py \
  lifecycle/agent/tests/test_workload.py \
  lifecycle/agent/tests/test_apply.py
```

These tests use a mechanical cluster seam and synthetic SQLite migration tables. They prove
rendering, signed-input selection, ordering, failure handling, and recovery, not a running
Operator, PostgreSQL, or kind installation. The existing nginx kind test remains demo evidence
only.

### Real Operator kind validation

`tests/test_kind_operator.py` is a separate opt-in test for the real `operator-service-v1`
workload. It requires a dedicated `kind-fdai-operator-*` context and an otherwise unused
`fdai-operator-*` namespace labeled `fdai.io/validation-owner=operator-kind`. It does not
provision the foundation or skip missing prerequisites once the context is selected.

Prepare the following task-owned dependencies before running it:

- Official native ARM64 Operator and Core images, loaded into the kind nodes and addressable by
  their immutable OCI manifest references. Set the source commit to the actual image revision.
- Disposable PostgreSQL with the canonical legacy and service migrations and materialized
  catalogs. Use isolated validation port `5433` and
  `scripts/automation/with-local-test-database.py` for host-side database preparation, not the
  runtime database or a remote database.
- A real broker and running Core, reachable from the Operator Pods. Independently verify Core
  readiness and initialized event consumers; the test's Operator health check alone does not
  establish Core readiness.
- Service accounts `operator-service` and `fdai-schema-check`; immutable Secrets
  `operator-database` and `schema-reader`, each with a `FDAI_DATABASE_URL` key. Use the Operator
  service role for the former and a read-only schema-check role for the latter.
- Immutable ConfigMaps `operator-config-v1`, `operator-config-v2`, and
  `operator-config-failure`, containing the real Operator runtime settings. The first two must
  differ in a valid setting, such as statement timeout. The failure configuration must leave
  `FDAI_API_AUDIENCE` empty to exercise startup failure and rollback.

The valid configurations use issuer `https://operator-kind.example.test`, audience
`operator-kind`, and JWKS URL `http://validation-jwks:8080/jwks.json`. The test creates a temporary
namespace-local public JWKS server and an in-memory Reader token. It uses the real Operator JWT
verification path; the JWKS server is only an authentication fixture.

```bash
export KUBECONFIG=/path/to/dedicated-kubeconfig
export FDAI_OPERATOR_KIND_CONTEXT=kind-fdai-operator-example
export FDAI_OPERATOR_KIND_NAMESPACE=fdai-operator-example
export FDAI_OPERATOR_KIND_IMAGE='repository/operator@sha256:<native-arm64-manifest>'
export FDAI_OPERATOR_KIND_CORE_IMAGE='repository/core@sha256:<native-arm64-manifest>'
export FDAI_OPERATOR_KIND_SOURCE_COMMIT='<image-source-commit>'
PYTHONPATH=lifecycle/agent/src:packages/deployment-cli/src:packages/service-contracts/src \
  uv run --no-sync python -m pytest -q --no-cov -o faulthandler_timeout=300 \
  lifecycle/agent/tests/test_kind_operator.py
```

The bounded scenarios verify signed install, a real **configuration revision** update using the
same image, startup failure and restoration of the previous healthy configuration. After a real
Deployment write, the harness interrupts the apply boundary and starts two separate Agent CLI
processes to verify durable journal recovery and replay without another rollout. This models a
process-loss boundary; it does not send an OS kill signal to the first Agent.

Before failure injection, the test reads the failure ConfigMap and requires an explicitly empty
audience. It counts distinct completed schema Jobs by name, not repeated observations.
`tests/test_kind_operator_harness.py` covers these assertions and partial JWKS setup cleanup
without a cluster; those offline checks are not evidence of a running Operator.

Checks include the running image digest, Deployment configuration, Pod readiness and replacement,
`/healthz`, an authenticated database-backed `/agents/activity` response, schema Job completion,
and Agent state, report, and journal readback. Activity may be empty. The Hub remains a signed
fixture with loopback HTTP transport for recovery, not the deployed Hub planner or enrollment
flow. No live model request is required. This is not a schema migration, a different application
image upgrade, a complete FDAI installation, or production validation.

The test deletes its Operator workload, schema Jobs, and JWKS fixture. It leaves the pre-existing
foundation and dedicated cluster for their owner to remove. Never point it at a shared namespace.
