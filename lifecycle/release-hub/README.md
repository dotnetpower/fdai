# FDAI Release Hub

For the vendor/customer journey, information handoff and current production gaps, see the
[Hub lifecycle operator guide](../../docs/runbooks/hub-lifecycle-operator-guide.md).

The Release Hub is the vendor's independent application for registering manifests,
publishing development signatures, contributing releases to channels, and recalling releases.
It does not deploy FDAI, build images, publish to a registry, or grant installation authority.

## Layout

| Path | Responsibility |
|------|----------------|
| `src/fdai_release_hub` | Loopback API, development signing and transactional local metadata |
| `ui` | Independent Preact UI using shared Calm Slate tokens and primitives |
| `tests` | API, persistence and Lifecycle Hub consumer regression tests |
| `../hub/src/fdai_lifecycle_hub/catalog_import.py` | Opt-in pinned export admission into the existing catalog |

## Local design, critique, and revised boundary

Initial design: expose vendor publication and channel mutation using the existing runtime
manifest parser and the installation agent's detached Ed25519 signature convention.

Critique: a valid manifest signature does not authenticate its version label, channel membership,
or recall state. It does not prove artifact availability, production trust, or catalog freshness.
An unauthenticated development service cannot safely listen on a public interface.

Revised boundary: this is a local-only, shadow development tool, not a production catalog
protocol. Registration retains exact manifest bytes, and publication signs those bytes with a
development key generated outside the checkout. SQLite transactions bind revision, metadata,
and audit events. Every mutation requires an exact current revision, target confirmation and
reason. Retry after an ambiguous result starts with a read, not an automatic repeated write.
Release ids cannot be reused, recalled releases cannot be republished or added to a channel,
and channel additions are manual curation, not an automatic promotion pipeline.

The export is a local JSON projection of releases, channels and recalls, not signed TUF
metadata. A Lifecycle Hub consumer requires a separately obtained exact SHA-256 pin and a
trusted development public key, verifies each release signature and parses existing manifest
and recall contracts. Changing membership or recalls changes the pin. Consumers reject expired
exports, a lower revision, and a changed export at the same revision. Pins and revision floors
must be retained by the caller; automatic remote sync and durable consumer trust state are not
part of this local CLI. The explicit remote-development profile below persists customer trust
state. Production root, snapshot, timestamp roles and key rotation remain future work.
The default unsigned `load_catalog` development path stays unchanged.

Freshness renewal has a separate boundary. A catalog GET must not silently extend an expired
export, and repeated publication or channel contribution is not a renewal mechanism.
The explicit `POST /v1/catalog/renew` operation reuses the publication lock, current-revision
check and attributed audit. It verifies existing signatures before writing and requires an
advancing clock, reason and exact `renew <revision>` confirmation. It appends one catalog event
without changing release bytes, signatures, channels, recalls or keys. The new revision and
profile-specific expiry change the export pin: 72 hours for private local CLI publication and
24 hours for remote development. Existing local exports keep their original 24-hour expiry and
pin until the next attributed publication or renewal; merely upgrading the executable does not
silently rewrite an export at the same revision. Customers must independently approve the new
pin and explicitly import, or use the separately authorized automatic adoption flow. This is
not production signed freshness or automatic recovery.

Local export admission accepts at most 8 MiB, including JSON decoding. Each manifest still
passes the existing manifest parser's own size and schema limits independently.
The canonical manifest digest identifies the parsed release, while the signed payload digest
hashes its exact original bytes, including whitespace. The UI shows both; neither establishes
registry availability or production trust.

## Running locally

From the repository root, use Python 3.12 or newer:

```bash
uv run --project lifecycle/release-hub fdai-release-hub dev-init /private/release-hub
uv run --project lifecycle/release-hub fdai-release-hub serve /private/release-hub --port 8091
npm --prefix lifecycle/release-hub/ui ci
npm --prefix lifecycle/release-hub/ui run dev
```

The API and UI bind only to `127.0.0.1`. The UI uses port `5291`, proxies the API on `8091`,
and rejects cross-origin mutation requests. No production authentication or key management is
implemented. The key is never returned by an API or accepted through a browser form.
The shared Hub login bootstrap bounds the authentication-configuration request to
10 seconds and displays an authentication error if the service does not respond.
For design review, `/design-previews/edition` is the sole Release Hub preview
(Control and Atelier have been retired). It presents the existing operating
areas-Stencil builder, releases and comparison, channels, deployment requests,
activity, and trust/recall-in a sample-only editorial workspace with selectable
release nodes. Feature sections use the navigation label without extra editorial
headlines or repeated preview disclaimers. The Stencil builder appears first, collapsed until opened; the
release's example components are available only in the collapsed-by-default
"구성 보기" detail of a right-side drawer, which opens on release-node or
table selection and closes on Escape or its close button. The release canvas
has no persistent detail card. The compact version comparison selects only the
baseline version and places baseline and selected values in adjacent columns;
it does not claim to show a real manifest diff. The release list uses consistent
text sizing and unboxed version links while retaining keyboard access to the drawer.
A separate `/design-previews/edition/installations`
screen presents only example registered installations, separates recently
reported versions from stale or missing reports, and explicitly leaves the number
and versions of unregistered installations unknown. Its fixed report times are
fictional; it does not monitor real installations, verify reported runtime effects,
or infer deployment from a planned target. Navigation, filters, and review flows are local to
the preview; no catalog data is read, and no register, publish, promote, recall,
renew, or authentication action is performed there. Use the existing authenticated
operating UI for those effects. The operational `/#/releases` graph and its
authorization remain unchanged.

The authenticated operating UI defaults to `/#/edition`. Unlike
the design preview, it reads the existing catalog through the same authenticated
app and uses the operational lineage graph for its connected version canvas.
Node or list version links go directly to `/#/edition/releases/<version>`; there
is no intermediate drawer. Its back link and browser Back return to the same
highlighted release on the canvas. The sidebar has three destinations:
**Release lineage** (`/#/edition`), **Deployment management** (`/#/channels`
and `/#/deployment-requests`), and **Trust & activity** (`/#/trust` and
`/#/activity`). Each combined destination has two scoped tabs rather than
duplicating the global sidebar. The sidebar and top bars use neutral backgrounds;
active navigation remains visible through text weight and a rule. Release
lineage opens the existing authenticated
Stencil Builder at `/#/edition/new`; original `/#/stencils` and `/#/releases`
bookmarks remain available without appearing in the sidebar. The existing
creation flow returns to the new release in Edition; changes from the Edition
builder or detail return to the Edition detail, while catalog readback still
determines whether their outcome is confirmed.
Keyboard arrows move focus across detail nodes without submitting a promotion;
clicking a stage node reveals its evidence or technical details. Only its
explicit action button starts a one-click operation. The one-click create and
promotion flows require a fresh catalog read, compare the attributed change
after a separate readback, and report incomplete DEV publication separately
from confirmed registration. Failed or uncertain actions disable further
mutations until an operator refreshes the catalog and reviews activity; the
builder remains available for read-only composition. Confirmation dialogs
require typing the exact target instead of pre-filling it. Channel heads use
the highest eligible SemVer, not the first channel member, and explicitly
refreshing the catalog also reloads the deployment request list.
The detail pre-check never marks label or soak observations as passed when
independent measurements are unavailable; an operator-entered gate claim is
not independent proof of health. The current promotion API still accepts
client-supplied requirements and observations, so a trusted policy and
observation source are required before treating those gates as verified.
Trust labels count only verified signed Stencil releases; draft Stencils are
not signed. The expiry warning updates when time passes without a refresh.
Capability recall history links to Trust and appears in the activity for
releases that declare the affected capability. Capability changes require a
typed target and independent catalog event readback before reporting success.
The Trust export button downloads the exact JSON response through the
authenticated request path; it does not open a bare unauthenticated URL.
The full-detail route shows the
existing detailed stage/workload topology and action handlers with an Edition
skin and natural-size, horizontally scrollable nodes; the original
`/#/releases/<version>` remains available. Recorded channel
membership is not proof of a passed gate or deployment effect, and a missing
workload declaration is not replaced with fictional topology nodes.
Edition detail uses unified, undivided node cards with editorial heading type,
quiet layered shadows, deliberate spacing and plain stage labels instead of
internal rule lines or colored fills. The detailed canvas shares the Edition
overview's rounded frame and dotted warm background; status meaning gets only
restrained text-color accents.
Status text and guarded action buttons retain their meaning. Stencil composition, channel
review, deployment request filtering/pagination, activity,
trust and explicit catalog renewal retain their existing authenticated routes
and action confirmation; only navigation and return destinations change.
The separate installation-monitoring design preview is not an operating page:
deployment requests do not establish active installation versions or enrollment.
The state path must resolve outside the checkout, be a private directory with no group or other
access, and contain a key created by `dev-init`. Serve ports must be between 1 and 65535.
Register an existing `fdai.runtime-release.v3` manifest; registration validates metadata only.
Artifact archives, SBOM contents, provenance semantics and registry presence remain unverified.
The optional local label may contain Korean; machine release ids remain canonical SemVer.

When the state argument is omitted, the local CLI uses
`~/.local/state/fdai/lifecycle-preview/release-hub`, the same persistent directory as the
committed local preview task. Initialize its development key explicitly with `dev-init`
before the first `serve`. An explicit state argument still selects another private directory.
Normal startup never loads demo releases or falls back to a temporary fixture database.
The UI lists only manifests registered in the selected database. An empty database shows no
releases; registration and development signatures do not verify a build, image availability,
or deployment. Keep intentional demo catalogs in separate, explicitly selected directories.

An untouched revision-zero empty catalog is labelled **Initial catalog**, not a failed build or
an available update. The trust view still displays the real export expiry and explains that expired
empty metadata cannot be imported. Once a catalog has a revision, release, event, or channel member,
the ordinary expiry warning remains authoritative. No read renews freshness. The absence of
capability recall records means only that no recalls are recorded, not that capabilities are healthy;
recall actions require an operator-authored reason rather than a prefilled test reason.
The Releases and Stencil Builder views also provide 1-click preset and custom Stencil release
creation (`1-Click Create Release` / `1-Click Compose & Register Release`) that composes the
manifest, registers the release, and signs it into `DEV` in one step without modal friction.
Preset one-click generation rejects invalid or existing versions rather than
silently switching to another version. Builder dependency previews do not
overwrite explicit selections, and a source commit must be a real full SHA
instead of a fabricated extension of a short prefix.
Optional add-ons can be selected in the Builder; required and dependency-added
ones stay locked while their prerequisites remain. Derived source commits are
shown only after the compose response supplies their real digest. Malformed
catalog or Stencil response structures produce explicit errors rather than
being treated as usable operational data.
The live Blueprint preview lists the privileged executor Azure role only when
both the executor workload and its governed-execution add-on are selected.
During Stencil composition, `registry_pipeline` inspects built local Docker images (or explicit
`component_digests`), publishes canonical OCI Distribution v2 manifests served at
`/v2/fdai/<component>/manifests/<reference>` and `/v1/registry/images`, and binds the verified
`sha256` digests into `release_manifest.components`.

Build the UI with `npm --prefix lifecycle/release-hub/ui run build`; the API serves the built
application from the same loopback origin when the build exists. The `serve` command never
creates a missing key implicitly. Keep the state directory outside source control.

## Explicit remote-development profile

The default commands above remain unauthenticated and loopback-only. A separate
`python -m fdai_lifecycle_hub.remote` entrypoint supports direct Entra authentication,
service-owned passwordless PostgreSQL, explicit schema revision 2 migration, attributed
publication audit, and a versioned Key Vault development signing-key reference. It rejects
missing configuration/migration instead of silently creating remote state or keys.
Its bundled UI uses operator Entra sign-in; the customer service identity can read only
`/v1/catalog/export`, never publish or operate the customer Hub.

See [Two-Hub development boundaries](../../infra/hubs-development/README.md) for configuration,
safe provisioning, images, migration Jobs, and static/live validation limits. The same test
subscription contains separate networks, ACA environments, database servers, identities,
vaults, and logs, not just separate RGs. This change has not deployed or validated Azure.
Customer pin approval is a separate authenticated operation using an independently obtained
digest/revision. Automatic polling, production TUF metadata/root ceremony, artifact availability,
and Agent apply remain unsupported.

### Review clone deployment requests

Open **Deployment requests** to review subscriptions that reported a clone deployment request.
Every record is **self-reported, ownership unverified**, with status `requested`. It is not
proof of subscription ownership, approval, deployment execution, or success. Intake never
changes catalog revision, expiry, channel membership, or installation authority.

`POST /v1/deployment-requests` accepts a JSON object with exactly these fields (2 KiB body limit):

| Field | Accepted value |
|-------|----------------|
| `request_id` | Stable lowercase SHA-256 hex, 64 characters |
| `subscription_id` | Canonical lowercase UUID |
| `release_id` | Canonical SemVer Release id, at most 64 characters |
| `channel` | `DEV`, `RELEASE_CANDIDATE`, `RELEASE`, or `custom-name`, at most 64 characters |
| `region` | Lowercase Azure location token, at most 64 characters |
| `source_commit` | Lowercase 40-character Git commit hex |
| `catalog_digest` | Lowercase 64-character SHA-256 hex |

Unknown or duplicate fields, credentials, tenant ids, deployment identities, callbacks, and
free-form messages are not accepted. New requests require a published, signature-verified,
non-recalled Release in the selected local catalog channel. The supplied commit and catalog
digest are self-reported metadata, not a verified source binding or independent trust input.
Intake allows eight in-flight requests per server process, bounds body reads to ten seconds,
and caps retained records at 100,000. Busy intake returns `429`, an expired body deadline `408`,
and exhausted capacity or unavailable storage `503`. Exact retries remain readable at capacity.
These local bounds do not replace deployment-edge abuse controls or a reviewed retention policy.

The response contains those seven fields plus server-supplied `recorded_at` (UTC),
`status: "requested"`, and `trust: "self-reported"`. First acceptance returns `201`; an exact
retry of the same request id returns `200` and the original record, even if the Release has
since been recalled. Changed metadata under the same id returns `409`. No automatic retry runs.

With an explicitly configured `public_catalog_export` profile, this POST and the existing
signed catalog export GET are public. All other writes and the request listing retain existing
vendor authentication. Default authenticated remote and loopback-only local behavior is unchanged.
Public intake cannot verify that the submitting party owns the named subscription.

Operator-only `GET /v1/deployment-requests` returns
`{"requests": [...], "limit": 25, "offset": 0, "has_more": false}`. Optional
`subscription_id` filters by exact canonical UUID; `limit` is 1-100 (default 25) and
`offset` is 0-100000, matching the retention cap so every retained page is reachable.
Results sort by `recorded_at` descending, then `request_id` descending.
Unknown or duplicate query fields are not accepted. Subscription rows never enter catalog
views or signed exports. The UI supports filtering, pagination, explicit refresh, and
per-request metadata disclosure, with separate loading, empty, and unavailable states.

Existing revision 1 databases need the explicit remote migration command before serving this
build. The transactional revision 2 expansion preserves catalog data and adds only the request
table and indexes. Remote serving does not migrate implicitly; local initialization keeps its
existing automatic-development-migration behavior. Local tests do not qualify production
intake abuse protection, retention policy, ownership attestation, or successful Azure deployment.

### Renew development catalog freshness

In a build containing renewal, review Releases, Channels and Activity, then open **Catalog trust**
and choose **Renew catalog freshness**. Supply a reason and type `renew <revision>` using the
displayed revision. Confirm once, then read back the new revision, expiry and export pin.
**Refresh catalog** only reads; it never renews. If the write times out, close the dialog and
read Catalog trust and Activity before another attempt. The UI never automatically retries a write.
The customer export-only service and installation Agent cannot renew the vendor catalog.
Follow the [operator guide](../../docs/runbooks/hub-lifecycle-operator-guide.md) for independent
pin approval and explicit customer import. An older deployed build needs an approved update;
don't bypass expiry checks or edit timestamps to recover it.

## Testing

```bash
uv run --project lifecycle/release-hub --with pytest --with pytest-cov --with httpx \
  python -m pytest -q --no-cov -p no:cacheprovider -c /dev/null \
  lifecycle/release-hub/tests lifecycle/hub/tests/test_release_hub_consumer.py \
  lifecycle/hub/tests/test_planning.py lifecycle/hub/tests/test_cli.py
npm --prefix lifecycle/release-hub/ui run typecheck
npm --prefix lifecycle/release-hub/ui test
npm --prefix lifecycle/release-hub/ui run build
```

## Consume a local export

Save `/v1/catalog/export` from the loopback API outside the checkout. Obtain its exact SHA-256
pin separately through the trusted local operator session; do not trust a digest delivered
alongside an untrusted download. Retain the last admitted revision and pin outside the checkout.
For an already enrolled development installation, use the existing Hub signing key and database:

```bash
uv run --project lifecycle/release-hub fdai-lifecycle-hub recompute-pinned \
  installation-alpha --export /private/catalog.json --sha256 "$TRUSTED_CATALOG_SHA256" \
  --release-public-key /private/release-hub/development.pub.pem \
  --minimum-revision "$LAST_ADMITTED_REVISION" --previous-sha256 "$LAST_ADMITTED_SHA256" \
  --key /private/lifecycle-hub.pem
```

On the first admission only, use a revision floor of `0` and omit `--previous-sha256`.
Choose the database with the existing `FDAI_LIFECYCLE_HUB_DATABASE_URL` setting. Tests use SQLite;
no runtime or remote PostgreSQL database is needed. Recall changes the pin and revision. Import
the newly approved export before recomputing; existing issued Plans are not revoked by this tool.

## Signed catalog roles (opt-in)

With a root installed, the Release Hub also serves `GET /v1/catalog/metadata`: a root chain, a
snapshot and a timestamp that vouch for the signed export. The root is signed offline by a
threshold of keys and never touches the Hub; the snapshot and timestamp use two separate online
keys. The renewal task then re-signs only the timestamp and appends no `renew` event.

```bash
# Local development Hub first: create its online keys (after dev-init).
uv run --project lifecycle/release-hub fdai-release-hub tuf-init /private/release-hub
# Offline, each holder for their own key; outside the checkout.
uv run --project lifecycle/release-hub fdai-release-hub root keygen --out-dir /private/ceremony --name root
uv run --project lifecycle/release-hub fdai-release-hub root build --out /private/root-v1.json \
  --version 1 --threshold 2 --root-public /private/ceremony/root-*.pub.pem \
  --snapshot-public /private/release-hub/snapshot.pub.pem \
  --timestamp-public /private/release-hub/timestamp.pub.pem \
  --export-public /private/release-hub/development.pub.pem
uv run --project lifecycle/release-hub fdai-release-hub root sign --record /private/root-v1.json \
  --key /private/ceremony/root-1.pem /private/ceremony/root-2.pem
uv run --project lifecycle/release-hub fdai-release-hub root verify --record /private/root-v1.json
# Install the signed root into the local Hub.
uv run --project lifecycle/release-hub fdai-release-hub install-root /private/release-hub \
  --root /private/root-v1.json
```

Private root keys are read only from files with mode `0600` and are never stored in a Hub. A
remote Release Hub enables `catalog_roles` in its configuration, reads the keys once from
`FDAI_HUB_CATALOG_SNAPSHOT_KEY` and `FDAI_HUB_CATALOG_TIMESTAMP_KEY`, and installs the root with
the `install-catalog-root` operation. The role tables are optional and created by that
operation; they do not move the Release Hub schema revision. A Release Hub with roles installed
stops extending the legacy export expiry, so move customer Hubs to `catalog.trust` first.

## Remaining production work

The production root ceremony with custody receipts, managed custody of the online keys,
authenticated contributor roles, automated promotion gates, custom channels, capability recall
delivery, registry mirroring, upgrade bundles and real FDAI workload deployment remain
unsupported.
The Recall action records local eligibility withdrawal; it does not cancel issued Plans or
roll off running installations. An operator must refresh the pinned export before recomputing.

## Related docs

| To learn about | Read |
|----------------|------|
| Release design | [Lifecycle Releases and Channels](../../docs/roadmap/deployment/lifecycle-releases-and-channels.md) |
| Installation planning | [Lifecycle Hub](../hub/README.md) |
| Current delivery scope | [Implementation ledger](../../docs/roadmap-implementation/deployment/lifecycle-releases-and-channels.md) |
