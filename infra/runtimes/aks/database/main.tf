resource "random_password" "postgres" {
  length  = 32
  special = false
}

resource "tls_private_key" "postgres" {
  algorithm   = "ECDSA"
  ecdsa_curve = "P384"
}

resource "tls_self_signed_cert" "postgres" {
  private_key_pem = tls_private_key.postgres.private_key_pem

  subject {
    common_name  = "postgres-private.${var.namespace}.svc"
    organization = "FDAI non-production runtime"
  }

  dns_names = [
    "postgres-private",
    "postgres-private.${var.namespace}",
    "postgres-private.${var.namespace}.svc",
  ]
  validity_period_hours = 8760
  allowed_uses = [
    "digital_signature",
    "key_encipherment",
    "server_auth",
  ]
}

resource "kubernetes_namespace_v1" "database" {
  metadata {
    name = var.namespace
    labels = {
      "app.kubernetes.io/part-of"          = "fdai"
      "app.kubernetes.io/managed-by"       = "terraform"
      "pod-security.kubernetes.io/enforce" = "restricted"
      "pod-security.kubernetes.io/warn"    = "restricted"
      "pod-security.kubernetes.io/audit"   = "restricted"
    }
  }
}

resource "kubernetes_secret_v1" "postgres" {
  metadata {
    name      = "postgres-bootstrap"
    namespace = kubernetes_namespace_v1.database.metadata[0].name
  }
  data = {
    POSTGRES_PASSWORD = random_password.postgres.result
  }
  type = "Opaque"
}

resource "kubernetes_secret_v1" "postgres_tls" {
  metadata {
    name      = "postgres-tls"
    namespace = kubernetes_namespace_v1.database.metadata[0].name
  }
  data = {
    "tls.crt" = tls_self_signed_cert.postgres.cert_pem
    "tls.key" = tls_private_key.postgres.private_key_pem
  }
  type = "kubernetes.io/tls"
}

resource "kubernetes_service_v1" "postgres_headless" {
  metadata {
    name      = "postgres-headless"
    namespace = kubernetes_namespace_v1.database.metadata[0].name
  }
  spec {
    cluster_ip = "None"
    selector   = { "app.kubernetes.io/name" = "postgres" }
    port {
      name        = "postgres"
      port        = 5432
      target_port = 5432
    }
  }
}

resource "kubernetes_stateful_set_v1" "postgres" {
  metadata {
    name      = "postgres"
    namespace = kubernetes_namespace_v1.database.metadata[0].name
    labels = merge(var.tags, {
      "app.kubernetes.io/name"       = "postgres"
      "app.kubernetes.io/component"  = "state-store"
      "app.kubernetes.io/managed-by" = "terraform"
      "fdai.io/runtime"              = "aks"
    })
  }

  spec {
    service_name = kubernetes_service_v1.postgres_headless.metadata[0].name
    replicas     = 1

    selector {
      match_labels = { "app.kubernetes.io/name" = "postgres" }
    }

    template {
      metadata {
        labels = { "app.kubernetes.io/name" = "postgres" }
      }
      spec {
        node_selector = { "fdai.io/pool" = "runtime" }

        security_context {
          run_as_non_root = true
          run_as_user     = 999
          run_as_group    = 999
          fs_group        = 999
          seccomp_profile {
            type = "RuntimeDefault"
          }
        }

        container {
          name  = "postgres"
          image = var.image
          args = [
            "-c",
            "ssl=on",
            "-c",
            "ssl_cert_file=/etc/postgresql/tls/tls.crt",
            "-c",
            "ssl_key_file=/etc/postgresql/tls/tls.key",
          ]

          security_context {
            allow_privilege_escalation = false
            capabilities {
              drop = ["ALL"]
            }
          }

          resources {
            requests = { cpu = "1000m", memory = "2Gi" }
            limits   = { cpu = "2000m", memory = "4Gi" }
          }

          port {
            name           = "postgres"
            container_port = 5432
          }

          env {
            name  = "POSTGRES_DB"
            value = var.database_name
          }
          env {
            name  = "POSTGRES_USER"
            value = var.admin_login
          }
          env {
            name = "POSTGRES_PASSWORD"
            value_from {
              secret_key_ref {
                name = kubernetes_secret_v1.postgres.metadata[0].name
                key  = "POSTGRES_PASSWORD"
              }
            }
          }
          env {
            name  = "PGDATA"
            value = "/var/lib/postgresql/data/pgdata"
          }

          readiness_probe {
            exec {
              command = ["/bin/sh", "-c", "pg_isready -U $POSTGRES_USER -d $POSTGRES_DB"]
            }
            initial_delay_seconds = 5
            period_seconds        = 5
            timeout_seconds       = 3
            failure_threshold     = 12
          }

          liveness_probe {
            exec {
              command = ["/bin/sh", "-c", "pg_isready -U $POSTGRES_USER -d $POSTGRES_DB"]
            }
            initial_delay_seconds = 30
            period_seconds        = 15
            timeout_seconds       = 3
            failure_threshold     = 6
          }

          volume_mount {
            name       = "data"
            mount_path = "/var/lib/postgresql/data"
          }
          volume_mount {
            name       = "tls"
            mount_path = "/etc/postgresql/tls"
            read_only  = true
          }
        }

        volume {
          name = "tls"
          secret {
            secret_name  = kubernetes_secret_v1.postgres_tls.metadata[0].name
            default_mode = "0640"
          }
        }
      }
    }

    volume_claim_template {
      metadata {
        name = "data"
      }
      spec {
        access_modes       = ["ReadWriteOnce"]
        storage_class_name = "managed-csi-premium"
        resources {
          requests = { storage = var.storage_size }
        }
      }
    }
  }
}

resource "kubernetes_service_v1" "postgres_private" {
  metadata {
    name      = "postgres-private"
    namespace = kubernetes_namespace_v1.database.metadata[0].name
    annotations = {
      "service.beta.kubernetes.io/azure-load-balancer-internal" = "true"
    }
  }
  spec {
    type     = "LoadBalancer"
    selector = { "app.kubernetes.io/name" = "postgres" }
    port {
      name        = "postgres"
      port        = 5432
      target_port = 5432
    }
  }
  wait_for_load_balancer = true
}

locals {
  private_host = kubernetes_service_v1.postgres_private.status[0].load_balancer[0].ingress[0].ip
  dsn          = "postgresql+psycopg://${var.admin_login}:${random_password.postgres.result}@${local.private_host}:5432/${var.database_name}?sslmode=require"
}

resource "azurerm_key_vault_secret" "state_store_dsn" {
  # checkov:skip=CKV_AZURE_41:Credential rotation requires coordinated database and workload updates; fixed secret expiry alone would cause an outage.
  name         = "fdai-state-store-dsn"
  value        = local.dsn
  key_vault_id = var.key_vault_id
  content_type = "postgresql-dsn"
  tags         = var.tags

  depends_on = [kubernetes_stateful_set_v1.postgres]
}

resource "azurerm_role_assignment" "runtime_secret_reader" {
  for_each = var.runtime_principal_ids

  scope                = azurerm_key_vault_secret.state_store_dsn.resource_versionless_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = each.value
}
