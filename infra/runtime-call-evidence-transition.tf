variable "runtime_call_evidence_transition" {
  description = "Require the protected runtime-call evidence updater to find its existing Inventory Job target."
  type        = bool
  default     = false
}

resource "terraform_data" "runtime_call_evidence_transition" {
  triggers_replace = [var.enable_runtime_call_evidence]

  provisioner "local-exec" {
    command     = "bash ../scripts/deployment/azure/update_inventory_job_runtime_call_evidence.sh"
    working_dir = path.module
    environment = {
      ENABLE_RUNTIME_CALL_EVIDENCE = tostring(var.enable_runtime_call_evidence)
      REQUIRE_EXISTING_TARGET      = tostring(var.runtime_call_evidence_transition)
      TARGET_CONTAINER_NAME        = "inventory"
      TARGET_JOB_NAME              = "ca-${var.workload}${local.full_suffix}-core-inventory"
      TARGET_RESOURCE_GROUP        = "rg-${var.workload}${local.full_suffix}"
    }
  }

  resource "terraform_data" "inventory_runtime_image_update" {
    triggers_replace = [var.core_image]

    provisioner "local-exec" {
      command     = "bash ../scripts/deployment/azure/update_analyzer_job_image.sh"
      working_dir = path.module
      environment = {
        DESIRED_IMAGE           = var.core_image
        REQUIRE_EXISTING_TARGET = tostring(var.runtime_call_evidence_transition)
        TARGET_CONTAINER_NAME   = "inventory"
        TARGET_JOB_NAME         = "ca-${var.workload}${local.full_suffix}-core-inventory"
        TARGET_RESOURCE_GROUP   = "rg-${var.workload}${local.full_suffix}"
      }
    }
  }
}
