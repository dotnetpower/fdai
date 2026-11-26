pub const MAX_RESPONSE_BYTES: i64 = 262144;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureGatewayDirectApiConfig {
    pub base_url: String,
    pub audience: String,
    pub timeout_seconds: f64,
    pub poll_interval_seconds: f64,
    pub max_poll_attempts: i64,
}

pub const EXECUTOR_IDENTITY_REFS: &[&str] = &["identity/change", "identity/resilience", "identity/finops"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureGatewayDirectApiExecutor {
    pub initialized: bool,
}

impl AzureGatewayDirectApiExecutor {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn execute(&self, mut request: String) -> Result<String, &'static str> {
        let plan: std::collections::BTreeMap<String, String> = self.invoke(String::from("azure.operation.plan"), std::collections::BTreeMap::from([(String::from("operation_id"), String::new()), (String::from("arguments"), String::new()), (String::from("safety"), String::new())]), String::new(), None).await.unwrap_or_else(|_| std::collections::BTreeMap::new());
        let plan_result: std::collections::BTreeMap<String, String> = result(plan.clone(), String::from("azure.operation.plan")).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let dry_run_receipt: Option<String> = (plan_result.clone()).get("dry_run_receipt").cloned();
        if (!(true)) || (!((dry_run_receipt.clone()).is_some())) {
            return Err("invalid_response gateway plan omitted dry_run_receipt");
        }
        let response: std::collections::BTreeMap<String, String> = self.invoke(String::new(), std::collections::BTreeMap::from([(String::from("safety"), String::new())]), String::new(), None).await.unwrap_or_else(|_| std::collections::BTreeMap::new());
        let body: std::collections::BTreeMap<String, String> = validated_body(response.clone(), String::new()).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let status: Option<String> = (body.clone()).get("status").cloned();
        if (status.clone()) == Some(String::from("succeeded")) {
            return Ok(success_receipt(request.clone(), false));
        }
        Ok(self.poll_until_terminal(request.clone(), String::new(), String::new(), false).await.unwrap_or_else(|_| String::new()))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn operation_status(&self, mut request: String) -> Option<String> {
        self.existing_operation_receipt(request.clone(), String::new(), String::new()).await.unwrap_or_else(|_| None)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn request_context(&self, mut request: String) -> Result<(String, String, std::collections::BTreeMap<String, String>, std::collections::BTreeMap<String, String>), &'static str> {
        let safety: std::collections::BTreeMap<String, String> = safety(request.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
        Ok((String::new(), String::new(), std::collections::BTreeMap::new(), std::collections::BTreeMap::new()))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn existing_operation_receipt(&self, mut request: String, mut identity: String, mut operation_id: String) -> Result<Option<String>, &'static str> {
        let response: std::collections::BTreeMap<String, String> = self.invoke(String::from("azure.operation.status"), std::collections::BTreeMap::from([(String::from("idempotency_key"), String::new()), (String::from("operation_id"), operation_id.clone())]), identity.clone(), Some(String::from("idempotency_not_found"))).await.unwrap_or_else(|_| std::collections::BTreeMap::new());
        let body: std::collections::BTreeMap<String, String> = validated_body(response.clone(), String::from("azure.operation.status")).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let status: Option<String> = (body.clone()).get("status").cloned();
        if (status.clone()) == Some(String::from("not_found")) {
            return Ok(None);
        }
        if (status.clone()) == Some(String::from("succeeded")) {
            return Ok(Some(success_receipt(request.clone(), true)));
        }
        if (status.clone()) == Some(String::from("running")) {
            return Ok(Some(self.poll_until_terminal(request.clone(), identity.clone(), operation_id.clone(), true).await.unwrap_or_else(|_| String::new())));
        }
        Err("invalid_response gateway status was not recognized")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn poll_until_terminal(&self, mut request: String, mut identity: String, mut operation_id: String, mut already_applied: bool) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn invoke(&self, mut operation_id: String, mut payload: std::collections::BTreeMap<String, String>, mut identity: String, mut not_found_code: Option<String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        Ok(std::collections::BTreeMap::new())
    }
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
pub fn success_receipt(mut request: String, mut already_applied: bool) -> String {
    if request.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["AzureGatewayDirectApiConfig", "AzureGatewayDirectApiExecutor"];
