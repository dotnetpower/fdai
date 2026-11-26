pub const MAX_RESPONSE_BYTES: i64 = 262144;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureGatewayDirectApiConfig {
    pub base_url: String,
    pub audience: String,
    pub timeout_seconds: f64,
    pub poll_interval_seconds: f64,
    pub max_poll_attempts: i64,
    pub poll_timeout_seconds: f64,
}

impl AzureGatewayDirectApiConfig {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.base_url.trim().is_empty() { return Err("base_url must be non-empty"); }
        if self.audience.trim().is_empty() { return Err("audience must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureGatewayDirectApiExecutor {
    pub initialized: bool,
}

impl AzureGatewayDirectApiExecutor {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn execute(&self, mut request: String) -> Result<String, &'static str> {
        let arguments: std::collections::BTreeMap<String, String> = arguments(String::new(), std::collections::BTreeMap::new(), String::new(), String::new()).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let safety: std::collections::BTreeMap<String, String> = safety(request.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let plan: std::collections::BTreeMap<String, String> = self.invoke(String::from("azure.operation.plan"), std::collections::BTreeMap::from([(String::from("operation_id"), String::new()), (String::from("arguments"), String::new()), (String::from("safety"), String::new())])).await.unwrap_or_else(|_| std::collections::BTreeMap::new());
        let plan_result: std::collections::BTreeMap<String, String> = result(plan.clone(), String::from("azure.operation.plan")).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let receipt: Option<String> = (plan_result.clone()).get("dry_run_receipt").cloned();
        if (!(true)) || (!((receipt.clone()).is_some())) {
            return Err("invalid_response gateway plan omitted dry_run_receipt");
        }
        let mut mutation_safety: std::collections::BTreeMap<String, String> = safety.clone();
        mutation_safety.insert(String::from("dry_run_receipt"), (receipt.clone()).unwrap_or_default());
        let response: std::collections::BTreeMap<String, String> = self.invoke(String::new(), std::collections::BTreeMap::from([(String::from("safety"), String::new())])).await.unwrap_or_else(|_| std::collections::BTreeMap::new());
        let body: std::collections::BTreeMap<String, String> = validated_body(response.clone(), String::new()).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let status: Option<String> = (body.clone()).get("status").cloned();
        if (status.clone()) == Some(String::from("succeeded")) {
            return Ok(success_receipt(request.clone()));
        }
        Ok(self.poll_until_terminal(request.clone()).await.unwrap_or_else(|_| String::new()))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn poll_until_terminal(&self, mut request: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn invoke(&self, mut operation_id: String, mut payload: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        Ok(std::collections::BTreeMap::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn arguments(mut operation_id: String, mut raw: std::collections::BTreeMap<String, String>, mut resource_ref: String, mut action_type_name: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if (operation_id.clone()) == (String::from("azure.compute.vmss.scale")) {
        return Ok(vmss_scale_arguments(raw.clone(), resource_ref.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new()));
    }
    if (operation_id.clone()).starts_with("azure.compute.vm.") {
        let mut required: String = String::from("resource_group\", \"vm_name");
    } else if (operation_id.clone()) == (String::from("azure.network.nsg.rule.delete")) {
        let mut required: String = String::from("resource_group\", \"nsg_name\", \"rule_name");
    } else {
        let mut required: String = String::from("resource_group\", \"nsg_name\", \"rule_name\", \"rule");
    }
    let mut arguments: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    Ok(arguments.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn tag_arguments(mut action_type_name: String, mut raw: std::collections::BTreeMap<String, String>, mut resource_ref: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let arguments: std::collections::BTreeMap<String, String> = raw.clone();
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn vmss_scale_arguments(mut raw: std::collections::BTreeMap<String, String>, mut resource_ref: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let target_ref: Option<String> = (raw.clone()).get("target_resource_ref").cloned();
    let replica_count: Option<String> = (raw.clone()).get("replica_count").cloned();
    let reason: Option<String> = (raw.clone()).get("reason").cloned();
    if (!(true)) || ((target_ref.clone()) != Some(resource_ref.clone())) {
        return Err("scale-out target_resource_ref must match the action resource");
    }
    Ok(std::collections::BTreeMap::from([(String::from("resource_group"), String::new()), (String::from("vmss_name"), String::new()), (String::from("target_resource_ref"), (target_ref.clone()).unwrap_or_default()), (String::from("replica_count"), (replica_count.clone()).unwrap_or_default()), (String::from("reason"), (reason.clone()).unwrap_or_default())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn safety(mut request: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let required: String = String::from("audit_ref\", \"stop_condition\", \"rollback_ref\", \"max_resources");
    Ok(std::collections::BTreeMap::from([(String::from("idempotency_key"), String::new()), (String::from("audit_ref"), String::new()), (String::from("stop_condition"), String::new()), (String::from("rollback_ref"), String::new()), (String::from("max_resources"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validated_body(mut body: std::collections::BTreeMap<String, String>, mut expected_operation: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if ((body.clone()).get("operation_id").cloned()) != Some(expected_operation.clone()) {
        return Err("invalid_response gateway response operation did not match");
    }
    Ok(body.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn result(mut body: std::collections::BTreeMap<String, String>, mut expected_operation: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let validated: std::collections::BTreeMap<String, String> = validated_body(body.clone(), expected_operation.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let result: Option<String> = (validated.clone()).get("result").cloned();
    if (((validated.clone()).get("status").cloned()) != Some(String::from("succeeded"))) || (!(true)) {
        return Err("invalid_response gateway plan did not succeed");
    }
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn success_receipt(mut request: String) -> String {
    if request.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["AzureGatewayDirectApiConfig", "AzureGatewayDirectApiExecutor"];
