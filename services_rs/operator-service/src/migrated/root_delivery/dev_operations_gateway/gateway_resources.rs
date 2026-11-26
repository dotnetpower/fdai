#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct GatewayResourceOperations {
    pub initialized: bool,
}

impl GatewayResourceOperations {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn mutation_resource_key(&self, mut operation_id: String, mut payload: std::collections::BTreeMap<String, String>) -> String {
        if (operation_id.clone()) == (String::from("azure.resource.tags.merge")) {
        } else if (operation_id.clone()) == (String::from("azure.subscription.tags.merge")) {
            let target_path: String = self.subscription_tag_extension_path(payload.clone()).unwrap_or_else(|_| String::new());
            let group: String = String::from("subscription");
        }
        if (operation_id.clone()) == (String::from("azure.compute.vmss.scale")) {
        } else if (operation_id.clone()).starts_with("azure.compute.vm.") {
            let mut target: String = format!("vm/{}", identifier(payload.clone(), String::from("vm_name")).unwrap_or_else(|_| String::new()));
        } else if !(matches!(operation_id.as_str(), "azure.resource.tags.merge" | "azure.subscription.tags.merge")) {
            let mut target: String = format!("nsg/{}/rule/{}", identifier(payload.clone(), String::from("nsg_name")).unwrap_or_else(|_| String::new()), identifier(payload.clone(), String::from("rule_name")).unwrap_or_else(|_| String::new()));
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_mutation_payload(&self, mut operation_id: String, mut payload: std::collections::BTreeMap<String, String>) {
        let _ = self.mutation_resource_key(operation_id.clone(), payload.clone());
        if (operation_id.clone()) == (String::from("azure.network.nsg.rule.upsert")) {
            let _ = nsg_rule_body(payload.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
        } else if matches!(operation_id.as_str(), "azure.resource.tags.merge" | "azure.subscription.tags.merge") {
            let _ = tag_argument(payload.clone(), String::from("tag_name"), String::new()).unwrap_or_else(|_| String::new());
            let _ = tag_argument(payload.clone(), String::from("tag_value"), String::new()).unwrap_or_else(|_| String::new());
        } else if (operation_id.clone()) == (String::from("azure.compute.vmss.scale")) {
            let _ = integer(payload.clone(), String::from("replica_count"), 1_i64, 1000_i64).unwrap_or_else(|_| 0_i64);
            let _ = scale_reason(payload.clone()).unwrap_or_else(|_| String::new());
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn preflight_mutation(&self, mut operation_id: String, mut payload: std::collections::BTreeMap<String, String>) -> Result<(), &'static str> {
        if (operation_id.clone()) == (String::from("azure.resource.tags.merge")) {
            let _ = self.read_tag_document(self.tag_extension_path(payload.clone())).await.unwrap_or_else(|_| std::collections::BTreeMap::new());
            return Ok(());
        }
        if (operation_id.clone()) == (String::from("azure.subscription.tags.merge")) {
            let _ = self.read_tag_document(self.subscription_tag_extension_path(payload.clone()).unwrap_or_else(|_| String::new())).await.unwrap_or_else(|_| std::collections::BTreeMap::new());
            return Ok(());
        }
        if (operation_id.clone()) == (String::from("azure.compute.vmss.scale")) {
        } else if (operation_id.clone()).starts_with("azure.compute.vm.") {
            let vm_name: String = identifier(payload.clone(), String::from("vm_name")).unwrap_or_else(|_| String::new());
        } else {
            let nsg_name: String = identifier(payload.clone(), String::from("nsg_name")).unwrap_or_else(|_| String::new());
        }
        if (operation_id.clone()) == (String::from("azure.compute.vmss.scale")) {
            let _ = self.validate_vmss_scale_observation(payload.clone(), std::collections::BTreeMap::new(), false).unwrap_or_else(|_| String::new());
        }
        Ok(())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn scope(&self, mut payload: std::collections::BTreeMap<String, String>) -> Result<(String, String), &'static str> {
        let resource_group: String = identifier(payload.clone(), String::from("resource_group")).unwrap_or_else(|_| String::new());
        Ok((String::new(), String::new()))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read_nsg(&self, mut payload: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
        let name: String = identifier(payload.clone(), String::from("nsg_name")).unwrap_or_else(|_| String::new());
        let mut projected_rules: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read_peerings(&self, mut payload: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
        let name: String = identifier(payload.clone(), String::from("vnet_name")).unwrap_or_else(|_| String::new());
        let mut peerings: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn probe_private_endpoint(&self, mut payload: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
        let alias: String = identifier(payload.clone(), String::from("probe")).unwrap_or_else(|_| String::new());
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn upsert_nsg_rule(&self, mut payload: std::collections::BTreeMap<String, String>) -> String {
        let nsg_name: String = identifier(payload.clone(), String::from("nsg_name")).unwrap_or_else(|_| String::new());
        let rule_name: String = identifier(payload.clone(), String::from("rule_name")).unwrap_or_else(|_| String::new());
        let body: std::collections::BTreeMap<String, String> = nsg_rule_body(payload.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read_resource_tag(&self, mut payload: std::collections::BTreeMap<String, String>) -> String {
        self.read_tag(payload.clone(), self.tag_extension_path(payload.clone())).await
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read_subscription_tag(&self, mut payload: std::collections::BTreeMap<String, String>) -> String {
        self.read_tag(payload.clone(), self.subscription_tag_extension_path(payload.clone()).unwrap_or_else(|_| String::new())).await
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read_tag(&self, mut payload: std::collections::BTreeMap<String, String>, mut target_path: String) -> String {
        let tag_name: String = tag_argument(payload.clone(), String::from("tag_name"), String::new()).unwrap_or_else(|_| String::new());
        let expected: String = tag_argument(payload.clone(), String::from("tag_value"), String::new()).unwrap_or_else(|_| String::new());
        let tags: std::collections::BTreeMap<String, String> = self.read_tag_document(target_path.clone()).await.unwrap_or_else(|_| std::collections::BTreeMap::new());
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn merge_resource_tag(&self, mut payload: std::collections::BTreeMap<String, String>) -> String {
        self.merge_tag(payload.clone(), self.tag_extension_path(payload.clone())).await.unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn merge_subscription_tag(&self, mut payload: std::collections::BTreeMap<String, String>) -> String {
        self.merge_tag(payload.clone(), self.subscription_tag_extension_path(payload.clone()).unwrap_or_else(|_| String::new())).await.unwrap_or_else(|_| String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn merge_tag(&self, mut payload: std::collections::BTreeMap<String, String>, mut target_path: String) -> Result<String, &'static str> {
        let tag_name: String = tag_argument(payload.clone(), String::from("tag_name"), String::new()).unwrap_or_else(|_| String::new());
        let tag_value: String = tag_argument(payload.clone(), String::from("tag_value"), String::new()).unwrap_or_else(|_| String::new());
        let prior: std::collections::BTreeMap<String, String> = self.read_tag_document(target_path.clone()).await.unwrap_or_else(|_| std::collections::BTreeMap::new());
        let observed: std::collections::BTreeMap<String, String> = self.read_tag_document(target_path.clone()).await.unwrap_or_else(|_| std::collections::BTreeMap::new());
        Err("502 effect_verification_failed Azure tag readback mismatched and the pri")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn restore_tag_snapshot(&self, mut target_path: String, mut prior: std::collections::BTreeMap<String, String>) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn read_tag_document(&self, mut target_path: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
        Ok(std::collections::BTreeMap::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn tag_extension_path(&self, mut payload: std::collections::BTreeMap<String, String>) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn subscription_tag_extension_path(&self, mut payload: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
        let target_ref: String = bounded(payload.clone(), String::from("target_resource_ref"), 2048_i64).unwrap_or_else(|_| String::new());
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn tag_target(&self, mut payload: std::collections::BTreeMap<String, String>) -> Result<(String, String, String), &'static str> {
        let target_ref: String = bounded(payload.clone(), String::from("target_resource_ref"), 2048_i64).unwrap_or_else(|_| String::new());
        Ok((String::new(), String::new(), String::new()))
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn delete_nsg_rule(&self, mut payload: std::collections::BTreeMap<String, String>) -> String {
        let nsg_name: String = identifier(payload.clone(), String::from("nsg_name")).unwrap_or_else(|_| String::new());
        let rule_name: String = identifier(payload.clone(), String::from("rule_name")).unwrap_or_else(|_| String::new());
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn start_vm(&self, mut payload: std::collections::BTreeMap<String, String>) -> String {
        self.vm_action(payload.clone(), String::from("start")).await
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn deallocate_vm(&self, mut payload: std::collections::BTreeMap<String, String>) -> String {
        self.vm_action(payload.clone(), String::from("deallocate")).await
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn vm_action(&self, mut payload: std::collections::BTreeMap<String, String>, mut action: String) -> String {
        let vm_name: String = identifier(payload.clone(), String::from("vm_name")).unwrap_or_else(|_| String::new());
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn scale_vmss(&self, mut payload: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
        let replica_count: i64 = integer(payload.clone(), String::from("replica_count"), 1_i64, 1000_i64).unwrap_or_else(|_| 0_i64);
        let etag: String = self.validate_vmss_scale_observation(payload.clone(), std::collections::BTreeMap::new(), true).unwrap_or_else(|_| String::new());
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_vmss_scale_observation(&self, mut payload: std::collections::BTreeMap<String, String>, mut observed: std::collections::BTreeMap<String, String>, mut require_etag: bool) -> Result<String, &'static str> {
        let sku: Option<String> = (observed.clone()).get("sku").cloned();
        let properties: Option<String> = (observed.clone()).get("properties").cloned();
        let requested_capacity: i64 = integer(payload.clone(), String::from("replica_count"), 1_i64, 1000_i64).unwrap_or_else(|_| 0_i64);
        if !(require_etag) {
            return Ok(String::from(""));
        }
        let etag: Option<String> = (observed.clone()).get("etag").cloned();
        Ok((etag.clone()).unwrap_or_default())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn vmss_target(&self, mut payload: std::collections::BTreeMap<String, String>) -> Result<(String, String, String), &'static str> {
        let vmss_name: String = identifier(payload.clone(), String::from("vmss_name")).unwrap_or_else(|_| String::new());
        let target_ref: String = bounded(payload.clone(), String::from("target_resource_ref"), 1024_i64).unwrap_or_else(|_| String::new());
        Ok((String::new(), String::new(), String::new()))
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn identifier(mut payload: std::collections::BTreeMap<String, String>, mut name: String) -> Result<String, &'static str> {
    let value: Option<String> = (payload.clone()).get(name.as_str()).cloned();
    Ok((value.clone()).unwrap_or_default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn tag_argument(mut payload: std::collections::BTreeMap<String, String>, mut name: String, mut pattern: String) -> Result<String, &'static str> {
    let value: Option<String> = (payload.clone()).get(name.as_str()).cloned();
    Ok((value.clone()).unwrap_or_default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn bounded(mut payload: std::collections::BTreeMap<String, String>, mut name: String, mut maximum: i64) -> Result<String, &'static str> {
    let value: Option<String> = (payload.clone()).get(name.as_str()).cloned();
    Ok((value.clone()).unwrap_or_default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn choice(mut payload: std::collections::BTreeMap<String, String>, mut name: String, mut choices: std::collections::BTreeSet<String>) -> Result<String, &'static str> {
    let value: String = bounded(payload.clone(), name.clone(), 0_i64).unwrap_or_else(|_| String::new());
    if !((choices.clone()).contains(value.as_str())) {
        return Err("400 argument_invalid fname is not allowed");
    }
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn integer(mut payload: std::collections::BTreeMap<String, String>, mut name: String, mut minimum: i64, mut maximum: i64) -> Result<i64, &'static str> {
    let value: Option<String> = (payload.clone()).get(name.as_str()).cloned();
    Ok(0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn scale_reason(mut payload: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    let reason: Option<String> = (payload.clone()).get("reason").cloned();
    Ok((reason.clone()).unwrap_or_default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn nsg_rule_body(mut payload: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let rule: Option<String> = (payload.clone()).get("rule").cloned();
    if !(true) {
        return Err("400 rule_invalid rule MUST be an object");
    }
    Ok(std::collections::BTreeMap::from([(String::from("properties"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn prefixes(mut payload: std::collections::BTreeMap<String, String>, mut singular: String, mut plural: String) -> String {
    let values: Option<String> = (payload.clone()).get(plural.as_str()).cloned();
    let value: Option<String> = (payload.clone()).get(singular.as_str()).cloned();
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn resource_name(mut value: String) -> String {
    if !(false) {
        return String::from("");
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn address_prefixes(mut value: String) -> String {
    if !(false) {
        return String::from("");
    }
    String::new()
}

