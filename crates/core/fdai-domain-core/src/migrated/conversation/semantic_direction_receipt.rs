#[derive(Clone, Debug, Default, PartialEq)]
pub struct DirectionCostReceipt {
    pub readers: i64,
    pub calls: i64,
    pub input_bytes: i64,
    pub output_tokens: i64,
    pub wall_ms: i64,
    pub unsettled_calls: i64,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn direction_cost_receipt(mut ledger: String, mut direction_calls: i64, mut tiebreak_calls: i64) -> Option<DirectionCostReceipt> {
    let first_calls: i64 = ((direction_calls).saturating_sub(tiebreak_calls)).max(0_i64);
    let receipt: DirectionCostReceipt = DirectionCostReceipt::default();
    Some(receipt.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["DirectionCostReceipt", "direction_cost_receipt"];
