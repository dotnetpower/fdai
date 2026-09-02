# FDAI console - Azure Static Web App.
#
# Layer 3 (`app-shape.instructions.md § Operator console`). The SPA is
# read-only; it never issues privileged calls, so no Managed Identity is
# attached. The Static Web App is a passive HTTPS artifact host for the
# `console/dist/` build output.
#
# NOTE: Wired into `infra/main.tf` behind the `enable_console` toggle
# (default false, so a day-zero deploy stays headless). Enable per env by
# setting `enable_console = true` (the `deploy-dev.yml` workflow exposes
# this as the `deploy_console` input). Location is decoupled from
# `var.region` via `console_region` because Azure Static Web Apps is not
# offered in every region.
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

  # No API surface - the console talks to the separate `fdai-api`
  # (Container Apps). The Static Web App's built-in Functions bridge is
  # left off so a fork does not accidentally publish a write endpoint
  # under the same origin.
  preview_environments_enabled = false

  # The protected deployment workflow retrieves the deployment token after
  # apply and injects it only into the step that uploads `console/dist/`. This
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
