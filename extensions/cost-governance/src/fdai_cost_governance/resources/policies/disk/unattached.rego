# METADATA
# title: Remove unattached disk
# description: |
#   A disk that is not attached to any compute resource is billed
#   but delivers no value; safe to remove.
# custom:
#   rule_id: disk.unattached
#   severity: low
#   category: cost
package fdai.disk.unattached

import rego.v1

default deny := false

deny if {
  input.resource.type == "disk"
  input.resource.props.managed_by == ""
}

deny_reason := "disk_unattached" if deny
