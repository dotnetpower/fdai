---
title: Hub-Managed Lifecycle
---
# Hub-Managed Lifecycle

This document defines FDAI's third installation path. A Lifecycle Hub keeps each installation on
its subscribed release channel and on the configuration that its customer approved, following the
hub-and-spoke model of Palantir Apollo. It owns the lifecycle architecture, the plan and state
loop, and the customer isolation boundary.

> **Status:** Partially implemented for development. The local Hub, planner, and explicit
> independent product deployment roots and remote startup without login/catalog bindings exist;
> the full managed installation path is not
> delivered. No Azure deployment or production trust-root ceremony is claimed. The
> [implementation ledger](../../roadmap-implementation/deployment/hub-managed-lifecycle.md)
> tracks the exact delivered boundaries. [ADR-0003](../architecture/decisions/0003-hub-managed-lifecycle-and-operator-governance.md)
> records the decisions.
>
> **Scope:** The Hub deployment engine is application-neutral. FDAI is one deployable application,
> not a required service inventory. Each installation remains restricted to its independently
> approved application, owned Entities and local effect envelope. This does not give the FDAI
> operations loop authority over other applications.
> [Lifecycle Configuration](lifecycle-configuration.md) owns configuration layers and secrets, and
> [Lifecycle Releases and Channels](lifecycle-releases-and-channels.md) owns Releases, channels,
> bundles, and recall.

## Design at a glance

**FDAI Lifecycle Hub** manages deployments for individual installations. It is separate from the
planned **FDAI Release Hub**, the vendor application for release publication, signing, channel
promotion, and recall. Release Hub provides the **Release Catalog**, the release list, data, or
feed consumed by Lifecycle Hubs. Catalog remains a technical data term, not an application name.
An initial Release Hub can start with CLI/API workflows; this design doesn't imply that the full
Release Hub service already exists.

| Concern | Decision |
|---------|----------|
| Product versus installation | One signed Release serves every customer. An installation differs only in configuration, policy, and bindings to its own environment. |
| Hub placement | A central Hub cell per connected customer, or a Target Hub inside the customer boundary that syncs online or imports signed bundles offline |
| Desired state | No single target state. The Hub derives the target from a channel subscription, version range, configuration revision, and constraints. |
| Plan computation | The Hub computes Lifecycle Plans. Installation agents derive the maximum effect envelope locally, and a Plan can only narrow it. |
| Installation agents | A lifecycle agent inside the cluster for workloads, and an infrastructure agent on the execution host for exact Terraform plans. Neither is a pantheon agent. |
| Upgrades | Automatic inside maintenance windows. Configuration changes need an approved change request, and deleting or replacing an Azure resource needs confirmation. |
| Data boundary | The Hub holds no customer workload credential or operational data. Its own bounded service identity and signing key do not authorize customer resource changes. Only lifecycle metadata crosses the boundary. |
| Records | Hub PostgreSQL per cell or Target Hub, and append-only installation receipts in Foundation storage |

## Application-neutral package boundary

The optional `fdai.application-release.v2` extension separates signed component images from the
customer's independently reviewed private runtime bundle. The
[runtime-bundle contract](lifecycle-runtime-bundles.md) owns its supported kinds, exact signed
configuration pin, security bounds and conservative scheduled-effect recovery holds.
It preserves the publication/admission/ownership sequence below and does not qualify a complete
FDAI installation. The [deployment handoff](../../runbooks/hub-lifecycle-deployment-handoff.md)
identifies each operator and manual/automatable boundary.

Publication, pinned import, planning, execution and reporting share `fdai.application-release.v1`.
Its product, application source, immutable component images and HTTP metadata are data, not engine
branches. The [Release contract](lifecycle-releases-and-channels.md#application-package-contract)
owns field bounds and optional configuration/database schema metadata. Without database metadata,
schema revision zero represents a stateless application, not migration or database-reset authority.

The operator-bound Hub Settings and installation-local Agent policy each bind `product`.
Enrollment cannot set this binding; neither can a package or Plan. A missing or different binding blocks the
application package. Existing installations without this field retain only legacy runtime-package
compatibility; explicit application bindings never fall back to that path. The legacy runtime
parser still validates complete FDAI inventories for source/offline compatibility.

For existing enrollments, operator-only `POST /v1/installations/{installation_id}/application-binding`
requires a UUID, current Settings digest, reason and confirmation
`bind application <installation_id> <product> <settings_digest>`. The installation row lock
serializes scheduling and planning; open Plans, stale digests and application retargeting are
blocked. Exact same-actor retry and attributed audit are retained without changing ownership,
permissions, configuration or reported state. The lazy **Application** tab requires the ID twice
and generates machine values. Uncertain results require refresh, not automatic resubmission.
Agent local policy remains independent; see the [operator procedure](../../runbooks/hub-lifecycle-operator-guide.md).

**Critique and revision:** Renaming a hardcoded application is not a shared engine. Image lists alone
permit cross-application substitution and omit health observation. Independent product bindings,
signed component/health metadata and strict JSON retain exact signatures, version/digest checks,
artifact availability, recall, windows, ownership, dry-run, rollback and durable replay guards.
Application packages reject legacy workload profiles. Packages never prove ownership or select app-specific flags or Entity kinds.
Arbitrary Kubernetes templates, privileges, namespace creation, new ownership evidence and
database migration execution remain outside this change.

Release ids remain unique within one Release Hub catalog. This change makes that catalog usable
for any application; it does not introduce a multi-product version namespace. Local synthetic
checks are not Azure deployment evidence or production qualification.

## Installation Agent configuration source consumer

The existing `fdai-lifecycle-agent poll-once` entry point and directory artifact store now accept
the original full v2 signed configuration container. Independent installation-local public keys,
X25519 private input, active revision and Entity/history bindings remain separate from Hub
transport. The Agent verifies the Plan, exact Release/schema, package and complete history before
decrypting and passing each Entity's values to its existing renderer. Missing prerequisites hold
only this capability; legacy flat artifacts and default dry-run behavior remain compatible.
The [configuration owner](lifecycle-configuration.md#installation-agent-consumer-design-and-critique)
records the pre-implementation critique and privacy boundaries.

The explicit read-only `reference-status` command uses the existing Kubernetes transport to
inspect exact CSI/Pod/provider metadata, with Entity, source version and freshness attribution.
Its strongest positive result is `reported-mounted`, not verified secret usability. It never
reads Kubernetes Secret data or mounted files, and absent source bindings remain unavailable.
See the [installation guide](../../runbooks/installation-agent-configuration.md) for local inputs.

This is implemented source/local synthetic evidence only: no live onboarding, artifact delivery,
CSI provider binding, Agent rollout, operational effect receipt or production qualification is
claimed. Hub import, change approval, activation, signed Plan admission and local execution
safeguards remain separate decisions.

## Legacy paired development fixture

For an admitted runtime v3 Release with optional configuration-schema metadata, the existing Hub
planner compares the installation's schema digest with that exact Release's accepted schema before
issuing a Plan. Mismatches block the candidate. The
[configuration owner](lifecycle-configuration.md#release-schema-admission-design-and-critique)
defines annotation and version checks. A Release without this optional capability keeps its
existing behavior; source and offline installation gain no new gate. Independent export pin,
manifest signature, expiry, recall and local effect-envelope checks remain authoritative.

The existing upgrade planner's `plan_next` source API can also receive a transient
`ConfigurationRevisionCandidate` for one signed full multi-Entity configuration revision. The
caller supplies independently bound customer/installation keys, sealed-key classification,
complete accepted history and the independently retained head. The planner verifies the exact
catalog Release version, manifest digest and schema, and requires the package to cover exactly
an independently supplied one-to-one map of the exact installation's already-managed Entity set to
opaque package bindings. Existing enrolled IDs remain unchanged in signed Plans. Every Entity resolves independently;
one failure blocks the whole candidate, and the signed Plan binds the complete package digest.
It neither manages an Entity because it appears in a package nor bypasses recall, timing or
effect-envelope checks. With no candidate, legacy planning is unchanged. With a candidate, a
Release without the schema capability is blocked rather than falling back to legacy configuration.

This API is in-memory source consumption only. It is not exposed as a remote import or enrollment
route, does not write a configuration-head receipt, and does not claim ciphertext-only database
storage. The [configuration owner](lifecycle-configuration.md#full-multi-entity-revision-design-and-critique)
defines the new format, compatibility and critique. Actual key onboarding,
persisted same-Release configuration-change scheduling, Agent delivery/decryption, CSI reference
resolution and production qualification remain open.

### Approved configuration-key consumption

The separate authenticated configuration-key APIs now attach public Ed25519 configuration-signing
and X25519 installation-encryption keys to an already enrolled installation. Its existing Ed25519
identity proves the complete request; a different authenticated customer operator approves the
exact digest. Local caller names and package keys cannot register trust. The
[configuration owner](lifecycle-configuration.md#approved-configuration-keys-design-and-critique)
defines the pre-implementation critique, role separation, deadlines and explicit version chain.

`HubStore.recompute_configuration` resolves current approved public bindings under the existing
installation lock and passes only those keys into the actual planner/verifier. The existing remote
catalog recompute API can consume a candidate and binding version from an explicit server-owned
`target_routes(..., configuration_candidates=...)` composition seam, never the HTTP body.
Entity mappings, sealed-key classification and retained accepted history remain independent
composition inputs for this compatibility seam. The configured default now uses
`HubStore.recompute_persisted`: it resolves the persisted activated revision, independently approved
Entity mapping, classification and original accepted history without candidate injection.
Starting the server never imports or activates a package automatically.

Configuration Plans persist the exact approved binding version and request digest in the same
transaction. Current-Plan retrieval holds them after expiry, rotation or revocation. Historical
public bindings remain intact; the atomic importer verifies each historical package with its exact
accepted key version and receipt, never a replacement key. Absent or unprovable bindings hold
only this new configuration capability. Legacy enrollment and planning remain compatible.
Explicit Lifecycle Hub schema revision 6 preserves the additive configuration upgrades from
revisions 1 and 2, revision-4 customer-local channels and revision-5 empty workload state.
It also prevents older readers from interpreting the new native ownership evidence.
Enrollment, public key
bindings and legacy raw configuration remain intact; Release Hub stays at revision 1.
The actual authenticated source API separately requests/approves an installation-proven Entity
scope, imports a complete signed container, approves its change request and activates its exact
receipt. The accepted head, import record and audit share the pinned-catalog/installation owner
transaction. Import, approval and activation are distinct and cannot grant execution or promotion.
The [configuration owner](lifecycle-configuration.md#atomic-import-and-configured-consumption-design-and-critique)
defines request formats, bounds, historical trust and the pre-implementation critique.

The same catalog transaction now supports [customer-local channel curation](lifecycle-releases-and-channels.md#customer-local-channel-curation-design-and-critique). Existing operator approval can narrow a fresh imported `RELEASE` set into `local-` membership; exact local revision and accepted pin/digest remain in planning audit. It changes no installation settings, execution approval or vendor bytes, and serving requires the explicit current schema migration.

Only this new import path stores original ciphertext containers and public metadata. Legacy raw
configuration remains unchanged. Local HTTP/JWT and isolated PostgreSQL tests prove default
consumption, independent approval, concurrent-fork rejection, audit rollback, restart/retry and
cross-key history. They do not register real keys, migrate a deployed database, enable Agent
transport, schedule same-Release configuration actions or establish production qualification.

The existing paired fixture remains available for its current state owners. It is not the default
deployment unit. Use the independent product roots below for new preparation.

The vendor Release Hub and customer Target Lifecycle Hub have separate ACA environments,
VNets, PostgreSQL servers/databases, managed identities, Key Vaults, and logs in separate RGs
of one test subscription. RG separation is administrative, not evidence of security isolation.
No peering or vendor-to-customer grant is introduced. Approved browser CIDRs and the customer
NAT address bound HTTPS ingress; private data planes remain separate.

The explicit remote profile verifies Entra bearer tokens directly, including issuer, audience,
time, operator object/client/scope binding, or the exact customer service identity and export-only
role. Proxy headers cannot authenticate a caller. The local CLIs retain loopback defaults.
Versioned secret references supply independent development signing keys; PostgreSQL uses only
the Hub's own managed identity and verified TLS. Explicit migrations precede remote serving.
Key rotation or an incompatible older schema requires a separate reviewed migration.

The customer operator approves a revision and exact digest obtained through a separately
approved trust channel before requesting one bounded outbound import. The export response's
digest is not that approval. Accepted bytes, digest, key binding, monotonic revision floor,
and attributed audit persist. Existing manifest signatures, expiry, recall contracts, and
planner constraints remain in force; recall import and planning serialize against one trust row.
The UI can compute a Plan for an already prepared synthetic installation. The legacy fixture does
not configure installation Agent bindings or execute a Plan.

[Two-Hub development boundaries](../../../infra/hubs-development/README.md) owns preparation
steps and validation commands. Static IaC and local containers do not establish Azure
network/RBAC isolation, real Entra sign-in, registry availability, or replica durability.
Those require a separately approved exact cloud preview and execution scope. This path does
not change source/offline installation and does not implement automatic polling, production
catalog metadata/root ceremony, cloud Agent apply, or a complete FDAI installation.

## Execution scheduling preparation design and critique

An authenticated customer operator can prepare daily maintenance windows and the Plan duration
for an already enrolled installation. `GET /v1/installations/{installation_id}/execution-settings`
returns only those scheduling fields and the digest of the complete current settings.
`POST` requires a request UUID, that expected digest, bounded windows and duration, a reason code,
and the exact confirmation `update execution settings <installation_id> <settings_digest>`.
The authenticated operator comes from verified transport claims, never the request body.

Windows use local wall-clock start times, IANA time zones, `duration_minutes` between 1 and
1440, and an explicit downtime flag. Fractional minutes preserve existing subminute precision
in the read projection. There are at most 32 windows; Plan duration is an integer from 1 to
1440 minutes. Unknown fields and invalid values return `422`; bodies above 8192 bytes return `413`.

**Critique and revision:** Updating all installation settings would also expose placement,
channel and fencing changes. This operation changes only windows and Plan duration. It holds the
existing installation lock and rejects an open Plan rather than silently changing its assumptions.
The same transaction updates settings and appends the attributed hash-chained audit. Repeating
an identical request UUID and actor returns its original applied digest without another change;
reusing that UUID with different bytes or another actor is a conflict. The returned digest on
a replay identifies the historical operation, not a claim that later settings remain unchanged.
An unchanged schedule is audited with `changed: false` without refreshing the installation's
recorded timestamp. Conflicting revisions, request reuse and open Plans return `409`.

This preparation doesn't manage an Entity, accept ownership evidence, register keys, import
artifacts, compute a Plan or authorize application. Installation Agents, catalog service identities
and unauthenticated loopback caller names can't use the operator route. No new table or remote
database mutation script is needed.

The installation's **Execution schedule** section loads this projection only when opened.
It provides bounded window controls, the server-read confirmation text and a browser-generated
request UUID. Reads and writes have ten-second deadlines. A rejected or uncertain save disables
further changes until an explicit refresh; it never retries a write or computes/applies a Plan.
Focused source and synthetic UI checks are not live deployment evidence. Exact-source activation,
human operational confirmation and the remaining evidence-backed workload preparation stay separate.

## Read-only input inventory

The read-only **Available releases** screen projects the already accepted catalog through
`GET /v1/catalog/releases`, rechecking its pin, signatures and expiry without an outbound import.
Unavailable catalog trust returns `503`; a verified empty catalog remains a distinct result.
**Configuration packages** uses `GET /v1/configurations` for stored digests, counts, timestamps
and current installation references, omitting values and sealed identifiers. It explicitly
states that independent package signature provenance is not recorded. Neither listing proves
artifact availability, eligibility or signed-input readiness, and Agent identities cannot read
these operator inventories. See the [operator guide](../../runbooks/hub-lifecycle-operator-guide.md)
for onboarding/release diagrams, public input provenance and the current manual/production gap.

## Opt-in installation Agent transport

The local development implementation accepts an explicit `auth.agent_principals` binding for
each installation. A caller needs the exact application object/client pair, no delegated `scp`
claim, and the `Agent.Access` role in a directly verified Entra token. When Entra emits `idtyp`,
it must be `app`; v2 Managed Identity tokens that omit this optional claim remain application
tokens because the exact object, client and app role must still match. It can only read that
installation's Plan and submit its state/reports. Operators, catalog identities and Agent
identities remain distinct; an Agent cannot enroll, approve, publish, import or recompute.
Release Hub refuses Agent bindings, and an empty binding list preserves existing denial.

For an explicitly bound installation, the verified operator can submit its signed enrollment to
`POST /v1/enrollments/{installation_id}/requests`. The existing installation proof, freshness,
matching-id and size checks still apply; the audit records the authenticated `requested_by`.
Submission creates only a pending request. Approval and Entity management remain separate.
The original Agent enrollment route stays closed, and unbound installations cannot use the
operator route. The independent Lifecycle Terraform root forwards nonempty Agent bindings;
empty bindings omit the runtime field for compatibility with older images.

The **Enrollment requests** screen lets the operator enter the bound installation ID and
upload a signed request JSON file of at most 64 KiB. It sends only `signed_payload` and
`proof`; private keys are never an upload input. Submission has a ten-second deadline and
does not retry automatically. After an uncertain result, refresh the pending list before
retrying. A pending result is not approval, ownership evidence, or permission to apply a Plan.

The Agent can explicitly exchange its AKS projected workload identity for the selected Hub API
scope and separately load in-cluster Kubernetes authentication without kubeconfig fallback.
Finite polling stops on errors, rejection or rollback. Signed inputs are independently pinned,
verified before offline staging, then verified again at admission. The existing fsynced replay
floor, pending report and rollback journal live with current state on a persistent volume in the
Agent namespace, outside its workload Role. Only namespace-scoped Deployment, Service and Job
operations are granted. See the [Agent preparation guide](../../../lifecycle/agent/README.md#remote-development-preparation).

For connected installations, the Agent can select `--artifact-source hub`. After it receives a
signed Plan, it requests only that Plan's exact Release and active configuration digests through
its installation-bound `Agent.Access` identity. Lifecycle Hub rechecks the current eligible Plan,
the accepted Release catalog, and the retained configuration import before returning original
signed bytes. It doesn't provide an artifact list or another installation's inputs.

The Agent verifies each signature and canonical digest before publishing the bytes to its private
state volume. A later poll reuses the exact cached files, which removes repeated Hub downloads
without treating cache presence as trust. Missing, changed, unbound, or unavailable artifacts
remain retryable input holds and cause no Kubernetes call. Vendor and customer public keys, the
private runtime bundle, installation policy, and decryption material remain independently
provisioned installation inputs. This transport does not mirror images or grant apply authority.

The independent [Lifecycle Agent deployment root](../../../infra/lifecycle-agent/README.md) prepares
one AKS Agent without changing the source/offline workload root. It creates a dedicated
user-assigned Managed Identity, one workload-federation binding, the exact `Agent.Access` app-role
assignment, an Agent namespace and persistent state, and a namespace-scoped workload Role. It
grants no Azure managed-resource role. `enable_agent=false` prepares these prerequisites without
starting a poller; an exact later plan starts one Recreate-strategy Agent only after enrollment,
ownership, reported state, signed inputs and a Plan exist. The installation identity private key
is never a Terraform input. A pre-staged customer configuration signature remains canonical Base64
through Terraform and uses the Kubernetes provider's binary-secret field; it is never decoded as
UTF-8 text or exposed as a Terraform command argument. The disabled stage creates its
`WaitForFirstConsumer` PVC without waiting for `Bound`; binding and independent readiness are
verified only after a consumer is scheduled. Activation runs a bounded one-shot initializer Job,
waits for it to complete, and only then creates or updates the Agent Deployment. The Job mounts
public and private inputs read-only so an optional pre-staged configuration and signature can reach
the persistent verified cache before the Agent process starts. It also copies the local policy and optional native
identity inputs to owner-only `0600` files beneath an exact current-UID mode-`0700`
`/state/private` boundary on the PVC. The main Agent never mounts the Kubernetes Secret and reads
only those private state files. `fsGroupChangePolicy=OnRootMismatch` prevents kubelet from
recursively broadening those modes after the PVC root already has the Agent group. The main Agent
bind-mounts only the required PVC files by `subPath` beneath the image's UID-owned mode-`0700`
`/config/private` directory, so the group-managed PVC root is never a private-input parent. The
initializer keeps its private-input and artifact-cache directories in distinct variables; native
approval and installation identity files cannot drift into the configuration cache. Because the
initializer is a separate Job, every PVC `subPath` source exists before kubelet prepares the Agent
Pod. Each run rewrites private inputs from the retained Secret through mode-`0600` temporary files
and atomic replacement; prior file presence is never treated as trust. An interrupted kubelet
`subPath` placeholder is removed only when it is an empty directory. Non-empty directories fail
closed. The Job Pod template binds a digest of every staged input, so policy, approval, native
state, current state, public identity or configuration changes replace and rerun it. The first 12
digest characters are also part of the bounded Job name, so provider patch behavior cannot suppress
the required rerun. After local native bootstrap, the enabled Agent input includes the validated
`lifecycle-native-scope.json`; the initializer stages it atomically at the Agent state path without
copying the installation private key into Terraform. All journal, current-state, native-state and
artifact-cache files live beneath the UID-owned mode-`0700` `/state/agent` directory; the
group-managed PVC mount root is never passed as the Agent state directory. The main container
mounts only that `agent` subdirectory at the image's UID-owned mode-`0700` `/agent-state` path, so
strict readers never traverse the group-writable PVC mount root. A bounded `64Mi` `emptyDir`
provides writable `/tmp` for Kubernetes dynamic discovery while the image root filesystem remains
read-only.

An expired native approval is a retryable local hold because an attributed operator can renew the
same exact scope without changing the installation proof or Plan bytes. The Agent re-evaluates both
new retryable records and legacy non-retryable records carrying this exact reason, including removal
of its legacy sequence tombstone; all other final rejections remain replay-safe.

`fdai-lifecycle-manager prepare` closes the installation-local preparation boundary before any
remote effect. From a clean source revision, digest-pinned component images, a reviewed private
runtime bundle, and independently obtained Hub/Release public keys, it creates a new private
directory containing the immutable publication request, signed enrollment, customer-signed
configuration, application-binding request, Entity settings, explicit empty state, native scope
approval, Agent policy/cache and installation-owned keys. It contacts no Hub, Azure endpoint,
registry or cluster and deletes a partial destination on failure. Its receipt contains digests
only and grants no publication, enrollment, ownership, Plan or apply authority. If infrastructure
and catalog stages outlive the bounded enrollment proof window, `refresh-enrollment` verifies the
retained proof and key pair, preserves the installation identity and payload, and writes a new
mode-`0600` proof with only `requested_at` refreshed. It never overwrites the original.

These opt-ins also have one bounded live development-installation receipt. Release Hub published
and Lifecycle Hub imported the exact signed Release, an installation-bound Managed Identity fetched
the Plan and artifacts, and the Agent applied and independently observed one ready FDAI Operator
canary before reporting `applied`. A fresh recompute returned `up-to-date`, and repeated polls
returned `no-plan`. This evidence covers one retained AKS development installation, not production,
volume eviction, identity rotation, multi-Entity updates, or configuration-key rotation. The
installation's existing database Secret reference was bound during workload preparation; future
private runtime bundles must carry every such dependency before Plan execution. Existing Hub
images, revisions, catalog bindings and network allowlists change only through exact cloud plans
and separate approval.

## Independent product deployment

Release Hub is the vendor's product. Lifecycle Hub is the customer's deployment-management
product. Each deploys its own bundled UI/API and PostgreSQL through one root and one state:

| Product | Deployment root | Required peer inputs |
|---------|-----------------|----------------------|
| Release Hub | [infra/release-hub](../../../infra/release-hub/README.md) | None |
| Lifecycle Hub | [infra/lifecycle-hub](../../../infra/lifecycle-hub/README.md) | None |

The same code serves development and production through private inputs and separate backend
state locations. Native local backends accept explicit absolute paths in durable private storage,
preserving existing local state without an Azure Storage prerequisite. A remote backend is an
optional, reviewed Terraform override prepared before candidate freeze, never an active-run switch.
The shared internal module creates only the selected product's resources. It doesn't read
the other Hub's state, IDs or NAT address. An approved registry remains an explicit external input
to both product roots. A product-separated deployment may place the shared Hub image transport in
the Release Hub resource group without transferring Lifecycle Hub state ownership. The validated
development topology uses one dedicated Release-Hub-owned ACR, grants each Hub Managed Identity
`AcrPull`, and pins every app and Job to its product-specific digest. Registry relocation changes
neither Hub database, Key Vault, network nor installation authority. No FDAI source/offline
installer, main infrastructure root, Agent or cluster deployment changes.

With zero Entra app registrations, each root plans without Graph or directory state and each
remote application can migrate its own schema, serve, report health/readiness and provide its UI.
PostgreSQL/Key Vault managed identities, verified TLS and the human DB administrator remain.
An app-owned bounded SQL/Key Vault bootstrap command runs in a temporary manual Job. Native
Terraform declares resources; native Azure CLI starts and observes Jobs. Temporary grants are
removed after initialization, separately from permanent runtime resources.

After startup, each product can retain one manual trusted-operations Job for automation that
doesn't depend on a browser session. Release Hub accepts only an exact private
`publish-release` request. Lifecycle Hub accepts only exact `import-catalog` or `recompute`
requests. The Job reads one exact-version Key Vault request, uses only that Hub's Managed Identity
and transactional store, emits a bounded digest-only receipt, and has no installation apply
identity. Exact retries read back the retained publication or import rather than adding another
effect. Operator enrollment, ownership acceptance and Plan application remain separate boundaries.

Login and Lifecycle's catalog source are optional explicit bindings, not placeholders.
Without login, management APIs fail closed with 503 and the UI reports their unavailability.
Without a catalog, Lifecycle doesn't instantiate a remote catalog client; that feature is
unavailable. A later source can be bound through attributed `bind-catalog`, which doesn't import
or approve a pin and never silently replaces a persisted key. Existing authenticated and local
loopback behavior remain unchanged.

The [single-product procedure](../../../infra/modules/hub-service/README.md) documents frozen
source/locks/base and runtime digests, manual Jobs, cleanup and backup-copy state rehearsal.
Legacy state and directory/registry owners aren't modified automatically.
The anonymous management API policy is deferred and the requested functionality remains unmet.
Management APIs continue to fail closed. This pending policy doesn't stop independent
migration/startup/UI preparation or a separately authorized UI/readiness-only deployment.
Such a deployment proves process, schema and screen availability, not usable anonymous
management functionality. A shell or unavailable-feature screen isn't full functional completion.
SQLite/mock/browser evidence, PostgreSQL/image acceptance and actual Azure deployment are
reported separately; unavailable local infrastructure doesn't count as a pass. Source delivery,
image publication and Azure changes each still require their own explicit authorization.

### Bounded database recovery inspection

Use the app-owned `python -m fdai_lifecycle_hub.database_inspection` command for separate
source and restored observations through an approved private observer. The command reuses each
product's runtime managed identity and verified TLS. It checks migrated schema and effective
runtime privileges only after rejecting URL-query routing overrides before connecting.
Observations use one repeatable-read, read-only transaction and always roll back.
Per table, counts stop at 1,001 rows, at most 1,000 are accepted, and primary-key ordering selects
at most 32 representative rows for SHA-256 comparison. Timestamp rendering uses UTC.

Private `0600`, no-overwrite receipts retain counts and fingerprints, not raw rows or connection
values. Retain them outside an ephemeral Job and use an approved private baseline-transfer path.
The [product procedure](../../../infra/modules/hub-service/README.md#read-only-database-recovery-comparison)
owns the command options and observation limits. This is not a restore orchestrator or evidence
of complete database equivalence: equal counts can hide changes outside the sample. Capture the
source near the selected restore point with writers excluded. Native server identity, private
DNS, Entra-only/admin bindings and temporary-resource absence need separate authoritative
readback. Local PostgreSQL tests don't validate Azure PITR or managed identity.

## Core concepts

Four concepts carry the whole design. Keeping them apart is what lets one product serve every
customer without a fork.

| Concept | What it is | Owner | Changes through | Lives in |
|---------|------------|-------|-----------------|----------|
| Product | FDAI itself, shipped as signed Releases that are identical for every customer | Vendor | Release pipeline, channel promotion, and recall | Release catalog |
| Installation | One FDAI deployment inside one customer boundary, which Apollo calls an Environment. A customer can have several. | Customer | Enrollment, channel subscription, and Entity settings | Hub `installation` and `entity` tables |
| Configuration | Desired values for one installation: Environment Config and Entity override blocks. It never carries authority. | Customer | Reviewed merge in customer Git, delivered as a signed package | Customer Git, then Hub configuration tables |
| Runtime state | What the installation actually runs and observes: reported state, receipts, policy and authority state, and operational data | Installation | Agents and governed authority paths only | Installation stores. The Hub sees lifecycle metadata only. |

## Design and critique

**Initial design:** A central control plane stores one desired state per customer, a five-layer
override stack resolves configuration, and new Deployment, Configuration, Drift, and Policy agents
run the rollout.

**Critique:**

- Apollo doesn't keep one target state per environment. A product follows a release channel and
  constraints, and the target emerges from them
  ([Apollo overview](https://www.palantir.com/docs/apollo/core/overview)).
- The pantheon is fixed. An agent that upgrades the runtime it runs on also creates a circular
  dependency.
- A central engine that renders exact plans needs every customer's Azure credentials, which
  regulated customers prohibit.
- A linear override stack lets configuration change authority, which ADR-0002 forbids.
- Offline sites can't poll a central service.

**Revised contract:** The Hub orchestrates. Signed artifacts and installation-side agents decide
what can actually change. Authority stays in policy and the promotion registry, and offline sites
run their own Target Hub.

## Apollo concepts in FDAI terms

| Apollo concept | FDAI equivalent | Difference |
|----------------|-----------------|------------|
| [Product, Release](https://www.palantir.com/docs/apollo/core/products-releases-versions) | FDAI Release: signed image digests and metadata | One product. Services aren't released separately. |
| [Release Channel](https://www.palantir.com/docs/apollo/core/release-channels) | `DEV`, `RELEASE_CANDIDATE`, `RELEASE`, and custom channels | Same model. See [Lifecycle Releases and Channels](lifecycle-releases-and-channels.md). |
| [Hub, Orchestration Engine](https://www.palantir.com/docs/apollo/core/overview) | Lifecycle Hub | Computes Plans but never renders exact infrastructure changes |
| [Environment](https://www.palantir.com/docs/apollo/core/environments) | Installation | One installation per environment. A customer can have several. |
| [Spoke Control Plane](https://www.palantir.com/docs/apollo/core/spoke-control-plane) | Lifecycle agent and infrastructure agent | Azure writes stay on the existing execution host |
| [Entity, Reported State](https://www.palantir.com/docs/apollo/core/entities) | Entity, reported state | Agents are sub-state of the Core Entity |
| [Environment Config](https://www.palantir.com/docs/apollo/managing-environments/environment-config), [config overrides](https://www.palantir.com/docs/apollo/managing-entities/set-config-overrides) | Environment Config, Entity override blocks | Authority values are excluded |
| [Change Requests](https://www.palantir.com/docs/apollo/managing-changes/change-requests) | Reviewed merge in customer Git, delivered as a signed configuration package | Git is the source of desired configuration |
| [Plans and Constraints](https://www.palantir.com/docs/apollo/core/plans-and-constraints) | Lifecycle Plans and constraints | Adds data residency and destructive-change confirmation |
| [Export and Import](https://www.palantir.com/docs/apollo/export-import/overview) | Upgrade bundle imported into a Target Hub | Configuration packages keep the customer signature |
| [Secrets](https://www.palantir.com/docs/apollo/managing-secrets/add-edit-delete-secrets) | Key Vault references only | The Hub never receives a secret value |

## Architecture

![Architecture. The main stages are FDAI Release Hub / signed Releases, channels, recalls, Lifecycle Hub / central Hub cell or Target Hub, Customer Git / desired configuration, Lifecycle agent / workloads and reported state, Infrastructure agent / exact Terraform plans, FDAI services / operations loop, Azure resources.](../../diagrams/generated/fdai-roadmap-deployment-hub-managed-lifecycle-01.en.svg)

| Component | Runs in | Identity | Holds | Never holds |
|-----------|---------|----------|-------|-------------|
| FDAI Release Hub | Vendor | Vendor release key, kept offline | Release Catalog: signed Releases, channel membership, recalls, promotion pipelines | Customer data |
| Lifecycle Hub | Central Hub cell or Target Hub | Hub service identity. Approvers sign in with the customer's Entra ID. | Installation settings, imported configuration packages, reported state, Plans, constraint results, audit | Azure credentials, secret values, clear-text sealed values, operational data |
| Lifecycle agent | Installation AKS cluster, own namespace | Workload identity with Kubernetes rights in FDAI namespaces only | Rendered workload manifests and workload receipts | Azure write identity, executor identity |
| Infrastructure agent | Existing execution host | Existing deployment managed identity | Exact Terraform plans, Foundation state, infrastructure receipts | Executor identity, operational data |
| FDAI services | Installation | Existing service identities | Operations-loop state | Lifecycle authority |

### Hub placement

| Placement | Location | Catalog source | Operated by | Typical customer |
|-----------|----------|----------------|-------------|------------------|
| Central Hub cell | Vendor subscription, in a region agreed with the customer. Each customer gets an isolated cell with its own database and customer-managed key. | Release catalog directly | Vendor | Connected, no boundary restriction |
| Online Target Hub | Customer operations resource group | Sync from the catalog over an allowlisted outbound path | Customer | Regulated and connected |
| Offline Target Hub | Customer operations resource group | Signed upgrade bundles that an operator imports | Customer | No internet access |

A Hub cell is a per-customer isolation unit of the central Hub. It's unrelated to the streaming
cells in [Hyperscale Cell Architecture](../architecture/hyperscale-cell-architecture.md).

### Trust boundaries

- The vendor release key signs Releases, catalog metadata, recall notices, and upgrade bundles.
  [Catalog integrity](lifecycle-releases-and-channels.md#catalog-integrity) defines freshness and
  ordering.
- The customer configuration key signs configuration packages. It stays in the customer's Key
  Vault or HSM.
- Each installation holds a non-exportable installation key in its Key Vault. It proves possession
  of that key at enrollment, then uses it to unwrap sealed values and sign receipts.
- Each Hub cell or Target Hub has its own Hub key. Hub and installation keys rotate through signed
  key records, and revoking a key invalidates every Plan it signed.
- Installation agents derive the maximum effect envelope locally from the signed Release, the
  configuration package, ownership evidence, and local hard policy. A Hub Plan can only narrow it.
- Only lifecycle metadata crosses the boundary: versions, digests, coarse component health,
  constraint results, and sanitized plan summaries. Event content, resource identities, ontology
  content, audit content, secrets, credentials, and clear-text identifiers stay inside the
  installation.

## Lifecycle loop

### Desired inputs

The Hub derives each installation's target from these inputs:

- channel subscription and an optional version range;
- current configuration revision: Environment Config and Entity override blocks;
- catalog facts: Releases, channel membership, recalls, product dependencies, and schema ranges;
- constraints and the latest reported state.

The target is the newest non-recalled Release on the subscribed channel inside the version range
that passes every constraint. It deploys with the override block whose version range matches that
Release most specifically.

### Entities and reported state

| Entity kind | Examples | Managed |
|-------------|----------|---------|
| Workload | Core, Operator API, Document Ingestion API, Document Processing Worker, isolated Executor, Console, CronJobs, lifecycle agent | Yes |
| Platform | AKS cluster, PostgreSQL, Event Hubs namespace, Key Vault, container registry, storage, network | Yes |
| Unmanaged | Customer-owned API Management, private DNS zones, ITSM endpoints | Observed only |

Reported state includes the Release version, image digests, configuration digest, coarse health,
and the last Plan result. The Core Entity adds a band for each agent: running, degraded, or stopped,
with bounded consumer-lag and idle-time bands. Event content and per-event times stay inside the
installation. Platform Entities add digests of Terraform state lineage, serial, and resource
identities. As in Apollo, an Entity with settings and reported state is managed, and an Entity with
reported state only is unmanaged. Reported state is append-only and keeps event and recorded time.

### Lifecycle Plans

Plan types are install, upgrade, configuration change, recall roll-off, drift reconciliation, and
uninstall. Uninstall always needs operator confirmation. Each Plan names its installation as the
audience, the Hub key epoch, the reported-state digest it was computed from, a sequence number that
increases per installation, a fencing generation, the target Release, the configuration revision,
the Entity set, constraint results, a narrowing envelope, and an expiry. Agents durably reject a
Plan whose sequence, generation, or source-state digest is stale.

> **Implemented admission boundary:** The Agent verifies canonical signed Plan bytes against
> independently configured Hub trust and durable local sequence state. Stale sequence, wrong
> audience, revoked key and an over-wide envelope are refused before cluster calls even when
> the apply adapter is enabled. Automatic apply additionally requires a local
> `LifecycleAuthorizationReceipt` bound to the exact Plan digest, fencing generation, Release and
> configuration digests, and open window, and holds the workload phase when an earlier
> `infrastructure` phase completion receipt for the same exact Plan digest is required but absent.
> Production key lifecycle, physical multi-host infrastructure coordination and operational
> installation qualification remain separate.

A Plan runs as a fenced sequence of phases. The infrastructure agent owns the infrastructure phase,
and the lifecycle agent owns the workload phase. A phase starts only after the previous phase's
receipt is recorded. A failure compensates completed phases in reverse order when the Release
allows it, and otherwise holds the installation for the operator.

1. An agent polls the Hub and verifies the Plan signature, audience, sequence, and generation.
2. The agent verifies the Release and configuration signatures. It rejects a Release older than
   the newest one it applied unless a vendor-signed recall allows the roll-back.
3. The infrastructure agent renders the exact Terraform plan with sealed values decrypted locally.
   The lifecycle agent renders workload manifests.
4. The agent compares the exact change with its locally derived envelope as narrowed by the Plan.
   It refuses any change outside that envelope and holds the deletion or replacement of an existing
   Azure resource for an operator confirmation bound to the same exact plan digest.
5. The agent writes a local lifecycle authorization receipt that binds the exact plan digest to the
   Plan, Release, configuration revision, and open window. That receipt stands in for the
   operator's invocation in the existing exact-plan claim, apply, and verification-only recovery
   stages. The agent reports the digest and a sanitized summary to the Hub.
6. Success requires healthy workloads, a second zero-change plan, and independent readback. The
   receipt is appended to Foundation storage, and the Hub records the result.

The lifecycle agent, the infrastructure agent, and a Target Hub upgrade themselves through two
slots. The new version starts beside the old one, passes health checks, and then takes over. The
old slot stays as the rollback target. `InfrastructureAgent` enforces the Plan envelope and holds
any Azure resource deletion or replacement for an operator `DestructiveChangeConfirmation` bound to
the exact Plan digest before calling the exact-plan coordinator, and `DualSlotUpgradeController`
starts the candidate slot without write authority, rolls back to the old slot on a failed health
check, and transfers fenced write authority only after health and post-handoff readback checks pass.

### Constraints

| Constraint | Set by | Blocks |
|------------|--------|--------|
| Maintenance window, no-downtime or downtime | Customer, in an IANA time zone with the time-zone database version pinned by the Release | Plans whose declared maximum duration doesn't fit inside the remaining window. Overlapping windows of one class merge, and the trusted UTC clock decides. |
| Suppression window | Operator, or automatic after a failure | Plans in its scope. A failure suppression doesn't block the rollback of the failed Plan. |
| Version range | Customer | Releases outside the range |
| Product dependency and schema range | Release metadata | Incompatible upgrades and roll-backs |
| Artifact availability | Installation registry | Plans whose images aren't inside the boundary |
| Override coverage | Customer | Releases without a matching override block |
| Data residency | Environment Config | Releases or model bindings that process data outside the allowed scope |
| Recall | Vendor | Proposing a recalled Release. It also triggers a roll-off. |
| Destructive change | Constitution | Deleting or replacing an existing Azure resource until confirmed |

> **Implemented planning constraint boundary:** `plan_next` evaluates maintenance and suppression
> windows, version and schema ranges, artifact availability, both installation-level and per-Entity
> `EntitySettings` override coverage, data residency, and Release/capability recalls before signing
> a Plan. Timing blocks (`maintenance` and `suppression` windows) hold in `Waiting` without falling
> back to an older Release, whereas non-timing blocks skip ineligible candidates or return
> `NoEligibleRelease`. Physical phase fencing, local authorization receipts, and live installation
> qualification remain separate.

### Failure, drift, and reconciliation

- A failed Plan places an automatic suppression window on its Entity. When failures cross a
  configured threshold, the whole installation is suppressed, as in Apollo. A rollback Plan to the
  previous Release runs when the schema range allows. Otherwise the installation holds for the
  operator.
- Lifecycle drift is a difference between reported state and the desired inputs, such as a manual
  change to a Deployment or Terraform refresh drift. The Hub issues a reconciliation Plan for the
  next matching window.
- The Hub recomputes Plans when reported state, Entity settings, the configuration revision,
  channel membership, or a recall changes, and when a Plan stays blocked past a bounded threshold.

> **Implemented Deployment drift reconciliation boundary:** When no Plan is pending, the lifecycle
> agent compares live in-scope Deployments against the recorded healthy rendering, preserves staged
> `available_artifact_digests`, and reports any drifted Entity as `degraded` with its observed
> image digests. When `plan_next` sees a managed Entity with non-healthy status or artifact digests
> outside the running Release manifest, it holds in `Waiting` outside maintenance windows and
> issues a signed `drift-reconciliation` Plan for the current Release in the next matching window.
> Terraform refresh drift and live AKS qualification remain separate.

### Commands and overrides

Apollo has no runtime-override layer. Its closest concepts are suppression windows, maintenance
window overrides, and break-glass commands. FDAI keeps that split:

| Command | Who | Effect | Expiry |
|---------|-----|--------|--------|
| Suppression window | Lifecycle operator | Stops new Plans in its scope immediately | Required |
| Authority-lowering command | Installation operator | Demotes an ActionType, lowers an autonomy ceiling, or engages the kill switch immediately | Required. The operator gets notice before expiry and can extend it. |
| Break-glass command | Break-glass role with fresh authentication | Applies an emergency configuration change, such as a scale-out, or bypasses a maintenance window, suppression window, or version range | Required. At expiry, the Hub reconciles to the approved Git revision unless a merged change adopted it. |

No command raises authority. A break-glass command can bypass only maintenance windows,
suppression windows, and version ranges. It still passes signature checks, the local envelope, the
exact plan, the lock, idempotency, audit intent, recall, destructive-change confirmation, recovery,
and independent readback. The installation's own kill switch route keeps its existing behavior.

> **Implemented command expiry and break-glass boundary:** `LifecycleCommand` and
> `validate_lifecycle_command` require an explicit expiry on every command (`suppression-window`,
> `authority-lowering`, and `break-glass`) and reject any authority-raising request (`target_mode`
> above `shadow`, `target_autonomy` above `hil`, kill-switch disengagement, or bypasses outside
> `maintenance-window`, `suppression-window`, and `version-range`). While active, a break-glass
> command applies its secret-scanned emergency overrides (`configuration-change` Plan) and bypasses
> only its declared window or version-range constraints while preserving recall, schema, artifact,
> and residency checks. At expiry, `plan_next` reconciles unadopted emergency overrides back to the
> approved configuration revision with a `drift-reconciliation` Plan. Dedicated Hub command HTTP/UI
> routes remain separate.

## Separation from the operations loop

- The lifecycle loop changes only resources it provably owns. Foundation resources require a
  signed creation receipt with a matching Terraform state identity. The
  [native first-creation path](#native-first-creation-of-an-application-workload) separately covers
  newly created workload objects, never their parent namespace. The `fdai:managed=true` tag is
  only a discovery hint, because anyone with tag rights can set it.
- The operations loop never proposes an action that targets a proven FDAI-owned resource, and the
  risk gate denies such a target. Heimdall may still report drift on those resources as advisory
  evidence.
- Lifecycle agents never publish authority-bearing events. Saga may cite lifecycle receipts as
  evidence references only.
- `ProvenFoundationOwnershipRegistry` admits only resources backed by a verified signed Foundation
  creation receipt and matching Terraform state digest, supplying the `deny` signal to `RiskGate`
  for operations-loop targets while keeping manually tagged customer resources (`fdai:managed=true`
  without a signed Foundation receipt) outside FDAI ownership.

## Customer isolation and data residency

| Requirement | How the design meets it | How to verify |
|-------------|-------------------------|---------------|
| Data stays in Korea | Target Hub and installation in Korea Central, and the Hub stores metadata only | Azure Policy allowed locations and reported binding scope |
| No overseas endpoints | Allowlisted catalog sync, or offline bundles | Egress firewall logs and the [network matrix](network-connectivity-matrix.md) |
| Approved model endpoints only | Model-binding allowlist and a residency constraint in Environment Config | Binding validation at startup |
| PTU required | Model bindings with capacity type `ptu` | Settings model inventory |
| Isolated network | Private endpoints, and agents poll a Target Hub inside the boundary | Network matrix scenario |
| No central access to data | Target Hub inside the boundary. Even a central cell holds no operational data and only sealed identifiers. | Hub data model review and audit |

Azure model deployment types differ in where prompts are processed. Global types may use any
region, Data Zone types stay inside a zone such as Asia Pacific, and Standard or Regional
Provisioned types stay inside the resource's geography
([deployment types](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/deployment-types)).
In-country processing with PTU therefore needs Regional Provisioned, which isn't offered for every
model.

### If a Hub is compromised

A compromised Hub can delay upgrades or withhold Plans. It can't widen the effect envelope, forge a
Release or configuration package, replay a Plan to another installation, read sealed values, or
obtain an Azure credential. Agents refuse a version roll-back without a vendor-signed recall, and
expired catalog metadata lowers authority as described in
[Catalog integrity](lifecycle-releases-and-channels.md#catalog-integrity). A compromised cell can't
affect another customer's cell, because each cell has its own key, database, and customer-managed
key.

### Vendor support

Support staff see only the metadata of central cells. A Target Hub's records stay with the
customer unless the customer exports a sanitized support bundle. Access to an installation uses a
time-bound role that the customer grants in its own tenant. The Hub grants none.

## Enrollment and migration

1. An operator creates the Foundation with their own sign-in, as in the other paths, or starts
   from an existing installation. An offline site installs its Target Hub and first Release from
   the signed offline package.
2. The operator installs the lifecycle agent and infrastructure agent from a signed Release.
3. The installation proves possession of its installation key by signing its enrollment request,
   and a customer approver accepts the enrollment by naming the key id they verified out of band.
   Until then the Hub plans nothing for the installation. A request whose proof fails, or whose
   request time differs from the Hub clock by more than five minutes in either direction, creates
   no installation, and the Hub audits why.
4. Entities start unmanaged. An Entity becomes managed only after its ownership is proven and the
   operator adds its settings. A signed Foundation creation receipt together with a Terraform state
   identity proves Foundation ownership. Native workloads use the separate first-creation and
   operator-acceptance path below. The `fdai:managed=true` tag alone keeps the Entity unmanaged,
   and the Hub records that reason. An installation without a managed Entity receives no Plan.
5. The first Plan replaces source-built images, or installs into an explicitly empty workload
   slot, with signed images.

### Empty workload state

An Entity that has never been installed reports `release_id: null`, no installed artifact
digests, and `health: unknown`. This is explicit absence, not an invented deployed version.
The snapshot separately reports `available_artifact_digests` for staged images. Omitting that
optional field retains legacy inventory behavior; an explicitly empty inventory means unavailable.

The planner considers every subscribed Release when a managed Entity is not installed, including
`0.0.0` when that is a real catalog version. Ownership, separate application binding, matching
configuration, artifact availability, signatures, windows and the local envelope remain required.
An ordinary first-install or upgrade Plan never lowers any already installed Entity's version.
Managing an empty slot requires `manage --initial-release <version>` to validate its override
coverage; this does not pin a Plan or bypass candidate checks.

**Critique and revision:** Missing health is not successful installation. Staged images are not
running images, and a fake current version can skip valid first Releases. The explicit null and
separate inventory retain these distinctions. Agent preflight still refuses an existing object
without a recorded rollback target. A failed first apply removes only objects created by that
attempt and independently verifies their absence. This state contract neither adopts a namespace
nor supplies ownership evidence. Native ownership/bootstrap remains a separate prerequisite.

The explicit lifecycle database migration advances its reader floor to 5 before storing null Release
IDs or separate inventory. Revision-4 local channel records, existing rows and snapshot digests remain
unchanged; old binaries refuse the newer database instead of misreading absence.
Serving never migrates a database automatically.

Today the Terraform application stage renders workloads. The Hub path moves the rendering of
namespaced workload objects to the lifecycle agent, as
[Workload rendering migration](#workload-rendering-migration) defines. Terraform keeps Azure
resources, cluster-scoped objects, and authority-granting role bindings.

## Native first creation of an application workload

An existing customer namespace remains unmanaged. A development installation may instead
create and own a new workload-scope anchor, an internal Service without a selector, inside an
independently approved namespace. This is ownership of that new object and the exact workload
objects subsequently created by this installation, not ownership or adoption of the namespace.
Foundation and Terraform evidence remains required for Foundation-owned resources.

### Design, critique and revised boundary

**Initial proposal:** Accept an installation-signed namespace claim as ownership.

**Critique:** Possessing the installation key proves identity, not human approval or creation.
A label, import, successful apply or empty namespace doesn't prove ownership. Apply can adopt
an object created between preflight and mutation. Name-only recovery can delete another
owner's replacement. A namespace name alone doesn't identify a namespace incarnation.

**Revised development contract:**

1. The customer supplies an independent, bounded local approval for the exact installation,
   application, Entity, namespace and component names. It names its approver, validity interval
   and full-authority development profile. A Hub, package, enrollment or Plan cannot supply it.
   Bootstrap is a dry run unless the customer explicitly selects apply.
2. The Agent holds its existing exclusive state lock, checks the independent local application
   policy, re-reads current state and execution history under that lock, performs an API dry run,
   and durably records creation intent before an atomic
   create-only request for the anchor. An existing anchor is a collision, never an adoption.
   Successful creation is independently read back and its API-assigned UID retained.
3. The Agent signs a purpose-specific claim containing installation, Entity and application
   bindings and digests of local scope, approval and actual creation evidence. Namespace names,
   resource UIDs, credentials and private approval values stay in the installation.
4. An authenticated customer operator separately accepts the exact claim with a request UUID,
   current Settings digest, reason and explicit confirmation. The Hub verifies the enrolled
   installation signature and application binding. The transaction rejects managed Entities,
   installed state, open Plans, changed Settings or conflicting retries and appends its audit.
   An Agent identity alone cannot grant Hub ownership.
   Acceptance registers a new unmanaged `native-workload-scope` Entity or binds an existing empty
   Entity of that exact kind; it never converts a namespace Entity. The Agent then reports the
   true empty state before the operator can manage the Entity with initial override coverage.
5. The ordinary signed Plan pipeline performs first installation. Local native execution checks
   the original anchor UID before each operation. Every permitted workload object is created
   atomically, and its actual UID is durably retained before further effects. Updates carry UID
   and resource-version preconditions; deletion carries a UID precondition. Missing, replaced or
   terminating anchors and foreign objects stop execution without adoption.
   Deployment and Service selectors and Pod labels bind the Entity and actual anchor creation
   identity, so a component label alone cannot select foreign Pods or orphan ReplicaSets.
   Health readback verifies those selectors and Pod labels again; terminating workloads cannot
   pass rollout verification even when deletion is already tracked locally.
   UID-capable adapters recheck current local approval at each POST, PATCH and DELETE submission,
   after blocking discovery, owned-object reads and intent persistence. A denied unsent request
   restores only its new local intent; it never clears evidence of an earlier uncertain request.
6. Recovery uses that retained UID history, never a name-only deletion. Uncertain creation,
   failed persistence or conflicting identity requires review rather than a success-shaped
   retry. Existing signed-input, product, window, envelope, dry-run, rollback, replay and
   independent health checks remain required.
   Only a provider-confirmed rejection without creation clears pending intent for retry or
   UID-fenced recovery. Timeouts, lost responses and server failures retain the uncertainty fence.
   A local deadline or approval failure before the create request is sent also clears pending
   intent; no API request has occurred in that case.
   Every apply poll rechecks native versus legacy mode under the exclusive state lock before
   fetching a Plan or recovering a journal; a legacy client composed before bootstrap stops.

The initial surface is limited to application-package Deployments and internal Services.
It adds no namespace, RoleBinding, Azure resource, secret read, database migration execution,
application-specific renderer or production authorization. Explicit Hub schema migration
advances the reader floor to 6 before persisting native evidence; old binaries do not reinterpret it.
For a staged cutover, the new server can serve revision 5 before that explicit migration.
Serving and readiness accept revisions 5 and 6, or explicitly prepared earlier revisions as
described below; native acceptance and explicit schema verification still require revision 6.
Missing, unprepared older and future revisions remain blocked.
Move traffic to the compatible image and drain old readers before advancing the floor.
Before migration, the old image remains a rollback option. After migration, recovery uses a
verified revision-6-compatible image, never a lowered reader floor.
The [implementation ledger](../../roadmap-implementation/deployment/hub-managed-lifecycle.md)
separates source validation, publication, activation and installed qualification.

### Preparing an older Hub without changing its reader floor

**Design and critique:** Serving revision 5 before migration doesn't cover an installation
still on revisions 1-4. Migrating its reader floor first stops the existing server. Merely
allowing the old marker in the new server is also unsafe: required columns may be absent,
and new writes could make rollback unreadable.

**Revised contract:** An explicit Lifecycle Hub `prepare` command applies the existing
additive migrations in one locked transaction, retains the original reader floor, and records
`prepared_revision: 6` in the schema-version table. It never initializes an absent database,
changes application data, accepts ownership, or advances the floor. Preparation is safe to
repeat; interruption rolls back both its structure and preparation record.

SQLite writers begin their real database write transaction before checking preparation metadata
and hold it through the write. A borrowed transaction remains under its caller's control.
After completion, recovery inspection validates and fingerprints both supported version-table
layouts: revision only, or revision plus a nullable integer preparation column. Unknown columns
and incompatible types remain blocked.

Use the existing service-owned migration job for these stages, not a local remote-database DSN:

1. Run `python -m fdai_lifecycle_hub.remote prepare`. Verify that the old server remains ready
   and its reader floor is unchanged.
2. Activate the compatible image. The new server accepts revisions 1-4 only with the preparation
   record. Unprepared older databases remain blocked. New writers refuse configuration,
   catalog and trusted-host writes during preparation. HTTP returns `503 schema_migration_pending`;
   the trusted-host CLI exits unsuccessfully with the explicit migration-pending error.
   Read-only projections and health remain available. Existing binaries retain their reader
   floor and data. Independently verify the image and readiness, then drain old readers.
3. Run `python -m fdai_lifecycle_hub.remote migrate`, then the strict `schema` command. This
   completes the transition to revision 6 without repeating its DDL. Only then may native
   acceptance and other new writes proceed.

Before completion, recovery can restore the old image without lowering a marker. After completion,
recovery uses a verified revision-6-compatible image. Release Hub, unprepared legacy trusted-host
operations and unversioned local development keep their existing contracts.

### Private proof handoff to a trusted Hub host

**Design and critique:** A private proof file inside an installation isn't accessible to a remote
operator. Printing it in logs, copying installation keys, accepting `Agent.Access` as an operator,
or substituting an Azure CLI token for the browser application would weaken existing boundaries.

**Revised contract:** An enrolled Agent may POST its existing `SignedNativeScope` to
`/v1/installations/{installation_id}/native-proofs`. This is transport, not ownership acceptance.
The Hub checks the exact Agent binding, an 8 KiB strict-JSON limit, enrolled signature, application
binding and completed schema 6 before appending an immutable audit entry. Each Entity has one
submitted claim; an identical retry is safe, while a different claim is a conflict. No Entity,
ownership, Settings, Plan or reported state changes. Anonymous callers and other installations
cannot submit, and the Agent cannot read proofs or accept ownership.

`fdai-lifecycle-agent submit-native-proof` sends an existing private `--proof` file over the
workload-identity HTTPS transport. It doesn't bootstrap resources, read keys, accept a Plan or
print the proof. A failed delivery leaves the private file available for a bounded later retry.
The trusted Hub CLI can select `--submitted-proof` by its claim digest for separate operator
acceptance, with the same UUID, Settings digest, reason and exact confirmation as a file request.
Acceptance rechecks the retained proof against current enrollment and application state.
Supply `--request-id`, `--settings-digest`, `--reason`, `--confirmation` and `--operator`;
a file request and a submitted-proof selection cannot be combined. The trusted-host
`bind-application <installation-id> <private-request-file> --operator <actor>` command uses the
same strict request, permanent product binding, Settings compare-and-swap and audit as the API.

When `FDAI_HUB_REMOTE_CONFIG` explicitly selects a remote target, the trusted-host CLI uses the
existing verified-TLS Managed Identity database engine. It rejects a Release Hub configuration or
incomplete schema rather than falling back to a local store or a password. Without that variable,
the existing local database path is unchanged. Remote-mode `serve` is rejected before handler
dispatch; use `fdai-hub-remote serve` for the authenticated server. Console access remains an independent Azure
authorization boundary; an Agent submission never grants console access or operator authority.
No new role, public proof-read endpoint, signing key, database table or reader-floor change is added.

### Local setup and acceptance

1. Bind the installation to its application separately. Supply a private local policy with the
   same `product`, one exact Entity/component mapping and `native_scope_digest`. The digest pins
   the complete `NativeScope` independently of Hub requests. Older Agent binaries reject the new
   policy key instead of silently selecting legacy apply.
2. Supply a separate `fdai.lifecycle-native-approval.v1` file. It contains the exact scope,
   `profile: full-authority-development`, `approved_by`, `approved_at` and `expires_at`.
   Approval lasts at most four hours. Keep the enrolled Ed25519 identity; its private key file
   must be owned by the running user with mode `0600`. Bootstrap never generates a key.
3. Run `fdai-lifecycle-agent bootstrap-slot` with `--installation-id`, `--state-dir`,
   `--local-policy`, `--current-state`, `--native-approval`, `--installation-key` and exactly one
   of `--kube-context` or `--in-cluster`. The default only dry-runs the anchor. Explicit `--apply`
   also requires a private `--proof-output`. It does not install the application.
4. Explicitly migrate the trusted local Hub with `fdai-lifecycle-hub migrate`; remote deployments
   use their explicit migration Job. Prepare a complete `NativeOwnershipAcceptance` request with a UUID, current full Settings
   digest, signed proof, reason and exact `required_confirmation`. Submit it as an authenticated
   operator to `POST /v1/installations/{installation_id}/native-ownership`, or from the trusted
   Hub host with `fdai-lifecycle-hub accept-native-ownership <installation-id> <request-file>
   --operator <actor>`. An unauthenticated loopback HTTP caller and `Agent.Access` cannot accept it.
5. After acceptance and the Agent's empty-state report, manage the Entity with
   `--initial-release`. Stage signed inputs and use the ordinary Plan flow. Native apply requires
   `--native-approval` and `--installation-public-key` in addition to the pinned local policy and
   durable native state. Missing state, missing independent inputs or an unpinned existing native
   state stops apply without a legacy fallback.

The Kubernetes identity needs namespace-scoped `get`, `create`, `patch` and `delete` for the
approved Deployments and internal Services; server-side dry-run uses the corresponding write
verb. Bootstrap adds no permission or role binding. Updates use a UID- and resource-version-bound
JSON Patch rather than field-manager takeover or a new update permission. A lost create response
requires review; a restart can
finish proof generation only when the original API-assigned anchor UID was already persisted.
Existing namespace-level RBAC and pre/post anchor checks are not an atomic namespace-lifetime
transaction. A lost or replaced anchor is never reported as a healthy successful effect.

## Workload rendering migration

This section defines how a Hub-managed installation moves workload rendering from the Terraform
application stage to the lifecycle agent, and how that move is rolled back. The one-command source
deployment and the signed offline package keep the Terraform application stage unchanged.

### Current rendering

The local `operator-service-v1` development slice is narrower than this target design. It uses
the existing signed Release digests and signed configuration to render the actual Operator
Deployment, an internal Service, and a read-only Core-image schema-check Job. It requires an
already migrated database, rejects every schema transition, and switches no workload before the
legacy and service heads match. It creates no Foundation object and adopts no existing object.
The [agent reference](../../../lifecycle/agent/README.md#same-schema-operator-profile) describes
its prerequisites and failure recovery. This is not schema-expand implementation or evidence
of an installed service; the [ledger](../../roadmap-implementation/deployment/hub-managed-lifecycle.md)
keeps those remaining outcomes separate.

The deployment CLI builds a `workloads` map and a `scheduled_jobs` map from substrate outputs,
image digests, and the product profile. It then applies one Terraform root,
`infra/runtimes/aks/workloads`, through the exact-plan claim, apply, and verification-only recovery
stages. That root writes three kinds of objects:

- namespaced Kubernetes objects for each workload and scheduled job;
- cluster-scoped Kubernetes objects and role bindings that grant FDAI identities their reach;
- Azure resources: federated identity credentials, the API Management browser gateway, and its
  network security rule.

### Design and critique

**Initial design:** Run the whole Terraform workloads root inside the lifecycle agent.

**Critique:**

- The root writes Azure resources, but ADR-0003 A11 keeps the Azure write identity on the
  execution host.
- The root creates the namespace and a cluster role. The lifecycle agent holds Kubernetes rights
  in FDAI namespaces only.
- API Management reads its backend address from the external LoadBalancer Services. If the agent
  owned those Services, the infrastructure phase would depend on the workload phase.
- Workload values mix product content, such as images, probes, and security settings, with
  installation identifiers, such as client IDs and endpoints. A Release can't carry the
  identifiers, and the Hub must never see them.
- Removing addresses with `terraform state rm` changes state outside a reviewed exact plan.

**Revised contract:** Split ownership by object kind. The lifecycle agent renders only namespaced
workload objects from three separately signed inputs. Terraform releases and readopts those
objects only through exact plans that use `removed` and `import` blocks.

### Object ownership on the Hub path

| Objects | Scope | Owner |
|---------|-------|-------|
| Deployment, HorizontalPodAutoscaler, PodDisruptionBudget, NetworkPolicy, internal Service, ServiceAccount, SecretProviderClass, CronJob, and the identity-bridge ConfigMap | FDAI namespace | Lifecycle agent |
| External LoadBalancer Services for the Operator API and the Document Ingestion API | FDAI namespace | Infrastructure agent, because API Management binds to their addresses |
| Executor external-scale Roles and RoleBindings | Exact target namespaces outside FDAI | Infrastructure agent, because they grant authority |
| Namespace, and the inventory-reader ClusterRole and ClusterRoleBinding | Cluster | Infrastructure agent |
| Federated identity credentials, the API Management browser gateway with its APIs and operations, and its network security rule | Azure | Infrastructure agent |

The lifecycle agent never creates or changes a role binding, so a workload apply can't widen any
identity's reach.

Two rules keep the lifecycle agent from fighting another writer over the same field:

- **No Executor effects inside the FDAI namespace.** On the existing paths, the isolated Executor
  can patch and scale Deployments and delete pods in the FDAI namespace. On the Hub path, the
  infrastructure agent doesn't bind that role, because the lifecycle agent would revert those
  changes and the operations loop must not target FDAI-owned resources, as
  [Separation from the operations loop](#separation-from-the-operations-loop) requires. As a result,
  Kubernetes ActionTypes such as pod restart and Deployment scale aren't available against FDAI's
  own workloads on the Hub path. Executor scale targets in other namespaces are unchanged.
- **The autoscaler owns the replica count.** When a workload has a HorizontalPodAutoscaler, the
  agent omits `spec.replicas` from the Deployment it applies, as the Terraform root does today with
  `ignore_changes`. Replica override values set the autoscaler's minimum and maximum instead.

### Render inputs

The lifecycle agent renders from three inputs. Each has its own signer and its own visibility.

| Input | Content | Signed by | Hub sees |
|-------|---------|-----------|----------|
| Workload template in the Release | Images by component, commands, ports, probes, security context, sidecars, default sizing, and environment keys with their value sources | Vendor release key | Digest |
| Entity override values | Replicas, CPU, and memory inside the template's bounds | Customer configuration key | Value |
| Installation binding | Identity client and resource IDs, the container registry login server, Kafka and PostgreSQL endpoints, Event Hubs topic names, the Key Vault name, secret names, the installation and license bindings, and sealed identifiers decrypted locally | Installation key | Digest only |

The infrastructure agent writes the installation binding inside the installation after its phase.
It combines the outputs of its own Terraform roots with the sealed identifiers that it decrypts from
the configuration package, as [Lifecycle Configuration](lifecycle-configuration.md#value-classes)
defines. Each environment entry in the template declares its
value source: a literal, a configuration key, or a binding key. The renderer rejects an unknown key
and any other value source, so a template can't carry an endpoint and a Plan never needs a binding
value.

### Phases of an upgrade Plan

1. **Infrastructure:** The infrastructure agent applies only additive and in-place changes to Azure
   resources, cluster-scoped objects, role bindings, and external Services, and creates a federated
   identity credential for every workload and job in the target Release. It then writes the
   installation binding and its receipt.
2. **Schema expand:** The Release ships its database migration as a Kubernetes Job template that
   uses the Core image, which already contains the migration and catalog tools. The Job runs the
   legacy migrations, the service-owned migrations in their declared order, and the authoritative
   catalog materialization, as the managed host's migration step does today. It runs only the
   revisions that the Release classifies as expand, and it rejects a revision that drops or renames
   schema. Contract revisions run in a later fenced Plan after the restore checkpoint that
   [Lifecycle Releases and Channels](lifecycle-releases-and-channels.md#schema-compatibility)
   requires. Only revisions added after an installation's enrollment baseline need a
   classification, because earlier revisions are already applied. Some existing upgrades drop
   tables, so a Hub-managed upgrade runs no new revision without one. The existing migration locks
   are separate transaction locks per step, and catalog materialization has none, so the Job holds
   one installation-wide migration lease across all three steps and its receipt. The lifecycle agent
   runs the Job in the FDAI namespace with a dedicated migration identity before any workload
   switches.
3. **Workloads:** The lifecycle agent renders the objects, compares them with its locally derived
   envelope, and applies them with server-side apply under its own field manager.
4. **Verify:** Both agents require healthy workloads, a second zero-change render, a zero-change
   plan for the remaining Terraform roots, and independent readback.
5. **Infrastructure cleanup:** After readback shows that the workloads a target Release dropped are
   gone, the infrastructure agent removes the external Services, API Management routes, role
   grants, and federated identity credentials that served them.

A workload that is new in a Release receives its federated identity credential in phase 1, before
its pod exists in phase 3. On the existing paths, the managed host keeps running migrations
directly before the application stage.

### Ownership handoff for an existing installation

An enrolled installation moves its workload objects to the lifecycle agent in four steps. Each step
needs a local lifecycle authorization receipt, and no step deletes or recreates a running object.

Two exact plans prepare the handoff and run before step 1:

- **Split the Service resource.** A Terraform `removed` block addresses a whole resource without
  instance keys, but internal and external Services share one resource block today. A refactor
  with `moved` blocks splits it into an internal and an external Service resource. It applies on
  every installation path as a zero-change plan.
- **Remove the Executor role from the FDAI namespace.** On the Hub path, a separate plan destroys
  the Executor Kubernetes-effect Role and RoleBinding in the FDAI namespace. It lowers authority, and
  it's the only destroy that the handoff allows.

1. **Shadow parity:** The agent renders the objects and compares them with the live objects without
   writing. Differences that come only from server defaults and binding order are normalized. The
   step passes after the configured number of consecutive zero-difference reports.
2. **Release from Terraform:** The infrastructure agent applies an exact plan of the Hub variant
   of the workloads root, which the Release ships. A `removed` block requires its resource block to
   be absent, so that variant replaces each agent-owned resource block with a `removed` block with
   `destroy = false`. Terraform 1.7 and later support these blocks, and the pinned toolchain is
   1.9.8. The plan must show no destroy and no update.
3. **Adopt:** The agent applies the same render with server-side apply under the
   `fdai-lifecycle-agent` field manager. It forces conflicts only on fields that the Terraform field
   manager owns, and stops on any other conflict. It adopts one object at a time and records a
   per-object receipt with the object UID, resource version, and render digest, so an interrupted
   adoption resumes from the last receipt. Each object records the Release ID and render digest in
   annotations.
4. **Verify:** A second render shows zero changes, workloads stay healthy, and the remaining
   Terraform roots plan zero changes.

After step 2, the installation records a local Hub ownership marker. Every deployment CLI entry
point that would plan the full workloads root refuses to run or uses the Hub variant, including the
ordinary application stage, per-service update, and historical reconciliation. So Terraform and the
agent never write the same object.

**Rollback:** First, the agent stops reconciling the adopted objects, releases its reconciliation
lease, and records the release. Then the infrastructure agent applies an exact plan with `import`
blocks for the same addresses, and a following zero-change plan proves that Terraform state matches
the live objects. A failure in step 2 or 3 changes at most field ownership and annotations on
already adopted objects. It never deletes or recreates a running object, so rollback never needs a
recreate.

### Render parity

Until a single renderer exists, the Terraform root and the lifecycle agent implement one workload
template contract. A focused test feeds the same input matrix to both renderers and compares the
planned Terraform values with the agent output. The matrix covers product profiles, add-ons, the
identity bridge, and executor scale targets. The comparison reuses the deployment CLI's existing
rules that drop Kubernetes server defaults and normalize secret-provider bindings. It also checks
the protected CronJob template digests, and that the selectors of the infrastructure agent's
external Services match the pod labels that the agent renders. Any difference fails the test.

On the Hub path, the one-shot Job execution that runs catalog review and the initial inventory
derives its protected CronJob template digests from the agent's render receipt instead of from
Terraform input.

### Decisions on earlier open questions

The Hub-managed lifecycle owner decided these points on 2026-10-07.

- **Migration identity:** The schema-expand Job runs under a dedicated migration ServiceAccount and
  managed identity that no workload shares. In the MVP, that identity reads the same Key Vault
  database secret that the managed host's migration step uses today. That secret holds the server
  administrator login, because migrations create service roles and backfill data. A later change
  replaces it with a dedicated migration database role that has only the privileges migrations
  need, after object ownership moves from the administrator to that role.
- **One renderer:** The Terraform root and the agent renderer both stay, behind the render parity
  check, until the MVP is validated. After that, the Terraform workloads root applies the
  agent-rendered manifests, so every installation path uses one renderer and the parity check
  retires.

### Open questions

- Which component runs the post-deployment steps that the managed host runs today after the
  application stage: Trial activation, the initial inventory, and catalog review.
- How the infrastructure agent keeps running when the execution host uses the optional daily
  auto-shutdown (`runner_auto_shutdown_time`).
- Which agent owns the in-cluster PostgreSQL namespace when an installation selects the
  `postgres-aks` database placement.

## Example installations

| Setting | Customer A | Customer B | Customer C |
|---------|------------|------------|------------|
| Hub | Online or offline Target Hub in Korea Central | Central Hub cell in East US | Central Hub cell or Target Hub |
| Channel | `RELEASE`, or a custom channel with manual promotion | `RELEASE_CANDIDATE` | `RELEASE` with range `>=1.4.0 <1.5.0` |
| Windows | Weekly downtime window and nightly no-downtime window | Daily windows | As agreed |
| Model | Regional Provisioned PTU on approved endpoints | Standard pay-as-you-go | Self-hosted model reachable from Azure through API Management |
| Governance | Policy holds every state change for approval | Single-operator production profile with operator-promoted actions and standing authorization | Per-execution approval |

[Lifecycle Configuration](lifecycle-configuration.md#examples) shows the configuration for these
installations. Customer C's on-premises runtime and local model need separate approval and an ADR.

## Hub data model

| Table | Key | Purpose | Time fields | Mutability |
|-------|-----|---------|-------------|------------|
| `installation` | `installation_id` | Enrollment status and installation key, Hub placement, channel, version range, windows | `requested_at`, `enrolled_at`, `recorded_at` | Revisioned |
| `entity` | `installation_id`, `entity_id` | Kind, ownership evidence, settings revision. An Entity with settings is managed | `effective_from`, `recorded_at` | Revisioned |
| `entity_reported_state` | `installation_id`, `entity_id`, `observed_at` | Version, digests, health, agent sub-state | `observed_at`, `recorded_at` | Append-only |
| `lifecycle_plan` | `plan_id` | Type, target Release, configuration revision, envelope, expiry | `created_at`, `issued_at`, `expires_at` | Status changes in `lifecycle_plan_event` |
| `plan_evaluation` | `evaluation_id` | One recompute: outcome, target Release, and the issued Plan if any | `evaluated_at` | Append-only |
| `plan_constraint_result` | `evaluation_id`, candidate Release, `constraint` | Result and reason | `evaluated_at` | Append-only |
| `plan_execution_report` | `plan_id`, `attempt` | Exact plan digest, sanitized summary, outcome | `reported_at` | Append-only |
| `lifecycle_command` | `command_id` | Suppression, lowering, or break-glass command with scope and actor | `starts_at`, `expires_at`, `recorded_at` | Revocable |
| `hub_audit` | `sequence` | Hash-chained record of every Hub change | `recorded_at` | Append-only |

A recompute that waits or finds no eligible Release issues no Plan, so constraint results belong to
the evaluation rather than to a Plan.

Release tables belong to [Lifecycle Releases and Channels](lifecycle-releases-and-channels.md), and
configuration tables belong to [Lifecycle Configuration](lifecycle-configuration.md).

## Honest limits

- Only the Lifecycle Hub's enrollment, Plan computation, storage, and agent API run today, in
  observation mode (shadow mode) on loopback ([Lifecycle Hub](../../../lifecycle/hub/README.md)).
  Everything else in this document is design only.
- Full workload rendering outside Terraform is designed in
  [Workload rendering migration](#workload-rendering-migration). The same-schema Operator
  development slice doesn't implement the full renderer, render parity, or ownership handoff.
- In Lifecycle I0, a failed apply doesn't produce a separate rollback Plan. The agent restores the
  previous images within the failed Plan and reports `rolled-back`. The Hub then holds each Entity
  of that Plan with a 24-hour failure suppression, which an operator can lift earlier. The
  installation-wide failure threshold isn't implemented.
- [Self-upgrade failure analysis](hub-managed-lifecycle-self-upgrade.md) defines the slot/fence,
  data-compatibility and recovery obligations. The controllers and operational drills remain unimplemented.
- [Entitlement continuity](hub-managed-lifecycle-entitlement.md) selects installation-local licensing
  authority and transport-only Hub mediation. The carrier/handoff remains unimplemented; upgrades never renew a Trial.
- Offline installations receive recalls only when an operator imports the next bundle.
- The Hub path supports AKS only, and on-premises runtimes are out of scope.

## Related docs

| To learn about | Read |
|----------------|------|
| Decision record | [ADR-0003](../architecture/decisions/0003-hub-managed-lifecycle-and-operator-governance.md) |
| Self-upgrade failures and recovery | [Failure analysis](hub-managed-lifecycle-self-upgrade.md) |
| Entitlement and Trial continuity | [Entitlement decision](hub-managed-lifecycle-entitlement.md) |
| Configuration layers, packages, and secrets | [Lifecycle Configuration](lifecycle-configuration.md) |
| Releases, channels, bundles, and recall | [Lifecycle Releases and Channels](lifecycle-releases-and-channels.md) |
| Approval profiles and policy administration | [Operator Governance Profiles](../decisioning/operator-governance-profiles.md) |
| Existing installation paths | [One-Command Source Deployment](source-deployment.md), [Disconnected Deployment](disconnected-deployment.md) |
| Exact-plan apply and recovery | [Installable Deployment CLI](installable-deployment-cli.md) |
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/deployment/hub-managed-lifecycle.md) |
