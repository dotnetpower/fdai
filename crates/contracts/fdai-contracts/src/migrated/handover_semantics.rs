#[derive(Clone, Debug, Default, PartialEq)]
pub struct HandoverSemanticReceipt {
    pub schema_version: String,
    pub source_id: String,
    pub source_revision: i64,
    pub source_digest: String,
    pub compiler_digest: String,
    pub package_ref: String,
    pub package_digest: String,
    pub disposition: String,
    pub reason: String,
    pub rule_count: i64,
    pub ontology_count: i64,
    pub review_required: bool,
    pub execution_authority: bool,
    pub projection_authority: bool,
    pub promotion_authority: bool,
}

impl HandoverSemanticReceipt {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !(1_i64..=9223372036854775807_i64).contains(&self.source_revision) { return Err("source_revision out of bounds"); }
        if !matches!(self.disposition.as_str(), "review_required" | "held" | "withdrawn") { return Err("invalid disposition literal"); }
        if !matches!(self.reason.as_str(), "candidates_compiled" | "source_unavailable" | "source_changed" | "source_withdrawn" | "acceptance_required" | "binding_unavailable" | "no_supported_candidates" | "verification_held" | "attempt_interrupted") { return Err("invalid reason literal"); }
        if !(0_i64..=20_i64).contains(&self.rule_count) { return Err("rule_count out of bounds"); }
        if !(0_i64..=20_i64).contains(&self.ontology_count) { return Err("ontology_count out of bounds"); }
        if !self.review_required { return Err("review_required violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        if self.projection_authority { return Err("projection_authority violated literal bool invariant"); }
        if self.promotion_authority { return Err("promotion_authority violated literal bool invariant"); }
        Ok(())
    }
}

impl HandoverSemanticReceipt {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn no_authority(mut value: String) -> Result<String, &'static str> {
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn review_required(mut value: String) -> Result<String, &'static str> {
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn counts(&self) -> Result<HandoverSemanticReceipt, &'static str> {
        let allowed: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("review_required"), String::new()), (String::from("withdrawn"), String::new()), (String::from("held"), String::new())]);
        if ((self.disposition.clone()) == (String::from("review_required"))) && (((self.rule_count).saturating_add(self.ontology_count)) == (0_i64)) {
            return Err("semantic success requires at least one actual candidate");
        }
        if ((self.disposition.clone()) != (String::from("review_required"))) && (((self.rule_count).saturating_add(self.ontology_count)) != 0) {
            return Err("held semantic receipt cannot advertise available candidates");
        }
        if ((self.rule_count).saturating_add(self.ontology_count)) > (20_i64) {
            return Err("semantic receipt exceeds its combined candidate bound");
        }
        if ((self.source_id.clone()) == (self.package_digest.clone())) || ((self.compiler_digest.clone()) == (self.package_digest.clone())) {
            return Err("semantic receipt package_digest MUST be distinct from input digests");
        }
        Ok(self.clone())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["HandoverSemanticReceipt"];
