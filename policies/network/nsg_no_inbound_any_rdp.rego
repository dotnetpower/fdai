# METADATA
# title: Disallow any-source inbound RDP on network.nsg
# description: |
#   A network.nsg MUST NOT allow inbound TCP/3389 from any source.
#   Public RDP exposure is a credential-brute-force surface.
# custom:
#   rule_id: network.nsg.no-inbound-any-rdp
#   severity: high
#   category: security
package fdai.network.nsg_no_inbound_any_rdp

import rego.v1

default deny := false

deny if {
  input.resource.type == "network.nsg"
  some rule in input.resource.props.security_rules
  rule.direction == "Inbound"
  rule.access == "Allow"
  rule.protocol == "Tcp"
  rule.destination_port_range == "3389"
  rule.source_address_prefix == "*"
}

deny_reason := "inbound_rdp_any" if deny
