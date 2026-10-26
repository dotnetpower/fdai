mock_provider "kubernetes" {}

override_resource {
  target = kubernetes_deployment_v1.workload
}

override_resource {
  target = kubernetes_service_v1.workload
}

override_resource {
  target = kubernetes_cron_job_v1.job
}

override_resource {
  target = kubernetes_horizontal_pod_autoscaler_v2.workload
}

variables {
  kubeconfig_path    = "/unused/mock-kubeconfig"
  kubeconfig_context = "example"
  namespace          = "fdai-runtime"
  deployments = {
    core-control-plane = "fdai-runtime/core-control-plane"
    operator-service   = "fdai-runtime/operator-service"
  }
  services = {
    core-control-plane = "fdai-runtime/core-control-plane"
    operator-service   = "fdai-runtime/operator-service"
  }
  cron_jobs = {
    analyzer  = "fdai-runtime/analyzer"
    inventory = "fdai-runtime/inventory"
  }
  horizontal_pod_autoscalers = {
    core-control-plane = "fdai-runtime/core-control-plane"
    operator-service   = "fdai-runtime/operator-service"
  }
}

run "exact_import_inventory" {
  command = plan

  assert {
    condition = (
      length(kubernetes_deployment_v1.workload) == 2 &&
      length(kubernetes_service_v1.workload) == 2 &&
      length(kubernetes_cron_job_v1.job) == 2 &&
      length(kubernetes_horizontal_pod_autoscaler_v2.workload) == 2
    )
    error_message = "The import phase must retain every exact reviewed object."
  }
}
