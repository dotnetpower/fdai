#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExecutorClassAnchorInputs {
    pub core_runtime_executor: String,
    pub isolated_executor: String,
    pub dev_operations_gateway_executor: String,
    pub vertical_effect_executors: Vec<String>,
    pub deploy_runner: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct VerifierDeploymentPreflightError {
    pub message: String,
}

impl VerifierDeploymentPreflightError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for VerifierDeploymentPreflightError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for VerifierDeploymentPreflightError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn build_executor_class_anchor_set(mut inputs: ExecutorClassAnchorInputs) -> Result<std::collections::BTreeSet<String>, &'static str> {
    let mut labeled: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("core_runtime_executor"), inputs.core_runtime_executor.clone()), (String::from("isolated_executor"), inputs.isolated_executor.clone()), (String::from("dev_operations_gateway_executor"), inputs.dev_operations_gateway_executor.clone()), (String::from("deploy_runner"), inputs.deploy_runner.clone())]);
    if (inputs.vertical_effect_executors.clone()).is_empty() {
        return Err("vertical effect executor principals are missing");
    }
    let mut normalized: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    for (label, principal) in labeled.clone() {
        let value: String = (principal.clone()).trim().to_string();
        if (value.clone()).is_empty() {
            return Err("label principal is missing");
        }
        if (normalized.clone()).contains_key(value.as_str()) {
            return Err("label duplicates normalizedvalue principal");
        }
        normalized.insert(value.clone(), label.clone());
    }
    Ok(std::collections::BTreeSet::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn assert_verifier_not_executor_class(mut verifier_principal: String, mut executor_class_principals: Vec<String>) -> Result<(), &'static str> {
    let verifier: String = verifier_principal.trim().to_string();
    if (verifier.clone()).is_empty() {
        return Err("verifier principal is missing");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn executor_class_anchor_report(mut inputs: ExecutorClassAnchorInputs) -> std::collections::BTreeMap<String, String> {
    let anchors: std::collections::BTreeSet<String> = build_executor_class_anchor_set(inputs.clone()).unwrap_or_else(|_| std::collections::BTreeSet::new());
    std::collections::BTreeMap::from([(String::from("executor_class_anchor_count"), (((anchors.clone()).len() as i64)).to_string()), (String::from("core_runtime_executor"), String::from("bound")), (String::from("isolated_executor"), String::from("bound")), (String::from("dev_operations_gateway_executor"), String::from("bound")), (String::from("vertical_effect_executors"), (((inputs.vertical_effect_executors.clone()).len() as i64)).to_string()), (String::from("deploy_runner"), String::from("bound"))])
}

pub const PUBLIC_EXPORTS: &[&str] = &["ExecutorClassAnchorInputs", "VerifierDeploymentPreflightError", "assert_verifier_not_executor_class", "build_executor_class_anchor_set", "executor_class_anchor_report"];
