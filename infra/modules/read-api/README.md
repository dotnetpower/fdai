# `infra/modules/read-api/`

Azure Container App for the operator console read API
([`src/fdai/delivery/read_api/prod.py`](../../../src/fdai/delivery/read_api/prod.py)),
plus a one-off schema-migration Container Apps Job.

## Contents

- `container-app/` - the read-API Container App (external ingress on port
  8000, running `uvicorn fdai.delivery.read_api.prod:app --factory`) and a
  manual-trigger migration job (`alembic upgrade head`). Both share the
  core app's executor MI and Container Apps Environment.

## Wiring

Wired into `infra/main.tf` behind the `enable_read_api` toggle (default
`false`, so a day-zero deploy stays headless). The `deploy-dev.yml`
workflow exposes it as the `deploy_read_api` input and, when enabled,
starts the migration job after apply.

```hcl
module "read_api" {
  count                        = var.enable_read_api ? 1 : 0
  source                       = "./modules/read-api/container-app"
  name                         = "ca-${var.workload}${local.full_suffix}-readapi"
  migrate_job_name             = "caj-${var.workload}${local.full_suffix}-migrate"
  container_app_environment_id = module.compute.environment_id
  location                     = var.region
  resource_group_name          = module.resource_group.name
  image                        = var.read_api_image
  executor_identity_id         = module.identity.resource_id
  acr_login_server             = module.container_registry.login_server
  state_store_dsn_secret_id    = azurerm_key_vault_secret.state_store_dsn.id
  entra_tenant_id              = var.tenant_id
  api_audience                 = var.read_api_audience
  rbac_readers_group_id        = var.rbac_readers_group_id
  # ...remaining rbac group ids + cors_allow_origins...
  tags = local.tags
}
```

## Auth + RBAC

The API enforces Entra JWT validation (JWKS + `aud` + `iss` + `exp`) and
resolves roles from the token's `groups` claim against five Entra security
group ids. The image must be built with the `serve` extra (uvicorn) and
bundle the alembic revisions (see the repo `Dockerfile`). Tenant-specific
values (audience, group ids) are supplied via CI Variables, never committed.

## Read-only invariant

The API projects audit / KPI / HIL-queue / ontology / views read-only from
Postgres. It issues no privileged calls and shares no execution identity
with the executor's action path.
