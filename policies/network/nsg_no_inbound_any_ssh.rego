# METADATA
# title: Disallow any-source inbound SSH on network.nsg
# description: |
#   A network.nsg MUST NOT allow inbound TCP/22 from any source. Public
#   SSH exposure is a credential-brute-force surface.
# custom:
#   rule_id: network.nsg.no-inbound-any-ssh
#   severity: high
#   category: security
package fdai.network.nsg_no_inbound_any_ssh

import rego.v1

default deny := false

deny if {
  input.resource.type == "network.nsg"
  some rule in input.resource.props.security_rules
  rule.direction == "Inbound"
  rule.access == "Allow"
  rule.protocol == "Tcp"
  rule.destination_port_range == "22"
  rule.source_address_prefix == "*"
}

deny_reason := "inbound_ssh_any" if deny
