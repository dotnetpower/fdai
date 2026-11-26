#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CostEffectKind {
    #[default]
    Cost,
    Capacity,
    Service,
    Recovery,
}

impl CostEffectKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Cost => "cost",
            Self::Capacity => "capacity",
            Self::Service => "service",
            Self::Recovery => "recovery",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CostSettlementStatus {
    #[default]
    Verified,
    Failed,
    Censored,
    Unscorable,
}

impl CostSettlementStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Verified => "verified",
            Self::Failed => "failed",
            Self::Censored => "censored",
            Self::Unscorable => "unscorable",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CostSavingsEvidenceClass {
    #[default]
    VerifiedRunRate,
    InvoiceAllocated,
}

impl CostSavingsEvidenceClass {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::VerifiedRunRate => "verified-run-rate",
            Self::InvoiceAllocated => "invoice-allocated",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum CostObservationLane {
    #[default]
    Independent,
    Execution,
}

impl CostObservationLane {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Independent => "independent",
            Self::Execution => "execution",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CostExpectedEffect {
    pub effect_id: String,
    pub kind: CostEffectKind,
    pub target_ref: String,
    pub metric: String,
    pub baseline_value: i64,
    pub acceptable_min: i64,
    pub acceptable_max: i64,
    pub predicted_at: String,
    pub horizon: String,
    pub telemetry_grace: String,
    pub source_digest: String,
    pub estimated_only: bool,
    pub savings_evidence_class: Option<CostSavingsEvidenceClass>,
    pub currency: Option<String>,
    pub baseline_window_digest: Option<String>,
    pub treatment_window_digest: Option<String>,
    pub demand_normalization_digest: Option<String>,
    pub finalized_billing_receipt_digest: Option<String>,
    pub allocation_rule_digest: Option<String>,
}

impl CostExpectedEffect {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn horizon_ends_at(&self) -> String {
        format!("{}{}", self.predicted_at.clone(), self.horizon.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn deadline_at(&self) -> String {
        core::hint::black_box(String::new())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["CostEffectKind", "CostExpectedEffect", "CostObservationLane", "CostSavingsEvidenceClass", "CostSettlementStatus"];
