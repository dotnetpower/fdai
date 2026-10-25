---
title: Lifecycle Releases and Channels
---
# Lifecycle Releases and Channels

This document defines what an application Release contains and how Releases move through release
channels. It also defines how connected and offline installations receive Releases, and how
recalls and database schema compatibility keep upgrades safe. It owns the Release manifest, the
channel model, upgrade bundles, and recall.

> **Status:** Partially implemented for local and explicit remote development; production lifecycle delivery remains
> design work. The [local Release Hub](../../../lifecycle/release-hub/README.md) provides manifest
> registration, development signing, manual built-in/custom channels, recall, a vendor UI, and opt-in
> pinned export admission by the Lifecycle Hub. It does not implement production authentication,
> production root-key custody, registry publication, or recall roll-off.
> FDAI also has signed deployment bundles and offline kits, and their
> new bundle signatures use `DEV`, `RELEASE_CANDIDATE`, and `RELEASE`. Verification maps legacy
> `development`, `beta`, and `stable` names without rewriting signed bytes. The deployment CLI
> still admits only `DEV` and its authenticated legacy equivalent. The
> [implementation ledger](../../roadmap-implementation/deployment/lifecycle-releases-and-channels.md)
> tracks the rest.
>
> **Scope:** This document serves the [Hub-managed lifecycle](hub-managed-lifecycle.md). The
> [source deployment](source-deployment.md) and the first-installation offline package keep their
> current contracts.

## Design at a glance

**FDAI Release Hub** is the vendor application for release publication, signing, channel
promotion, and recall. **Release Catalog** means the release list, data, or feed that Release Hub
provides, not the application name. **FDAI Lifecycle Hub** remains the separate application that
manages deployments for individual installations.

The local Release Hub exposes API workflows and a web UI. Existing signed bundles and
local shadow-only validators alone don't constitute an implemented production Release Hub service. Catalog
directories, APIs, schemas, and identifiers keep their technical names.

The opt-in [two-Hub development path](../../../infra/hubs-development/README.md) adds direct
Entra operator/service separation, PostgreSQL publication storage with explicit migrations,
independent development signing-key provisioning, bundled UI images, and durable customer
pin/revision state. A customer operator must approve the exact export pin through a separate
authenticated trust operation before bounded import; a digest beside the download grants no
trust. Local loopback defaults and existing manifest/signature/catalog contracts remain unchanged.
Opt-in TUF-style catalog roles (see [Catalog integrity](#catalog-integrity)) replace the single
development key with threshold offline root keys and separate online snapshot and timestamp keys.
This is not a production root ceremony, registry publication, Agent apply, or evidence of a
successful Azure deployment.

| Concern | Decision |
|---------|----------|
| Release | A signed manifest of prebuilt image digests, schema range, dependencies, configuration schema, and capability maximums |
| Build once | The vendor builds each image once, and every installation runs the same digests |
| Channels | `DEV`, `RELEASE_CANDIDATE`, `RELEASE`, and custom channels |
| Subscription | Each installation subscribes to one channel, optionally with a version range |
| Upgrade | Automatic: the newest eligible Release inside a maintenance window |
| Connected delivery | Images are mirrored into a registry inside the customer boundary |
| Offline delivery | A signed upgrade bundle that an operator imports into a Target Hub |
| Recall | A Release recall triggers roll-off. A capability recall returns an ActionType or Workflow to shadow mode everywhere. |
| Catalog integrity | Signed root, snapshot, and timestamp records with increasing versions and recall sequence numbers |
| Schema | Expand/contract and forward-only. Each Release declares the schema revisions it tolerates. |

## Explicit development catalog renewal

A development export expires 24 hours after its latest publication event. Reading the catalog,
refreshing a screen or downloading the same export does not renew it. An unchanged release set
still needs a reviewed freshness publication; don't manufacture a channel or recall change.

`POST /v1/catalog/renew` requires the existing vendor operator identity, current catalog revision,
nonblank reason and exact confirmation `renew <revision>`. The same publication lock and revision
check serialize it with registration, publication, channel contribution and recall. Before any
write, reverify every published manifest signature with the current key and require the publication
clock to advance. An invalid signature, stale revision, wrong confirmation or clock regression
leaves publication state unchanged.

Renewal appends an attributed `renew` event targeting `catalog`. It advances the revision and
24-hour expiry, changing the export digest without changing manifests, signatures, channels,
recalls or the signing key. Customer Hubs retain their old accepted bytes until either an
operator independently approves the new exact pin and explicitly imports it, or
[automatic adoption](#automatic-catalog-adoption) verifies the signature and the policy allows it.
Renewal never imports, plans or applies an installation change and does not replace production
signed catalog roles. An optional Release Hub task can perform the renewal automatically.
The UI distinguishes read-only **Refresh catalog** from **Renew catalog freshness**.

## Automatic catalog adoption

The manual pin flow above makes a person copy a revision and digest for every catalog change,
because the export bytes carry unsigned metadata. This section replaces that transcription with
verification and policy. It keeps the same trust anchor: the Release public key that the customer
Hub binds at deployment time.

**Direction rule.** Release Hub never calls a customer. The Lifecycle Hub polls Release Hub, the
installation Agent polls the Lifecycle Hub, and every connection starts inside the customer
boundary. Release Hub stores no customer callback address, execution identity or schedule. The explicit
[deployment-request intake](hub-image-deployment.md#see-subscription-deployment-requests) is a
separate, minimal exception: it retains a reported subscription ID, region, Release/channel,
input digests and server receipt time for an operator-only list. These self-reported requests
never enter the public catalog, prove subscription ownership, authorize deployment or report
operational success. Customer configuration identifiers remain sealed under their existing contract.

| Concern | Decision |
|---------|----------|
| Signed export | Release Hub signs the exact export bytes with its Release key. The signed message is `fdai.catalog-export.v1`, a newline, then the body. The detached signature and key id travel in `X-FDAI-Export-Signature` and `X-FDAI-Export-Key-Id` on the same response, so the body and signature cannot come from different revisions. The body and its `ETag` digest are unchanged. |
| Conditional poll | The Lifecycle Hub sends `If-None-Match` with its accepted digest. An unchanged catalog returns `304` after one cheap position query. Release Hub caches the last signed export by revision and builds at most one export at a time. |
| Public read | `public_catalog_export` lets Release Hub serve `GET /v1/catalog/export` without a bearer token. The export holds manifests, signatures, channel membership and recalls only. Integrity comes from the signature, and images stay behind registry authorization. The default stays authenticated. |
| Automatic freshness | An optional Release Hub renewal task appends an attributed `renew` event as `system:timestamp-renewal` when less than half of the validity remains. It re-asserts the already published content and cannot add a Release, channel or recall. With [signed catalog roles](#signed-catalog-roles-in-the-hubs) it re-signs only the timestamp and appends no event. |
| Periodic check | The Lifecycle Hub checks on `check_interval_seconds` (300 to 86400, default 3600, zero disables) with jitter and capped retry. Each attempt is one bounded request without redirects. |
| Adoption policy | Rego decides whether a verified candidate may replace the accepted catalog without a person. Input is the signature result, the change summary and the owner's standing authorization. Output is `allow` and the reasons a review is needed. The default is `review`. |
| Fail closed | A missing signature, a wrong key, an expired candidate, a lower revision, an unavailable policy engine or an expired standing authorization never adopts automatically. The candidate waits for review. |
| Review | One **Updates** screen shows the candidate revision, expiry, signature result and the change summary. **Review and apply** names the exact revision and digest that the Hub itself verified. If the source moved in the meantime, the Hub refuses and shows the new candidate. |
| Atomic adoption | One transaction verifies the signature and the manifests, enforces the revision floor, requires that the accepted catalog is still the one the policy assessed, refuses to overwrite an operator-approved pin for the same revision, records the accepted bytes, and appends audit events attributed to the policy or the reviewing operator. |
| After adoption | The Hub computes a Plan for every enrolled installation. Issuing a Plan never applies it. The Agent still verifies signatures and its local envelope before any effect. |

The standing authorization is the existing human authorization from the constitution. Its
`authorized_by` and `authorization_expires_at` are configuration, so a change is a reviewed
deployment change. When it expires, adoption returns to review. Silence never approves.

In `auto` mode, a candidate with a valid signature gets these outcomes. In `review` mode, which
is the default, every change waits for a person.

| Change | Outcome |
|--------|---------|
| First catalog, or the same releases, channels and recalls with a later expiry | Adopt |
| New Release in an allowed channel, up to `max_new_releases` (not counted for the first catalog) | Adopt |
| New recall with nothing else changed | Adopt |
| Membership in a channel outside `allowed_channels`, a new channel outside that list, a removed or replaced Release, removed membership, a lifted or dropped recall or a widened schema range | Review |
| Expired or missing standing authorization, or an unavailable or invalid policy engine | Review |
| A missing signature, a signature from another key, a lower revision, an expired candidate or an unreachable source | No candidate; the Updates screen shows the failure and the legacy pin flow remains |

A recall mixed with other changes waits for review, and the screen marks it urgent.

### Configuration and interfaces

The deployment supplies the standing authorization through the Lifecycle Hub `catalog` setting:
`access` (`managed-identity` by default, or `anonymous`), `check_interval_seconds`, and an
`adoption` object with `mode`, `allowed_channels`, `max_new_releases`, `authorized_by` and
`authorization_expires_at`. `auto` requires both authorization fields. Release Hub gains
`auth.public_catalog_export` and `timestamp_renewal_check_seconds`. Existing configurations keep
their behavior because every new field is optional. The optional `trust` setting and the Release
Hub `catalog_roles` setting select [signed catalog roles](#signed-catalog-roles-in-the-hubs).

| Interface | Purpose |
|-----------|---------|
| `GET /v1/catalog/updates` | Policy, accepted catalog, last check, candidate with decision and change summary, and recent events |
| `POST /v1/catalog/updates/check` | Run one bounded poll now |
| `POST /v1/catalog/updates/apply` | Adopt the reviewed `revision` and `sha256` if the source still offers exactly that candidate; otherwise `409 candidate_changed` |
| `fdai-lifecycle-hub sign-enrollment` | Sign an enrollment request inside the installation boundary and write only the file the operator uploads |
| `GET /v1/enrollments/bindable` | List the installations the deployment bound to an Agent, so the operator selects one and types nothing |

**What stays a person's decision.** First trust of the vendor key, the choice of channels and
standing authorization, installation enrollment, ownership, configuration signing and any
effect on a workload. **What stays opt-in.** Threshold root keys and TUF snapshot and timestamp
roles exist as an opt-in mode (see [Catalog integrity](#catalog-integrity)). Without it, the
single development key signs the export, and the dev profile label stays. The physical
production root ceremony remains an operator procedure.

**Critique and revision.** Auto-adopting a digest taken from the download response would
reintroduce the unsigned-metadata gap, so the signature, not the digest, is the evidence.
Public read exposes release metadata to anyone, which the vendor accepts because it carries no
image content or customer data and the signature prevents tampering. A mixed recall and release
change cannot be split because adoption is atomic. Splitting would let unreviewed content ride
along with a recall, so the design delays adoption and surfaces the recall instead. The renewal
task is the timestamp role in miniature: it cannot widen content, only keep reviewed content
fresh. The legacy pin approval and import remain for unsigned exports and offline use.

## Application package contract

The Hub engine accepts `fdai.application-release.v1` without an application-specific service list.
FDAI is one possible application. Publication, exact pinned admission, recall and channel
selection use the same path for every `product`; a channel does not grant production qualification.

| Field | Current contract |
|-------|------------------|
| `schema_version` | `fdai.application-release.v1` |
| `product` | Independent application ID: `[a-z][a-z0-9-]{0,62}` |
| `release_version`, `source_commit`, `platform_tag` | Semantic version, exact application source revision and artifact platform |
| `workloads` | 1-64 named HTTP components; each name is a Service-compatible DNS label starting with a lowercase letter |
| `workloads.<component>.image_digest` | Required immutable `sha256:` image digest |
| `workloads.<component>.port` | Integer 1-65535; default 8080 |
| `workloads.<component>.health_path` | Bounded ASCII absolute readiness path, not a URL or `//` path; default `/` |
| `workloads.<component>.replicas` | Integer 1-3; default 1 |
| `configuration_schema`, `schema` | Optional existing version/digest-bound configuration schema and database compatibility metadata |

Strict UTF-8 JSON rejects duplicate keys and nonfinite numbers, including exponent overflow.
Both incoming UTF-8 and its stored canonical representation fit the same 1 MiB decoder limit;
Unicode defaults that expand beyond that limit are rejected before publication.
Unknown fields cannot inject templates, privileges or namespaces. Legacy workload profiles are
blocked; application rendering produces only bounded Deployments and ClusterIP Services.
Missing supply-chain evidence is displayed as **Not declared**, not manufactured or verified.
The product must match both independently approved installation Settings and local Agent policy.
Missing database metadata selects revision zero and cannot reset an existing database.
Release versions remain globally unique within a catalog, not namespaced by product.
The separate `fdai.runtime-release.v3` adapter preserves the existing complete FDAI inventory and
source/offline contracts. It is not the required shape for an unrelated application.

## FDAI runtime adapter contents

| Field | Content |
|-------|---------|
| `product`, `version`, `source_commit` | Product identity, semantic version, and exact source revision |
| `images` | OCI digests for Core, Operator API, Document Ingestion API, Document Processing Worker, isolated Executor, the ClamAV sidecar, the Console bundle, and both installation agents |
| `sbom`, `provenance` | Digests of the supply-chain evidence for each image |
| `schema` | `target`, the revision its migrations produce, and `tolerates`, the range of revisions its code accepts |
| `dependencies` | Supported version ranges for the Hub and both installation agents |
| `configuration_schema` | Keys, defaults, and the `x-fdai-axis` and `x-fdai-owner` annotations described in [Lifecycle Configuration](lifecycle-configuration.md) |
| `capabilities` | The maximum mode for each ActionType and Workflow, and any capability recall |
| `downtime` | Which Entities need a downtime window for this upgrade |
| `workloads` | The workload template and the schema-expand migration Job template that the lifecycle agent renders, as [Workload rendering migration](hub-managed-lifecycle.md#workload-rendering-migration) defines |
| Signature | Detached signature by the vendor release key over the canonical manifest |

The implemented runtime v3 manifest optionally embeds the digest-pinned, version-bound
`configuration_schema` artifact defined in
[Release schema admission design and critique](lifecycle-configuration.md#release-schema-admission-design-and-critique).
Release Hub registration/publication and independently pinned Lifecycle Hub admission validate it
through the canonical configuration validator. Its bytes are covered by the existing manifest
signature. Releases without it retain existing behavior but do not offer this configuration
capability. This development contract neither establishes production Release qualification nor
changes source/offline installation.

The configured Lifecycle Hub now uses this same independently pinned Release/schema for its
[atomic configuration import](lifecycle-configuration.md#atomic-import-and-configured-consumption-design-and-critique)
and persisted activated-revision consumer. Catalog and installation decisions share a transaction,
so replacement or recall cannot race a stale import/planning snapshot. Configuration scope,
signature, key-version history and independent change approval remain separate from Release
admission; neither import nor activation publishes a Release or grants execution authority.

An image built from a source checkout has no vendor signature and is labeled
`unverified-source-build`. Such an installation can enroll with a Hub. The Hub treats every Entity
that runs an unverified image as drifted, and the first Plan replaces those images with a signed
Release from the subscribed channel.

## Versions

- Versions are ordered semantic versions. A release candidate such as `1.5.0-rc1` orders before
  `1.5.0`, as in [Apollo versions](https://www.palantir.com/docs/apollo/core/products-releases-versions).
- A new major version is deployable only after the customer adds an Entity override block that
  covers it.
- An installation never moves to an older version unless a vendor-signed recall allows it and the
  older Release tolerates the current schema revision.

## Release channels

| Channel | Receives | Typical subscriber |
|---------|----------|--------------------|
| `DEV` | Every published build | Vendor test installations |
| `RELEASE_CANDIDATE` | Release candidates and releases | Early adopters, such as Customer B |
| `RELEASE` | Releases that passed the promotion pipeline | Production installations |
| Custom | Releases that a channel contributor adds manually or a pipeline promotes | A customer that curates eligible Releases, or a pilot group |

A promotion pipeline defines the channel order and the criteria for each stage: required labels,
such as a completed security review, soak time with healthy canary installations, product
maintenance windows, and bounded timeouts. A channel contributor can also add a Release manually,
for example to ship an incident fix, as in
[Apollo channel promotion](https://www.palantir.com/docs/apollo/core/release-channels).
`evaluate_promotion_stage` and `ReleaseStore.promote_stage` enforce source-channel presence,
required labels, canary health, minimum soak seconds, bounded stage timeouts, and active
Release/capability recall checks before advancing a Release to its target channel.

A regulated customer that reviews each Release before it becomes eligible can create a custom
channel in its Target Hub and add Releases from `RELEASE` by hand. Channel membership is
eligibility curation, not installation approval. Installations that subscribe to that channel still
apply each eligible Release automatically inside their windows.

Channel names migrate one way. `development` maps to `DEV`, `beta` maps to `RELEASE_CANDIDATE`, and
`stable` maps to `RELEASE`. Artifacts signed before the migration keep their legacy names, and the
deployment CLI maps those names only to verify them.

**Migration design and critique:** Normalize metadata only after verifying the original
signature and canonical bytes; rewriting the signed document would invalidate its provenance.
New bundle producers accept canonical names only, and the package-pinned eligible channel stays
`DEV`, including authenticated legacy `development`. Mapping `beta` or `stable` does not make
either eligible. Unknown names hold rather than becoming custom channels. Compatibility is
one-way: old binaries are not claimed to accept newly signed canonical names. This change
adds no installation gate, trust root, promotion or production qualification.

## Development custom-channel curation design and critique

The Release Hub's existing operator contribution route may create a nonempty custom channel
with its first reviewed membership. Names use `custom-` followed by lowercase ASCII alphanumeric
segments separated by single hyphens, at most 64 characters total. This avoids collisions with
built-in and legacy names without changing signed bundle-channel spelling.

The existing exact Release confirmation, catalog revision, reason and authenticated operator
remain required. A custom contribution additionally confirms the exact destination through
`channel_confirmation`. Both the membership and attributed event commit in one transaction.
Drafts, recalls, duplicates, stale revisions and invalid inputs leave both unchanged. Custom
membership survives restart and changes the exported pin; customers independently approve and
import that exact pin before it affects their catalog. Creating empty channels, renaming/deleting
them, customer-local Target Hub curation and automatic promotion are outside this increment.

**Critique and revision:** Arbitrary strings could alias a built-in or hide whitespace, so use a
distinct bounded namespace. Confirming only a Release would not confirm a newly typed destination,
so require both values without changing built-in requests. Never infer approval from a new export
digest or let a channel bypass recall, schema constraints, local Plan authority or effect checks.

## Customer-local channel curation design and critique

An existing authenticated Target Hub operator may add one exact imported `RELEASE` member to a
`local-` channel, using lowercase ASCII alphanumeric segments separated by single hyphens, at
most 64 characters. The request binds the accepted catalog digest, exact Release id/digest, local
revision, reason and typed `add <release> to <channel>` confirmation. It cannot select or change
an installation's subscription, source, key, maximum envelope or approval policy.
The development store supports at most 1024 immutable local memberships; reaching the limit
explicitly holds further additions, and an oversized retained set is unavailable, never truncated.

One immutable membership row is also its attributed audit record. Explicit Hub migration adds
that table at schema revision 4; serving never migrates. Older binaries refuse the newer schema
rather than silently ignoring curation. Recovery preserves the table and history; no downgrade or
destructive rollback is supplied. Existing deployments need an explicit migration before using
the new binary, not a Hub or new trust gate for source/offline installation.

Local membership is a narrowing view: the current independently verified catalog must still
contain the same Release digest in `RELEASE`, under the same key, without an active recall.
Unknown, changed, withdrawn or recalled members remain visible as held provenance, not eligible
fallbacks. Vendor/local namespace collisions hold rather than overwrite either side. Import,
curation and planning use the same catalog lock and transaction. Planning audit records the exact
accepted pin and local revision/digest; original vendor bytes and digests are never rewritten.

**Critique and revision:** Copying a channel dictionary would lose durable approval and permit
stale membership to survive a changed source. Persist exact bindings and recheck them for each
fresh view instead. A channel grants no installation approval, promotion or executor authority.
This add-only development increment does not rename/delete channels or implement automatic
recall roll-off of previously issued Plans; those keep the existing lifecycle safeguards.

## Subscriptions and automatic upgrades

- Installation settings name one channel and an optional version range. Every Entity follows the
  installation's channel, because FDAI services release together.
- Inside each maintenance window, the Hub plans the newest Release on the channel that passes every
  constraint. Entities that the Release marks as needing downtime wait for a downtime window.
- A version pin is a version range, such as `>=1.4.0 <1.5.0`, or `=1.4.3` for an exact version.
- When a recall leaves a pinned range without an eligible Release, the Hub reports that no Release
  is eligible and alerts the operator. It doesn't move the installation outside its range.

| Situation | Recommended subscription |
|-----------|--------------------------|
| Standard production | `RELEASE` |
| A change board reviews each version before it becomes eligible | A custom channel with manual additions |
| Early access to new capabilities | `RELEASE_CANDIDATE` |
| A certified version or an integration requires one release line | A version range pin, widened through a reviewed merge |
| Vendor or customer test installation | `DEV` |

## Recall

- **Release recall:** A vendor-signed recall notice stops the Hub from proposing the Release and
  cancels pending Plans that target it. Installations that run it receive a roll-off Plan to the
  newest eligible Release that isn't recalled. Roll-off takes priority over other Plans. A manual
  suppression window still blocks it, and the Hub raises an alert.
- **Capability recall:** A Release or signed recall notice can name ActionTypes and Workflows that
  must return to shadow mode. The installation demotes them immediately, outside maintenance
  windows, because lowering authority is always allowed. It blocks a new promotion of the same
  capability until a later Release lifts the recall, and this precedence also covers an operator
  override promotion.
- Offline installations apply recalls when an operator imports the bundle that carries them.

The Release Hub records both Release-scope recalls and capability-scope recall and lift events,
exports them as signed `RecallRecord` entries, and blocks manual channel promotion (`contribute`)
whenever a Release or one of its declared `capability_maximums` remains under an active recall
below its lifting Release. When a managed Entity is running a Release that is recalled directly or
through a declared capability, the Lifecycle Hub planner issues a `recall-rolloff` Plan to the
newest non-recalled Release on the subscribed channel that passes schema, window, and override
constraints, superseding an open `upgrade` Plan and bypassing `plan:upgrade` suppression while
still honoring manual installation or Entity suppressions.

## Catalog integrity

A signature proves who published a record, but not that the record is current. The vendor
therefore signs catalog metadata in separate roles, following
[The Update Framework (TUF)](https://theupdateframework.io/):

- A root record names the keys that may sign every other record. It changes only through a
  threshold of offline keys.
- A snapshot record lists the current version of every channel membership and recall record.
- A timestamp record names the current snapshot and expires after a short published interval.
- Every record carries a version that only increases. Installations and Target Hubs reject a
  lower version, and each upgrade bundle names the bundle it extends.
- Recall notices carry a sequence number per product, so a withheld recall shows up as a gap.

When the timestamp record expires, the installation accepts only recall roll-off Plans and raises
an alert. It also returns operator-override promotions to shadow mode until fresh metadata arrives,
because those promotions rely on recall as their safety net. An offline Target Hub sets the expiry
interval to match its bundle cadence. `evaluate_catalog_integrity` verifies threshold root
signatures, monotonic versions, and recall-sequence continuity (`recall_sequence_gap`), and
`StateStoreActionPromotionRegistry.set_catalog_timestamp_expired` returns operator-override
promotions to shadow mode while timestamp metadata is expired.

**Installation-side freshness.** The installation's Core verifies the public metadata itself, so
no Agent, Hub or event carries authority for the result. When
`FDAI_CATALOG_FRESHNESS_METADATA_URL` selects it, the Core fetches that URL, verifies the root
chain against the pinned `FDAI_CATALOG_FRESHNESS_ROOT_KEY_IDS` (threshold
`FDAI_CATALOG_FRESHNESS_ROOT_THRESHOLD`, default all keys) and applies `evaluate_catalog_integrity`
before each promotion refresh, at most once per `FDAI_CATALOG_FRESHNESS_REFRESH_SECONDS` (default
300, minimum 30). The flag is set when no metadata has been verified, when the signed timestamp,
snapshot or root has expired on the local clock. A failed fetch, an unpinned root, a bad signature or a lower version never replaces
the last verified state, so it cannot extend freshness and the local clock still ends it. The
metadata URL must be `https` (or loopback `http`), carries no credentials, is fetched without
redirects, and is bounded to 1 MiB. Selecting the feature without a root pin is a startup error;
leaving it unselected changes nothing. The Core keeps its version floors in memory only, so a
restart accepts any validly signed, unexpired metadata. Each transition logs
`catalog_freshness_changed` with a stable reason. The verification code lives in
`fdai_service_contracts` (`catalog_integrity`, `catalog_roles`, `catalog_metadata`), shared with the
Hubs.

### Signed catalog roles in the Hubs

The Hubs implement these roles as an opt-in mode that replaces the single development key. The
Lifecycle Hub enters the mode when `catalog.trust` has `mode: "tuf"`. Without it, the single-key
signed export and the unsigned pin flow behave exactly as before. Release Hub never calls a
customer, the Lifecycle Hub still polls, Rego still decides automatic adoption, and every failure
refuses the candidate.

| Role | Holder | What it signs |
|------|--------|---------------|
| Root | A threshold of offline keys held by people. No Hub database or process holds a root private key. | The key ids and public keys of every role, the threshold, a version and an expiry. A new root takes effect only when a threshold of the previous root's keys and a threshold of its own keys sign it. |
| Snapshot | One online key, separate from every other key | The export digest and revision, a version for each channel listing, the digest of each Release manifest and the recall ordinals `1..N` |
| Timestamp | A second online key | The current snapshot version and digest, with a short expiry (default 24 hours) |
| Export (targets) | The existing export key, now named in the root as `export_key_ids` | The exact export bytes under `fdai.catalog-export.v1`, and each Release manifest |

Each role signs under its own domain: `fdai.catalog-root.v1`, `fdai.catalog-snapshot.v1` or
`fdai.catalog-timestamp.v1`, a newline, then the canonical payload. A signature for one role
cannot stand in for another or for the export. Keys are Ed25519. A key id is `ed25519-` and the
SHA-256 of the raw public key, so an id cannot name a different key. The root carries the public
keys. Existing root and snapshot records that omit the new optional `export_key_ids`,
`public_keys`, `export_digest` and `export_revision` fields keep their canonical payload.

| Concern | Decision |
|---------|----------|
| Metadata | `GET /v1/catalog/metadata` returns the root chain, snapshot and timestamp in one document with an `ETag`, under the same public or authenticated rules as the export. Release Hub signs only when the export digest changes, a record is missing or the snapshot has a third of its validity left. Responses are cached by the export digest and the persisted version counters, so a request storm costs one small state query and no signing. |
| Timestamp renewal | The renewal task re-signs only the timestamp before it expires. It appends no `renew` event, the export and its revision stay byte-identical, and versions only increase across replicas because one locked row holds the counters. |
| Root ceremony | `fdai-release-hub root keygen`, `build`, `sign` and `verify` run offline. Each holder signs with a private key file of mode `0600`. `install-catalog-root` checks the chain and that the root authorizes the Hub's own snapshot, timestamp and export keys before it stores the public record. |
| Trust pin | `catalog.trust` holds `mode`, `root_key_ids` and `root_threshold` instead of `release_public_key`. The first root MUST name exactly those keys and that threshold. A later root never changes the pin. |
| Verification | The Lifecycle Hub verifies the root chain from the pin, the snapshot and timestamp, an export signature by an export key the root names, the export digest and revision that the snapshot binds, the channel listing, the manifest digests, the recall ordinals, and `evaluate_catalog_integrity` for threshold, versions, recall continuity and expiry. |
| Persisted floors | The Hub persists the highest verified root, snapshot and timestamp versions with their digests, the highest recall ordinal and the channel versions. A lower version is a rollback. The same version with different content is equivocation. Floors survive a restart and advance with adoption. |
| Policy input | Rego receives `integrity` with `verified`, `expired` and `root_rotation`. New deny reasons are `integrity_not_verified`, `timestamp_expired` and `root_rotation_requires_review`. Without `integrity`, none of them fires. |
| Expired timestamp | The Hub still verifies the roles. It adopts only a candidate that consists of recalls, refuses an operator apply of anything else, and plans only `recall-rolloff`. The accepted catalog carries an allowed plan-type set, and the planner blocks every other plan type with `catalog_timestamp_expired`. The Updates screen says so. |
| Root rotation | A rotation verifies like any root, never adopts automatically, and does not advance the persisted root until a person applies it from Updates. |
| Storage | The optional tables `catalog_integrity_state` (Lifecycle Hub, created by `bind-catalog`) and `catalog_role_root` and `catalog_role_state` (Release Hub, created by `install-catalog-root`) do not move either schema revision, so an older binary ignores them. |
| Compatibility | A Release Hub with roles installed stops extending the legacy export expiry, so move consumers to `tuf` first. A bound database refuses a changed trust (`bind-catalog` requires explicit rebinding), so switching an existing installation needs a fresh trust binding. |

**Critique and revision.** Naming the online keys in the root, not in configuration, lets a
rotation retire them, so a Release Hub whose keys the root no longer authorizes refuses to serve
metadata instead of signing with an unauthorized key. With roles, freshness comes from the signed
timestamp and snapshot, so the export's own `expires_at` is not enforced in `tuf` mode. Recall
ordinals count recalls in the export, because event revisions are not contiguous. The continuity
check catches a withheld or dropped recall, but cannot help when the snapshot and export keys
are both compromised. One export key signs every manifest, so retiring it needs every manifest
re-signed, and it stays in `export_key_ids` until then. The root chain is bounded at 32 roots.
Keys for snapshot and timestamp come from secret references, so a hardware-backed key is an
operator choice that this design does not enforce.

**Not yet implemented.** A production root ceremony with retained custody receipts, which stays
an operator procedure. Terraform and chart wiring of the installation freshness settings, and
durable version floors for it. The standalone Release Hub
root already installs the root through its operation Job, so the legacy paired fixture stays
unchanged. Database inspection fingerprints the optional role tables when they exist.

## Schema compatibility

Database migrations stay expand/contract and forward-only. [Deployment](deployment.md) already
serializes them with a database-scoped lock, bounds their deadlines, and runs them before a new
revision takes traffic.

| Phase | Change | Runs as | Roll-back target |
|-------|--------|---------|------------------|
| Expand | Additive schema only | The Release's migration job, before any workload switches | The previous Release, which tolerates the expanded schema |
| Switch | Workloads move to the new Release | The lifecycle agent's workload phase | The previous Release |
| Contract | Removes the old shape in a later Release | A migration job after a point-in-time restore checkpoint | None for that shape. Only a forward fix. |

- An upgrade is eligible only when the target Release tolerates the current schema revision and
  its migrations move forward from it.
- A roll-back is eligible only when the older Release tolerates the current schema revision.
  Otherwise the installation holds for the operator and a forward fix.
- A contract Release is scheduled only when every Release that the installation might roll back to
  inside the supported window tolerates the contracted shape, and only after the restore checkpoint
  is recorded.
- A migration that stops partway suppresses the installation. The next Plan resumes the same
  forward migration under the same lock and never runs a Release against a shape it doesn't
  tolerate.

The current Hub planner already passes the parsed Release and installation-reported schema
revision through the shared transition validator before signing a Plan. Tolerance endpoints
are inclusive; an upgrade also refuses a target schema below the current revision. Rollback and
recall roll-off retain their separate direction rule. The Agent's workload validators hold
unsupported schema changes before cluster calls.

An application component Release may include a strict `fdai.schema-expand-job.v1` object. It binds
the `fdai.migration-classification.v1` expand-only revision map and an active deadline inside the
signed manifest. The Agent renders no arbitrary command from that object: it uses a fixed
Core-image runner and the installation-reviewed runtime references. The completed Kubernetes Job
is the schema receipt and remains after a workload rollback; the reported schema revision advances
only when that Job has a valid completion receipt. Contract revisions remain unsupported in this
phase and require the later restore-checkpoint Plan.

## Artifact delivery

### Connected installations

The installation imports each Release's images into its own container registry inside the
boundary. The artifacts-missing constraint blocks a Plan until every required digest is present,
as in [Apollo constraints](https://www.palantir.com/docs/apollo/core/plans-and-constraints).
`BoundaryRegistryMirror` tracks mirrored immutable `sha256:<hex>` digests inside the boundary and
feeds `available_artifact_digests` so `plan_next` blocks a Release with `artifact_unavailable`
until every required image digest is mirrored.

### Offline installations

An upgrade bundle carries Releases, channel membership, recall notices, and the minimal image
layers that the Target Hub doesn't already have. The vendor release key signs the bundle's
checksum list. The customer may add its own signed configuration packages to the transfer media,
and the Target Hub verifies each package signature separately.

1. An operator imports the bundle into the Target Hub.
2. The Target Hub verifies the signature and every checksum, publishes images into the registry
   inside the boundary, and updates its catalog.
3. Plans proceed under the normal constraints.

`verify_and_import_upgrade_bundle` verifies the vendor signature over the canonical checksum
manifest, checks the catalog export and every minimal image layer digest, verifies each attached
customer configuration package signature independently, and publishes the verified layer digests
into `BoundaryRegistryMirror`.

The first-installation offline package keeps its current contract. For a Hub-managed offline site,
it also contains the Target Hub.

## Release data model

| Table | Key | Purpose | Time fields | Mutability |
|-------|-----|---------|-------------|------------|
| `release` | `release_id` | Product, version, manifest digest, signature, schema range, dependencies | `published_at`, `recorded_at` | Immutable |
| `release_artifact` | `release_id`, `artifact` | Image digest, SBOM digest, provenance digest | `recorded_at` | Immutable |
| `release_channel` | `channel_id` | Name, default or custom, owning Hub | `effective_from` | Revisioned |
| `channel_membership` | `channel_id`, `release_id` | Pipeline or manual addition, and the actor | `added_at` | Append-only. Removal is a new row. |
| `promotion_pipeline` | `product`, `revision` | Stage order and criteria | `effective_from` | Revisioned |
| `promotion_run` | `run_id` | Stage results and soak observations | `started_at`, `finished_at` | Append-only |
| `recall` | `recall_id` | Release or capability scope, reason, sequence number, signed notice digest | `issued_at`, `recorded_at` | Append-only. Lifting is a new row. |
| `catalog_record` | `role`, `version` | Root, snapshot, or timestamp record and its signature | `signed_at`, `expires_at`, `recorded_at` | Append-only |
| `bundle_import` | `bundle_id` | Checksum digest and import result in a Target Hub | `imported_at` | Append-only |

## Honest limits

- Signed deployment bundles and offline kits implement the one-way channel migration. The local
  Release Hub also has the bounded development capabilities listed above; production catalog trust,
  automated promotion and distribution remain open.
- The production trust-root ceremony hasn't run. A vendor release key must exist before any Hub
  path can verify Releases.
- Reproducible double-build verification of the signed bundle remains open.
- Runtime v3 Releases declare schema ranges, capability maximums and downtime metadata.
  Local planning and pre-effect guards are implemented; physical schema migration and
  old-binary rollback qualification remain separate operational work.

## Related docs

| To learn about | Read |
|----------------|------|
| Lifecycle architecture and Plans | [Hub-Managed Lifecycle](hub-managed-lifecycle.md) |
| Configuration layers and packages | [Lifecycle Configuration](lifecycle-configuration.md) |
| Signed bundles and the deployment CLI | [Installable Deployment CLI](installable-deployment-cli.md) |
| Offline delivery today | [Disconnected Deployment](disconnected-deployment.md) |
| Channel history in the productization plan | [Productization and Extensibility](../fork-and-sequencing/productization-and-extensibility.md) |
| Decision record | [ADR-0003](../architecture/decisions/0003-hub-managed-lifecycle-and-operator-governance.md) |
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/deployment/lifecycle-releases-and-channels.md) |
