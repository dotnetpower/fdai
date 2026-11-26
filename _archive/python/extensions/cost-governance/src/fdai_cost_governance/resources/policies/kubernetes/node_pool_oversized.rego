# METADATA
# title: Right-size oversized kubernetes-node-pool
# description: |
#   A kubernetes-node-pool running well below CPU threshold with more
#   nodes than the operator floor is a candidate for scale-down. Both
#   conditions MUST hold to avoid breaching the floor.
# custom:
#   rule_id: kubernetes-node-pool.oversized
#   severity: medium
#   category: cost
package fdai.kubernetes.node_pool_oversized

import rego.v1

default deny := false

cpu_t := t if {
  t := input.parameters.cpu_p95_threshold
} else := 25

floor := f if {
  f := input.parameters.min_headroom_nodes
} else := 2

deny if {
  input.resource.type == "kubernetes-node-pool"
  input.resource.props.cpu_p95_percent < cpu_t
  input.resource.props.node_count > floor
}

deny_reason := "node_pool_oversized" if deny
