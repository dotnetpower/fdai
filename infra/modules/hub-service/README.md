# Single-product Hub deployment procedure

This internal module declares one Hub's private database, vault, managed identity, network and
bundled UI/API. Invoke it through one product root, never as a combined two-product deployment.
This procedure is preparation guidance, not permission to execute Azure changes.
Apps and both manual Jobs explicitly select the environment's `Consumption` workload profile.
Omitting it lets Azure assign a default that Terraform would subsequently plan to clear.

## Files

| File | Purpose |
|------|---------|
| `boundaries.tf` | Product-owned infrastructure and retained human database administrator |
| `bootstrap.tf` | Temporary manual initialization Job, identity and grants |
| `migrations.tf` | Manual schema migration Job using only the runtime identity |
| `apps.tf` | Runtime grants and bundled UI/API |
| `variables.tf` | Inputs shared by the two product roots |

## Freeze one candidate

Choose `ROOT` and `TARGET` from the owning product README. Work from a clean immutable candidate
checkout with committed Python, npm and Terraform locks. Record its source SHA, lock hashes,
three base image digests, Buildx metadata and resulting `linux/amd64` image digest privately.
Choose approved Node 22 Bookworm, Python 3.13 Bookworm and uv 0.10.12 digest references.
The Node digest should resolve for the builder's native platform (or be a multi-platform index);
Python and uv should resolve for the requested AMD64 target. Don't pin an AMD64-only Node leaf
on an ARM builder and call it a native UI build.
Don't use a tag as the final runtime image input.

```bash
set -euo pipefail
umask 077
SOURCE_SHA=$(git rev-parse HEAD)
test -z "$(git status --porcelain --untracked-files=normal)"
for image in "$NODE_IMAGE" "$PYTHON_IMAGE" "$UV_IMAGE"; do
  if ! [[ "$image" =~ @sha256:[0-9a-f]{64}$ ]]; then
    echo "All base images require approved digests." >&2
    exit 1
  fi
done
docker buildx build --platform linux/amd64 --target "$TARGET" \
  --build-arg NODE_IMAGE="$NODE_IMAGE" \
  --build-arg PYTHON_IMAGE="$PYTHON_IMAGE" \
  --build-arg UV_IMAGE="$UV_IMAGE" \
  --file lifecycle/Dockerfile.hubs --tag "$IMAGE_TAG" \
  --metadata-file "$PRIVATE_BUILD_METADATA" --load .
test "$SOURCE_SHA" = "$(git rev-parse HEAD)"
test -z "$(git status --porcelain --untracked-files=normal)"
```

The UI builds on the builder's native architecture. Lifecycle's target doesn't build the
vendor UI or package. Release reuses the shared backend/auth library but doesn't build the
customer UI. For approved disconnected builds retain `OFFLINE_DEPS=true` and the existing
`hub-dependencies` and `hub-npm-cache` named build contexts. No TLS bypass is supported.
Run the opt-in packaged-image tests on a Docker-capable host before publishing through native
Docker tools. Publication is a separately authorized action.

For each locally loaded product image, set only its matching test variable
(`FDAI_TEST_RELEASE_HUB_IMAGE` or `FDAI_TEST_TARGET_HUB_IMAGE`) and run:

```bash
uv run --frozen --project lifecycle/release-hub --with pytest --with pytest-cov \
  python -m pytest -q --no-cov -p no:cacheprovider -c /dev/null \
  lifecycle/hub/tests/test_hub_images.py
```

For an explicitly emulated AMD64 run on an ARM host, set `FDAI_TEST_HUB_EMULATION=1`.
It multiplies only the test command/startup budgets by four; native budgets remain unchanged.
Record emulation separately from native performance evidence. A measured ARM-host QEMU import
of the remote module took 31 seconds, exceeding the native 15-second entrypoint budget.

Prepare private `backend.hcl` and `hub.tfvars` files outside the checkout. The roots use native
local backends so an existing local state can be retained without provisioning a storage
account. Set `path` in each product's backend file to a different absolute state path in durable
private storage; don't accept the checkout-relative default or share a path between products.
Back up state before cutover and retain native file locking. A remote backend is an optional,
separately reviewed standard Terraform backend override, prepared before freezing the candidate,
not a prerequisite for application startup. Never change backend type during an active attempt.
Required inputs are subscription/tenant, prefix/location/tags,
network CIDRs, human `database_admin`, DB SKU/storage/backup/HA policy, log retention,
replicas, approved ingress CIDRs, existing registry and the product's digest-pinned image.
Tenant identity here is for PostgreSQL and Key Vault, not a browser login requirement.
`operator_auth` and Lifecycle's `catalog` default to absent.

Record the source, image, target subscription and tenant before planning. Keep these fixed for
the attempt. Bootstrap cleanup and activation intentionally need different inputs: prepare a
new private input file and saved plan for each reviewed stage instead of editing a sealed file.
Secret version identifiers produced by bootstrap belong to the next stage's input, not a rewrite
of the approved bootstrap plan. Each stage requires its own approval.

### Verify a sealed stage before dispatch

In the same Bash session, set `SUBSCRIPTION_ID`, `TENANT_ID` and `RUNTIME_IMAGE` to the approved
target and published digest reference. Use distinct absolute paths outside the checkout for
`PRIVATE_BUILD_METADATA`, `PRIVATE_BACKEND`, `PRIVATE_INPUTS`, `PRIVATE_PLAN`, `PRIVATE_PLAN_JSON`,
`PRIVATE_STAGE_CONTEXT` and `PRIVATE_STAGE_HASHES`. Retain the `SOURCE_SHA` recorded before
building; don't recompute it to accept a source change. The following functions use native
Git, SHA-256, jq and Azure CLI only. They don't grant approval, apply Terraform or start Jobs.

```bash
candidate_context() {
  printf '%s\n' "$SOURCE_SHA" "$ROOT" "$TARGET" "$SUBSCRIPTION_ID" "$TENANT_ID" \
    "$RUNTIME_IMAGE" "$PRIVATE_BUILD_METADATA" "$PRIVATE_BACKEND" "$PRIVATE_INPUTS" "$PRIVATE_PLAN" \
    "$PRIVATE_PLAN_JSON" "$PRIVATE_STAGE_CONTEXT" "$PRIVATE_STAGE_HASHES"
}

planned_job() {
  if ! jq -ec --arg name "$1" '
    [.planned_values | .. | objects |
      select(.mode? == "managed" and .type? == "azurerm_container_app_job" and .name? == $name)]
    | select(length == 1) | .[0].values
    | {group: .resource_group_name, name: .name}
    | select(all(.[]; type == "string" and length > 0))
    ' "$PRIVATE_PLAN_JSON"; then
    echo "Hub saved plan does not identify one complete Job binding." >&2
    return 1
  fi
}

verify_candidate() {
  local head changes
  case "$ROOT:$TARGET" in
    infra/release-hub:release|infra/lifecycle-hub:target) ;;
    *) echo "Hub product/root binding changed." >&2; return 1 ;;
  esac
  if ! head=$(git rev-parse HEAD) ||
     ! changes=$(git status --porcelain --untracked-files=normal); then
    echo "Hub candidate source could not be observed." >&2
    return 1
  fi
  if [[ "$head" != "$SOURCE_SHA" || -n "$changes" ]]; then
    echo "Hub candidate source changed or is not clean." >&2
    return 1
  fi
  if ! candidate_context | cmp -s "$PRIVATE_STAGE_CONTEXT" - ||
     ! sha256sum --check --status "$PRIVATE_STAGE_HASHES"; then
    echo "Hub stage inputs, saved plan or bindings changed." >&2
    return 1
  fi
  if ! [[ "$RUNTIME_IMAGE" =~ ^[^[:space:]@]+@sha256:[a-f0-9]{64}$ ]]; then
    echo "Hub runtime image requires a digest reference." >&2
    return 1
  fi
  if ! jq -e --arg digest "${RUNTIME_IMAGE##*@}" --arg source "$SOURCE_SHA" '
    .["containerimage.digest"] == $digest and
    .["buildx.build.provenance"].invocation.parameters.root.request.args["vcs:revision"] == $source
    ' "$PRIVATE_BUILD_METADATA" >/dev/null; then
    echo "Hub build metadata does not bind this source and image." >&2
    return 1
  fi
  if ! timeout 30s terraform -chdir="$ROOT" show -json "$PRIVATE_PLAN" |
    cmp -s "$PRIVATE_PLAN_JSON" -; then
    echo "Hub saved plan does not match its reviewed JSON." >&2
    return 1
  fi
  if ! jq -e --arg kind "$TARGET" --arg image "$RUNTIME_IMAGE" \
    --arg subscription "$SUBSCRIPTION_ID" --arg tenant "$TENANT_ID" '
      .variables.subscription_id.value == $subscription and
      .variables.tenant_id.value == $tenant and
      .variables.image.value == $image and
      .configuration.root_module.module_calls.hub.expressions.kind.constant_value == $kind and
      ([.planned_values | .. | objects |
        select(.mode? == "managed" and
          (.type? == "azurerm_container_app" or .type? == "azurerm_container_app_job"))]
        | length > 0 and all(.[];
          (.values.template | type == "array" and length > 0) and
          all(.values.template[];
            (.container | type == "array" and length > 0) and
            all(.container[]; .image == $image))))
    ' "$PRIVATE_PLAN_JSON" >/dev/null; then
    echo "Hub saved-plan target, product or image binding is invalid." >&2
    return 1
  fi
  if ! timeout 10s az account show \
    --query '{subscription:id,tenant:tenantId}' -o json |
    jq -e --arg subscription "$SUBSCRIPTION_ID" --arg tenant "$TENANT_ID" \
      '.subscription == $subscription and .tenant == $tenant' >/dev/null; then
    echo "Hub Azure account binding changed or could not be observed." >&2
    return 1
  fi
}

seal_candidate() {
  if [[ -e "$PRIVATE_STAGE_CONTEXT" || -L "$PRIVATE_STAGE_CONTEXT" ||
        -e "$PRIVATE_STAGE_HASHES" || -L "$PRIVATE_STAGE_HASHES" ]]; then
    echo "Use new private seal paths for a newly reviewed stage." >&2
    return 1
  fi
  umask 077
  (set -o noclobber; candidate_context > "$PRIVATE_STAGE_CONTEXT") || return 1
  (set -o noclobber; sha256sum -- "$PRIVATE_BUILD_METADATA" "$PRIVATE_BACKEND" "$PRIVATE_INPUTS" \
    "$PRIVATE_PLAN" "$PRIVATE_PLAN_JSON" "$PRIVATE_STAGE_CONTEXT" \
    > "$PRIVATE_STAGE_HASHES") || return 1
  chmod 400 "$PRIVATE_STAGE_CONTEXT" "$PRIVATE_STAGE_HASHES" || return 1
  verify_candidate
}
```

Run `seal_candidate` only after producing and privately reviewing the saved plan below.
Run `verify_candidate` immediately before each apply or Job start. A failed guard stops that
dispatch; don't continue in a shell that ignores failures. These functions assume the
`set -euo pipefail` session above. A changed source/image needs a rebuilt and revalidated
candidate; a changed sealed stage needs a new plan, seal and approval. Never reseal drift
automatically. Keep the read-only seals and validation evidence with the private saved plan.
This detects accidental drift, not a hostile operator rewriting both the files and their seal.
It doesn't replace Terraform's own state-lock/stale-plan checks or independent effect readback.

## Native Terraform and manual Jobs

Every apply below requires explicit approval of its saved plan. Inspect plan JSON privately;
stop on any unreviewed delete/replace. Don't print state, full environment or secret values.
The application initialization can be retried only after investigating an explicit failure.

1. Initialize the product's backend and plan its foundation with `enable_bootstrap_job=true`,
   `enable_apps=false` and `enable_migration_jobs=false` in the private inputs.

   ```bash
   terraform -chdir="$ROOT" init -backend-config="$PRIVATE_BACKEND"
   terraform -chdir="$ROOT" plan -var-file="$PRIVATE_INPUTS" -out="$PRIVATE_PLAN"
   terraform -chdir="$ROOT" show -json "$PRIVATE_PLAN" > "$PRIVATE_PLAN_JSON"
   # Review the private plan and obtain its explicit approval before continuing.
   seal_candidate
   verify_candidate
   terraform -chdir="$ROOT" apply "$PRIVATE_PLAN"
   ```

2. Start only this product's manual bootstrap Job. Capture its execution name, then inspect
   status and sanitized app logs with native CLI. There is no automatic retry or polling loop.

   ```bash
   verify_candidate
   JOB_BINDING=$(planned_job bootstrap)
   RG=$(jq -er .group <<< "$JOB_BINDING")
   JOB=$(jq -er .name <<< "$JOB_BINDING")
   EXECUTION=$(az containerapp job start -g "$RG" -n "$JOB" --query name -o tsv)
   az containerapp job execution show -g "$RG" -n "$JOB" \
     --job-execution-name "$EXECUTION" --query '{name:name,status:properties.status}' -o json
   az containerapp job logs show -g "$RG" -n "$JOB" --execution "$EXECUTION" \
     --container bootstrap --tail 50
   ```

   An accepted start isn't success. Require a succeeded execution and independently verify the
   runtime principal's exact object ID, DB/schema grants and enabled secret versions from an
   approved private observer. Bootstrap initializes roles/secrets, not the Hub schema.
   Matching secrets are preserved; conflicting roles, DSNs or keys stop without replacement.
   Principal lookup, creation and readback run in `postgres`; schema grants run in the product DB.
   A `postgres` session advisory lock spans principal commits, product grants and secret readback,
   and releases when the session closes on success or failure. A later failure may leave a matching
   principal committed; a reviewed retry preserves it. Don't run external secret writers concurrently.

3. Read only version identifiers into private `secret_versions`, never secret values:

   ```bash
   VAULT=$(terraform -chdir="$ROOT" output -json deployment | jq -r .vault_uri)
   az keyvault secret show --id "${VAULT}secrets/hub-database-url" --query id -o tsv
   az keyvault secret show --id "${VAULT}secrets/development-signing-key" --query id -o tsv
   ```

   In a new private stage input, set `enable_bootstrap_job=false` and
   `enable_migration_jobs=true`; produce, review and seal a new plan before applying it.
   The only expected deletions are the temporary bootstrap Job, identity, its two grants and
   its separate PG administrator. The human administrator and all runtime resources remain.
   After cleanup, independently verify those temporary bindings are absent. If PostgreSQL
   retains the temporary DB role, the retained human administrator should revoke/drop that
   exact bootstrap principal through the approved private SQL session; never drop the runtime
   role. Verify the human administrator still connects. Cleanup failure blocks activation.

4. Start and observe the migration Job exactly as above using
   `JOB_BINDING=$(planned_job migrate)` and container `migrate`. Derive the RG and Job name
   from this stage's sealed plan, not mutable Terraform output or a prior stage's shell variables.
   Require succeeded execution.
   The command migrates only this product's namespace and verifies revision 1.
   Keep `enable_migration_jobs=true` once it exists; don't invert runtime flags to change stages.
   Re-run the existing Job with `schema` as an explicitly reviewed command override if an
   independent schema check is required. Don't mutate a shared Job while it is running.

5. In a new sealed stage set `enable_apps=true`, plan/apply, then independently read this product's `/healthz`,
   `/readyz`, UI assets and deep links from an allowed client. A second Terraform plan should
   report no changes. Without login bindings `/auth/config` reports `remote-unconfigured`,
   `/v1` returns 503, and the UI says management isn't ready. Don't report this as anonymous
   management functionality. Anonymous management API policy is deferred; it doesn't block
   independent startup/UI preparation. A UI/readiness-only deployment still requires separate
   explicit authorization and doesn't prove anonymous management functionality.

Runtime `enable_apps` and `enable_migration_jobs` have `prevent_destroy` guards and aren't
stage selectors. Only the explicitly temporary bootstrap resources are removed during cleanup.
RBAC propagation or provider failure stops an attempt; don't conceal it with retry controllers.

## Existing state

The legacy root and existing registry state are preserved. New roots don't read either state.
Before any live cutover, back up each source and destination state, stop concurrent Terraform
writers, retain lineage/serial and inspect private resource addresses without dumping attributes.
Move only objects actually present. Never use an empty-state apply, import, recreation,
cross-root `moved` blocks, `-target` or broad `ignore_changes` as an ownership shortcut.

| Legacy ownership | New owner and address |
|------------------|-----------------------|
| Every `boundaries.tf` instance keyed `["release"]` | Release root, `module.hub.<original-address>` |
| Every `boundaries.tf` instance keyed `["target"]` | Lifecycle root, `module.hub.<original-address>` |
| Registry reader, secret readers, app and migration Job for one product | Same product root, `module.hub.<original-address>` |
| Directory apps, SPs, consent, identifier URI and catalog assignment | Existing legacy/directory state, unchanged; not adopted by either product root |
| Dedicated ACR | Its existing separate registry state, unchanged |
| Human PostgreSQL administrator | Same product root, same principal, module address only |

The foundation address inventory is below. For every row, move only the selected product key
(`["release"]` or `["target"]`) to that product root's `module.hub.<original-address>`.
This enumerates ownership, not permission to mutate live state.

| Original resource address, before its product key | Owner |
|-------------------------------------------------|-------|
| `azurerm_resource_group.hub` | Selected product |
| `azurerm_virtual_network.hub` | Selected product |
| `azurerm_subnet.apps` | Selected product |
| `azurerm_subnet.database` | Selected product |
| `azurerm_subnet.secrets` | Selected product |
| `azurerm_public_ip.egress` | Selected product |
| `azurerm_nat_gateway.hub` | Selected product |
| `azurerm_nat_gateway_public_ip_association.hub` | Selected product |
| `azurerm_subnet_nat_gateway_association.hub` | Selected product |
| `azurerm_log_analytics_workspace.hub` | Selected product |
| `azurerm_container_app_environment.hub` | Selected product |
| `azurerm_user_assigned_identity.hub` | Selected product |
| `azurerm_key_vault.hub` | Selected product |
| `azurerm_private_dns_zone.vault` | Selected product |
| `azurerm_private_dns_zone.database` | Selected product |
| `azurerm_private_dns_zone_virtual_network_link.vault` | Selected product |
| `azurerm_private_dns_zone_virtual_network_link.database` | Selected product |
| `azurerm_private_endpoint.vault` | Selected product |
| `azurerm_postgresql_flexible_server.hub` | Selected product |
| `azurerm_postgresql_flexible_server_active_directory_administrator.hub` | Selected product, retained human |
| `azurerm_postgresql_flexible_server_database.hub` | Selected product |
| `azurerm_postgresql_flexible_server_configuration.log_connections` | Selected product |
| `azurerm_postgresql_flexible_server_configuration.log_checkpoints` | Selected product |
| `azurerm_postgresql_flexible_server_configuration.connection_throttle` | Selected product |
| `azurerm_postgresql_flexible_server_configuration.tls_floor` | Selected product |
| `azurerm_role_assignment.registry_reader` | Selected product |
| `azurerm_role_assignment.secret_reader` | Selected product, keys `<product>-<secret>` |
| `azurerm_container_app.hub` | Selected product, if present |
| `azurerm_container_app_job.migrate` | Selected product, if present |
| `azuread_application.api`, `azuread_application.browser` | Existing directory owner, unchanged |
| `azuread_application_identifier_uri.api` | Existing directory owner, unchanged |
| `azuread_service_principal.api`, `azuread_service_principal.browser` | Existing directory owner, unchanged |
| `azuread_service_principal_delegated_permission_grant.operator` | Existing directory owner, unchanged |
| `azuread_app_role_assignment.catalog_reader` (singleton or `[0]`) | Existing directory owner, unchanged |
| `data.azuread_client_config.current[0]`, if cached | Existing directory owner, unchanged |
| `azurerm_container_registry.hub` | Existing separate registry state, unchanged |

For example, rehearse one move on **backup copies**, with the backend disconnected:

```bash
terraform state mv -state="$PRIVATE_SOURCE_COPY" -state-out="$PRIVATE_RELEASE_COPY" \
  'azurerm_user_assigned_identity.hub["release"]' \
  'module.hub.azurerm_user_assigned_identity.hub["release"]'
```

Move individual keys, not whole resource collections. Preserve pre-existing destination
objects; occupied addresses stop the move. Retire moved declarations from the old owner in the
same reviewed cutover before either root is applied. This repository leaves the legacy root
unchanged, so it is not safe to apply it after a state cutover without that follow-up.
Compare backup-copy inventories and private real-provider plans. Require zero unintended
deletes/replacements, duplicate owners or lost objects before approving a real state operation.
The synthetic fixture verifies native address movement and a no-op ownership model, not Azure
schema normalization or live drift.

### Preserve dependency metadata when rehearsing native moves

Move referenced resource collections before their dependents. Terraform 1.15's native
`state mv` invalidates dependency lists in the destination when a later move matches one
of their references. An alphabetical inventory or dependent-first ordering can therefore
preserve attributes and private provider data while silently dropping nonempty dependencies.
Don't treat an address-count check alone as a preservation result.

Prepare `PRIVATE_MOVE_RESOURCES` as a reviewed JSON array of the source resource collection
addresses to move, without instance keys. Leave directory and registry collections out.
The following local-only command writes a dependency-first collection order; cycles fail
before any move. Use this order for the reviewed instance-by-instance mapping, retaining
the existing `release`/`target` keys and adding only the `module.hub.` address prefix.

```bash
jq --slurpfile mapped "$PRIVATE_MOVE_RESOURCES" '
  def dependency_order($remaining):
    if ($remaining | length) == 0 then [] else
      ($remaining | map(.key)) as $keys |
      [$remaining[] | select(all(.dependencies[];
        . as $dep | $keys | index($dep) | not))] as $ready |
      if ($ready | length) == 0 then error("State dependency cycle; stop.") else
        ($ready | map(.key)) + dependency_order($remaining - $ready)
      end
    end;
  [.resources[] | (.type + "." + .name) as $key |
    select($mapped[0] | index($key)) |
    {key: $key, dependencies: ([.instances[].dependencies[]? |
      sub("\\[.*$"; "") | select(. as $dep | $mapped[0] | index($dep))] | unique)}] |
  dependency_order(.)[]
' -r "$PRIVATE_SOURCE_COPY" > "$PRIVATE_RESOURCE_ORDER"
```

Use only backup copies for this rehearsal. Compare every original instance's attributes,
sensitive metadata, provider reference, private data and nonempty dependency lists with the
union of all resulting copies. Also verify retained objects, source outputs/lineage, distinct
destination lineages and the untouched original file digest. Don't hand-edit state JSON to
hide a mismatch. Dependency metadata preservation doesn't prove the new module's provider
plan is unchanged; review that graph and require zero unintended delete/replace before a
separately authorized cutover.

## Local validation

```bash
terraform -chdir="$ROOT" init -backend=false
terraform -chdir="$ROOT" validate
terraform -chdir="$ROOT" test
```

Focused Python checks cover `test_hubs_state_split.py`, `test_bootstrap.py`,
`test_standalone_remote.py`, auth and catalog regression tests. PostgreSQL checks use only the
existing `with-local-test-database.py` wrapper and its isolated port 5433. Don't use runtime 5432.
Docker image execution and real Azure/Entra/managed-identity observation require their own
available infrastructure and explicit authorization; mock passes are not live evidence.

## Related docs

| To learn about | Read |
|----------------|------|
| Vendor entry point | [Release Hub](../../release-hub/README.md) |
| Customer entry point | [Lifecycle Hub](../../lifecycle-hub/README.md) |
