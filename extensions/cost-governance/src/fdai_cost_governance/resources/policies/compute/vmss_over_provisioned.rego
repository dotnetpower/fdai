# METADATA
# title: Over-provisioned VM scale set
# description: |
#   A VM scale set MUST be right-sized when observed CPU utilisation is
#   well below the operator threshold AND enough headroom above the
#   configured minimum replica floor exists. Both conditions MUST hold
#   so we never propose a scale-down that would breach the floor.
# custom:
#   rule_id: compute.vm-scale-set.over-provisioned
#   severity: medium
#   category: cost
package fdai.compute.vmss_over_provisioned

import rego.v1

default deny := false

max_cpu := t if {
	t := input.parameters.max_cpu_p95_percent
} else := 30

min_headroom := h if {
	h := input.parameters.min_headroom_replicas
} else := 1

deny if {
	input.resource.type == "compute.vm-scale-set"
	input.resource.props.cpu_p95_percent < max_cpu
	input.resource.props.instance_count > min_headroom
}

deny_reason := "cpu_utilisation_below_threshold_with_headroom" if deny
