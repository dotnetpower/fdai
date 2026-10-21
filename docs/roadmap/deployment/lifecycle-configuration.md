---
title: Lifecycle Configuration
---
# Lifecycle Configuration

This document defines how an installation's desired lifecycle configuration is authored, layered,
packaged, and delivered to a Lifecycle Hub. It also keeps that configuration separate from
customer identifiers, secrets, policy, and authority. It owns the value classes, the configuration
layers, and the signed configuration package.

> **Status:** Schema, layer and secret-reference validators, an offline signed package builder and
> reader, a local single/multi-Entity packaging/verification CLI, installation-key sealing and
> explicit in-memory Hub planning consumption are implemented, together with a placeholder repository
> template and key-custody runbook. Authenticated public-key registration/rotation and durable
> key-bound Hub planning, atomic signed-package import, independent scope/change approval and
> durable activated-revision consumption are implemented for local verification. The existing
> installation Agent entry point also consumes full v2 artifacts with local decryption and
> per-Entity rendering, and has a read-only CSI metadata adapter. Actual onboarding
> and operational Agent delivery remain open. The
> [implementation ledger](../../roadmap-implementation/deployment/lifecycle-configuration.md)
> tracks delivery.
>
> **Scope:** [Hub-Managed Lifecycle](hub-managed-lifecycle.md) owns how the Hub uses this
> configuration. [Operator Governance Profiles](../decisioning/operator-governance-profiles.md)
> owns approval and admission policy, which are never configuration.

## Design at a glance

| Concern | Decision |
|---------|----------|
| Source of truth | A customer-owned Git repository. A reviewed merge is the change request. |
| Delivery | One signed configuration package per merged revision. It carries the full revision and names its predecessor. |
| Layers | Release defaults, then Environment Config, then Entity override blocks per Release version range |
| Missing override | A Release without a matching override block isn't deployed |
| Customer identifiers | Sealed to the installation key. The Hub stores only ciphertext and digests. |
| Secrets | Key Vault references only. Managed identities replace credentials wherever Azure allows it. |
| Authority | Never configuration. Policy revisions and the promotion registry own it. |

## Value classes

Every value an installation needs belongs to exactly one class. The class decides who owns it,
where it lives, how it changes, and what the Hub can see.

| Class | Examples | Owner | Stored in | Changed through | Hub sees |
|-------|----------|-------|-----------|-----------------|----------|
| Lifecycle configuration | Region, channel, windows, sizing, replicas, model capacity type, integration kinds | Customer | Customer Git, then the configuration package | Reviewed merge | Value |
| Sealed identifier | Tenant ID, subscription ID, resource names, endpoint URLs, client IDs | Customer | Sealed section of the package | Reviewed merge | Ciphertext and digest |
| Secret reference | Name of a Key Vault secret for an API key or integration token | Customer | Package for the name, Key Vault for the value | Merge for the name, Key Vault for the value | Name only |
| Policy revision | Approval policy, admission (OPA/Rego) policy | Installation operators | Installation PostgreSQL | Console policy administration | Digest only |
| Authority state | Promotion state, standing authorizations, kill switch, approval profile | Installation governance | Installation stores | Governed authority paths | Digests and counts |
| Runtime state | Reported state, receipts, operational data | Installation | Installation | Not configurable | Lifecycle metadata only |

Each configuration key in a Release's configuration schema declares its
[ADR-0002](../architecture/decisions/0002-independent-runtime-axes.md) axis and owner through
`x-fdai-axis` and `x-fdai-owner` annotations. The packager rejects a key without both annotations.
It also rejects any key on an authority axis, such as action lifecycle, approval profile,
authorization policy, or standing authority.

### Release schema admission design and critique

Runtime Release v3 can carry an optional `configuration_schema` object with exactly `format`
(`fdai.release-configuration-schema.v1`), `release_version`, `schema_sha256`, and `keys`.
`keys` uses the existing `x-fdai-axis`, `x-fdai-owner`, and optional `default` vocabulary.
Both annotations are explicit, and the configuration owner is `customer`. Unknown metadata,
blank or unknown owners, unsupported or authority axes,
and authority-state keys are not accepted. `schema_sha256` pins the canonical `keys` bytes.
The complete object is inside the existing manifest digest and detached signature.

**Critique and revision:** A schema beside a manifest, a caller-selected key, or a digest returned
with a download cannot establish Release trust. Release Hub registration and publication validate
the schema and its exact Release version. Lifecycle Hub admission first verifies the separately
approved export pin and existing manifest signature, then validates the same schema/version binding.
It exposes the accepted schema on that exact Release, not as an independent trusted schema file.
Before issuing a Plan, the existing Hub planner compares the installation configuration's schema
digest with this Release schema. A mismatch blocks that candidate. Publication also rechecks the
persisted draft's manifest digest before signing, so changed draft bytes cannot reuse its identity.
No signing key, channel membership, or local packaging result grants production eligibility.

This is an authority-neutral development capability, not a production root ceremony. Missing
metadata means configuration-schema capability is unavailable for that Release. Legacy Releases
remain readable, and source and offline installation gain no new prerequisite. Production Release
qualification, configuration import, Agent delivery and customer-key registration remain separate.

## Where common items belong

| Item | Class | Where it lives | Notes |
|------|-------|----------------|-------|
| Azure region | Configuration | Environment Config | Feeds the data-residency constraint |
| Subscription ID | Sealed | Environment Config, sealed section | The installation also proves it from its own binding |
| Resource group | Sealed | Environment Config, sealed section | Names follow [resource conventions](deployment-resource-conventions.md) |
| Model endpoint | Sealed | `endpoint_ref` in the model binding, resolved inside the installation | The Hub never sees the URL |
| Model and deployment name | Configuration | Model binding | Not a secret |
| PTU | Configuration | Model binding with capacity kind `ptu` and a unit count | The Settings model inventory confirms it |
| Tenant ID | Sealed | Environment Config, sealed section | An identifier, not a secret |
| Client ID | Sealed | Entity override block | Prefer a managed identity with no client secret |
| Client secret | Secret | Avoid it. If an integration requires one, store it in Key Vault and reference it by name. | The customer rotates it |
| API key | Secret | Key Vault secret referenced by name | Runtime T1 and T2 model bindings use Microsoft Entra ID, not keys |
| Database connection | Derived | Built inside the installation from a managed identity and a private endpoint | Service-owned DSNs keep no password |
| ITSM endpoint | Sealed | Integration binding | Its credential is a separate secret reference |
| OPA policy | Policy revision | Installation policy store through FDAI Console | The Release ships the baseline |
| Approval policy | Policy revision | Installation policy store through FDAI Console | The approval profile inside it is authority state |

## Configuration layers

The installation resolves its effective configuration in this order:

1. **Release defaults:** The configuration schema and default values that ship inside the signed
   Release.
2. **Environment Config:** Values that apply to the whole installation, such as region,
   residency, network profile, and model bindings. Installation settings, such as the channel,
   version range, maintenance windows, and Entity list, travel in the same package.
3. **Entity override blocks:** Values for one Entity and one Release version range. The most
   specific range that contains the target Release wins, as in
   [Apollo config overrides](https://www.palantir.com/docs/apollo/managing-entities/set-config-overrides).
   An Entity override can reference an Environment Config key.

A later layer replaces a key from an earlier layer. The packager validates the result against
the target Release's configuration schema and rejects unknown keys, authority keys, and sealed keys
outside the sealed section. When no override block covers a Release's major version, that Release
isn't deployable for the Entity. This rule lets a customer decide in advance which major versions
it accepts.

The initially proposed five layers map onto this model as follows:

| Proposed layer | Where it goes |
|----------------|---------------|
| Product defaults | Release defaults |
| Environment configuration | Environment Config and installation settings |
| Customer policy | Policy revisions, never configuration |
| Entity configuration | Entity override blocks |
| Runtime override | Commands with an expiry, not a configuration layer |

## Customer Git and configuration packages

The customer keeps one directory per installation in its own Git repository:

```text
installations/<installation-id>/
  installation.yaml   # channel, version range, maintenance windows, Entities
  environment.yaml    # Environment Config values that the Hub may read
  sealed.yaml         # identifiers and endpoints, sealed during packaging
  entities/
    core.yaml         # Entity override blocks by Release version range
```

The repository stays inside the customer's control, so `sealed.yaml` can hold readable values
there. Sealing protects those values from the Hub, not from the customer.

1. A reviewed merge to the protected branch starts packaging in the customer's pipeline or
   through `fdaictl`.
2. The packager validates every layer, encrypts the sealed section to the installation's public
   key from enrollment, and records the revision ID, Git commit, predecessor digest, and content
   digests.
3. The customer configuration key signs the package.
4. The package is uploaded to the Hub, or carried inside an upgrade bundle for an offline Target
   Hub.
5. The Hub verifies the signature and the predecessor digest. A missing or forked revision blocks
   the import until the gap is resolved.
6. The Hub recomputes Plans. Installation agents verify the signature again and decrypt sealed
   values only inside the installation.

A configuration rollback is a revert commit that produces a new revision. An older package is
never imported again as the current revision. A break-glass change is reconciled to the approved
revision when it expires, unless a merged change adopted it.

## Offline package boundary and design review

The deployment CLI library owns the offline package builder and reader. A canonical JSON
manifest binds the complete existing `schema`, `environment`, and `entity_overrides` document,
the target Release version, full Git revision, predecessor package digest, installation encryption
key digest, and sealed identifiers. A detached Ed25519 customer signature covers the exact
manifest bytes. This container does not replace the existing Hub/Agent configuration input
contract; importing it and extracting independently verified inputs requires a separate integration.

The reader receives the trusted Release schema and customer verification key from its caller,
not from the package. The caller also supplies the trusted sealed-key classification, so a package
cannot reclassify an identifier as public configuration. It validates every layer, including
nonmatching overrides and defaults,
before signing or accepting a package. Missing coverage holds packaging. The caller supplies the
complete previously accepted chain: gaps, competing children, reused revisions, and reordering
are rejected. Retrying the same revision with identical inputs returns the original signed bytes,
including the original randomized ciphertext. Durable storage and atomic chain-head updates
remain the importer's responsibility.

Identifiers use an installation-owned X25519 encryption key, HKDF-SHA256, and authenticated
AES-256-GCM encryption. The enrollment Ed25519 identity key is a signing key, not an encryption
key; it is never converted or reused. Enrollment still needs to bind the encryption public key
to the installation before operational use. Plaintext values are scanned for secret-bearing
fields before encryption and signing, and package metadata contains only ciphertext and digests.

Design critique and revision (2026-10-21): accepting an embedded schema would let a customer
mislabel authority keys; the reader therefore requires an independently supplied schema.
Randomized sealing would otherwise produce multiple packages on retry; verified history and an
input digest preserve exact retry bytes. Caller-supplied history alone cannot prevent concurrent
writers, so this offline library makes no durable import or operational delivery claim.
Equivalent override intervals are ambiguous even when their comparator order differs. Defaults
cannot bypass the sealed-section boundary.

The implementation is in `fdai_deployment_cli.lifecycle_configuration_package` and
`fdai_deployment_cli.lifecycle_configuration_sealing`. The existing single-Entity configuration
document remains unchanged. The full multi-Entity source path is defined below. Actual encryption-key
onboarding and Agent transport/decryption integration remain open. The bounded atomic Hub importer
below owns source persistence separately from the offline library.

### Full multi-Entity revision design and critique

The authority-neutral `fdai.lifecycle-configuration-package.v2` format keeps the v1 signed
envelope fields and cryptography and adds the exact `release_digest` of the Release manifest.
Its `configuration` contains `schema`, `environment`, and
an `entities` array. Each entry has exactly `entity_id` and `entity_overrides`. Entries are
sorted by `entity_id`; duplicates and noncanonical ordering are not accepted.
Package `entity_id` carries an opaque 64-character lowercase hexadecimal binding supplied
independently by the installation, never a customer name, resource ID or hash of a customer name.
This binding identifies configuration; it proves neither ownership nor permission.

The Hub's existing enrolled Entity identifiers are a different vocabulary (up to 63 lowercase
letters, digits and hyphens). They remain unchanged in enrollment, storage and signed Plans.
The transient planner candidate requires the exact installation identifier and an independently
supplied one-to-one mapping from its already-managed Entity identifiers to package bindings.
Both mapping sets are checked without deriving opaque bindings from customer names. Missing,
duplicate or foreign-installation mappings hold; the package cannot supply its own trusted map.
This is an explicit source-composition input, not durable key/mapping enrollment or Hub import.

Each selected Entity independently resolves the same exact Release schema and Environment Config
with its own most-specific override. Missing coverage, ambiguous intervals or an unknown key in
any block blocks the whole revision. Common sealed inputs are overlaid only by that Entity's
sealed inputs. Every resulting identifier map has exactly the independently classified sealed
keys. One authenticated encrypted object maps opaque Entity bindings to their complete identifier
maps. The customer signature and encryption context cover the entire revision and Entity mapping.

**Critique and revision (2026-10-21):** A signed list alone cannot prove completeness, and a
valid child package could otherwise be relabeled for another Entity. The reader therefore requires
the exact independently selected Entity set, Release version and manifest digest, verifies one whole signed
document, and binds all Entity mappings into authenticated encryption. A package cannot supply
its own trust, classification or selection. A version alone cannot distinguish two manifest builds.
Ordering is canonical before the retry input digest;
the complete existing predecessor chain, including legacy v1 ancestors, remains authoritative.
The legacy reader refuses v2 rather than treating the first Entity as a single-Entity result.

Compatibility and intentional rejection changes:

- Existing v1 package bytes and the legacy CLI input shape remain supported. Selecting the new
  format is explicit; it never upgrades local Release eligibility.
- Both formats reject crossing matching intervals without one uniquely most-specific interval.
  Equivalent intervals remain duplicates even if comparator order differs.
- Only the current chain head can be retried. Building an already superseded Git revision is
  rejected rather than returning an obsolete artifact. A revert uses a new Git revision.
- A full revision contains 1-256 Entities and the complete accepted history contains at most
  256 packages. Missing, extra or duplicate bindings never truncate to an accepted subset.

The existing Hub upgrade planner can consume this candidate through explicit caller-supplied verification
inputs and the exact catalog Release schema. It checks coverage for every already-managed Entity,
binds the Plan to the package digest, and retains ownership, recall, envelope and timing checks.
This in-memory consumption does not enroll a key, import or persist configuration, or change
production eligibility. Atomic Hub import is the separately governed source path below. Actual key
onboarding, Agent transport, CSI secret resolution and production qualification remain open.
This source API does not implement
persisted same-Release configuration-change scheduling.

### Local packaging and verification commands

Use `fdaictl configuration build` and `fdaictl configuration verify` for explicit local files.
Neither command contacts a Hub, Azure, a model or a key provider. Both require independently
supplied Ed25519 verification and X25519 encryption public keys as PEM files. Building additionally
reads an unencrypted PKCS8 Ed25519 signing-key file and checks it against the verification key.
Supply file paths only, never key bytes or identifier values in arguments. All input files use
absolute paths, current-user ownership, mode `0600` and one link, in mode-`0700` private directories.
Symlinks, nonregular files and unsafe parent directories are not accepted.

For legacy single-Entity packages, the private `--release-input` JSON object contains exactly
`release_version`, `configuration_schema` (the annotated key map), and `sealed_keys` (a unique array of identifier
key names). Obtain these inputs independently of the package; supplying a file does not qualify
a production Release or register trust. The private `--input` JSON object contains exactly
`revision_id` (the full Git commit), `environment` (an object), `entity_overrides` (an array of
`versions`/`values` blocks), and `sealed` (the identifier object). These existing inputs produce v1.

For a full multi-Entity revision, add exactly `entity_ids` and `release_digest` to the independent
Release input. `entity_ids` is a unique array of the opaque bindings selected by the installation;
`release_digest` is the exact Release manifest's SHA-256. These local inputs still establish no
Release or key trust. The configuration input contains exactly `revision_id`, `environment`,
`sealed`, and `entities`. Each Entity contains exactly `entity_id`, `entity_overrides`, and
`sealed`. Common sealed values are overlaid separately by each Entity's sealed object; every
result must cover the trusted sealed keys exactly. The CLI builds v2, then independently reads it
against the supplied full selection, Release version/digest, schema, keys and accepted chain before
publishing the private file. A legacy/multi-Entity shape mixture is not accepted.

```bash
fdaictl configuration build \
  --release-input /private/release-input.json \
  --configuration-key /private/configuration-public.pem \
  --installation-key /private/installation-encryption-public.pem \
  --input /private/configuration-input.json \
  --signing-key /private/configuration-signing.pem \
  --initial-revision --destination /private/configuration-package.json --output json
fdaictl configuration verify \
  --release-input /private/release-input.json \
  --configuration-key /private/configuration-public.pem \
  --installation-key /private/installation-encryption-public.pem \
  --initial-revision --package /private/configuration-package.json --output json
```

`--initial-revision` explicitly asserts an empty accepted chain. For later revisions, replace it
with `--expected-predecessor <independently-retained-head-sha256>` and repeat `--history <file>`
for the complete accepted chain, oldest first (at most 256 packages). Missing history, a wrong
head, forks, reordered revisions and attempts to make an old revision current are blocked.
Retrying the current revision with identical inputs preserves the signed bytes.

The destination is a new mode-`0600` file and is never overwritten. The
`fdai.lifecycle-configuration-file.v1` JSON container has exactly `format`, `payload`, and
`signature`; the last two are strict base64 of the existing signed manifest and detached
signature. The reader verifies schema, classification, expected Release version, signature and
chain before build publication or verification success. Build success also requires exact file
readback. Results expose a digest and verification state, never configuration or key values;
errors omit input-derived diagnostics. Success means a verified local artifact only.

CLI critique and hardening (2026-10-21): separate payload and signature output files could expose
a partial artifact, so the CLI writes one closed container. Deriving trust from the signing key
would self-admit it, so a separate verification-key input is mandatory. Explicit empty-chain or
retained-head assertions prevent accidental history omission; they cannot prove that the caller
supplied the latest durable head or serialize concurrent builds. Qualified Release admission,
key registration/rotation, atomic Hub import and activation remain separate governed work.

## Installation Agent consumer: design and critique

This source increment extends the existing `fdai-lifecycle-agent poll-once` artifact path.
It does not enroll an installation, distribute keys, activate a revision, or add an apply mode.
The configuration remains subordinate to the signed Plan and installation-local hard policy.

### Compatibility and independent inputs

- The existing Agent accepts a complete `fdai.runtime-release.v3` manifest, not a Release Hub
  export or an offline kit. That manifest has no top-level semantic Release ID. For v2
  configuration, the independently verified manifest's `configuration_schema.release_version`
  binds the Plan's Release ID; its canonical digest binds the manifest. Without that optional
  schema capability, the full-revision consumer holds instead of guessing compatibility.
- `configurations/<package-digest>.json` can contain the unchanged
  `fdai.lifecycle-configuration-file.v1` container produced by `fdaictl configuration build`.
  The digest names its original signed payload, not the wrapper. Legacy flat documents and
  detached `.sig` files keep their existing path. Container inputs use private-file readers.
- The existing local configuration verification key remains independent of package bytes.
  An optional private `--configuration-binding` input pins the installation, active package
  digest, one-to-one map from already-managed Entity IDs to opaque bindings, sealed-key names,
  and the complete ancestor digests with their historical public-key files and recipient
  digests. An independent private `--installation-encryption-key` is X25519, never the
  installation's Ed25519 identity. Neither file is obtained from the artifact directory or Hub.
  This is a local provisioning input, not a new approval workflow or proof of production trust.
  The existing Hub independent import/change approval and signed Plan admission remain required.

### Verification, rendering and privacy

Before preparing any change, verify Plan admission, exact active package digest, full Entity
coverage, current independent signer/recipient, complete ordered history with acceptance-time
keys, exact Release version/manifest/schema, and authenticated sealed identifier coverage.
Missing bindings, encryption input or schema capability produce retryable unavailable outcomes;
invalid or substituted bytes are rejected without prepare, journal or cluster effects.

Resolve every Entity separately. Regions intersect the existing local/Release envelope for
every selected Entity. Only the existing demo and same-schema Operator renderer shapes are
supported; configuration cannot supply a namespace, image repository, component ownership,
capability mode or grant. The demo profile may set bounded replicas independently per Entity.
Operator profile checks run on its own Entity values. Cross-Entity object-name collisions hold.
Sealed identifiers are available only to the installation's in-memory render inputs; only
supported reference fields reach rendered objects. Rendered private references require a private
installation journal. Reports, current-state snapshots and logs never contain decrypted values.
The existing dry run, lock, two-phase reports, rollback, deadline and restart journal remain.

### CSI reference state

A separate read-only Agent command reads exactly named `SecretProviderClassPodStatus`, Pod and
`SecretProviderClass` objects through the existing Kubernetes mechanical transport, bounded to
one namespace. Independently supplied references pin Entity, Pod UID, class, object ID and
expected secret version. The adapter never requests a Secret or mounted file.
Provider status and resource versions are source-attributed reports, not independent proof that a
secret value is usable. Missing bindings/source yield unavailable; absent timestamp yields unknown;
old timestamps yield stale; differing Pod/class/Entity/version yields conflict. Even a fresh
`mounted` report is only reported state, never operational secret-resolution qualification.
Tests with synthetic objects demonstrate wiring only, not real Key Vault or CSI operation.

### Critique and revision before implementation

Parsing v2 as the legacy flat document would silently lose Entity isolation. Reusing the first
Entity's values or inferring trust from a wrapper key would widen authority. Therefore exact
independent coverage and per-Entity rendering are required, and the wrapper contains no key.
Revalidating ancestors with today's recipient/signer breaks rotation, so each ancestor retains
its own verification binding without current permission. A signed configuration is not a
change approval: the signed admitted Plan and the independently retained active digest remain
separate prerequisites. File presence and CSI `mounted=true` cannot establish secret resolution;
the reader retains reported-only provenance and never opens secret data. Existing journals can
contain rendered reference names, so private state is checked before v2 preparation.

## Secrets

- Secret values never enter Git, configuration packages, the Hub, Plans, logs, or command lines.
- Managed identities and workload identity federation replace client secrets for Azure access.
- An unavoidable third-party secret lives in the installation's Key Vault. Workloads read it
  through the Key Vault CSI driver with workload identity, as the existing runtime does.
- The customer rotates secrets in Key Vault. Rotation doesn't create a configuration revision, and
  reported state shows only whether each reference resolves.
- Apollo creates Kubernetes secrets through Plans
  ([Apollo secrets](https://www.palantir.com/docs/apollo/managing-secrets/add-edit-delete-secrets)).
  FDAI deliberately doesn't, so the Hub never carries a secret value.

## Policy and authority aren't configuration

- Approval policy and admission policy revisions are authored in FDAI Console under
  [Operator Governance Profiles](../decisioning/operator-governance-profiles.md) and stay inside the
  installation.
- Promotion state, standing authorizations, the kill switch, and the approval profile change only
  through their governed authority paths.
- The Hub sees only digests of policy and authority state in reported state. A Release may declare
  a maximum mode for an ActionType, and no policy revision can exceed it.

## Examples

These examples use placeholders. Customer A runs an online Target Hub in Korea Central with PTU
capacity and in-country processing:

```yaml
# installations/<customer-a-installation>/installation.yaml
hub: target-hub-online
channel: RELEASE
version_range: ">=1.5.0 <2.0.0"
maintenance_windows:
  downtime: "Sun 02:00-04:00 Asia/Seoul"
  no_downtime: "daily 01:00-05:00 Asia/Seoul"
entities: [core, operator-api, document-ingestion-api, document-processing-worker,
           isolated-executor, console]
```

```yaml
# installations/<customer-a-installation>/environment.yaml
region: koreacentral
data_residency:
  processing_scope: geography       # geography | data-zone | global
network:
  profile: private-endpoints-only
model_bindings:
  diversity_policy: same-publisher-distinct-models
  primary:
    provider: azure-openai
    deployment_type: ProvisionedManaged
    capacity: { kind: ptu, units: 100 }
    endpoint_ref: model-primary
  secondary:
    provider: azure-openai
    deployment_type: ProvisionedManaged
    capacity: { kind: ptu, units: 50 }
    endpoint_ref: model-secondary
integrations:
  itsm:
    endpoint_ref: itsm-primary
    credential_ref: itsm-token      # Key Vault secret name
```

```yaml
# installations/<customer-a-installation>/sealed.yaml
tenant_id: 00000000-0000-0000-0000-000000000000
subscription_id: 00000000-0000-0000-0000-000000000000
resource_group: <customer-a-application-rg>
endpoints:
  model-primary: https://model-primary.example.com
  model-secondary: https://model-secondary.example.com
  itsm-primary: https://itsm.example.com
```

```yaml
# installations/<customer-a-installation>/entities/core.yaml
overrides:
  - versions: ">=1.5.0 <2.0.0"
    values:
      replicas: 2
      resources: { cpu: "2", memory: 4Gi }
```

Customer B uses a central Hub cell in East US, subscribes to `RELEASE_CANDIDATE`, sets
`processing_scope: global` with Standard pay-as-you-go capacity, and keeps the default
`mixed-publisher` diversity policy. Customer C pins `version_range: ">=1.4.0 <1.5.0"` and binds a
`self-hosted` provider through an `apim-gateway` route with capacity kind `gpu`.

## Configuration data model

| Table | Key | Purpose | Time fields | Mutability |
|-------|-----|---------|-------------|------------|
| `configuration_revision` | `installation_id`, `revision_id` | Git commit, predecessor digest, package digest, signer key | `committed_at`, `imported_at`, `recorded_at` | Append-only |
| `installation_settings` | `revision_id` | Channel, version range, windows, Entity list | Inherits the revision | Immutable per revision |
| `environment_config_value` | `revision_id`, `key` | Value, axis, and owner annotation | Inherits the revision | Immutable per revision |
| `sealed_value` | `revision_id`, `key` | Ciphertext reference and digest | Inherits the revision | Immutable per revision |
| `entity_override_block` | `revision_id`, `entity_id`, `version_range` | Override values and digest | Inherits the revision | Immutable per revision |
| `package_import` | `import_id` | Source, such as upload or bundle, and the verification result | `imported_at` | Append-only |

## Customer repository template and key onboarding

The [placeholder template](../../../config/lifecycle-configuration-template/README.md) provides the
installation, Environment Config, private sealing input and Entity layout above, plus a synthetic
annotated Release schema. Its focused offline tests call the existing validators; they do not
create a package, key, signature, upload or deployment. The
[configuration key runbook](../../runbooks/lifecycle-configuration-key-onboarding.md) separates
customer key custody and local packaging from independent trust registration and Hub import.
Do not upload readable `sealed.yaml` input or treat an example schema as a trusted Release.

## Approved configuration keys: design and critique

This source-only increment registers public trust metadata, not actual customer keys or a
production trust root. Existing enrollment and source/offline installation remain unchanged.

1. An authenticated customer operator submits canonical `fdai.configuration-keys.v1` bytes,
   signed by the installation's already enrolled Ed25519 identity and separately by the proposed
   configuration Ed25519 signer. The bytes bind the installation, requester principal, unique
   request ID, next version, predecessor binding digest, both role-labelled 32-byte public keys,
   request time, approval deadline and binding expiry. The X25519 encryption recipient is neither
   signing identity. Reusing public bytes across these roles is not accepted.
2. Request proofs have a five-minute clock window; approval expires within ten minutes of the
   request. Binding expiry is later than the deadline and at most 90 days after the request.
   A different operator authenticated through the existing Hub access-token boundary approves
   the exact request digest. Body actor strings, proxy headers, local unauthenticated approvals,
   service tokens and package-supplied keys cannot establish trust.
3. The existing installation-row lock serializes requests, approval, revocation and planning.
   Approval rechecks enrollment identity, deadline, requester separation, next version and exact
   predecessor. Accepted versions and their proofs remain immutable. Replayed approvals and
   concurrent stale predecessors fail without changing trust. An authenticated operator may
   revoke the exact current digest; revocation only removes configuration capability.
4. Public bindings and attributed decisions use additive Hub tables and the existing hash-chained
   audit in one transaction. Denials are committed before returning a bounded reason. Explicit
   migrations upgrade existing databases; serving never creates tables or invents a binding.
5. The real Hub configuration-planning store resolves the requested active version from these
   tables under the same lock. Missing, expired, revoked, wrong-installation or mismatched bindings
   hold configuration planning, not legacy enrollment or planning. Historical versions are retained
   and never replaced by the current signer. Issued configuration Plans pin the approved binding
   version and request digest; current-Plan retrieval holds them after expiry, rotation or revocation.
   The atomic importer below resolves historical packages with their exact retained bindings;
   an unprovable chain holds rather than being silently reinterpreted. Registering a key is not
   package import or configuration activation.

**Critique and revision before implementation:** A caller-selected key plus an actor field is
self-asserted trust, even when the package signature is valid. Therefore only the existing verified
operator principal reaches approval, a second principal is required, and identity proof covers the
complete canonical request. Merely adding a registry would leave the old consumer trusting caller
keys, so configuration planning explicitly resolves persisted trust inside its transaction.
Crypto-provider signature success alone can accept a small-order Ed25519 identity-point forgery.
The new binding boundary therefore validates canonical, on-curve, non-small-order signing public
points before either possession proof; it never derives an encryption key from a signing identity.
Rotation cannot overwrite a row or reset a version after revocation, and schema initialization
cannot be called a migration. Private keys, credentials and customer identifiers are not stored.
No live enrollment, Azure operation, Agent/CSI delivery or production qualification is included.

## Atomic import and configured consumption: design and critique

This bounded source path separates five decisions: scope binding, package import, configuration
change approval, activation, and upgrade planning. None grants execution or promotion authority.

### Proposed contract

- An enrolled installation signs a short-lived scope request binding its unchanged managed Entity
  identifiers to independently chosen opaque package identifiers, the sealed-key classification,
  and an exact admitted Release/schema. A different JWT-authenticated customer operator approves
  the exact request digest. The package cannot create this binding or manage a new Entity.
- A bounded authenticated import supplies the complete original signed file container, an explicit
  current key-binding version, the approved scope digest and an installation-identity proof over
  this complete import context. The server resolves Release/schema from its independently pinned
  catalog and keys from the persisted approved registry. Hub never decrypts sealed values.
- Under the existing installation lock, successful verification appends an immutable import
  receipt and advances the accepted head together with the existing audit chain. The retained
  predecessor is authoritative. Exact current-head retries preserve original container bytes;
  competing children, reused Git revisions, reordered history and conflicting retry bytes fail.
  Catalog and installation locks share one database transaction. A validation denial commits its
  audit before the API error; an unexpected storage or audit failure rolls back the entire change.
- Every receipt pins its accepted key version, key-request digest, scope digest, original signed
  bytes and predecessor. Historical verification checks each signature with that receipt's
  independently approved retained binding, at its acceptance time. Rotation is not permission to
  rewrite history. Revoked, missing or unprovable historical bindings hold with a bounded reason.
  Each issued imported-configuration Plan also retains its exact import and acceptance receipt.
  Missing Plan/import/head provenance holds rather than falling back to key-only verification.
  Historical Entity coverage uses that receipt's independently approved mapping, not today's
  managed set: reapplying today's selection would prevent a legitimate full successor after an
  Entity becomes managed. Current import, approval, activation and consumption still require
  today's exact managed set; historical acceptance grants no new Entity permission. During
  catalog-bound import/planning, every historical Release/schema still needs its exact admitted
  catalog entry. A missing historical Release holds; an old receipt does not invent admission.
- Import creates a change request, not approval. A different authenticated operator approves its
  exact receipt within ten minutes; explicit activation rechecks current trust, complete history,
  selected scope and accepted-head compare-and-swap. Activation only selects configuration for
  the existing upgrade planner. It neither schedules a same-Release action nor applies anything.
- Default configured recomputation reads the persisted activated head within the planning
  transaction, without injected candidates. Missing configuration leaves legacy planning intact;
  staged but unactivated configuration holds only this capability and preserves unrelated legacy
  Plans. Recall, windows, ownership, local envelope and explicit approval checks remain unchanged.

### Critique and revision before implementation

A map in an HTTP body is still self-asserted even when its package verifies. Therefore mapping
and sealed classification need their own installation proof and independent exact-digest approval,
reusing the key-approval principal separation rather than inventing an enrollment grant. Existing
enrolled identifiers and signed Plan identifiers stay unchanged; no customer identifier is hashed.

Rechecking all ancestors with the newest signer breaks valid rotation, while trusting previously
parsed dictionaries hides tampering. The canonical package reader and builder therefore accept
explicit per-ancestor public verification bindings and still verify original bytes and the complete
chain. The Hub derives those bindings only from immutable import receipts and approved key records;
historical acceptance never makes an old key current permission.
An explicit Plan-to-import receipt prevents missing persisted packages from being mistaken for
the older transient compatibility seam.

A helper or an optional composition candidate leaves default startup disconnected. The actual
pinned-catalog recompute route therefore resolves durable state by default. The new additive Hub
schema revision preserves legacy raw configuration records, which are not ciphertext-only.
Only this new import path claims ciphertext/public-metadata storage. Local tests do not establish
real enrollment, deployed migration, Agent delivery, CSI integration or production qualification.

### Authenticated source API

The configured Target Lifecycle Hub exposes these operator-only routes beneath
`/v1/installations/{installation_id}`. Existing JWT issuer, audience, client, scope and principal
checks apply; local caller names, service tokens and actor fields cannot approve anything.

| Route | Input and effect |
|-------|------------------|
| `POST /configuration-scope/request` | Base64 canonical `fdai.configuration-scope.v1` payload and enrolled installation identity proof; exact Release/schema, one-to-one Entity map, sealed-key names and bounded deadlines |
| `POST /configuration-scope/approve` | Exact `digest`, approved by a different authenticated operator |
| `GET /configuration-scope/requests/{digest}` | Public request metadata for independent review |
| `POST /configuration/import` | Base64 original file container, canonical `fdai.configuration-import.v1` context and identity proof; context binds installation, requester, current key version, scope, container/package digests and retained predecessor |
| `POST /configuration/approve` | Exact package `digest` and `receipt_digest`; independent configuration-change approval |
| `POST /configuration/activate` | Same exact pair, with current head/trust/history and unexpired approval rechecked |
| `GET /configuration` | Accepted and active digests, which are distinct |
| `GET /configuration/revisions/{digest}` | Original ciphertext container and public acceptance digests, never decrypted values |

Serving never migrates automatically. Explicit Hub schema revision 3 additively creates
`lifecycle_configuration_scope_request`, `lifecycle_configuration_scope_approval`,
`lifecycle_configuration_import`, `lifecycle_configuration_head` and
`lifecycle_configuration_change_approval`, plus `lifecycle_configuration_plan_import` to retain
issued Plan provenance. Revisions 1 and 2 upgrade without reinitializing legacy
enrollment, keys or raw configuration. Accepted history is bounded to 256 packages and 16 MiB of
signed payloads; overflow holds rather than truncating. The canonical builder, reader and
installation-local decryption API accept per-ancestor `ConfigurationHistoryBinding` inputs.
Those inputs authenticate history only and never establish current key permission.

## Honest limits

- The offline builder signs real packages, checks predecessor chains, and encrypts identifiers.
  Focused tests exercise its reader and installation-local decryption with synthetic in-memory
  keys; operational package delivery is not implemented.
- The example schema has annotations, but production Releases don't yet carry a qualified
  configuration-package schema. Runtime v3 development publication and independently pinned Hub
  admission now bind optional schemas to exact Release artifacts; this is not production qualification.
- Local packaging and verification commands do not register trusted keys or update a durable Hub
  chain head. Separate authenticated Hub public-key request/approval/revocation APIs now persist
  trust and gate configuration planning. They require an already enrolled installation and
  independently authenticated customer operators. No operational enrollment was performed here,
  and no operational Agent delivery is claimed. The separate atomic source importer persists
  original signed containers, independently approved mappings and accepted/active heads; existing
  legacy raw configuration records do not become ciphertext-only.
- A customer who loses the configuration key can't publish new revisions until a key rotation
  is registered with the Hub.

## Related docs

| To learn about | Read |
|----------------|------|
| Lifecycle architecture and Plans | [Hub-Managed Lifecycle](hub-managed-lifecycle.md) |
| Releases, channels, and bundles | [Lifecycle Releases and Channels](lifecycle-releases-and-channels.md) |
| Approval and admission policy | [Operator Governance Profiles](../decisioning/operator-governance-profiles.md) |
| Model bindings, capacity, and diversity | [Model Capability Lifecycle](../architecture/model-capability-lifecycle.md) |
| Decision record | [ADR-0003](../architecture/decisions/0003-hub-managed-lifecycle-and-operator-governance.md) |
| Customer key custody and onboarding prerequisites | [Configuration key runbook](../../runbooks/lifecycle-configuration-key-onboarding.md) |
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/deployment/lifecycle-configuration.md) |
