# METADATA
# title: Remove orphaned network.public-ip
# description: |
#   A network.public-ip that is not associated to any resource is
#   billed but delivers no value; safe to remove.
# custom:
#   rule_id: network.public-ip.orphan
#   severity: low
#   category: cost
package fdai.network.public_ip_orphan

import rego.v1

default deny := false

deny if {
  input.resource.type == "network.public-ip"
  input.resource.props.associated_resource_id == ""
}

deny_reason := "public_ip_unassociated" if deny
