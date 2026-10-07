# FDAI Lifecycle Hub

`fdai-lifecycle-hub` computes the next signed Lifecycle Plan for each registered installation and
serves it to the installation's lifecycle agent. It reuses the pure Release, configuration, and Plan
checks in `fdai-deployment-cli`, so the Hub and the agent judge a Plan with the same code.

Lifecycle I0 runs in shadow mode, where the Hub observes and decides but nothing applies a change.
It needs no Azure credential and grants no lifecycle authority.

## How a Plan is chosen

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

The Hub computes each configuration digest from the canonical JSON of its content, so a digest
always names exactly one configuration. An admitted report must name the SHA-256 of the exact Plan
bytes it checked, and the Hub rejects a report that names other bytes.

## Layout

| Path | Purpose |
|------|---------|
| `src/fdai_lifecycle_hub/domain.py` | Installation aggregate, reported state, and planning outcomes |
| `src/fdai_lifecycle_hub/catalog.py` | Release catalog and its development directory loader |
| `src/fdai_lifecycle_hub/planning.py` | `plan_next`: chooses the target Release and signs the Plan |
| `src/fdai_lifecycle_hub/signing.py` | Ed25519 development Hub keys |
| `src/fdai_lifecycle_hub/models.py` | SQLAlchemy ORM models for the Hub data model |
| `src/fdai_lifecycle_hub/store.py` | Repository: transactions and row locks |
| `src/fdai_lifecycle_hub/audit.py` | Hash-chained audit records and chain verification |
| `src/fdai_lifecycle_hub/schemas.py` | JSON boundary: request bodies and operator input files |
| `src/fdai_lifecycle_hub/api.py` | Agent HTTP API |
| `src/fdai_lifecycle_hub/cli.py` | `fdai-lifecycle-hub` command line |
| `tests/` | Hub-owned tests; the PostgreSQL variants run only when `FDAI_DATABASE_URL` is set |

## Agent API

| Method and path | Result |
|-----------------|--------|
| `GET /v1/installations/{id}/plan` | `200` with `{"plan": {"signed_payload", "signature"}}` in base64, or `204` when no Plan is open |
| `POST /v1/installations/{id}/plans/{plan_id}/reports` | `202` for a new or identical report, `409` for a conflicting attempt or other Plan bytes, `422` for an invalid body, `503` with `Retry-After` when a concurrent write committed first |
| `GET /healthz` | `200` |

`signed_payload` is exactly the canonical Plan bytes that the signature covers. A report's
`exact_plan_digest` is `sha256:` followed by the hex SHA-256 of those bytes.

## Try it locally

The Hub has its own lock file, like `packages/deployment-cli`, so `uv run` installs and runs the
`fdai-lifecycle-hub` command. [samples/](samples) holds three sample Releases and one
installation on 1.4.0 whose maintenance window is open all day. SQLite needs no setup.

Run these from `lifecycle/hub/`:

```bash
mkdir -p /tmp/fdai-hub
export FDAI_LIFECYCLE_HUB_DATABASE_URL=sqlite+pysqlite:////tmp/fdai-hub/hub.db

uv run fdai-lifecycle-hub migrate
uv run fdai-lifecycle-hub dev-keygen /tmp/fdai-hub/hub.pem
uv run fdai-lifecycle-hub register samples/installation.json
uv run fdai-lifecycle-hub recompute example --catalog samples/catalog --key /tmp/fdai-hub/hub.pem
uv run fdai-lifecycle-hub show example
```

`recompute` prints `"outcome": "issued"` with target `1.6.0`. Run it again and it prints
`"unchanged"`, because nothing changed.

Start the API in a second terminal with the same environment variable, then read the Plan as an
agent would:

```bash
uv run fdai-lifecycle-hub serve
curl -s localhost:8090/v1/installations/example/plan | jq -r .plan.signed_payload | base64 -d | jq
```

Record the upgraded state, and the Hub reports that nothing is left to do:

```bash
uv run fdai-lifecycle-hub record-state example samples/state-1.6.0.json
uv run fdai-lifecycle-hub recompute example --catalog samples/catalog --key /tmp/fdai-hub/hub.pem
curl -s -o /dev/null -w "%{http_code}\n" localhost:8090/v1/installations/example/plan
```

`recompute` prints `"up-to-date"`, and the API answers `204`. Execution reports come from the
lifecycle agent (#1951); `tests/test_api.py` covers them.

The database URL comes only from `FDAI_LIFECYCLE_HUB_DATABASE_URL`, so credentials stay out of
process arguments. For PostgreSQL, use the loopback database from `infra/local/docker-compose.yml`.
A catalog directory contains `releases/<release-id>.json` runtime release manifests,
`channels.json` (`{"<channel>": ["<release-id>", ...]}`), and an optional `recalls.json`.

## Limits

- The API binds to loopback and has no caller authentication. Agent identity is Lifecycle I1 work.
- `migrate` creates the schema directly. Versioned migrations replace it in Lifecycle I1.
- Catalog files are trusted as-is. Vendor signatures on Releases and recalls are Lifecycle I2 work.
- Signing keys are development keys from `dev-keygen` (#1947).
- Enrollment approval, configuration package import, and Hub commands are later stories.
- Entities aren't revisioned yet. Entity revisions with `effective_from` arrive with enrollment.
