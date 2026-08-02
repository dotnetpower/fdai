# `infra/modules/operator-api/`

Azure Container App for the operator console Operator API
([`src/fdai/delivery/operator_api/prod.py`](../../../src/fdai/delivery/operator_api/prod.py)),
plus a one-off schema-migration Container Apps Job.

## Contents

- `container-app/` - the Operator API Container App (external ingress on port
  8000, running `uvicorn fdai.delivery.operator_api.prod:app --factory`) and a
  manual-trigger migration job (`alembic upgrade head`). Both use a dedicated
  Operator API MI and share only the Container Apps Environment with the core app.

## Wiring

Wired into `infra/main.tf` behind the `enable_operator_api` toggle (default
`false`, so a day-zero deploy stays headless). The `deploy-dev.yml`
workflow exposes it as the `deploy_operator_api` input and, when enabled,
starts the migration job after apply.

```hcl
module "operator_api" {
  count                        = var.enable_operator_api ? 1 : 0
  source                       = "./modules/operator-api/container-app"
  name                         = "ca-${var.workload}${local.full_suffix}-operator"
  migrate_job_name             = "caj-${var.workload}${local.full_suffix}-migrate"
  container_app_environment_id = module.compute.environment_id
  location                     = var.region
  resource_group_name          = module.resource_group.name
  image                        = var.operator_api_image
  operator_api_identity_id         = module.operator_api_identity[0].resource_id
  operator_api_identity_client_id  = module.operator_api_identity[0].client_id
  monitor_workspace_customer_id = module.log_analytics.workspace_customer_id
  resolved_models_path         = var.operator_api_resolved_models_path
  web_search_enabled           = var.operator_api_web_search_enabled
  web_search_allowed_domains   = var.operator_api_web_search_allowed_domains
  acr_login_server             = module.container_registry.login_server
  state_store_dsn_secret_id    = azurerm_key_vault_secret.state_store_dsn.id
  entra_tenant_id              = var.tenant_id
  api_audience                 = var.operator_api_audience
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
Set the audience to the token's exact `aud` claim. For Entra v2 tokens this is
commonly the API application client id, not the `api://.../access` scope string.

Set `operator_api_resolved_models_path` to the container path of the resolver output
to enable `/chat`, `/chat/stream`, and `/chat/health`. The production factory
uses the dedicated Operator API managed identity to invoke the configured narrator.
Leave the value empty to keep those routes disabled.

The module also projects `monitor_workspace_customer_id` as
`FDAI_MONITOR_WORKSPACE_ID`. When chat and this value are configured, explicit
`query_log` commands use the same dedicated Operator API managed identity to run
bounded KQL against that workspace. The browser cannot select another workspace
or provide an identity.

Web search stays disabled by default. To enable it, set
`operator_api_web_search_enabled=true` and provide exact public source hosts in
`operator_api_web_search_allowed_domains`. The module projects the result cap,
request budget, narrator probe interval, and web-search probe interval into
the Container App. Azure web search uses Evidence check with Bing, so review its
external compliance and geography boundary before enabling it.

## Identity and write boundary

The API projects audit / KPI / human approval-queue / ontology / views read-only from
Postgres. Its bounded write routes can stage immutable Python task artifacts,
store cron bindings, and publish typed proposals. It cannot create an Azure VM
Run Command: the dedicated identity receives ACR pull, state-store secret read,
Event Hubs send/receive for typed pipeline and live projection topics, and Azure OpenAI model
invocation plus read-only Azure and Log Analytics access. VM execution authority remains on
the separate executor identity and target-scoped role.
