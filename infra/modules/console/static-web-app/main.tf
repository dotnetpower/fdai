# AIOpsPilot console - Azure Static Web App.
#
# Layer 3 (`app-shape.instructions.md § Operator console`). The SPA is
# read-only; it never issues privileged calls, so no Managed Identity is
# attached. The Static Web App is a passive HTTPS artifact host for the
# `console/dist/` build output.
#
# NOTE: Deployment is gated by the P1-completion rule (see repo memory
# `p1-w3-handoff.md` -> "no terraform apply before P1 completion"). This module is
# scaffolded but NOT wired into `infra/main.tf` yet - a fork enables it
# by adding `module "console" { source = "./modules/console/static-web-app" ... }`
# once its Azure Static Web App region and (optional) custom domain are
# decided.
#
# Sub-module layout matches the existing convention
# (`infra/modules/<category>/<flavor>/`), so the seam can grow a second
# flavor (e.g. `blob-static-website`) without renaming call sites.

resource "azurerm_static_web_app" "console" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  sku_tier            = var.sku_tier
  sku_size            = var.sku_size

  # No API surface - the console talks to the separate `aiopspilot-api`
  # (Container Apps). The Static Web App's built-in Functions bridge is
  # left off so a fork does not accidentally publish a write endpoint
  # under the same origin.
  preview_environments_enabled = false

  # Deployment token is retrieved out-of-band by the fork's CI pipeline
  # (`az staticwebapp secrets list --name ... --query properties.apiKey`)
  # and injected into the build step that uploads `console/dist/`. This
  # module intentionally does NOT bind an app_settings block - every
  # console runtime value (MSAL, API base URL) is a build-time env var
  # (`VITE_*`) baked into the static bundle.
  tags = var.tags
}

# Optional custom domain. `hostname` empty → skip.
resource "azurerm_static_web_app_custom_domain" "console" {
  count             = var.custom_hostname == "" ? 0 : 1
  static_web_app_id = azurerm_static_web_app.console.id
  domain_name       = var.custom_hostname
  # `cname-delegation` is the safe default for a fork that owns its own
  # apex/subdomain DNS elsewhere. Switch to `dns-txt-token` for apex
  # binding once DNS control is confirmed.
  validation_type = "cname-delegation"
}
