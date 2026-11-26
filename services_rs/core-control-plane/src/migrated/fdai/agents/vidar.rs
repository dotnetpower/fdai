#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Vidar {
    pub initialized: bool,
}

impl Vidar {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn bind_bus(&mut self, mut bus: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn bind_rollback_rehearsal_port(&mut self, mut port: Option<String>) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn validated_contract_count(&self) -> i64 {
        0_i64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn maintenance_tick(&self) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn bind_rollback_contracts(&mut self, mut contracts_by_action_type: std::collections::BTreeMap<String, String>) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_rollback_paths(&mut self) {
        let mut validated: i64 = 0_i64;
        let mut missing: i64 = 0_i64;
        let total: i64 = (validated).saturating_add(missing);
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn bind_typed_read_demoter(&mut self, mut demoter: String) {
        if !self.initialized {
            return;
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["RollbackClaimInProgressError", "RollbackExecutor", "RollbackRecord", "Vidar"];
