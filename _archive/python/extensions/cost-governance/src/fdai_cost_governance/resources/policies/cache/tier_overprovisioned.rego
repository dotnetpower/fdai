# METADATA
# title: Right-size over-provisioned cache
# description: |
#   A cache with high hit-rate AND low server load p95 is a candidate
#   for a smaller SKU. Both conditions MUST hold so a cold cache is
#   not scaled down further.
# custom:
#   rule_id: cache.tier-overprovisioned
#   severity: low
#   category: cost
package fdai.cache.tier_overprovisioned

import rego.v1

default deny := false

load_t := t if {
  t := input.parameters.server_load_p95_threshold
} else := 30

hit_t := t if {
  t := input.parameters.min_hit_rate
} else := 0.99

deny if {
  input.resource.type == "cache"
  input.resource.props.server_load_p95_percent < load_t
  input.resource.props.hit_rate > hit_t
}

deny_reason := "cache_overprovisioned" if deny
