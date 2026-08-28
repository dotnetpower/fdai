# METADATA
# title: Cap retention on log-workspace
# description: |
#   A log-workspace MUST NOT retain data beyond the operator-configured
#   ceiling (default 90 days). Longer retention is billed as archive.
# custom:
#   rule_id: log-workspace.retention-excessive
#   severity: low
#   category: cost
package fdai.log_workspace.retention_excessive

import rego.v1

default deny := false

max_days := d if {
  d := input.parameters.max_retention_days
} else := 90

deny if {
  input.resource.type == "log-workspace"
  input.resource.props.retention_days > max_days
}

deny_reason := "retention_above_ceiling" if deny
