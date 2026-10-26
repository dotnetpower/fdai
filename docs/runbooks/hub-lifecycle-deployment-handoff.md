---
title: Hub deployment handoff
---
# Hub deployment handoff

Use this checklist to repeat an application deployment without relying on an engineer's terminal
history. It identifies the responsible person, the input to preserve, the observable result, and
the mechanics that can be automated.

> **Scope:** The bounded nginx rehearsal and the local generic-engine tests are different evidence.
> The runtime-bundle extension is not installed in existing Hubs or Agents by this change.
> A full FDAI cloud qualification remains separate. No command here grants deployment permission.

## What this covers

The order is the same for nginx and FDAI: prepare infrastructure, publish images, independently
approve the catalog, enroll, accept ownership, sign configuration, stage inputs, approve a Plan,
run the Agent, and independently observe the result. Application-specific data changes; the
execution engine and trust boundaries do not.

Use the [operator guide](hub-lifecycle-operator-guide.md) for the complete existing command/API
reference. Use [runtime bundles](../roadmap/deployment/lifecycle-runtime-bundles.md) for the extended
input contract. Do not substitute a renamed HTTP manifest for the full FDAI topology.

## Who does each previously manual step?

| Step / responsible person | Required input and action | Preserve privately / completion evidence | Automation opportunity |
|---------------------------|---------------------------|------------------------------------------|------------------------|
| 1. Customer infrastructure owner | Approve the exact target, cost, retention and cleanup; prepare namespace, storage, database and identities | Reviewed infrastructure plan, initialized schema, namespace and identity references | Existing infrastructure tooling can generate references; it cannot approve its own changes |
| 2. Hub network owner | Verify operator reachability separately from Agent-to-Hub and Lifecycle-to-Release catalog reachability | Approved source ranges, outbound origin, ingress readback and both product/build identities | Preflight DNS, route, ingress and API separately; never widen roles to fix network denial |
| 3. Customer identity owner | Bind user sign-in separately from Agent federation and `Agent.Access`; keep existing identity keys | Exact application/scope binding, federation subject and namespace ServiceAccount | Generate a reviewed setup record; no administrator role or broad Graph grant |
| 4. Vendor release operator | Build immutable images, sign the exact manifest bytes, register/publish and maintain recall state | Source/image digests, signature verification, channel/catalog revision and pin | Build/sign/publish pipeline; no customer approval |
| 5. Customer catalog approver | Obtain publisher key and exact catalog pin independently; approve, then import | Accepted key ID, revision, pin, freshness and import result | Transfer and compare public metadata without retyping; never trust a downloaded pin merely because it downloaded |
| 6. Customer setup operator | Preserve installation ID/key, submit fresh enrollment, then obtain separate human acceptance | Public key ID, enrollment decision and durable installation identity | Supported enrollment commands; resumable UI handoff is still needed |
| 7. Customer ownership approver | Review exact native object scope and, for a development transition, every existing kind/name/UID; run `bootstrap-slot` dry-run, then approved anchor creation; submit and separately accept proof | Approval, exact existing-object list, scope digest, anchor UID and signed proof in private storage | `bootstrap-slot` and `submit-native-proof`; proof creation never approves ownership or adopts a workload |
| 8. Customer runtime/configuration owner | Review private bundle, existing references and image repositories; pin its digest in signed configuration | Owner-only local policy, signed configuration bytes, key ID and exact digests | Schema validation and digest generation; a guided private bundle editor is not shipped |
| 9. Installation input operator | Transfer verified release/configuration document and detached signature pairs; mirror images | Atomic staged files and independent signature/digest checks | `stage-inputs`; there is no automatic file transfer merely because a Plan exists |
| 10. Customer execution approver | Set explicit execution window, current Settings/constraints and exact Plan approval | Actor, source-state digest, Plan expiry and confirmation | Existing forms generate IDs/digests; preserve approval |
| 11. Installation runtime owner | Start one approved bounded Agent run with persistent state and in-cluster authentication | Agent contact, reports, journal, healthy state and any halt marker | A reviewed finite Job template; permanent scheduling is not implied by enrollment |
| 12. Application owner | Independently inspect expected workload and application effects; handle recall/holds separately | Installed version, controller readiness, independent application result and recovery outcome | Read-only checks and a timeline; never invent success from dispatch or Pod existence |
| 13. Customer environment owner | Remove only approved temporary Jobs/resources, retain the agreed cluster/state/identity, acknowledge ongoing cost | UID-fenced absence checks, retained-resource inventory and responsible owner | Cleanup plan and retention summary; do not erase recovery state or identity |

Separate catalog metadata, signed input delivery, image availability and Agent scheduling.
Completing one does not complete the others. A healthy cluster is not proof that an Agent runs.

## Private runtime input example

This synthetic bundle illustrates one Deployment and internal Service. Store it as the
`runtime_bundle` object inside the existing `fdai.lifecycle-local-policy.v1` document.
Keep that file in a current-user-owned private directory as a single-link mode-0600 regular file.
It is not a public release manifest or a Hub upload.

```json
{
  "format": "fdai.application-runtime-bundle.v1",
  "product": "example-web",
  "namespace": "example-test",
  "objects": [
    {
      "entity_id": "application",
      "kind": "Deployment",
      "name": "frontend",
      "spec": {
        "replicas": 1,
        "template": {
          "spec": {
            "serviceAccountName": "frontend",
            "automountServiceAccountToken": false,
            "securityContext": {
              "runAsNonRoot": true,
              "seccompProfile": {"type": "RuntimeDefault"}
            },
            "containers": [{
              "name": "frontend",
              "image_component": "frontend",
              "ports": [{"name": "http", "containerPort": 8080}],
              "readinessProbe": {"httpGet": {"path": "/healthz", "port": "http"}},
              "resources": {
                "requests": {"cpu": "100m", "memory": "128Mi"},
                "limits": {"cpu": "1000m", "memory": "512Mi"}
              },
              "securityContext": {
                "runAsNonRoot": true,
                "allowPrivilegeEscalation": false,
                "readOnlyRootFilesystem": true,
                "capabilities": {"drop": ["ALL"]}
              }
            }]
          }
        }
      }
    },
    {
      "entity_id": "application",
      "kind": "Service",
      "name": "frontend",
      "spec": {"ports": [{"port": 80, "targetPort": "http"}]}
    }
  ]
}
```

Also bind `product`, `entity_ids`, `entity_components`, `component_images`, and the approved
`native_scope_digest` in local policy. The Entity's image-component set includes sidecars and
initialization containers. Native `components` instead names Deployment objects.
Optional `service_components` selects only Deployments that need a Service; omitted means all
Deployments, preserving old scopes. `scheduled_components` explicitly names CronJob objects.
The bundle's complete kind/name inventory must equal that separately approved native scope.

To compute the bundle pin without displaying private contents, use the installed Agent's parser:

```bash
python -c 'import sys; from pathlib import Path; from fdai_lifecycle_agent.cli import load_local_policy; print(load_local_policy(Path(sys.argv[1]))["runtime_bundle"].digest)' "$LOCAL_POLICY"
```

Set the resulting `sha256:<hex>` as `runtime_bundle_digest` in each selected Entity's signed
configuration. This v2 execution path accepts only that pin and optional `region` as resolved
configuration values. Runtime settings and connection values belong in pre-existing
ConfigMaps/Secret references, not unconsumed configuration keys or literal environment values.
Review and re-sign a new pin when private templates or reference names change.

The vendor's `fdai.application-release.v2` uses `components.<name>.image_digest`, not `workloads`.
It carries immutable images, product/version/source/platform and optional existing schema metadata,
not private templates. Preserve detached signatures over exact bytes and the existing canonical
digest convention when publishing and staging.

## Reconstruct workload state without changing workloads

`generate-runtime-bundle` now writes three owner-only handoff files beside the bundle:

| File | Purpose |
|------|---------|
| `workload-handoff-inventory.json` | Digest-bound Terraform address, exact `namespace/name` import ID, and render digest for every approved object |
| `workload-handoff.tfvars.json` | Complete Deployment, Service, CronJob, and HorizontalPodAutoscaler maps for the handoff roots |
| `workload-handoff-commands.txt` | Initial import, zero-change check, forget-only release, rollback import, and final zero-change commands |

Use this path only when the retained workloads state is unavailable. Keep one new private absolute
local backend path and use it for every command in the generated sequence. Start with `umask 077`
so plan JSON and receipts remain owner-only. Supply the exact private
kubeconfig and context separately. Review `terraform show -json` through
`verify-workload-handoff-plan` before every apply.

The first import plan may contain only exact import records with `no-op` actions. Apply it, then
require the next plan to return Terraform detailed exit code 0 and pass the `zero-change` verifier.
The release plan may contain only `forget` actions for the same digest-bound inventory. Its
`removed` blocks all set `destroy = false`, so the apply releases state ownership without deleting
live objects. Don't continue if a plan contains create, update, delete, replace, drift, a moved
address, a deferred change, or an unapproved import ID.

For rollback, first retain the Agent's reconciliation-release receipt. Reuse the same import root,
input file, and absolute backend path. Verify the exact rollback import plan, apply it, then require a second
zero-change plan. Only after that receipt exists may the installation release its Hub ownership
marker. Never edit a state file or use `terraform state rm` as a substitute.

## Adopt exact existing objects in a mixed scope

Use this transition only with an explicitly approved `full-authority-development` native scope.
Keep the same `scope` in `native-approval.json` and add `existing_resources`, sorted by kind and
name. Each entry contains exactly `kind`, `name`, and the Kubernetes `uid` read from the current
object. Do not list an object that is absent, terminating, owned by another field manager, or
outside the generated runtime bundle. Every scope object omitted from `existing_resources` must be
absent.

Run `bootstrap-slot` without `--apply` first. It verifies the existing UIDs and absence set while
keeping the anchor create-only. For an existing native state, it verifies the retained anchor and
proof instead of recreating them. Obtain a fresh Hub Plan only after the operator has accepted that
proof. The signed Plan must carry the same claim digest in `ownership_digests`; a Plan without that
binding cannot perform adoption.

Run the bounded Agent apply with the same private approval and persistent state. The preflight
captures resource versions and original manifests and server-dry-runs every adoption. After the Hub
accepts `apply-started`, the Agent checkpoints adopted objects one by one, writes their UIDs into
native state, and creates only objects that the approval declared absent. Preserve the adoption
receipt. It binds the approval, accepted ownership claim, Plan, rendered objects, UIDs and resource
versions without sending the private inventory to the Hub.

If the run stops, restart with the same state and approval. The Agent recognizes only the exact
anchor marker and UID, rolls adopted specs back to their captured versions, and leaves not-yet
adopted objects untouched. A new Plan may retry the remaining set. A UID conflict, another field
manager, a missing object that was declared existing, or an object that appears in the absent set
requires a new observation and approval. Never edit native state, patch labels with `kubectl`, or
reuse the old approval for a changed UID.

For an installed legacy Entity, prepare and obtain the separate Hub transition approval before
running `transition-native-scope`. Supply the authenticated `--hub-url` and exact `--hub-scope`.
After the crash-safe local commit, the command automatically submits its digest-bound receipt,
new empty state and complete approved kind/name/UID inventory through the Agent workload identity.
Success requires the returned Hub completion receipt. Inspect that receipt before requesting the
next Plan.

If Hub delivery fails after the local commit, don't edit either state or submit the new state
through the ordinary state endpoint. Retry the same `transition-native-scope` command and inputs.
The local retry returns the original local receipt, and the Hub returns its original receipt after
an exact completed retry. A trusted Hub host can use `fdai-lifecycle-hub
complete-native-transition` with the same private completion document and attributed Agent
principal for bounded recovery. Changed bytes, a different identity, an open Plan or partial
Entity management is a conflict, not a reason to split the unmanage, state and manage writes.

If that completed transition came from the legacy millisecond timestamp producer, compare the
immutable local transition receipt with the retained Hub completion receipt before requesting a
Plan. Use reconciliation only when all canonical state fields match, the local state and receipt
use the same millisecond timestamp, the Hub completion audit retains a later sub-millisecond value
for that same instant, and the Hub state still carries the legacy millisecond digest. Do not use
this procedure for a changed Entity, scope, UID, artifact inventory, health, schema revision, or
timestamp difference greater than one millisecond.

1. Stop bounded polling and confirm that the Hub has no open Plan and the Agent has no unreported
   Plan or prepared/applying journal. Preserve the local transition receipt, Hub completion
   receipt, native approval, installation public key, Hub public key, and current-state path.
2. Run `fdai-lifecycle-agent prepare-native-transition-reconciliation` with `--state-dir`,
   `--current-state`, `--native-approval`, `--hub-completion-receipt`,
   `--installation-public-key`, and an owner-only `--destination`. This command takes the Agent
   state lock and creates no mutation.
3. Submit the private request as an authenticated operator to
   `POST /v1/installations/{installation_id}/native-transition-state-reconciliation-approval`.
   Preserve the returned signed approval. A `409` is a stop condition; do not broaden a timestamp
   tolerance or edit either receipt.
4. Run `fdai-lifecycle-agent reconcile-native-transition-state` with the same state, native
   approval, Hub completion receipt, installation public key, exact Hub key id/epoch and public
   key, returned `--hub-reconciliation-approval`, authenticated `--hub-url` and `--hub-scope`, and
   the original Kubernetes context or in-cluster identity.
5. Require the command to return both `reported_state_digest` and
   `reconciliation_receipt_digest`. Inspect the owner-only rollback and reconciliation receipt
   files. The transition receipt, native state, and workload journal must remain byte-for-byte
   unchanged. Request the next Plan only after Hub readback and local current-state carry the same
   full-precision timestamp and digest.

If the command stops after writing pending state, rerun it with the exact same inputs. It restores
the retained current-state bytes before retrying and treats a committed Hub write as an exact
idempotent completion. A changed request, different Agent identity, concurrent Hub state, replaced
UID, altered receipt, or different prior reconciliation is a conflict that requires investigation,
not another recovery attempt.

## Execute without an invisible helper

1. Follow the existing guide to enroll and accept installation identity. Do not regenerate the
   installation key to repair an incomplete setup.
2. Prepare a current private native approval. Run `fdai-lifecycle-agent bootstrap-slot` with
   `--installation-id`, `--state-dir`, `--local-policy`, `--current-state`, `--native-approval`,
   `--installation-key`, and either `--in-cluster` or an explicitly selected `--kube-context`.
   The default is dry-run. Only the separately authorized creation adds `--apply` and
   `--proof-output`. Transfer public proof through `submit-native-proof` and obtain human acceptance.
   For a mixed transition, include the exact `existing_resources` list described above. Bootstrap
   still creates only the anchor; the signed Plan execution performs adoption.
3. Stage signed inputs using the guide's `stage-inputs` command. Verify mirrored image digests.
4. Obtain a fresh exact Plan. A default `poll-once` validates admission without loading Kubernetes
   or creating a journal; it is not a server-side Kubernetes dry-run.
5. Start the approved bounded run using `poll --apply --in-cluster`, the approved namespace and
   persistent state, `--hub-auth workload-identity`, and the exact `--hub-scope`. Supply the
   required existing trust/input/native approval flags. `poll --help` documents finite poll and
   total-duration limits. Apply mode performs server dry-run before intent/report and mutation.
6. Read back Agent and workload results independently. Do not reissue a different Plan just
   because the first response was lost. Resume the same persistent journal and pending report.

The existing HTTP RBAC template does not grant CronJob access. Scheduled bundles need a separately
reviewed namespace Role for `batch/cronjobs`, available in the
[optional template](../../lifecycle/agent/deploy/scheduled-runtime-rbac.yaml).
It grants no Secret reads, identity writes or cluster-wide permissions. Applying it is a separate
permission change, not a step this document silently performs.

## What changes for FDAI?

Only the approved inputs change: product binding, immutable image set, private runtime bundle,
references, native object inventory, signed configuration pin, and independent effect checks.
The existing AKS topology is expressed with backend/Console Deployments, selected internal
Services, ClamAV sidecar/initialization, CSI/ConfigMap/PVC references and bounded scheduled tasks.
Database substrate, existing workload identities and initialized same-schema databases remain
prerequisites. Schema-changing migrations and unsupported topology deletion stop for review.

The synthetic tests establish shared execution and recovery behavior, not that real FDAI
integrations, models, inventory or application health have passed in Azure.
Prepare and verify actual references and application observations before that separate rehearsal.
If actual input needs an unsupported resource/security/authority effect, stop and review the
gap rather than changing a product name or expanding permission as a workaround.

## Failure, interruption and retention

- Distinguish network ingress denial, API 401/403, expired login and backend failure. A raw
  ingress denial can occur before the UI loads. Fix the approved source/network path, not roles.
- A v2 image or configuration failure restores recorded templates when safely verifiable.
  Schema changes and removal of previously healthy selected objects are blocked before writes.
- Any recovery involving a potentially active CronJob remains held: suspend scheduling, restore
  bounded templates, mark recovery unverified and halt subsequent applies. A suspended or absent
  template cannot prove that a task never ran. Inspect existing tasks and persistent effects
  independently before an authorized repair. Do not delete a halt marker merely to retry.
- Unknown native creation is not adoption permission. Preserve UID evidence and pending state.
  Resume with the same installation key and state; do not overwrite an existing object by name.
  A supported development adoption requires the exact local kind/name/UID approval and the
  Hub-signed ownership digest. Its rollback keeps the ownership marker while restoring the prior
  spec; only the separate reconciliation-release and Terraform import procedure reverses ownership.
- Environment retention, the execution schedule, local native approval validity and Plan expiry
  are separate limits. Keeping AKS online does not authorize unlimited ongoing changes.
- Retain durable Agent storage, installation identity and exact evidence. Cleanup requires an
  explicit target/UID list and independent absence checks; verify cost for retained infrastructure.

## Next steps

| To learn about | Read |
|---------------|------|
| Supported command/API sequence | [Hub operator guide](hub-lifecycle-operator-guide.md) |
| Contract, critique and implementation status | [Application runtime bundles](../roadmap/deployment/lifecycle-runtime-bundles.md) |
| Prioritized UI/process design backlog | [Operator experience improvements](hub-lifecycle-operator-experience.md) |
