#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RuleReplicaDisposition {
    #[default]
    Acknowledged,
    Refused,
}

impl RuleReplicaDisposition {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Acknowledged => "acknowledged",
            Self::Refused => "refused",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RuleReplicaDepartureKind {
    #[default]
    Drained,
    LeaseExpired,
}

impl RuleReplicaDepartureKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Drained => "drained",
            Self::LeaseExpired => "lease_expired",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleReplicaIdentity {
    pub replica_id: String,
    pub principal_id: String,
    pub release_id: String,
    pub startup_epoch: String,
    pub serving_lease_id: String,
    pub serving_lease_expires_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleReplicaDepartureEvidence {
    pub replica: Box<RuleReplicaIdentity>,
    pub kind: RuleReplicaDepartureKind,
    pub serving_inventory_digest: String,
    pub authentication_receipt_digest: String,
    pub observed_at: String,
    pub evidence_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleCohortPrepareV2 {
    pub schema_version: String,
    pub generation: String,
    pub predecessor_prepare_digest: Option<String>,
    pub serving_inventory_digest: String,
    pub revision_registry_root: String,
    pub catalog_manifest_digest: String,
    pub replicas: Vec<RuleReplicaIdentity>,
    pub departures: Vec<RuleReplicaDepartureEvidence>,
    pub prepared_at: String,
    pub prepare_digest: String,
    pub approval_authority: bool,
    pub activation_authority: bool,
    pub execution_authority: bool,
}

impl RuleCohortPrepareV2 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "2.0.0") { return Err("invalid schema_version literal"); }
        if self.approval_authority { return Err("approval_authority violated literal bool invariant"); }
        if self.activation_authority { return Err("activation_authority violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleReplicaAcknowledgementV2 {
    pub schema_version: String,
    pub prepare_digest: String,
    pub replica_id: String,
    pub principal_id: String,
    pub release_id: String,
    pub startup_epoch: String,
    pub serving_lease_id: String,
    pub revision_registry_root: String,
    pub catalog_manifest_digest: String,
    pub profile_snapshot_digest: String,
    pub generation_digest: String,
    pub supported_read_schema_versions: Vec<String>,
    pub write_schema_version: String,
    pub disposition: RuleReplicaDisposition,
    pub reason: String,
    pub authentication_receipt_digest: String,
    pub observed_at: String,
    pub acknowledgement_digest: String,
    pub activation_authority: bool,
    pub execution_authority: bool,
}

impl RuleReplicaAcknowledgementV2 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "2.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.write_schema_version.as_str(), "1.0.0" | "2.0.0") { return Err("invalid write_schema_version literal"); }
        if self.activation_authority { return Err("activation_authority violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleCohortCandidateActiveV2 {
    pub schema_version: String,
    pub prepare_digest: String,
    pub generation_digest: String,
    pub acknowledgement_set_digest: String,
    pub activated_at: String,
    pub activation_authority: bool,
    pub execution_authority: bool,
}

impl RuleCohortCandidateActiveV2 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "2.0.0") { return Err("invalid schema_version literal"); }
        if self.activation_authority { return Err("activation_authority violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RuleReplicaAppliedV2 {
    pub schema_version: String,
    pub prepare_digest: String,
    pub acknowledgement_set_digest: String,
    pub replica_id: String,
    pub principal_id: String,
    pub release_id: String,
    pub startup_epoch: String,
    pub serving_lease_id: String,
    pub generation_digest: String,
    pub applied_at: String,
    pub activation_authority: bool,
    pub execution_authority: bool,
}

impl RuleReplicaAppliedV2 {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "2.0.0") { return Err("invalid schema_version literal"); }
        if self.activation_authority { return Err("activation_authority violated literal bool invariant"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

impl RuleReplicaIdentity {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn exact_text(mut value: String) -> Result<String, &'static str> {
        if (true) && ((value.clone()) != (value.trim().to_string())) {
            return Err("Rule replica identity text MUST be exact");
        }
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn aware_utc(mut value: String) -> Result<String, &'static str> {
        if value.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

impl RuleReplicaDepartureEvidence {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn aware_utc(mut value: String) -> String {
        utc(value.clone()).unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn canonical_evidence(&self) -> Result<String, &'static str> {
        let expected: String = rule_replica_departure_evidence_digest(*(self.replica.clone()), self.kind.clone(), self.serving_inventory_digest.clone(), self.authentication_receipt_digest.clone(), self.observed_at.clone());
        if (self.evidence_digest.clone()) != (expected.clone()) {
            return Err("Rule replica departure evidence digest mismatch");
        }
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn replica_id(&self) -> String {
        core::hint::black_box(String::new())
    }
}

impl RuleCohortPrepareV2 {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn aware_utc(mut value: String) -> Result<String, &'static str> {
        if value.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn canonical_prepare(&self) -> Result<String, &'static str> {
        let expected: String = rule_cohort_prepare_digest(self.generation.clone(), self.predecessor_prepare_digest.clone(), self.serving_inventory_digest.clone(), self.revision_registry_root.clone(), self.catalog_manifest_digest.clone(), self.replicas.clone(), self.departures.clone(), self.prepared_at.clone());
        if (self.prepare_digest.clone()) != (expected.clone()) {
            return Err("Rule cohort prepare digest mismatch");
        }
        Ok(String::new())
    }
}

impl RuleReplicaAcknowledgementV2 {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn exact_text(mut value: String) -> Result<String, &'static str> {
        if (true) && ((value.clone()) != (value.trim().to_string())) {
            return Err("Rule replica acknowledgement text MUST be exact");
        }
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn aware_utc(mut value: String) -> Result<String, &'static str> {
        if value.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn canonical_acknowledgement(&self) -> Result<String, &'static str> {
        if !((self.supported_read_schema_versions.clone()).contains(&(self.write_schema_version.clone()))) {
            return Err("Rule replica MUST be able to read its write schema version");
        }
        let expected: String = rule_replica_acknowledgement_digest(std::collections::BTreeMap::new());
        if (self.acknowledgement_digest.clone()) != (expected.clone()) {
            return Err("Rule replica acknowledgement digest mismatch");
        }
        Ok(String::new())
    }
}

impl RuleCohortCandidateActiveV2 {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn aware_utc(mut value: String) -> Result<String, &'static str> {
        if value.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

impl RuleReplicaAppliedV2 {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn exact_text(mut value: String) -> Result<String, &'static str> {
        if (true) && ((value.clone()) != (value.trim().to_string())) {
            return Err("Rule replica applied identity text MUST be exact");
        }
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn aware_utc(mut value: String) -> Result<String, &'static str> {
        if value.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::too_many_arguments)]
pub fn build_rule_cohort_prepare_v2(mut generation: String, mut predecessor_prepare_digest: Option<String>, mut serving_inventory_digest: String, mut revision_registry_root: String, mut catalog_manifest_digest: String, mut replicas: Vec<RuleReplicaIdentity>, mut departures: Vec<RuleReplicaDepartureEvidence>, mut prepared_at: String) -> RuleCohortPrepareV2 {
    RuleCohortPrepareV2 { generation: generation.clone(), predecessor_prepare_digest: predecessor_prepare_digest.clone(), serving_inventory_digest: serving_inventory_digest.clone(), revision_registry_root: revision_registry_root.clone(), catalog_manifest_digest: catalog_manifest_digest.clone(), replicas: replicas.clone(), departures: departures.clone(), prepared_at: prepared_at.clone(), prepare_digest: rule_cohort_prepare_digest(generation.clone(), predecessor_prepare_digest.clone(), serving_inventory_digest.clone(), revision_registry_root.clone(), catalog_manifest_digest.clone(), replicas.clone(), departures.clone(), prepared_at.clone()), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::too_many_arguments)]
pub fn rule_cohort_prepare_digest(mut generation: String, mut predecessor_prepare_digest: Option<String>, mut serving_inventory_digest: String, mut revision_registry_root: String, mut catalog_manifest_digest: String, mut replicas: Vec<RuleReplicaIdentity>, mut departures: Vec<RuleReplicaDepartureEvidence>, mut prepared_at: String) -> String {
    if generation.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn rule_replica_acknowledgement_digest(mut values: std::collections::BTreeMap<String, String>) -> String {
    if values.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_rule_replica_departure_evidence(mut replica: RuleReplicaIdentity, mut kind: RuleReplicaDepartureKind, mut serving_inventory_digest: String, mut authentication_receipt_digest: String, mut observed_at: String) -> RuleReplicaDepartureEvidence {
    RuleReplicaDepartureEvidence { replica: Box::new(replica.clone()), kind: kind.clone(), serving_inventory_digest: serving_inventory_digest.clone(), authentication_receipt_digest: authentication_receipt_digest.clone(), observed_at: observed_at.clone(), evidence_digest: rule_replica_departure_evidence_digest(replica.clone(), kind.clone(), serving_inventory_digest.clone(), authentication_receipt_digest.clone(), observed_at.clone()), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn rule_replica_departure_evidence_digest(mut replica: RuleReplicaIdentity, mut kind: RuleReplicaDepartureKind, mut serving_inventory_digest: String, mut authentication_receipt_digest: String, mut observed_at: String) -> String {
    if serving_inventory_digest.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn rule_acknowledgement_set_digest(mut acknowledgements: Vec<RuleReplicaAcknowledgementV2>) -> Result<String, &'static str> {
    if acknowledgements.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn utc(mut value: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["RuleCohortCandidateActiveV2", "RuleCohortPrepareV2", "RuleReplicaAcknowledgementV2", "RuleReplicaAppliedV2", "RuleReplicaDepartureEvidence", "RuleReplicaDepartureKind", "RuleReplicaDisposition", "RuleReplicaIdentity", "build_rule_replica_departure_evidence", "build_rule_cohort_prepare_v2", "rule_acknowledgement_set_digest", "rule_cohort_prepare_digest", "rule_replica_acknowledgement_digest", "rule_replica_departure_evidence_digest"];
