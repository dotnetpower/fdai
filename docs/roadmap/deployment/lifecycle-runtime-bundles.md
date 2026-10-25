---
title: Application Runtime Bundles
---
# Application Runtime Bundles

This design extends the shared Lifecycle Agent beyond the bounded HTTP demonstration. You supply
an independently reviewed installation-local runtime bundle and signed application images, rather
than adding a renderer branch for each application.

> **Status:** Local implementation and focused validation; see the linked delivery ledger.
> This document does not qualify a
> complete FDAI installation or authorize a live deployment.
>
> **Scope:** Existing namespace, identity, storage, configuration references and initialized
> databases are prerequisites. Infrastructure creation, permission grants and schema-changing
> migrations retain their separate deployment and approval paths.

## Design at a glance

Use the same release publication, independent catalog approval, enrollment, ownership, signed
configuration, Plan admission, dry-run, apply, recovery and reporting sequence for every application.
Application differences belong in images and private reviewed data, not product-name conditions.

| Input | Producer | Consumer | Trust boundary |
|-------|----------|----------|----------------|
| `fdai.application-release.v1` | Vendor | Both Hubs and Agent | Existing bounded HTTP contract remains unchanged |
| `fdai.application-release.v2` | Vendor | Both Hubs and Agent | Signed immutable component images; no private Pod configuration |
| `fdai.application-runtime-bundle.v1` | Customer deployment owner | Agent only | Independently approved exact namespace, objects, references and Pod templates |
| `runtime_bundle_digest` | Customer configuration signer | Agent | Signed configuration pins the reviewed local bundle; it cannot supply or widen it |
| Native creation approval | Customer operator | Agent and ownership acceptance | Exact object kinds/names and existing UID-fenced creation/recovery |

The local policy and Hub installation independently bind the same product. The private bundle
also binds it. A bundle, package or Plan cannot change those independent bindings.

## Release and private runtime contracts

Release v2 keeps `product`, `release_version`, `source_commit`, `platform_tag` and optional
configuration/database schema metadata. Its `components` map contains 1-64 named records with
required `image_digest` and optional `image_ref`. When present, `image_ref` is a credential-free
registry reference pinned to that exact digest; a mutable tag alone is not accepted.
Omission preserves existing component manifests. The
[connected image bootstrap](hub-image-deployment.md) requires signed references for its complete
seven-component inventory rather than inventing registry coordinates or building replacements.
The Lifecycle Agent still uses its independently approved local repository bindings; the new
field never grants registry access or widens its local policy.
Unlike v1's `workloads`, v2 makes no HTTP claim about a sidecar,
initialization container or scheduled task. Unknown fields, invalid names/digests, duplicate JSON
keys, nonfinite values and existing byte limits remain blocked.

The installation-local bundle contains a format, product, namespace and bounded object list.
Each object names its Entity, kind, name and private specification. Only Deployments,
ClusterIP Services, bounded CronJobs and bounded HorizontalPodAutoscalers are in scope. Every container and initialization
container names an approved Release component instead of a repository, tag or raw image.
The Agent resolves it through the existing independently approved Entity/component/repository map.

The bundle permits reviewed service accounts, resource limits, non-root sidecars, initialization
containers, existing CSI/PVC/ConfigMap references and ephemeral writable directories.
It never creates a namespace, role, identity, Secret, PVC or SecretProviderClass.
Environment variables use references, not literal secret or connection values.
Host namespaces, host paths, privileged containers, added capabilities, root execution and
unrestricted resources remain unavailable.

Every selected Entity's signed configuration pins the exact canonical local bundle digest.
Missing/mismatched bundles, bindings or schema compatibility stop before application.
Reference syntax is validated locally. Existence/access of Secret, ConfigMap, PVC or CSI inputs
is not proved by that syntax check; server admission and bounded rollout expose missing inputs.
The Agent receives no Secret-read permission to inspect their contents.
Private rendered specifications remain in protected installation storage, not reports or Hub
metadata. The public configuration can carry the digest without exposing reference names.

## Autoscaled Deployments

A HorizontalPodAutoscaler is a bounded object that names its own Entity's Deployment of the same
name. It carries `minReplicas` and `maxReplicas` between 1 and 10 and one or two `Resource`
metrics (`cpu` or `memory`) with a `Utilization` target from 1 to 100. Behavior policies,
custom and external metrics and scale targets outside the bundle are rejected.

The autoscaler owns the replica count. A Deployment that has an autoscaler therefore omits
`replicas`, and a Deployment that omits `replicas` requires one; pinning both is rejected. The
renderer binds `scaleTargetRef` to the same-name Deployment and applies the autoscaler after the
Deployment. An update that replaces the Deployment spec keeps the live replica count instead of
resetting it to one. The rollout check follows the controller-reported replica count and is never
complete at zero. The native scope binds the autoscaler in `autoscaled_components`, which is
omitted when empty so existing scope digests and approvals do not change. The Agent role gains the
`autoscaling` `horizontalpodautoscalers` verbs it needs and nothing wider.

## Installation binding

A container environment variable takes exactly one source: an existing `valueFrom` reference, a
bounded `value` literal, a `binding` key, or a `configuration` key. A `binding` names a value the
installation owner supplies in the private `installation_binding` object of the same owner-only local policy
(`format: fdai.installation-binding.v1`, a map of at most 128 keys). The infrastructure agent
writes only the exact reviewed Terraform-output key set to a new owner-only file. It does not
replace an existing binding.

Binding keys are lowercase identifiers. Values and literals are 1 to 1024 printable characters and
cannot look like a credential: a URL with userinfo, `Password=`, `AccountKey=`,
`SharedAccessKey=` or a PEM header is rejected. A variable whose name suggests a credential (secret,
password, token, DSN, key, signing and similar) accepts only a Secret reference, never a literal
or either render-time key. The Agent rejects a binding key the bundle does not reference and a
referenced key the binding lacks, at policy load and again at render, with fixed messages that
never echo a value.

The values are resolved into plain environment values at render time and are not part of the
bundle. A `configuration` key names one non-secret field in the authenticated, signed,
Entity-scoped configuration render values. It is not a Key Vault lookup, cryptographic key, or
installation binding. Unknown, missing, unused, credential-shaped, and cross-Entity sources fail
closed. The pinned bundle digest covers literals and both key names, so changing a reference
changes the pin while changing an installation-local or signed configuration value does not.

## Native ownership and workload behavior

Old native scopes retain exactly their original serialized shape, digests, and Deployment/Service
resource set. Explicit additional resource records extend a newly approved scope to CronJobs.
`service_components` can explicitly restrict Services to a subset of the named Deployments,
so workers need no placeholder Service. Omitting it preserves the original all-Service scope.
They are digest-bound and never inferred from a Release or downloaded bundle.
Old readers that do not understand an extended private scope should reject it, not widen it.

Every object keeps the existing anchor ownership, exact namespace, Entity attribution, create-only
first write, retained UID/resourceVersion update and UID-preconditioned deletion.
CronJob Pod-template labels receive the same scope isolation labels as Deployments.
New kinds do not permit adoption of existing resources or mutation of generated Jobs by name.

Use the same private durable journal and pending-report store for bundle-rendered objects.
Server dry-run precedes the intent journal and `apply-started` report.
Deployments roll out before scheduled workloads are activated. Scheduled tasks have finite
deadlines, no concurrent execution and bounded retry/history settings.
Rollback restores recorded templates and removes only proven newly created objects.
An uncertain creation, failed recovery or unproved side effect stops for review.
Recovery involving a potentially active schedule conservatively suspends it and halts:
current suspension or absence cannot prove that an earlier task never ran. This is not automatic
reversal of persistent task effects, even if the workload templates were restored.

Installed templates and Pod readiness are not proof that FDAI's detection, inventory, model
bindings or scheduled operational effects are ready. Independent application-specific observation
remains input/evidence work; the engine does not manufacture an operational-success receipt.

## Design critique and revision

| Initial option | Problem | Revised decision |
|----------------|---------|------------------|
| Rename the HTTP demo to FDAI | Images alone omit configuration, identities, sidecars and scheduled work | Add an application-neutral component format and private runtime contract |
| Accept arbitrary Kubernetes YAML from a Hub Plan | A vendor or transport could supply local authority and private topology | Only independently supplied local bundles; signed configuration pins but cannot supply them |
| Add fields to the existing v1 manifest | Existing strict readers and HTTP semantics would become ambiguous | Distinct v2 image-component contract; preserve v1 byte/digest behavior |
| Reuse root images or enlarge roles for compatibility | Changes security and authority instead of expressing a workload | Preserve restricted Pod security and existing preapproved identities |
| Treat database revision metadata as migration permission | A workload rollback cannot reverse arbitrary persistent effects | Same-schema only; initialized DB and schema changes stay separately governed |
| Claim a CronJob template is a successful task run | Installation metadata does not verify operational effects | Report installation bounds; require independent task/effect evidence |
| Remove objects absent from a new bundle automatically | Deletion and active-task effects need separate approval/recovery design | Reject unsupported topology removal rather than silently leave or delete resources |

## Acceptance criteria

- [ ] Existing HTTP v1 and legacy runtime paths retain their behavior and signatures.
- [ ] Both Hubs publish/import v2 component releases through the existing catalog path.
- [ ] One Agent entry point accepts nginx-shaped and full FDAI-shaped data without product branches.
- [ ] Local bundle/product/namespace/component/digest mismatches fail before mutation.
- [ ] Private references and configuration values stay outside reports and public metadata.
- [ ] Native ownership, collisions, UID replacement, rollback, restart and duplicate Plan tests
  include the new supported object kinds.
- [ ] Real FDAI service, sidecar, initialization and scheduled-work topology can be expressed as
  private input, with pre-existing infrastructure/schema requirements explicit.
- [ ] An unsupported schema transition, topology deletion or unproved recovery blocks execution.
- [ ] Focused type, lint and behavior checks pass; actual cloud qualification remains separate.

## Related docs

| To learn about | Read |
|---------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/deployment/lifecycle-runtime-bundles.md) |
| Responsible operators, inputs and recovery | [Deployment handoff](../../runbooks/hub-lifecycle-deployment-handoff.md) |
| Shared protocol and ownership | [Hub-managed lifecycle](hub-managed-lifecycle.md) |
| Manifest publication and recall | [Releases and channels](lifecycle-releases-and-channels.md) |
| Existing operator steps | [Hub operator guide](../../runbooks/hub-lifecycle-operator-guide.md) |
| Foundation and schema preparation | [Source deployment](source-deployment.md) |
