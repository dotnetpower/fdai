package fdai.lifecycle.catalog_adoption

import rego.v1

# Decides whether a signature-verified catalog candidate may replace the accepted catalog
# without a person. The Hub supplies every input; nothing here reads a clock or the network.
# Anything not explicitly allowed waits for review, so the default is deny.

default allow := false

allow if count(reasons) == 0

reasons contains "signature_not_verified" if not input.signature.verified

reasons contains "adoption_mode_review" if input.config.mode != "auto"

reasons contains "standing_authorization_missing" if {
	input.config.mode == "auto"
	not authorization_present
}

reasons contains "standing_authorization_expired" if {
	input.config.mode == "auto"
	authorization_present
	not authorization_current
}

reasons contains "release_removed" if count(input.change.removed_releases) > 0

reasons contains "release_replaced" if count(input.change.changed_releases) > 0

reasons contains "new_channel" if {
	input.baseline_present
	some channel in input.change.new_channels
	not channel in input.config.allowed_channels
}

reasons contains "channel_membership_removed" if count(input.change.channel_removals) > 0

reasons contains "recall_lifted" if count(input.change.lifted_recalls) > 0

reasons contains "recall_dropped" if count(input.change.removed_recalls) > 0

reasons contains "schema_range_widened" if input.change.schema_widened

reasons contains sprintf("channel_not_allowed:%s", [addition.channel]) if {
	some addition in input.change.channel_additions
	not addition.channel in input.config.allowed_channels
}

reasons contains "too_many_new_releases" if {
	input.baseline_present
	count(input.change.added_releases) > input.config.max_new_releases
}

# Signed catalog roles. Without `integrity` (legacy single-key trust) none of these fire.
reasons contains "integrity_not_verified" if {
	input.integrity
	not input.integrity.verified
}

# A stale timestamp can no longer prove the catalog is current. Only a change that consists of
# new recalls may be adopted, because recall roll-off lowers risk.
reasons contains "timestamp_expired" if {
	input.integrity.expired
	not recall_only_change
}

# Trust in a new offline root key set is always a person's decision.
reasons contains "root_rotation_requires_review" if input.integrity.root_rotation

recall_only_change if {
	count(input.change.new_recalls) > 0
	count(input.change.added_releases) == 0
	count(input.change.changed_releases) == 0
	count(input.change.channel_additions) == 0
	count(input.change.new_channels) == 0
}

authorization_present if {
	input.config.authorized_by != null
	input.config.authorization_expires_at != null
}

authorization_current if {
	time.parse_rfc3339_ns(input.config.authorization_expires_at) > time.parse_rfc3339_ns(input.now)
}

decision := {
	"allow": allow,
	"reasons": sort(reasons),
}
