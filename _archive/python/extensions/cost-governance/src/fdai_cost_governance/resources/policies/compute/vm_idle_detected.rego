# METADATA
# title: Flag idle compute.vm
# description: |
#   A compute.vm with CPU p95 below the operator threshold AND
#   almost no network traffic is idle and safe to deallocate.
# custom:
#   rule_id: compute.vm.idle-detected
#   severity: medium
#   category: cost
package fdai.compute.vm_idle_detected

import rego.v1

default deny := false

cpu_t := t if {
  t := input.parameters.cpu_p95_threshold
} else := 5

net_t := t if {
  t := input.parameters.network_p95_bytes
} else := 1024

deny if {
  input.resource.type == "compute.vm"
  input.resource.props.cpu_p95_percent < cpu_t
  input.resource.props.network_p95_bytes < net_t
}

deny_reason := "vm_idle" if deny
