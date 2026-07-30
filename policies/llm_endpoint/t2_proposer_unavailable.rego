# METADATA
# title: T2 proposer routes unavailable
# description: |
#   Detects a sanitized control-plane observation showing that every bounded
#   T2 proposer route failed. The resulting recovery action remains HIL-only;
#   this policy never selects a route or executes a mutation.
# custom:
#   rule_id: llm-endpoint.t2-proposer-unavailable
#   severity: high
#   category: reliability
package fdai.llm_endpoint.t2_proposer_unavailable

import rego.v1

default deny := false

deny if {
	input.resource.type == "llm-endpoint"
	input.resource.props.event_type == "control_plane.t2_proposer_failure"
	input.resource.props.terminal == true
}

deny_reason := "t2_proposer_candidates_exhausted" if deny
