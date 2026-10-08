# Lifecycle agent

This package is the Lifecycle I0 skeleton of the in-cluster lifecycle agent described in
[Hub-Managed Lifecycle](../../docs/roadmap/deployment/hub-managed-lifecycle.md). It polls the
Lifecycle Hub, admits a signed Plan, verifies the signed Release and configuration package,
computes the change it would make, and reports the result. It never applies anything.

## Boundary

- No Kubernetes or Azure client is imported, and no write is performed. `tests/test_no_write.py`
  proves this statically and in a fresh interpreter.
- Only `hub_client.py` opens a network connection, and only outbound to the Hub. Plain HTTP is
  accepted only for a loopback Hub, because the Lifecycle I0 Hub has no authentication.
- The maximum effect envelope is derived locally. `--local-policy` sets the hard limit. The signed
  Release's `capabilities.<id>.maximum_mode` lowers each capability mode and drops any capability
  the Release doesn't name, and a `region` in the signed configuration narrows the regions. Neither
  signed input can widen the limit, and a Hub Plan can only narrow the result.
- An admitted report carries a reason code, `exact_plan_digest` (`sha256:` and the hex SHA-256 of
  the decoded `signed_payload`), and a summary string with counts only. Entity ids, digests,
  installation identifiers, and secrets stay inside the installation. A rejection reports only its
  reason, with a `null` digest and an empty summary.
- Development test keys are generated outside the repository (#1947). Only public keys are read.

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
   of `parse_runtime_release_manifest`, and the configuration package must resolve for the target
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
   unreachable. Only a `409 report_conflict` makes the next poll start a new `attempt`. A reported
   Plan is not evaluated again.

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
| `--inputs-dir` | `releases/<digest>.json` (a runtime release manifest) and `configurations/<digest>.json` (`schema`, `environment`, `entity_overrides`), each with a raw Ed25519 signature over the file bytes in `<digest>.sig`. `<digest>` is the hex SHA-256 of the document's canonical JSON. |
| `--current-state` | The Hub's reported-state shape: `{"digest": "<64 hex>", "schema_revision": 15, "entities": {"<entity>": {"release_id": "1.4.0", "artifact_digests": ["sha256:..."], "health": "healthy"}}, "observed_at": "<RFC 3339>"}` |
| `--local-policy` | `{"schema": "fdai.lifecycle-local-policy.v1", "entity_ids": [...], "regions": [...], "capability_modes": {...}, "destructive_allowed": false, "max_duration_minutes": 60, "entity_components": {"core": ["core-control-plane"]}}`. Every Entity in `entity_ids` must name at least one component. |

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

The command prints one JSON result. It exits `0` when the poll finished and any required report
was accepted, `1` when the Hub or local state failed or a report didn't land, and `2` for invalid
configuration.

## Not in Lifecycle I0

Apply, the local lifecycle authorization receipt, phase fencing, health verification, workload
rendering (#1946), Release roll-back protection, and envelope inputs from ownership evidence and the
configuration package belong to Lifecycle I1. The pure checks are imported from
`packages/deployment-cli` until they move to a shared lifecycle-contracts package (#1948).

## Testing

Run `PYTHONPATH=lifecycle/agent/src uv run python -m pytest -q --no-cov lifecycle/agent/tests`
from the repository root. From `lifecycle/agent/`, `mypy --config-file pyproject.toml` checks the
sources and the tests in strict mode. The package isn't a uv workspace member. It runs in the root
development environment, which already provides its dependencies.
