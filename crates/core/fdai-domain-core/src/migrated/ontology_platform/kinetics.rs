use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum MutationEffectKind {
    #[default]
    ExpectedProperty,
    ExpectedObservation,
    InternalWrite,
    CatalogPr,
    ProviderCommand,
    Notification,
    Schedule,
}

impl MutationEffectKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ExpectedProperty => "expected_property",
            Self::ExpectedObservation => "expected_observation",
            Self::InternalWrite => "internal_write",
            Self::CatalogPr => "catalog_pr",
            Self::ProviderCommand => "provider_command",
            Self::Notification => "notification",
            Self::Schedule => "schedule",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AuthorityClass {
    #[default]
    CatalogOwned,
    FdaiOwned,
    ProviderObserved,
    LedgerOwned,
    Derived,
}

impl AuthorityClass {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::CatalogOwned => "catalog_owned",
            Self::FdaiOwned => "fdai_owned",
            Self::ProviderObserved => "provider_observed",
            Self::LedgerOwned => "ledger_owned",
            Self::Derived => "derived",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ReconciliationStatus {
    #[default]
    Matched,
    Mismatched,
    TimedOut,
    Unscorable,
}

impl ReconciliationStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Matched => "matched",
            Self::Mismatched => "mismatched",
            Self::TimedOut => "timed_out",
            Self::Unscorable => "unscorable",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TargetRevision {
    pub object_id: String,
    pub type_ref: String,
    pub revision: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct MutationEffect {
    pub effect_id: Option<String>,
    pub kind: MutationEffectKind,
    pub target_id: String,
    pub property_name: Option<String>,
    pub value: String,
    pub command_ref: Option<String>,
    pub observation_ref: Option<String>,
    pub function_ref: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ActionArgumentBinding {
    pub name: String,
    pub value_digest: String,
    pub redacted: bool,
    pub safe_value_json: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ActionReadSetReceipt {
    pub function_ref: String,
    pub properties: Vec<String>,
    pub object_count: i64,
    pub complete: bool,
    pub truncated: bool,
    pub observed_at: String,
    pub fresh_until: String,
    pub evidence_refs: Vec<String>,
    pub receipt_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct MutationPlan {
    pub schema_version: String,
    pub plan_id: String,
    pub digest: String,
    pub action_type_ref: String,
    pub planner_ref: String,
    pub operational_plan_ref: String,
    pub targets: Vec<TargetRevision>,
    pub effects: Vec<MutationEffect>,
    pub rollback_effects: Vec<MutationEffect>,
    pub expected_effects: Vec<MutationEffect>,
    pub created_at: String,
    pub arguments_digest: Option<String>,
    pub argument_bindings: Vec<ActionArgumentBinding>,
    pub read_set_receipt_digests: Vec<String>,
    pub criterion_receipt_digests: Vec<String>,
    pub transaction_mode: Option<String>,
    pub lock_scope: Option<String>,
    pub lock_keys: Vec<String>,
    pub max_affected_objects: Option<i64>,
    pub irreversible: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CriterionResult {
    pub criterion_ref: Option<String>,
    pub function_ref: Option<String>,
    pub passed: bool,
    pub reason_code: String,
    pub evidence_refs: Vec<String>,
    pub complete: bool,
    pub truncated: bool,
    pub observed_at: String,
    pub fresh_until: String,
    pub receipt_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProjectionBinding {
    pub binding_id: String,
    pub source_id: String,
    pub object_type_ref: String,
    pub authority_class: AuthorityClass,
    pub identity_field: String,
    pub property_map: BTreeMap<String, String>,
    pub watermark_field: String,
    pub delete_field: Option<String>,
    pub max_batch_size: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReconciliationReceipt {
    pub schema_version: String,
    pub plan_digest: String,
    pub status: ReconciliationStatus,
    pub observed_at: String,
    pub evidence_refs: Vec<String>,
    pub mismatches: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProjectedBatch {
    pub objects: Vec<String>,
    pub deleted_ids: Vec<String>,
    pub watermark: Option<String>,
}

impl MutationEffect {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn effect_shape_is_explicit(&self) -> Result<MutationEffect, &'static str> {
        Err("runtime_binding_required")
    }
}

impl ActionReadSetReceipt {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn create(mut values: std::collections::BTreeMap<String, String>) -> String {
        values = values.clone();
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn receipt_is_content_addressed(&self) -> Result<ActionReadSetReceipt, &'static str> {
        let _ = require_receipt_times(self.observed_at.clone(), self.fresh_until.clone()).unwrap_or_else(|_| ());
        if (self.receipt_digest.clone()) != (content_digest(String::new()).unwrap_or_else(|_| String::new())) {
            return Err("read-set receipt digest does not match its content");
        }
        Ok(self.clone())
    }
}

impl MutationPlan {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn has_bounded_targets_and_recovery(&self) -> Result<MutationPlan, &'static str> {
        if (self.targets.clone()).is_empty() {
            return Err("MutationPlan requires at least one target");
        }
        if (self.effects.clone()).is_empty() {
            return Err("MutationPlan requires at least one effect");
        }
        if ((self.rollback_effects.clone()).is_empty()) && (!(self.irreversible)) {
            return Err("MutationPlan requires rollback or compensation effects");
        }
        if (self.schema_version.clone()) == (String::from("2.0.0")) {
            if self.arguments_digest.is_none() {
                return Err("semantic MutationPlan requires arguments_digest");
            }
            if (self.transaction_mode.is_none()) || (self.lock_scope.is_none()) {
                return Err("semantic MutationPlan requires transaction and lock policy");
            }
            if (self.max_affected_objects.is_none()) || ((self.lock_keys.clone()).is_empty()) {
                return Err("semantic MutationPlan requires bounded deterministic lock keys");
            }
            if ((((self.read_set_receipt_digests.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) != (((self.read_set_receipt_digests.clone()).len() as i64)) {
                return Err("semantic MutationPlan read-set receipt digests MUST be unique");
            }
            if ((((self.criterion_receipt_digests.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) != (((self.criterion_receipt_digests.clone()).len() as i64)) {
                return Err("semantic MutationPlan criterion receipt digests MUST be unique");
            }
        }
        Ok(self.clone())
    }
}

impl CriterionResult {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn create(mut values: std::collections::BTreeMap<String, String>) -> String {
        values = values.clone();
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn criterion_receipt_is_canonical(&self) -> Result<CriterionResult, &'static str> {
        if (self.criterion_ref.is_none()) == (self.function_ref.is_none()) {
            return Err("CriterionResult requires exactly one criterion reference");
        }
        let _ = require_receipt_times(self.observed_at.clone(), self.fresh_until.clone()).unwrap_or_else(|_| ());
        if (self.receipt_digest.clone()) != (content_digest(String::new()).unwrap_or_else(|_| String::new())) {
            return Err("criterion receipt digest does not match its content");
        }
        Ok(self.clone())
    }
}

impl ReconciliationReceipt {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn status_and_evidence_are_canonical(&self) -> Result<ReconciliationReceipt, &'static str> {
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn content_digest(mut value: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn json_default(mut value: String) -> Result<String, &'static str> {
    Err("unsupported action receipt value typevalue.__name__")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn require_receipt_times(mut observed_at: String, mut fresh_until: String) -> Result<(), &'static str> {
    if (fresh_until.clone()) < (observed_at.clone()) {
        return Err("action receipt fresh_until precedes observed_at");
    }
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["ActionArgumentBinding", "ActionReadSetReceipt", "AuthorityClass", "CriterionResult", "MutationEffect", "MutationEffectKind", "MutationPlan", "OntologyFunctionKind", "OntologyFunctionType", "ProjectionBinding", "ProjectedBatch", "ReconciliationReceipt", "ReconciliationStatus", "TargetRevision"];
