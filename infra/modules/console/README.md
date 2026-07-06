# `infra/modules/console/`

Azure Static Web App module for the operator console
([`console/`](../../../console/README.md)).

## Contents

- `static-web-app/` — the day-zero flavor (Azure Static Web Apps).
  Emits a `default_hostname` output that the fork wires into MSAL app
  registration redirect URIs.

## Not-yet-wired

This module is scaffolded but not yet consumed by `infra/main.tf`.
Deployment is gated by the P1-completion rule
(`terraform apply` blocked until P1 baseline is verified — see repo
memory `p1-w3-handoff.md`).

A fork enables the module by adding:

```hcl
module "console" {
  source              = "./modules/console/static-web-app"
  name                = "stapp-${var.workload}${local.full_suffix}"
  location            = var.region   # or the nearest region where Static Web Apps
                                     # publishes the Free tier
  resource_group_name = module.resource_group.name
  # custom_hostname   = "console.<fork-domain>"   # optional
  tags                = local.tags
}
```

## Read-only invariant

The Static Web App hosts static assets only. The SPA never issues a
`POST` / `PUT` / `DELETE` / `PATCH`, so no App Service Managed Identity
is attached and no back-end write endpoint is configured
(`preview_environments_enabled = false`, no `app_settings` block).
