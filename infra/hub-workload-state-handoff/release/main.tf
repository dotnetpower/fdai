removed {
  from = kubernetes_deployment_v1.workload

  lifecycle {
    destroy = false
  }
}

removed {
  from = kubernetes_service_v1.workload

  lifecycle {
    destroy = false
  }
}

removed {
  from = kubernetes_cron_job_v1.job

  lifecycle {
    destroy = false
  }
}

removed {
  from = kubernetes_horizontal_pod_autoscaler_v2.workload

  lifecycle {
    destroy = false
  }
}
