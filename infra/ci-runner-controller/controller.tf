# AzureRM Container App Read calls ListSecrets, including ignored secrets. The
# generic AzAPI resource uses ARM GET only; real values belong to the operator.
resource "azapi_resource" "controller" {
  type      = "Microsoft.App/containerApps@2024-03-01"
  name      = "ca-${var.name}-controller"
  parent_id = azurerm_resource_group.controller.id
  location  = var.location
  tags      = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.controller.id]
  }

  body = {
    properties = {
      managedEnvironmentId = azurerm_container_app_environment.controller.id
      configuration = {
        activeRevisionsMode  = "Single"
        maxInactiveRevisions = 1
        registries = [{
          server   = var.registry_server
          identity = azurerm_user_assigned_identity.controller.id
        }]
        # Creation seeds only nonsecret placeholders, never operator credentials.
        secrets = [
          { name = "github-pat", value = "unset" },
          { name = "webhook-hmac", value = "unset" },
        ]
        ingress = {
          external      = true
          allowInsecure = false
          targetPort    = 8080
          transport     = "http"
          traffic       = [{ latestRevision = true, weight = 100 }]
        }
      }
      template = {
        scale = { minReplicas = 1, maxReplicas = 1 }
        containers = [{
          name      = "controller"
          image     = var.controller_image
          resources = { cpu = 0.5, memory = "1Gi" }
          env = [
            { name = "GITHUB_REPOSITORY", value = var.github_repository },
            { name = "CONFIG_JSON", value = jsonencode(local.config) },
            { name = "GITHUB_RUNNER_CREDENTIAL", secretRef = "github-pat" },
            { name = "GITHUB_WEBHOOK_SECRET", secretRef = "webhook-hmac" },
            { name = "FDAI_RUNNER_CONTROLLER_APPLY", value = var.controller_apply ? "1" : "0" },
            { name = "AZURE_CLIENT_ID", value = azurerm_user_assigned_identity.controller.client_id },
          ]
          probes = [
            for kind in ["Liveness", "Readiness"] : {
              type             = kind
              tcpSocket        = { port = 8080 }
              periodSeconds    = 10
              timeoutSeconds   = 1
              failureThreshold = 3
            }
          ]
        }]
      }
    }
  }

  response_export_values    = ["properties.configuration.ingress.fqdn"]
  schema_validation_enabled = true

  # On an unrelated update, use redacted metadata from generic GET rather than
  # replaying the initial "unset" values. No ListSecrets action is invoked.
  ignore_body_changes = ["properties.configuration.secrets"]
  lifecycle {
    ignore_changes = [body.properties.configuration.secrets]
  }

  depends_on = [
    azurerm_role_assignment.controller_pull,
    azurerm_role_assignment.state,
    azurerm_role_assignment.jobs,
    azurerm_role_assignment.vm_workers,
    azurerm_role_assignment.subnet_join,
    azurerm_role_assignment.image_read,
  ]
}
