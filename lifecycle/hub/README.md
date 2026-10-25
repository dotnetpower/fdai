# FDAI Lifecycle Hub

`fdai-lifecycle-hub` enrolls installations, computes the next signed Lifecycle Plan for each
enrolled installation, and serves it to the installation's lifecycle agent. It reuses the pure
Release, configuration, and Plan checks in `fdai-deployment-cli`, so the Hub and the agent judge a
Plan with the same code.

Lifecycle I0 runs in observation mode (shadow mode): the Hub decides and records what the agent
reports, but never applies a change itself. It needs no Azure credential and grants no lifecycle
authority.

## Local Release Hub catalog admission

The separate [Release Hub](../release-hub/README.md) provides a local-only vendor UI and export.
`recompute-pinned` accepts that export only with an out-of-band SHA-256 pin, a trusted development
public key, an expiry check, and an operator-retained revision floor. It reuses the existing
manifest parser, detached signature convention, recall records, and planner. The ordinary
`recompute --catalog` development directory loader remains unchanged. This opt-in transport is
not a production signed catalog protocol and does not prove registry availability.

## Explicit remote-development profile

Local CLIs keep their loopback defaults. The independent
`python -m fdai_lifecycle_hub.remote` entrypoint requires direct Entra operator authentication,
its own passwordless PostgreSQL identity, a separately provisioned development signing key,
and explicit schema revision 1 migration. It never trusts ACA principal headers.
The existing enrollment approval API binds the approver to the verified operator OID.
Without explicit installation Agent bindings, enrollment/state/report/Plan transport remains
closed. The opt-in [Agent preparation](../agent/README.md#remote-development-preparation) opens
only an installation-bound Agent's Plan/state/report routes.

For a bound installation, an authenticated operator can submit a signed enrollment through
`POST /v1/enrollments/{installation_id}/requests`. The body uses the existing `signed_payload`
and `proof` base64 fields. The Hub verifies the installation signature, request freshness,
matching installation id and request-size limit, and audits the verified operator as
`requested_by`, including proof failures. Submission creates only a pending request visible in
Enrollment requests; approval remains separate and Entities remain unmanaged. Empty bindings
retain the existing closed route, and the original Agent enrollment route stays closed even to
an operator.

The Agent bound to exactly one installation can also propose that installation's pending
enrollment through `POST /v1/installations/{installation_id}/enrollment-request` (see
`fdai-lifecycle-agent enroll`). It requires the exact object/client binding, `Agent.Access` and
no delegated `scp`, reuses the proof, freshness, matching-id and size checks, and audits the
Agent object id as `requested_by` with `requested_via=agent`. The Agent cannot approve, reject,
manage Entities, record ownership or set `settings.product`, and an operator token cannot use
this route. Enrollment requests shows who proposed each pending request.

`GET /v1/enrollments/bindable` lists the bound installation IDs with their status.
`fdai-lifecycle-hub sign-enrollment <request.json> --key <installation.pem> --out <file>` signs
inside the installation boundary and writes only the upload file; it prints the key id and the
submission deadline and refuses to overwrite an existing file.

In the operator UI, open **Enrollment requests**, select the bound installation,
and choose the signed request JSON file. **Submit request** sends only its `signed_payload`
and `proof` fields to that operator route. Files are limited to 64 KiB; private keys must
never be uploaded. A successful submission remains pending and requires a separate approval
after independent installation-key verification. If submission times out, refresh the pending
list before retrying; the UI never retries automatically.

The **Updates** screen is the pull-only path. The Lifecycle Hub polls the bound Release Hub on
`catalog.check_interval_seconds`, verifies the Release key's signature over the exact export
bytes, and evaluates the packaged Rego policy (`policy/catalog_adoption.rego`, run with the
`opa` binary). In `auto` mode a change inside the standing authorization is adopted and Plans are
issued for enrolled installations. Otherwise the candidate waits for **Review and apply**. The
default is `review`; a missing signature, key, engine or authorization never adopts. Routes:
`GET /v1/catalog/updates`, `POST /v1/catalog/updates/check` and `POST /v1/catalog/updates/apply`.
Release Hub never calls this Hub. See [Automatic catalog adoption](../../docs/roadmap/deployment/lifecycle-releases-and-channels.md#automatic-catalog-adoption).

With `catalog.trust` set to `{ "mode": "tuf", "root_key_ids": [...], "root_threshold": n }` in place
of `release_public_key`, the poll verifies TUF-style signed roles instead of one key: the root
chain from the pinned keys (rotation needs the previous threshold), the snapshot and timestamp,
the export digest and revision they bind, and persisted anti-rollback floors
(`catalog_integrity_state`, created by `bind-catalog`). The Rego policy gains `integrity` facts
and the reasons `integrity_not_verified`, `timestamp_expired` and `root_rotation_requires_review`.
An expired timestamp adopts only recalls and plans only `recall-rolloff`; a root rotation always
waits for a person. **Updates** shows the root, snapshot and timestamp versions and expiry, and
`GET /v1/catalog/updates` carries an `integrity` object. A bound database refuses a changed
trust, so switching an installation from the single key needs a fresh binding. See
[Catalog integrity](../../docs/roadmap/deployment/lifecycle-releases-and-channels.md#signed-catalog-roles-in-the-hubs)
and the [operator guide](../../docs/runbooks/hub-lifecycle-operator-guide.md#c1-use-signed-catalog-roles-opt-in).

The Catalog import screen separates independent exact-pin approval from one bounded outbound
import using the customer's managed identity. Accepted bytes, digest, key binding, revision
floor, and approval/import audit survive restart in PostgreSQL. The existing planner revalidates
the persisted catalog, including expiry; publishing metadata alone never proves artifact
availability. No operation here applies a Plan or deploys FDAI.

The same screen supports reviewed customer-local membership from the fresh accepted `RELEASE`
set. It records exact catalog/key/Release bindings, operator attribution and a local revision;
the planner retains that provenance without changing subscriptions or execution approval.
Run the existing explicit migration before serving schema revision 4; older binaries hold on
that schema rather than ignore curation. See the [paired channel contract](../../docs/roadmap/deployment/lifecycle-releases-and-channels.md#customer-local-channel-curation-design-and-critique)
for bounds, expiry/recall holds, immutable history and the absence of a destructive downgrade.

**Available releases** reads the accepted catalog without fetching or importing it. Every read
revalidates its accepted pin, signatures and expiry; an unavailable catalog returns `503`, not
an empty success. The read-only **Configuration packages** screen lists stored revision metadata
and enrolled installation references, never configuration values or sealed identifiers. Enrollment can
create a revision without independent package signature provenance, so the screen explicitly
shows **Not recorded** rather than claiming signed-input readiness. Neither route is available
to an Agent identity.

See the [operator guide](../../docs/runbooks/hub-lifecycle-operator-guide.md) for diagrams,
responsibilities, the source of each identifier, human enrollment steps and production gaps.

See [Two-Hub development boundaries](../../infra/hubs-development/README.md) for images,
separate IaC boundaries, safe key/database provisioning, manual migration Jobs, validation
commands, and the remaining live Azure acceptance checks. Browser interaction tests cover
desktop and constrained layouts with built assets and synthetic API responses, not live Entra.
This development path does not change source or offline installation contracts.

Without operator login configured, either product's bundled UI displays only its own runtime
status and explicitly unavailable management APIs. Health and database-readiness probes are
independent and bounded to five seconds. A failed connection, invalid JSON or timeout marks only
that probe unavailable; the product heading, management notice and other probe's result remain.
This status page does not enable anonymous management access.

## Enrollment and managed Entities

1. The installation signs an enrollment request with its installation key and submits it. The
   request carries the installation's settings, configuration, declared Entities, and reported
   state. The Hub checks the proof with an injected verifier against the exact request bytes and
   accepts a `requested_at` no more than five minutes from its own clock. A failed proof creates
   nothing: the Hub audits `enrollment_proof_invalid` or `enrollment_proof_stale` and refuses the
   request. The request reaches the Hub three ways: the loopback `enrollment` route, an operator
   upload through `POST /v1/enrollments/{id}/requests`, or, in the explicit remote profile, the
   installation Agent bound to exactly that installation through
   `POST /v1/installations/{id}/enrollment-request` (`fdai-lifecycle-agent enroll`). Every way
   creates only a pending request, and the audit records `requested_by` and `requested_via`.
2. The installation is `pending`. It receives no Plan, the Hub doesn't recompute it, and it
   accepts no reported state or suppression.
3. A customer approver uses the operator UI or `approve` with the installation key id they
   verified out of band, or rejects with a reason code. The audit records the approver.
   Operator approval is separate from submission; an installation can't approve itself through
   the agent API. Rejection is final.
4. Every Entity starts unmanaged. `record-ownership` records an Entity's ownership evidence, and
   the audit keeps the operator who supplied it and its digests. Ownership is proven only by a Foundation receipt digest together with a Terraform state
   digest. The `fdai:managed=true` tag alone records `ownership_tag_only`, and anything less than
   both digests records `ownership_unproven`.
5. `manage` gives an Entity with proven ownership its settings: override blocks by Release version
   range. The shared configuration resolver must accept them and find a block that covers the
   Entity's running Release. An Entity with settings is managed, and only managed Entities appear
   in Plans.

## How a Plan is chosen

An enrolled installation without a managed Entity gets `no-managed-entity` and no Plan.
Otherwise:

1. The Hub lists the Releases on the installation's channel that are newer than its oldest managed
   entity, newest first.
2. It skips a Release that a Release-specific check blocks, such as a recall, the version range, the
   schema range, a missing artifact, or data residency.
3. For the first Release that passes, a closed maintenance window or an active suppression makes the
   installation wait. The Hub doesn't fall back to an older Release.
4. Otherwise the Hub signs a Plan with the next sequence number. If the open Plan already targets the
   same Release from the same reported state and configuration, the Hub keeps it.

Every recompute records its outcome and every constraint result. Every change appends to a
hash-chained audit.

Secret values never enter the Hub. Configuration values and Entity settings pass the shared
configuration-package secret scan, so a literal value under a secret-bearing key is refused and
only a Key Vault reference is accepted.

The Hub computes each configuration digest from the canonical JSON of its content, so a digest
always names exactly one configuration. Every report except `rejected` must name the SHA-256 of the
exact Plan bytes it checked, and the Hub rejects a report that names other bytes.

## Apply reports and failure holds

An agent that applies a Plan reports `apply-started` with attempt *k* right before the change, then
`applied` (reason code `applied`) or `rolled-back` (reason code `health_check_failed` or
`apply_failed`) with attempt *k*+1. The Hub doesn't apply anything itself.

A new `rolled-back` report holds every Entity of its Plan in the same transaction: the Hub adds an
`entity:<id>` suppression with origin `failure`, the failed Plan id, and a 24-hour end, and audits
it. The agent API stops serving the Plan at once, and the next `recompute` waits with
`suppression_window_active` instead of planning the failed Release again. `unsuppress --scope
entity:<id>` lifts the hold early, and `show` lists every active suppression with its origin.

After an apply or a rollback, the agent reports its new snapshot with
`POST /v1/installations/{id}/state`. The Hub checks it as `record-state` does: the snapshot must be
newer than the current one, include every managed Entity, and name only known Entities.

## Layout

| Path | Purpose |
|------|---------|
| `src/fdai_lifecycle_hub/domain.py` | Installation aggregate, reported state, and planning outcomes |
| `src/fdai_lifecycle_hub/entity.py` | Entities, ownership evidence, and settings |
| `src/fdai_lifecycle_hub/enrollment.py` | Enrollment requests, key proof, and enrollment status |
| `src/fdai_lifecycle_hub/catalog.py` | Release catalog and its development directory loader |
| `src/fdai_lifecycle_hub/planning.py` | `plan_next`: chooses the target Release and signs the Plan |
| `src/fdai_lifecycle_hub/signing.py` | Ed25519 development Hub keys |
| `src/fdai_lifecycle_hub/models.py` | SQLAlchemy ORM models for the Hub data model |
| `src/fdai_lifecycle_hub/store.py` | Repository: one transaction per public method |
| `src/fdai_lifecycle_hub/rows.py` | Row lookups, locks, and small row writes the transactions share |
| `src/fdai_lifecycle_hub/mapping.py` | Mapping between ORM rows and domain records |
| `src/fdai_lifecycle_hub/reports.py` | Report outcomes, their reason codes, and failure holds |
| `src/fdai_lifecycle_hub/errors.py` | Requests the Hub refuses |
| `src/fdai_lifecycle_hub/audit.py` | Hash-chained audit records and chain verification |
| `src/fdai_lifecycle_hub/schemas.py` | JSON boundary: request bodies, operator input files, and the UI's read-only view records |
| `src/fdai_lifecycle_hub/api.py` | The agent HTTP API, the operator UI's read-only and approval routes, and serving the built UI |
| `src/fdai_lifecycle_hub/cli.py` | `fdai-lifecycle-hub` command line |
| `tests/` | Hub-owned tests; the PostgreSQL variants run only when `FDAI_DATABASE_URL` names a loopback database |
| `ui/` | The operator UI: a read-only Preact and Vite single-page app. See [Operator UI](#operator-ui) |

## Agent API

| Method and path | Result |
|-----------------|--------|
| `POST /v1/installations/{id}/enrollment` | `202` with the installation key id for a pending request, `403` with `enrollment_proof_invalid` or `enrollment_proof_stale`, `409` when the installation exists, `422` for an invalid body or another installation id |
| `POST /v1/installations/{id}/enrollment-request` | Remote profile only, for the Agent bound to exactly this installation (`Agent.Access`, no `scp`). Same body and checks as the enrollment route; `202` pending, `403` for any other caller, an invalid proof or a stale request, `409` `installation_exists`, `413` above 64 KiB, `422`. It creates a pending request only; the Agent cannot approve, reject, manage Entities or record ownership |
| `GET /v1/installations/{id}/plan` | `200` with `{"plan": {"signed_payload", "signature"}}` in base64, or `204` when the installation isn't enrolled or no Plan is open |
| `POST /v1/installations/{id}/plans/{plan_id}/reports` | `202` for a new or identical report, `409` for a conflicting attempt or other Plan bytes, `413` above 16 KiB, `422` for an invalid body, `503` with `Retry-After` when a concurrent write committed first |
| `POST /v1/installations/{id}/state` | `202` when the snapshot becomes current, `409` with `stale_state` when its `observed_at` isn't newer, `413` above 64 KiB, `422` with `state_invalid`, `404` for an unknown or unenrolled installation |
| `GET /healthz` | `200` |

## Operator UI API

Read-only routes for the installations and Plans screens, and the two routes an approver's
browser calls to decide a pending enrollment. Like the agent API, these serve on loopback only
and have no caller authentication yet (see [Limits](#limits)).

Enrollment decisions require `Content-Type: application/json` and a loopback Host.
When the browser sends `Origin`, it must match the request's scheme, Host, and port;
cross-site requests are refused before their bodies are read. The Vite development
proxy preserves Host and Origin, so browser decisions stay same-origin in both modes.
This protects browser requests against cross-origin submission; it is not authentication.
Installation details include only suppressions active at the Hub's current clock.
Declared Entities missing from the latest report keep their rows with `null` release
and health values, displayed as "Not reported".

| Method and path | Result |
|-----------------|--------|
| `GET /v1/configurations` | `200` with stored revision digests, timestamps, counts and enrolled installation references; pending/rejected requests retain revision metadata without installation links; package signature provenance is explicitly `not-recorded`; values and sealed identifiers are omitted |
| `GET /v1/catalog/releases` (remote catalog profile) | `200` with accepted and reverified Release metadata; `503` when unimported, invalid or expired; never fetches/imports or asserts registry readiness |
| `GET /v1/installations` | `200` with every enrolled installation's channel, current and target Release, latest outcome, health, and the next maintenance window with whether it's already open |
| `GET /v1/installations/{id}` | `200` with settings, Entities, suppressions, the open Plan, the last evaluation, and every report; `404` for an unknown or not-yet-enrolled installation |
| `GET /v1/installations/{id}/plans/{plan_id}` | `200` with the Plan's status (`open` or `superseded`), its events, every report, and every recompute that targeted it; `404` for an unknown Plan |
| `GET /v1/enrollments/pending` | `200` with every pending enrollment request: the installation key id, requested time, `requested_by` and `requested_via` (`agent` or `operator`, `null` for a signed file or older record), settings, and declared Entities (unmanaged; ownership evidence doesn't exist until after approval) |
| `GET /v1/enrollments/pending/{id}` | `200` with one pending request's full detail; `404` when it isn't pending |
| `POST /v1/installations/{id}/enrollment/approve` | Body `{"approver", "installation_key_id"}`. `200` with `{"enrolled": id}`, `409` with `not_pending`, `422` with `installation_key_mismatch` or `approval_invalid` |
| `POST /v1/installations/{id}/enrollment/reject` | Body `{"approver", "reason"}`. `200` with `{"rejected": id}`, `409` with `not_pending`, `422` with `rejection_invalid` |

An enrollment body is `{"signed_payload", "proof"}` in base64. `signed_payload` is the JSON request
with `installation_key` (the raw Ed25519 public key in base64) and a timezone-aware
`requested_at`, and `proof` is the installation key's signature over exactly those bytes.

A Plan's `signed_payload` is exactly the canonical Plan bytes that the signature covers. A report's
`exact_plan_digest` is `sha256:` followed by the hex SHA-256 of those bytes. A report's `outcome` is
`dry-run-admitted`, `rejected`, `apply-started`, `applied`, or `rolled-back`; only `rejected` may
omit the digest. A state body has the shape of [samples/state-1.6.0.json](samples/state-1.6.0.json).

## Try it locally

The Hub has its own lock file, like `packages/deployment-cli`, so `uv run` installs and runs the
`fdai-lifecycle-hub` command. [samples/](samples) holds three sample Releases, an enrollment
request for one installation on 1.4.0 whose maintenance window is open all day, ownership evidence,
and Entity settings. SQLite needs no setup.

Run these from `lifecycle/hub/`. `migrate` refuses a database that an earlier Hub created, because
Lifecycle I0 has no migrations, so start from a new database file:

```bash
mkdir -p /tmp/fdai-hub && rm -f /tmp/fdai-hub/hub.db
export FDAI_LIFECYCLE_HUB_DATABASE_URL=sqlite+pysqlite:////tmp/fdai-hub/hub.db

uv run fdai-lifecycle-hub migrate
uv run fdai-lifecycle-hub dev-keygen /tmp/fdai-hub/hub.pem
uv run fdai-lifecycle-hub dev-keygen /tmp/fdai-hub/installation.pem
uv run fdai-lifecycle-hub dev-enroll samples/enrollment.json --key /tmp/fdai-hub/installation.pem
uv run fdai-lifecycle-hub show example
```

`dev-enroll` stands in for the lifecycle agent: it adds the installation's public key and the
current time to the request, signs it, and submits it. It prints the installation key id, and
`show` prints `"enrollment": "pending"` with no Plan. Approve the enrollment with that key id:

```bash
uv run fdai-lifecycle-hub approve example --approver alice --installation-key-id <key-id>
uv run fdai-lifecycle-hub recompute example --catalog samples/catalog --key /tmp/fdai-hub/hub.pem
```

`recompute` prints `"no-managed-entity"`, because the `core` Entity starts unmanaged. Tag-only
evidence keeps it unmanaged, so `manage` fails with `ownership_tag_only`. Proven ownership lets
`manage` succeed:

```bash
uv run fdai-lifecycle-hub record-ownership example core samples/ownership-tag-only.json --operator bob
uv run fdai-lifecycle-hub manage example core samples/core-settings.json --operator bob
uv run fdai-lifecycle-hub record-ownership example core samples/ownership.json --operator bob
uv run fdai-lifecycle-hub manage example core samples/core-settings.json --operator bob
uv run fdai-lifecycle-hub recompute example --catalog samples/catalog --key /tmp/fdai-hub/hub.pem
uv run fdai-lifecycle-hub show example
```

`recompute` now prints `"outcome": "issued"` with target `1.6.0`. Run it again and it prints
`"unchanged"`, because nothing changed.

Start the API in a second terminal with the same environment variable, then read the Plan as an
agent would:

```bash
uv run fdai-lifecycle-hub serve
curl -s localhost:8090/v1/installations/example/plan | jq -r .plan.signed_payload | base64 -d | jq
```

Hold the Plan with a suppression. While a suppression that covers the open Plan is active, the API
stops serving it and answers `204`, even before anyone recomputes. A suppression set to start later
takes effect at its start time. `recompute` then prints `"waiting"` with
`suppression_window_active`, and after `unsuppress` the next `recompute` issues a new Plan:

```bash
uv run fdai-lifecycle-hub suppress example --minutes 60
uv run fdai-lifecycle-hub recompute example --catalog samples/catalog --key /tmp/fdai-hub/hub.pem
uv run fdai-lifecycle-hub unsuppress example
uv run fdai-lifecycle-hub recompute example --catalog samples/catalog --key /tmp/fdai-hub/hub.pem
```

`--scope` takes `installation` (the default), `entity:<entity-id>`, or `plan:<plan-type>`. A
suppression covers a Plan only when its scope names the installation, that Plan's type, or one of
its entities, the same rule the shared constraint check uses.

Record the upgraded state, and the Hub reports that nothing is left to do:

```bash
uv run fdai-lifecycle-hub record-state example samples/state-1.6.0.json
uv run fdai-lifecycle-hub recompute example --catalog samples/catalog --key /tmp/fdai-hub/hub.pem
curl -s -o /dev/null -w "%{http_code}\n" localhost:8090/v1/installations/example/plan
```

`recompute` prints `"up-to-date"`, and the API answers `204`. Execution reports come from the
lifecycle agent (#1951), and `show` lists every report on the installation's Plans with its reason
code. [`test_lifecycle_loop.py`](../tests/test_lifecycle_loop.py) runs the agent against this API
end to end.

The database URL comes only from `FDAI_LIFECYCLE_HUB_DATABASE_URL`, so credentials stay out of
process arguments. For PostgreSQL, use the loopback database from `infra/local/docker-compose.yml`.
A catalog directory contains `releases/<release-id>.json` runtime release manifests,
`channels.json` (`{"<channel>": ["<release-id>", ...]}`), and an optional `recalls.json`.

## Operator UI

[`ui/`](ui) is a small read-only Preact, Vite, and TypeScript single-page app: the installations
list, one installation's detail, one Plan's detail, and the pending-enrollment list and approval
screen. It calls only the [Operator UI API](#operator-ui-api) above, and the Hub serves it as a
static build from `ui/dist/` - there's no separate frontend server in production. It shares the
Console's `ui/calm-slate-tokens.css` and `ui/calm-slate-primitives.css` foundation but keeps its
own accent (`--lc-accent`, teal) and sidebar instead of Console's steel-blue lockup, so the two
stay visually distinguishable: the Hub sits outside every installation and keeps working when one
installation's Console doesn't (see the design note in #1945).

The installations list separates update status from reported health and supports filtering by
installation ID. Use **Refresh** to fetch a new snapshot; the UI does not stream agent state.
Installation and Plan details show every recorded constraint block, including its reason code
and details. Failed reads offer **Try again** without reloading the application. Loading
placeholders and enrollment submissions honor the reduced-motion preference.

For local development, run the Hub API from this directory as in
[Try it locally](#try-it-locally), then in a second terminal:

```bash
cd ui
npm install
npm run dev
```

Vite serves the UI on `http://127.0.0.1:5290` and proxies `/v1` and `/healthz` to the Hub API on
its default port, 8090. If that port is already in use, start the Hub with `serve --port 8099`
and run `FDAI_HUB_API_URL=http://127.0.0.1:8099 npm run dev`.
For a production-shaped check, build it and let the Hub serve the result:

```bash
npm run build
cd ..
uv run fdai-lifecycle-hub serve
```

`serve` picks up `ui/dist/` automatically when it exists; pass `--ui <path>` to serve a different
build, or omit the build entirely to run the Hub API alone. `npm test` runs the UI's Vitest unit
tests, and `npm run typecheck` runs strict TypeScript across the app and its tests.

## Limits

- The API binds to loopback and has no caller authentication. Agent identity is Lifecycle I1 work.
- `migrate` creates the schema directly and refuses tables from an earlier Hub schema. Versioned
  migrations replace it in Lifecycle I1.
- Catalog files are trusted as-is. Vendor signatures on Releases and recalls are Lifecycle I2 work.
- Signing keys are development keys from `dev-keygen` (#1947).
- The enrollment proof binds the request bytes to the installation key and a five-minute window,
  not to a Hub-issued challenge or a Hub identity. Without caller authentication, a request signed
  with any key can claim a free installation id, and rejecting it keeps the id. Every failed proof
  also appends an audit record, so the API needs a rate limit before it leaves loopback.
  Re-enrollment and rate limiting arrive with agent authentication in Lifecycle I1. The enrollment
  screen exists, but whoever can reach the loopback API can approve or reject through it; Microsoft
  Entra ID sign-in and key rotation for approvers are later stories.
- The Hub records ownership evidence as digests that the installation reports. It doesn't verify
  the Foundation receipt signature or match it to the Terraform state. By design the installation
  agent checks both locally; that check arrives with its ownership-evidence inputs in Lifecycle I1.
- Entity settings are stored and checked but don't change Plans yet. Configuration package import
  and Hub commands are later stories.
- Suppressions live on the installation record without an actor. A failure hold records its origin
  and failed Plan id. The design's revocable `lifecycle_command` record, with actor and expiry,
  arrives with Hub commands.
- A failure hold lasts a fixed 24 hours, and repeated failures don't suppress the whole
  installation yet. The Hub doesn't check that `applied` or `rolled-back` follows `apply-started`,
  and it treats the reported-state digest as an opaque value.
- Entities aren't revisioned yet. `manage` replaces an Entity's settings, and the hash-chained audit
  keeps who changed them, when, and the settings digest, but not the earlier content. Entity
  revisions with `effective_from` arrive with versioned migrations.
