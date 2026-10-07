# METADATA
# title: Disallow any-source inbound SSH on network.nsg
# description: |
#   A network.nsg MUST NOT allow inbound TCP/22 from any source.
#   Public SSH exposure is a credential-brute-force surface. A rule exposes the
#   port when its protocol is TCP or `*`, its destination port, range, or port list
#   covers 22 or is `*`, and its source is `*`, `Internet`, `Any`, `0.0.0.0/0`, or
#   `::/0`, whether given as one prefix or in a prefix list.
# custom:
#   rule_id: network.nsg.no-inbound-any-ssh
#   severity: high
#   category: security
package fdai.network.nsg_no_inbound_any_ssh

import rego.v1

default deny := false

exposed_port := 22

any_source := {"*", "internet", "any", "0.0.0.0/0", "::/0"}

tcp_protocol(protocol) if lower(protocol) == "tcp"

tcp_protocol(protocol) if protocol == "*"

source_is_any(rule) if any_source[lower(rule.source_address_prefix)]

source_is_any(rule) if {
  some prefix in rule.source_address_prefixes
  any_source[lower(prefix)]
}

port_covers(spec) if spec == "*"

port_covers(spec) if to_number(spec) == exposed_port

port_covers(spec) if {
  bounds := split(spec, "-")
  count(bounds) == 2
  to_number(bounds[0]) <= exposed_port
  exposed_port <= to_number(bounds[1])
}

exposes_port(rule) if port_covers(rule.destination_port_range)

exposes_port(rule) if {
  some spec in rule.destination_port_ranges
  port_covers(spec)
}

deny if {
  input.resource.type == "network.nsg"
  some rule in input.resource.props.security_rules
  lower(rule.direction) == "inbound"
  lower(rule.access) == "allow"
  tcp_protocol(rule.protocol)
  source_is_any(rule)
  exposes_port(rule)
}

deny_reason := "inbound_ssh_any" if deny
