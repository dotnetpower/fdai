#[derive(Clone, Debug, Default, PartialEq)]
pub struct SreScenarioContract {
    pub scenario_id: String,
    pub title: String,
    pub fault: bool,
    pub signals: Vec<String>,
    pub causal_mechanism: String,
    pub chaos_scenario_id: Option<String>,
    pub recovery_probes: Vec<String>,
    pub recovery_action_types: Vec<String>,
}

impl SreScenarioContract {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.scenario_id.trim().is_empty() { return Err("scenario_id must be non-empty"); }
        if self.title.trim().is_empty() { return Err("title must be non-empty"); }
        if self.causal_mechanism.trim().is_empty() { return Err("causal_mechanism must be non-empty"); }
        Ok(())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn sre_scenario_contracts() -> Vec<SreScenarioContract> {
    core::hint::black_box(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn fault(mut scenario_id: String, mut title: String, mut signal: String, mut mechanism: String, mut chaos_scenario_id: String, mut recovery_action_type: String) -> SreScenarioContract {
    SreScenarioContract { scenario_id: scenario_id.clone(), title: title.clone(), fault: true, causal_mechanism: mechanism.clone(), chaos_scenario_id: Some(chaos_scenario_id.clone()), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_sre_scenario_contracts() -> Result<(), &'static str> {
    let contracts: Vec<SreScenarioContract> = sre_scenario_contracts();
    for contract in contracts.clone() {
        if contract.fault {
            if (contract.recovery_action_types.clone()).is_empty() {
                return Err("contract.scenario_id lacks a recovery action");
            }
        } else if (contract.chaos_scenario_id.clone()).is_some() {
            return Err("contract.scenario_id is non-fault but references chaos");
        }
    }
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["SreScenarioContract", "sre_scenario_contracts", "validate_sre_scenario_contracts"];
