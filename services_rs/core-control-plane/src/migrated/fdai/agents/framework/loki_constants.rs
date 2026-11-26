pub const MAX_HELD_PROPOSALS: i64 = 256;
pub const MAX_RESILIENCE_SCORES: i64 = 512;
pub const MAX_CHAOS_TARGETS: i64 = 32;
pub const MAX_CHAOS_IDENTIFIER_CHARS: i64 = 512;

pub const CHAOS_OUTBOX_PREFIX: &str = "pantheon/loki/chaos-outbox/";
pub const HELD_PREFIX: &str = "pantheon/loki/held-proposals/";
pub const RESILIENCE_PREFIX: &str = "pantheon/loki/resilience-scores/";
pub const SAFE_CLOSURE_STATES: &[&str] = &["succeeded", "rejected", "deny_dropped", "rolled_back"];
pub const PUBLIC_EXPORTS: &[&str] = &["_CHAOS_EVIDENCE_FIELDS", "_CHAOS_OUTBOX_PREFIX", "_DEFAULT_RESERVATION_TTL", "_HELD_PREFIX", "_MAX_CHAOS_IDENTIFIER_CHARS", "_MAX_CHAOS_TARGETS", "_MAX_HELD_PROPOSALS", "_MAX_RESILIENCE_SCORES", "_RESILIENCE_PREFIX", "_SAFE_CLOSURE_STATES"];
