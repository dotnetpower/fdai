#[derive(Clone, Debug, Default, PartialEq)]
pub struct MutationDependencyReadiness {
    pub saga_audit_durable: bool,
    pub vidar_recovery_contracts: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct InProcessThorExecutionPort {
    pub pr_native: String,
    pub direct_api: Option<String>,
    pub tool_call: Option<String>,
    pub safeguard_lifecycle_ready: bool,
}

pub trait PrNativeExecutionPort {
    fn execute(&self, action: String, rule: String, execution_path: String) -> String;
}

pub trait DirectApiExecutionPort {
    fn execute(&self, action: String) -> String;
}

pub trait ToolCallExecutionPort {
    fn execute(&self, action: String) -> String;
}

impl MutationDependencyReadiness {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn mutation_ready(&self) -> bool {
        (self.saga_audit_durable) && (!(self.vidar_recovery_contracts.clone()).is_empty())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn require_for_mode(&self, mut enforce: bool) -> Result<(), &'static str> {
        let mut missing: Vec<String> = Vec::<String>::new();
        if !(self.saga_audit_durable) {
            missing.push(String::from("durable_saga"));
        }
        if (self.vidar_recovery_contracts.clone()).is_empty() {
            missing.push(String::from("rollback_executors"));
        }
        Err("Thor mutation requires explicit durable safety bindings:    .joinmissing")
    }
}

pub trait ThorExecutionPort {
    fn pr_native(&self) -> String;
    fn safeguard_lifecycle_ready(&self) -> bool;
    fn direct_api(&self) -> Option<String>;
    fn tool_call(&self) -> Option<String>;
}

pub const PUBLIC_EXPORTS: &[&str] = &["DirectApiExecutionPort", "InProcessThorExecutionPort", "MutationDependencyReadiness", "ThorExecutionPort", "ThorSafetyDependencyReadiness"];
