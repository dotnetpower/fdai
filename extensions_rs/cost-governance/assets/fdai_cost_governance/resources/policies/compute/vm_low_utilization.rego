# METADATA
# title: Right-size low-utilisation compute.vm
# description: |
#   A compute.vm running well below CPU and memory thresholds is a
#   candidate for a smaller SKU. Both thresholds MUST hold so a
#   spiky workload is not misclassified.
# custom:
#   rule_id: compute.vm.low-utilization
#   severity: medium
#   category: cost
package fdai.compute.vm_low_utilization

import rego.v1

default deny := false

cpu_t := t if {
  t := input.parameters.cpu_p95_threshold
} else := 20

mem_t := t if {
  t := input.parameters.memory_p95_threshold
} else := 30

deny if {
  input.resource.type == "compute.vm"
  input.resource.props.cpu_p95_percent < cpu_t
  input.resource.props.memory_p95_percent < mem_t
}

deny_reason := "vm_low_utilization" if deny
