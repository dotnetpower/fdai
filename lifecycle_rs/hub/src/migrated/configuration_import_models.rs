#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConfigurationScopeRequest {
    pub digest: String,
    pub installation_id: String,
    pub payload: String,
    pub identity_proof: String,
    pub requested_by: String,
    pub recorded_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConfigurationScopeApproval {
    pub digest: String,
    pub installation_id: String,
    pub approved_by: String,
    pub approved_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConfigurationImport {
    pub digest: String,
    pub installation_id: String,
    pub revision_id: String,
    pub predecessor_digest: String,
    pub container: String,
    pub context: String,
    pub identity_proof: String,
    pub binding_version: String,
    pub binding_digest: String,
    pub scope_digest: String,
    pub receipt_digest: String,
    pub requested_by: String,
    pub imported_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConfigurationHead {
    pub installation_id: String,
    pub accepted_digest: String,
    pub active_digest: String,
    pub activated_by: String,
    pub activated_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConfigurationChangeApproval {
    pub digest: String,
    pub receipt_digest: String,
    pub approved_by: String,
    pub approved_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConfigurationPlanImport {
    pub plan_id: String,
    pub import_digest: String,
    pub receipt_digest: String,
}

