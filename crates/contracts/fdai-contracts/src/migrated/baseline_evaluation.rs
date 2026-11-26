#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum BaselineEvaluationTerminalOutcome {
    #[default]
    Compliant,
    Violated,
    Abstained,
}

impl BaselineEvaluationTerminalOutcome {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Compliant => "compliant",
            Self::Violated => "violated",
            Self::Abstained => "abstained",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum BaselineEvaluationCoverageLimitation {
    #[default]
    PairMissing,
    DuplicatePair,
    ConflictingPair,
    UnexpectedPair,
    RuleRevisionDrift,
}

impl BaselineEvaluationCoverageLimitation {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::PairMissing => "pair_missing",
            Self::DuplicatePair => "duplicate_pair",
            Self::ConflictingPair => "conflicting_pair",
            Self::UnexpectedPair => "unexpected_pair",
            Self::RuleRevisionDrift => "rule_revision_drift",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BaselineEvaluationOutcome {
    pub schema_version: String,
    pub generation_id: String,
    pub generation_digest: String,
    pub inventory_observation_digest: String,
    pub resource_ref: String,
    pub resource_digest: String,
    pub catalog_revision: String,
    pub rule_ref: String,
    pub rule_revision: String,
    pub expected_denominator: i64,
    pub outcome: BaselineEvaluationTerminalOutcome,
    pub reason_code: Option<String>,
    pub evaluation_receipt_ref: String,
    pub evaluation_receipt_digest: String,
    pub saga_audit_ref: String,
    pub saga_audit_digest: String,
    pub evaluated_at: String,
    pub execution_authority: bool,
    pub outcome_digest: String,
}

impl BaselineEvaluationOutcome {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !(1_i64..=10000000_i64).contains(&self.expected_denominator) { return Err("expected_denominator out of bounds"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BaselineEvaluationCompletion {
    pub schema_version: String,
    pub generation_id: String,
    pub generation_digest: String,
    pub inventory_observation_digest: String,
    pub catalog_revision: String,
    pub expected_denominator: i64,
    pub compliant_count: i64,
    pub violated_count: i64,
    pub abstained_count: i64,
    pub outcome_set_digest: String,
    pub completion_receipt_ref: String,
    pub completion_receipt_digest: String,
    pub saga_audit_ref: String,
    pub saga_audit_digest: String,
    pub completed_at: String,
    pub complete: bool,
    pub projection_authority: bool,
    pub execution_authority: bool,
    pub completion_digest: String,
}

impl BaselineEvaluationCompletion {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !(0_i64..=10000000_i64).contains(&self.expected_denominator) { return Err("expected_denominator out of bounds"); }
        if !(0_i64..=10000000_i64).contains(&self.compliant_count) { return Err("compliant_count out of bounds"); }
        if !(0_i64..=10000000_i64).contains(&self.violated_count) { return Err("violated_count out of bounds"); }
        if !(0_i64..=10000000_i64).contains(&self.abstained_count) { return Err("abstained_count out of bounds"); }
        if !self.complete { return Err("complete violated literal bool invariant"); }
        if self.projection_authority { return Err("projection_authority violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BaselineEvaluationCoverage {
    pub schema_version: String,
    pub generation_id: String,
    pub generation_digest: String,
    pub inventory_observation_digest: String,
    pub rule_activation_generation_id: String,
    pub rule_activation_generation_digest: String,
    pub rule_catalog_digest: String,
    pub evaluated_rule_catalog_digest: String,
    pub dispatch_signal: String,
    pub expected_pair_set_digest: String,
    pub expected_pair_count: i64,
    pub covered_pair_count: i64,
    pub compliant_count: i64,
    pub violated_count: i64,
    pub abstained_count: i64,
    pub missing_pair_count: i64,
    pub duplicate_pair_count: i64,
    pub conflicting_pair_count: i64,
    pub unexpected_pair_count: i64,
    pub revision_mismatch_count: i64,
    pub outcome_set_digest: String,
    pub complete: bool,
    pub limitations: Vec<BaselineEvaluationCoverageLimitation>,
    pub audit_ref: String,
    pub audit_digest: String,
    pub completed_at: String,
    pub projection_authority: bool,
    pub execution_authority: bool,
    pub coverage_digest: String,
}

impl BaselineEvaluationCoverage {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !(0_i64..=10000000_i64).contains(&self.expected_pair_count) { return Err("expected_pair_count out of bounds"); }
        if !(0_i64..=10000000_i64).contains(&self.covered_pair_count) { return Err("covered_pair_count out of bounds"); }
        if !(0_i64..=10000000_i64).contains(&self.compliant_count) { return Err("compliant_count out of bounds"); }
        if !(0_i64..=10000000_i64).contains(&self.violated_count) { return Err("violated_count out of bounds"); }
        if !(0_i64..=10000000_i64).contains(&self.abstained_count) { return Err("abstained_count out of bounds"); }
        if !(0_i64..=10000000_i64).contains(&self.missing_pair_count) { return Err("missing_pair_count out of bounds"); }
        if !(0_i64..=10000000_i64).contains(&self.duplicate_pair_count) { return Err("duplicate_pair_count out of bounds"); }
        if !(0_i64..=10000000_i64).contains(&self.conflicting_pair_count) { return Err("conflicting_pair_count out of bounds"); }
        if !(0_i64..=10000000_i64).contains(&self.unexpected_pair_count) { return Err("unexpected_pair_count out of bounds"); }
        if !(0_i64..=10000000_i64).contains(&self.revision_mismatch_count) { return Err("revision_mismatch_count out of bounds"); }
        if self.projection_authority { return Err("projection_authority violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

impl BaselineEvaluationOutcome {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn canonical_outcome(&self) -> Result<BaselineEvaluationOutcome, &'static str> {
        let expected: String = baseline_evaluation_outcome_digest(std::collections::BTreeMap::new());
        if (self.outcome_digest.clone()) != (expected.clone()) {
            return Err("baseline evaluation outcome digest mismatch");
        }
        Ok(self.clone())
    }
}

impl BaselineEvaluationCompletion {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn canonical_completion(&self) -> Result<BaselineEvaluationCompletion, &'static str> {
        let observed: i64 = (self.compliant_count).saturating_add((self.violated_count).saturating_add(self.abstained_count));
        if (observed) != (self.expected_denominator) {
            return Err("baseline evaluation completion counts MUST match the denominator");
        }
        let expected: String = baseline_evaluation_completion_digest(std::collections::BTreeMap::new());
        if (self.completion_digest.clone()) != (expected.clone()) {
            return Err("baseline evaluation completion digest mismatch");
        }
        Ok(self.clone())
    }
}

impl BaselineEvaluationCoverage {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn canonical_coverage(&self) -> Result<BaselineEvaluationCoverage, &'static str> {
        if ((self.compliant_count).saturating_add((self.violated_count).saturating_add(self.abstained_count))) != (self.covered_pair_count) {
            return Err("baseline evaluation coverage outcome counts MUST match covered pairs");
        }
        if (self.covered_pair_count) > (self.expected_pair_count) {
            return Err("baseline evaluation coverage cannot exceed the expected pairs");
        }
        let expected: String = baseline_evaluation_coverage_digest(std::collections::BTreeMap::new());
        if (self.coverage_digest.clone()) != (expected.clone()) {
            return Err("baseline evaluation coverage digest mismatch");
        }
        Ok(self.clone())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn baseline_evaluation_outcome_digest(mut values: std::collections::BTreeMap<String, String>) -> String {
    let mut body: std::collections::BTreeMap<String, String> = values.clone();
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn baseline_evaluation_completion_digest(mut values: std::collections::BTreeMap<String, String>) -> String {
    let mut body: std::collections::BTreeMap<String, String> = values.clone();
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn baseline_evaluation_coverage_digest(mut values: std::collections::BTreeMap<String, String>) -> String {
    let mut body: std::collections::BTreeMap<String, String> = values.clone();
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["BaselineEvaluationCompletion", "BaselineEvaluationCoverage", "BaselineEvaluationCoverageLimitation", "BaselineEvaluationOutcome", "BaselineEvaluationTerminalOutcome", "baseline_evaluation_completion_digest", "baseline_evaluation_coverage_digest", "baseline_evaluation_outcome_digest"];
