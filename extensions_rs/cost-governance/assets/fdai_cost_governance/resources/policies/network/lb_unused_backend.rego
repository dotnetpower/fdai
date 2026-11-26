# METADATA
# title: Remove load-balancer with empty backend pool
# description: |
#   A load-balancer whose backend pool is empty routes to nothing;
#   it is billed but delivers no value.
# custom:
#   rule_id: network.load-balancer.unused-backend
#   severity: low
#   category: cost
package fdai.network.lb_unused_backend

import rego.v1

default deny := false

deny if {
  input.resource.type == "network.load-balancer"
  input.resource.props.backend_count == 0
}

deny_reason := "lb_backend_empty" if deny
