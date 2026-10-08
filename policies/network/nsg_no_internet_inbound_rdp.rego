# METADATA
# title: Disallow Internet-reachable inbound RDP on network.nsg
# description: |
#   A network.nsg MUST NOT let any source reach TCP/3389. An inbound allow rule exposes the
#   port when its protocol is TCP or `*`, its destination port, range, or port list covers 3389
#   or is `*`, and its source is `*`, `Internet`, `Any`, `0.0.0.0/0`, or `::/0`, given as one
#   prefix or in a prefix list. The exposure is blocked only by an inbound deny rule with a
#   strictly lower priority number whose protocol, port, and source cover the same traffic for
#   every source (`*`, `Internet`, or `Any`), every source port (`*`), and every destination
#   (`*`, with no destination application security group). A rule without a numeric priority is
#   never treated as blocked.
# custom:
#   rule_id: network.nsg.no-internet-inbound-rdp
#   severity: high
#   category: security
package fdai.network.nsg_no_internet_inbound_rdp

import rego.v1

default deny := false

exposed_port := 3389

exposing_source := {"*", "internet", "any", "0.0.0.0/0", "::/0"}

blocking_source := {"*", "internet", "any"}

tcp_protocol(protocol) if lower(protocol) == "tcp"

tcp_protocol(protocol) if protocol == "*"

has_source(rule, sources) if sources[lower(rule.source_address_prefix)]

has_source(rule, sources) if {
  some prefix in rule.source_address_prefixes
  sources[lower(prefix)]
}

port_covers(spec) if spec == "*"

port_covers(spec) if to_number(spec) == exposed_port

port_covers(spec) if {
  bounds := split(spec, "-")
  count(bounds) == 2
  to_number(bounds[0]) <= exposed_port
  exposed_port <= to_number(bounds[1])
}

covers_port(rule) if port_covers(rule.destination_port_range)

covers_port(rule) if {
  some spec in rule.destination_port_ranges
  port_covers(spec)
}

inbound(rule, access) if {
  lower(rule.direction) == "inbound"
  lower(rule.access) == access
  tcp_protocol(rule.protocol)
  covers_port(rule)
}

every_value(rule, single, list) if object.get(rule, single, "") == "*"

every_value(rule, single, list) if {
  some value in object.get(rule, list, [])
  value == "*"
}

blocks_all_traffic(rule) if {
  every_value(rule, "destination_address_prefix", "destination_address_prefixes")
  every_value(rule, "source_port_range", "source_port_ranges")
  not rule.destination_application_security_groups
}

blocked(allow) if {
  is_number(allow.priority)
  some rule in input.resource.props.inbound_security_rules
  inbound(rule, "deny")
  is_number(rule.priority)
  rule.priority < allow.priority
  has_source(rule, blocking_source)
  blocks_all_traffic(rule)
}

deny if {
  input.resource.type == "network.nsg"
  some rule in input.resource.props.inbound_security_rules
  inbound(rule, "allow")
  has_source(rule, exposing_source)
  not blocked(rule)
}

deny_reason := "inbound_rdp_internet" if deny
