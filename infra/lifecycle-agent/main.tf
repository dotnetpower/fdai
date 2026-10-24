locals {
  agent_namespace = var.installation.agent_namespace
  service_account = "fdai-lifecycle-agent"
  identity_name   = "id-${var.prefix}-lifecycle-agent"
  native          = var.installation.native_approval_json != null
  initialize_state_script = join(";", concat(
    [
      "from pathlib import Path",
      "state=Path('/state/agent')",
      "state.mkdir(mode=0o700,exist_ok=True)",
      "state.chmod(0o700)",
      "p=state/'current-state.json'",
      "p.exists() or p.write_bytes(Path('/config/public/current-state.json').read_bytes())",
      "p.chmod(0o600)",
      "private=state/'private'",
      "private.mkdir(mode=0o700,exist_ok=True)",
      "private.chmod(0o700)",
      "p=private/'local-policy.json'",
      "t=private/'.local-policy.json.tmp'",
      "t.write_bytes(Path('/config/private/local-policy.json').read_bytes())",
      "t.chmod(0o600)",
      "p.is_dir() and p.rmdir()",
      "t.replace(p)",
    ],
    var.installation.configuration_artifact == null ? [] : [
      "cache=state/'artifact-cache/configurations'",
      "cache.mkdir(mode=0o700,parents=True,exist_ok=True)",
      "q=cache/'${var.installation.configuration_artifact.digest}.json'",
      "q.exists() or q.write_bytes(Path('/config/private/configuration.json').read_bytes())",
      "q.chmod(0o600)",
      "s=cache/'${var.installation.configuration_artifact.digest}.sig'",
      "s.exists() or s.write_bytes(Path('/config/private/configuration.sig').read_bytes())",
      "s.chmod(0o600)",
    ],
    local.native ? [
      "p=private/'native-approval.json'",
      "t=private/'.native-approval.json.tmp'",
      "t.write_bytes(Path('/config/private/native-approval.json').read_bytes())",
      "t.chmod(0o600)",
      "p.is_dir() and p.rmdir()",
      "t.replace(p)",
      "p=private/'installation-public.pem'",
      "t=private/'.installation-public.pem.tmp'",
      "t.write_bytes(Path('/config/private/installation-public.pem').read_bytes())",
      "t.chmod(0o600)",
      "p.is_dir() and p.rmdir()",
      "t.replace(p)",
    ] : [],
    var.installation.native_state_json == null ? [] : [
      "p=state/'lifecycle-native-scope.json'",
      "t=state/'.lifecycle-native-scope.json.tmp'",
      "t.write_bytes(Path('/config/private/native-state.json').read_bytes())",
      "t.chmod(0o600)",
      "t.replace(p)",
    ],
  ))
  initialize_input_digest = sha256(jsonencode({
    current_state           = var.installation.current_state_json
    local_policy            = var.installation.local_policy_json
    native_approval         = var.installation.native_approval_json
    native_state            = var.installation.native_state_json
    installation_public_key = var.installation.installation_public_key_pem
    configuration_artifact  = var.installation.configuration_artifact
  }))
}

data "azuread_service_principal" "hub_api" {
  client_id = var.hub.api_client_id
}

resource "azurerm_user_assigned_identity" "agent" {
  name                = local.identity_name
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags
  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_federated_identity_credential" "agent" {
  name      = "fic-${var.prefix}-lifecycle-agent"
  parent_id = azurerm_user_assigned_identity.agent.id
  audience  = ["api://AzureADTokenExchange"]
  issuer    = var.cluster_oidc_issuer_url
  subject   = "system:serviceaccount:${local.agent_namespace}:${local.service_account}"
  lifecycle {
    prevent_destroy = true
  }
}

resource "azuread_app_role_assignment" "agent_access" {
  app_role_id         = var.hub.agent_role_id
  principal_object_id = azurerm_user_assigned_identity.agent.principal_id
  resource_object_id  = data.azuread_service_principal.hub_api.object_id
}

resource "kubernetes_namespace_v1" "agent" {
  metadata {
    name = local.agent_namespace
    labels = {
      "app.kubernetes.io/managed-by"       = "terraform"
      "pod-security.kubernetes.io/audit"   = "restricted"
      "pod-security.kubernetes.io/enforce" = "restricted"
      "pod-security.kubernetes.io/warn"    = "restricted"
    }
  }
  lifecycle {
    prevent_destroy = true
  }
}

resource "kubernetes_service_account_v1" "agent" {
  metadata {
    name      = local.service_account
    namespace = kubernetes_namespace_v1.agent.metadata[0].name
    annotations = {
      "azure.workload.identity/client-id" = azurerm_user_assigned_identity.agent.client_id
    }
  }
  automount_service_account_token = true
  lifecycle {
    prevent_destroy = true
  }
}

resource "kubernetes_role_v1" "workloads" {
  metadata {
    name      = "fdai-lifecycle-agent"
    namespace = var.installation.target_namespace
  }
  rule {
    api_groups = ["", "apps", "batch"]
    resources  = ["services", "deployments", "jobs", "cronjobs"]
    verbs      = ["get", "create", "patch", "delete"]
  }
  lifecycle {
    prevent_destroy = true
  }
}

resource "kubernetes_role_binding_v1" "workloads" {
  metadata {
    name      = "fdai-lifecycle-agent"
    namespace = var.installation.target_namespace
  }
  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "Role"
    name      = kubernetes_role_v1.workloads.metadata[0].name
  }
  subject {
    kind      = "ServiceAccount"
    name      = kubernetes_service_account_v1.agent.metadata[0].name
    namespace = kubernetes_namespace_v1.agent.metadata[0].name
  }
  lifecycle {
    prevent_destroy = true
  }
}

resource "kubernetes_persistent_volume_claim_v1" "state" {
  wait_until_bound = false
  metadata {
    name      = "fdai-lifecycle-agent-state"
    namespace = kubernetes_namespace_v1.agent.metadata[0].name
  }
  spec {
    access_modes       = ["ReadWriteOnce"]
    storage_class_name = var.storage_class_name
    resources {
      requests = {
        storage = "1Gi"
      }
    }
  }
  lifecycle {
    prevent_destroy = true
  }
}

resource "kubernetes_config_map_v1" "public_inputs" {
  metadata {
    name      = "fdai-lifecycle-agent-public"
    namespace = kubernetes_namespace_v1.agent.metadata[0].name
  }
  data = {
    "hub-public.pem"           = var.hub.public_key_pem
    "release-public.pem"       = var.hub.release_key_pem
    "configuration-public.pem" = var.hub.config_key_pem
    "current-state.json"       = var.installation.current_state_json
  }
}

resource "kubernetes_secret_v1" "private_inputs" {
  metadata {
    name      = "fdai-lifecycle-agent-private"
    namespace = kubernetes_namespace_v1.agent.metadata[0].name
  }
  data = merge(
    { "local-policy.json" = var.installation.local_policy_json },
    var.installation.native_approval_json == null ? {} : {
      "native-approval.json" = var.installation.native_approval_json
    },
    var.installation.native_state_json == null ? {} : {
      "native-state.json" = var.installation.native_state_json
    },
    var.installation.installation_public_key_pem == null ? {} : {
      "installation-public.pem" = var.installation.installation_public_key_pem
    },
    var.installation.configuration_artifact == null ? {} : {
      "configuration.json" = var.installation.configuration_artifact.payload
    },
  )
  binary_data = var.installation.configuration_artifact == null ? {} : {
    "configuration.sig" = var.installation.configuration_artifact.signature_base64
  }
  type = "Opaque"
}

resource "kubernetes_job_v1" "initialize" {
  count               = var.enable_agent ? 1 : 0
  wait_for_completion = true
  metadata {
    name      = "fdai-lifecycle-agent-initialize"
    namespace = kubernetes_namespace_v1.agent.metadata[0].name
    labels = {
      "app.kubernetes.io/name"       = "fdai-lifecycle-agent-initialize"
      "app.kubernetes.io/managed-by" = "terraform"
    }
  }
  spec {
    active_deadline_seconds = 120
    backoff_limit           = 0
    template {
      metadata {
        labels = {
          "app.kubernetes.io/name"       = "fdai-lifecycle-agent-initialize"
          "app.kubernetes.io/managed-by" = "terraform"
        }
        annotations = {
          "fdai.io/input-digest" = local.initialize_input_digest
        }
      }
      spec {
        restart_policy                  = "Never"
        service_account_name            = kubernetes_service_account_v1.agent.metadata[0].name
        automount_service_account_token = false
        security_context {
          run_as_non_root        = true
          run_as_user            = 65532
          run_as_group           = 65532
          fs_group               = 65532
          fs_group_change_policy = "OnRootMismatch"
          seccomp_profile {
            type = "RuntimeDefault"
          }
        }
        container {
          name    = "initialize-state"
          image   = var.agent_image
          command = ["python", "-c"]
          args    = [local.initialize_state_script]
          resources {
            requests = {
              cpu    = "50m"
              memory = "64Mi"
            }
            limits = {
              cpu    = "250m"
              memory = "128Mi"
            }
          }
          security_context {
            allow_privilege_escalation = false
            read_only_root_filesystem  = true
            run_as_non_root            = true
            capabilities {
              drop = ["ALL"]
            }
          }
          volume_mount {
            name       = "state"
            mount_path = "/state"
          }
          volume_mount {
            name       = "public-inputs"
            mount_path = "/config/public"
            read_only  = true
          }
          volume_mount {
            name       = "private-inputs"
            mount_path = "/config/private"
            read_only  = true
          }
        }
        volume {
          name = "state"
          persistent_volume_claim {
            claim_name = kubernetes_persistent_volume_claim_v1.state.metadata[0].name
          }
        }
        volume {
          name = "public-inputs"
          config_map {
            name = kubernetes_config_map_v1.public_inputs.metadata[0].name
          }
        }
        volume {
          name = "private-inputs"
          secret {
            secret_name = kubernetes_secret_v1.private_inputs.metadata[0].name
          }
        }
      }
    }
  }
}

resource "kubernetes_deployment_v1" "agent" {
  count = var.enable_agent ? 1 : 0
  metadata {
    name      = "fdai-lifecycle-agent"
    namespace = kubernetes_namespace_v1.agent.metadata[0].name
    labels = {
      "app.kubernetes.io/name"       = "fdai-lifecycle-agent"
      "app.kubernetes.io/managed-by" = "terraform"
    }
  }
  spec {
    replicas = 1
    strategy {
      type = "Recreate"
    }
    selector {
      match_labels = {
        "app.kubernetes.io/name" = "fdai-lifecycle-agent"
      }
    }
    template {
      metadata {
        labels = {
          "app.kubernetes.io/name"       = "fdai-lifecycle-agent"
          "app.kubernetes.io/managed-by" = "terraform"
          "azure.workload.identity/use"  = "true"
        }
      }
      spec {
        service_account_name            = kubernetes_service_account_v1.agent.metadata[0].name
        automount_service_account_token = true
        security_context {
          run_as_non_root        = true
          run_as_user            = 65532
          run_as_group           = 65532
          fs_group               = 65532
          fs_group_change_policy = "OnRootMismatch"
          seccomp_profile {
            type = "RuntimeDefault"
          }
        }
        container {
          name    = "agent"
          image   = var.agent_image
          command = ["fdai-lifecycle-agent"]
          args = concat(
            [
              "poll",
              "--hub-url", var.hub.url,
              "--hub-auth", "workload-identity",
              "--hub-scope", "api://${var.hub.api_client_id}/.default",
              "--installation-id", var.installation.id,
              "--state-dir", "/agent-state",
              "--hub-public-key", "/config/public/hub-public.pem",
              "--hub-key-id", var.hub.signing_key_id,
              "--hub-key-epoch", tostring(var.hub.signing_epoch),
              "--fencing-generation", tostring(var.installation.fencing_generation),
              "--release-public-key", "/config/public/release-public.pem",
              "--configuration-public-key", "/config/public/configuration-public.pem",
              "--artifact-source", "hub",
              "--current-state", "/agent-state/current-state.json",
              "--local-policy", "/config/private/local-policy.json",
              "--apply",
              "--in-cluster",
              "--namespace", var.installation.target_namespace,
              "--poll-interval-seconds", tostring(var.installation.poll_interval_seconds),
              "--max-polls", "720",
              "--max-duration-seconds", "3600",
            ],
            local.native ? [
              "--native-approval", "/config/private/native-approval.json",
              "--installation-public-key", "/config/private/installation-public.pem",
            ] : [],
          )
          env {
            name  = "AZURE_CLIENT_ID"
            value = azurerm_user_assigned_identity.agent.client_id
          }
          resources {
            requests = {
              cpu    = "100m"
              memory = "256Mi"
            }
            limits = {
              cpu    = "500m"
              memory = "512Mi"
            }
          }
          security_context {
            allow_privilege_escalation = false
            read_only_root_filesystem  = true
            run_as_non_root            = true
            capabilities {
              drop = ["ALL"]
            }
          }
          volume_mount {
            name       = "state"
            mount_path = "/agent-state"
            sub_path   = "agent"
          }
          volume_mount {
            name       = "public-inputs"
            mount_path = "/config/public"
            read_only  = true
          }
          volume_mount {
            name       = "tmp"
            mount_path = "/tmp"
            read_only  = false
          }
          volume_mount {
            name       = "state"
            mount_path = "/config/private/local-policy.json"
            sub_path   = "agent/private/local-policy.json"
            read_only  = true
          }
          dynamic "volume_mount" {
            for_each = local.native ? toset([
              "native-approval.json",
              "installation-public.pem",
            ]) : toset([])
            content {
              name       = "state"
              mount_path = "/config/private/${volume_mount.value}"
              sub_path   = "agent/private/${volume_mount.value}"
              read_only  = true
            }
          }
        }
        volume {
          name = "state"
          persistent_volume_claim {
            claim_name = kubernetes_persistent_volume_claim_v1.state.metadata[0].name
          }
        }
        volume {
          name = "public-inputs"
          config_map {
            name = kubernetes_config_map_v1.public_inputs.metadata[0].name
          }
        }
        volume {
          name = "tmp"
          empty_dir {
            size_limit = "64Mi"
          }
        }
        volume {
          name = "private-inputs"
          secret {
            secret_name = kubernetes_secret_v1.private_inputs.metadata[0].name
          }
        }
      }
    }
  }
  lifecycle {
    prevent_destroy = true
  }
  depends_on = [kubernetes_job_v1.initialize]
}

output "deployment" {
  value = nonsensitive({
    identity_id        = azurerm_user_assigned_identity.agent.id
    identity_client_id = azurerm_user_assigned_identity.agent.client_id
    identity_object_id = azurerm_user_assigned_identity.agent.principal_id
    agent_namespace    = kubernetes_namespace_v1.agent.metadata[0].name
    service_account    = kubernetes_service_account_v1.agent.metadata[0].name
    target_namespace   = nonsensitive(var.installation.target_namespace)
    enabled            = var.enable_agent
  })
  sensitive = true
}
