# FDAI Lifecycle Hub

`fdai-lifecycle-hub` enrolls installations, computes the next signed Lifecycle Plan for each
enrolled installation, and serves it to the installation's lifecycle agent. It reuses the pure
Release, configuration, and Plan checks in `fdai-deployment-cli`, so the Hub and the agent judge a
Plan with the same code.

Lifecycle I0 runs in observation mode (shadow mode): the Hub decides, but nothing applies a change.
It needs no Azure credential and grants no lifecycle authority.

## Enrollment and managed Entities

1. The installation signs an enrollment request with its installation key and submits it. The
   request carries the installation's settings, configuration, declared Entities, and reported
   state. The Hub checks the proof with an injected verifier against the exact request bytes and
   accepts a `requested_at` no more than five minutes from its own clock. A failed proof creates
   nothing: the Hub audits `enrollment_proof_invalid` or `enrollment_proof_stale` and refuses the
   request.
2. The installation is `pending`. It receives no Plan, the Hub doesn't recompute it, and it
   accepts no reported state or suppression.
3. A customer approver runs `approve` with the installation key id they verified out of band, or
   `reject` with a reason code. The audit records the approver. Approval is a command-line action
   only, so an installation can't approve itself through the agent API. Rejection is final.
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
always names exactly one configuration. An admitted report must name the SHA-256 of the exact Plan
bytes it checked, and the Hub rejects a report that names other bytes.

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
| `src/fdai_lifecycle_hub/store.py` | Repository: transactions and row locks |
| `src/fdai_lifecycle_hub/mapping.py` | Mapping between ORM rows and domain records |
| `src/fdai_lifecycle_hub/errors.py` | Requests the Hub refuses |
| `src/fdai_lifecycle_hub/audit.py` | Hash-chained audit records and chain verification |
| `src/fdai_lifecycle_hub/schemas.py` | JSON boundary: request bodies and operator input files |
| `src/fdai_lifecycle_hub/api.py` | Agent HTTP API |
| `src/fdai_lifecycle_hub/cli.py` | `fdai-lifecycle-hub` command line |
| `tests/` | Hub-owned tests; the PostgreSQL variants run only when `FDAI_DATABASE_URL` is set |

## Agent API

| Method and path | Result |
|-----------------|--------|
| `POST /v1/installations/{id}/enrollment` | `202` with the installation key id for a pending request, `403` with `enrollment_proof_invalid` or `enrollment_proof_stale`, `409` when the installation exists, `422` for an invalid body or another installation id |
| `GET /v1/installations/{id}/plan` | `200` with `{"plan": {"signed_payload", "signature"}}` in base64, or `204` when the installation isn't enrolled or no Plan is open |
| `POST /v1/installations/{id}/plans/{plan_id}/reports` | `202` for a new or identical report, `409` for a conflicting attempt or other Plan bytes, `422` for an invalid body, `503` with `Retry-After` when a concurrent write committed first |
| `GET /healthz` | `200` |

An enrollment body is `{"signed_payload", "proof"}` in base64. `signed_payload` is the JSON request
with `installation_key` (the raw Ed25519 public key in base64) and a timezone-aware
`requested_at`, and `proof` is the installation key's signature over exactly those bytes.

A Plan's `signed_payload` is exactly the canonical Plan bytes that the signature covers. A report's
`exact_plan_digest` is `sha256:` followed by the hex SHA-256 of those bytes.

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
  Re-enrollment and rate limiting arrive with agent authentication in Lifecycle I1. Approvers aren't authenticated; Microsoft Entra
  ID sign-in, key rotation, and the enrollment screen are later stories.
- The Hub records ownership evidence as digests that the installation reports. It doesn't verify
  the Foundation receipt signature or match it to the Terraform state. By design the installation
  agent checks both locally; that check arrives with its ownership-evidence inputs in Lifecycle I1.
- Entity settings are stored and checked but don't change Plans yet. Configuration package import
  and Hub commands are later stories.
- Suppressions live on the installation record without an actor. The design's revocable
  `lifecycle_command` record, with actor and expiry, arrives with Hub commands.
- Entities aren't revisioned yet. `manage` replaces an Entity's settings, and the hash-chained audit
  keeps who changed them, when, and the settings digest, but not the earlier content. Entity
  revisions with `effective_from` arrive with versioned migrations.
