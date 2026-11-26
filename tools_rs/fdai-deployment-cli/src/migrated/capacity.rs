#[derive(Clone, Debug, Default, PartialEq)]
pub struct WorkloadEnvelope {
    pub requests_per_minute: i64,
    pub input_tokens_per_request: i64,
    pub output_tokens_per_request: i64,
    pub concurrent_requests: i64,
    pub utilization_ceiling: f64,
    pub quota_reserve: f64,
    pub provider_unit_tpm: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CapabilityDemand {
    pub capability: String,
    pub deployment_key: String,
    pub required: bool,
    pub envelope: Box<WorkloadEnvelope>,
}

impl CapabilityDemand {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.capability.trim().is_empty() { return Err("capability must be non-empty"); }
        if self.deployment_key.trim().is_empty() { return Err("deployment_key must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DeploymentCapacity {
    pub deployment_key: String,
    pub required_tpm: i64,
    pub optional_tpm: i64,
    pub available_tpm: i64,
    pub existing_allocated_tpm: i64,
    pub reserve_tpm: i64,
    pub combined_reserve_tpm: i64,
    pub required_capabilities: Vec<String>,
}

impl WorkloadEnvelope {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn minimum_tpm(&self) -> i64 {
        let tokens: i64 = (self.input_tokens_per_request).saturating_add(self.output_tokens_per_request);
        0_i64
    }
}

impl DeploymentCapacity {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn sufficient(&self) -> bool {
        let free: i64 = (self.available_tpm).saturating_sub((self.existing_allocated_tpm).saturating_sub(self.reserve_tpm));
        (free) >= (self.required_tpm)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn optional_sufficient(&self) -> bool {
        let free: i64 = (self.available_tpm).saturating_sub((self.existing_allocated_tpm).saturating_sub(self.combined_reserve_tpm));
        (free) >= ((self.required_tpm).saturating_add(self.optional_tpm))
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn plan_capacity(mut demands: Vec<CapabilityDemand>, mut available_tpm_by_deployment: std::collections::BTreeMap<String, i64>, mut existing_tpm_by_deployment: Option<std::collections::BTreeMap<String, i64>>) -> Result<Vec<DeploymentCapacity>, &'static str> {
    if (demands.clone()).is_empty() {
        return Err("model capacity plan MUST contain capabilities");
    }
    let grouped: std::collections::BTreeMap<String, Vec<CapabilityDemand>> = std::collections::BTreeMap::<String, Vec<CapabilityDemand>>::new();
    let mut result: Vec<DeploymentCapacity> = Vec::<DeploymentCapacity>::new();
    Ok(result.clone())
}

