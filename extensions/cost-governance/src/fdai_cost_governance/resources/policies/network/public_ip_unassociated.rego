# METADATA
# title: Remove unassociated Standard public IP
# description: |
#   A Standard-tier public IP that is not associated to any resource
#   is billed hourly regardless.
# custom:
#   rule_id: network.public-ip.unassociated
#   severity: low
#   category: cost
package fdai.network.public_ip_unassociated

import rego.v1

default deny := false

deny if {
  input.resource.type == "network.public-ip"
  input.resource.props.sku_tier == "Standard"
  input.resource.props.associated_resource_id == ""
}

deny_reason := "public_ip_standard_unassociated" if deny
