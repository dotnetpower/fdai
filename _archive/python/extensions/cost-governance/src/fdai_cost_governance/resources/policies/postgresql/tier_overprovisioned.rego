# METADATA
# title: Right-size over-provisioned postgresql-server
# description: |
#   A postgresql-server whose CPU p95 sits below the operator
#   threshold is a candidate for a smaller SKU.
# custom:
#   rule_id: postgresql-server.tier-overprovisioned
#   severity: medium
#   category: cost
package fdai.postgresql.tier_overprovisioned

import rego.v1

default deny := false

cpu_t := t if {
  t := input.parameters.cpu_p95_threshold
} else := 20

deny if {
  input.resource.type == "postgresql-server"
  input.resource.props.cpu_p95_percent < cpu_t
}

deny_reason := "pg_cpu_low" if deny
