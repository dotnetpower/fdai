# METADATA
# title: Right-size over-provisioned sql-database
# description: |
#   A sql-database whose DTU/vCore p95 sits below the operator
#   threshold is a candidate for a smaller service tier.
# custom:
#   rule_id: sql-database.tier-overprovisioned
#   severity: medium
#   category: cost
package fdai.sql_database.tier_overprovisioned

import rego.v1

default deny := false

dtu_t := t if {
  t := input.parameters.dtu_p95_threshold
} else := 20

deny if {
  input.resource.type == "sql-database"
  input.resource.props.dtu_p95_percent < dtu_t
}

deny_reason := "sql_dtu_low" if deny
