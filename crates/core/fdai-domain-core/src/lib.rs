pub mod azure_iam_catalog;
pub mod migrated;
pub mod causal_ontology;
pub mod temporal_causal;
pub use fdai_contracts::ServiceKind;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct NoCurrentIncarnationError;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct FixedDecimalMicros(pub i128);

impl FixedDecimalMicros {
    #[must_use]
    pub const fn from_units(units: i64, micros: u32) -> Self {
        let sign = if units < 0 { -1_i128 } else { 1_i128 };
        Self((units as i128) * 1_000_000 + sign * (micros as i128))
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum GateVerdict { Auto, Hil, Abstain, Deny }

#[must_use]
pub const fn evaluate_cost_and_risk_gate(spend: FixedDecimalMicros, auto_cap: FixedDecimalMicros, grounded: bool) -> GateVerdict {
    if !grounded { GateVerdict::Abstain } else if spend.0 <= auto_cap.0 { GateVerdict::Auto } else { GateVerdict::Hil }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BitemporalRevision<T> {
    pub event_time_ms: i64,
    pub knowledge_time_ms: i64,
    pub value: T,
}

pub fn resolve_bitemporal_as_of<T>(revs: &[BitemporalRevision<T>], ev_cut: i64, kn_cut: i64) -> Result<&T, NoCurrentIncarnationError> {
    revs.iter().filter(|r| r.event_time_ms <= ev_cut && r.knowledge_time_ms <= kn_cut).max_by_key(|r| (r.event_time_ms, r.knowledge_time_ms)).map(|r| &r.value).ok_or(NoCurrentIncarnationError)
}
