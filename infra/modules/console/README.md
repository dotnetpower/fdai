# `infra/modules/console/`

Azure Static Web App module for the operator console
([`console/`](../../../console/README.md)).

## Contents

- `static-web-app/` - the day-zero flavor (Azure Static Web Apps).
  Emits a `default_hostname` output that the fork wires into MSAL app
  registration redirect URIs.

## Wiring

This module is wired into `infra/main.tf` behind the `enable_console`
toggle (default `false`, so a day-zero deploy stays headless). Enable it
per environment by setting `enable_console = true` (the `deploy-dev.yml`
workflow exposes this as the `deploy_console` input). Because Azure
Static Web Apps is not offered in every region (e.g. `koreacentral` is
unsupported), the SWA location is decoupled from `var.region` via
`console_region` (default `eastasia`).

```hcl
module "console" {
  count               = var.enable_console ? 1 : 0
  source              = "./modules/console/static-web-app"
  name                = "stapp-${var.workload}${local.full_suffix}"
  location            = var.console_region
  resource_group_name = module.resource_group.name
  # custom_hostname   = "console.<fork-domain>"   # optional
  tags                = local.tags
}
```

The `console_default_hostname` root output surfaces the
`<name>.azurestaticapps.net` origin. After an apply with `deploy_console=true`,
`deploy-dev.yml` passes that origin to `scripts/deployment/azure/sync-entra-spa-redirect.py`,
which preserves existing MSAL redirect URIs and adds the deployed origin when
needed. The `console/dist/` build output is uploaded out-of-band with the SWA
deployment token (`az staticwebapp secrets list ...`).

## Read-only invariant

The Static Web App hosts static assets only. The SPA never issues a
`POST` / `PUT` / `DELETE` / `PATCH`, so no App Service Managed Identity
is attached and no back-end write endpoint is configured
(`preview_environments_enabled = false`, no `app_settings` block).
