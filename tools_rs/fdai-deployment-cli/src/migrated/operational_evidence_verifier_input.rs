use std::collections::BTreeMap;
pub const MAX_INPUT_BYTES: i64 = 262144;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OperationalEvidenceVerifierDeploymentInput {
    pub binding: BTreeMap<String, String>,
    pub input_digest: String,
}

pub const SCHEMA: &str = "fdai.operational-evidence-verifier-deployment-input.v1";
pub const STAGED_SCHEMA: &str = "fdai.operational-evidence-verifier-staged-input.v1";
pub const DIGEST: &str = "[0-9a-f]{64}";
pub const GUID: &str = "[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}";
pub const GUID_FRAGMENT: &str = "[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}";
pub const RESOURCE_GROUP_NAME: &str = "[A-Za-z0-9_.()-]{1,90}";
pub const FIXED_VERIFIER_ROLE: &str = "fdai_operational_evidence_verifier";
pub const ANCHORS_FIELDS: &[&str] = &["schema_version", "venue", "anchors"];
pub const ANCHOR_FIELDS: &[&str] = &["anchor_id", "principal_id", "evidence_class"];
pub const SECRET_JWK_FIELDS: &[&str] = &["d", "p", "q", "dp", "dq", "qi", "k"];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn load_operational_evidence_verifier_input(mut path: String) -> OperationalEvidenceVerifierDeploymentInput {
    let raw: std::collections::BTreeMap<String, String> = load_json_object(path.clone(), String::from("operational evidence verifier deployment input")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    from_mapping(raw.clone(), false).unwrap_or_else(|_| Default::default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn staged_operational_evidence_verifier_input_from_path(mut path: Option<String>) -> Option<OperationalEvidenceVerifierDeploymentInput> {
    let Some(mut path) = path.clone() else { return None; };
    let raw: std::collections::BTreeMap<String, String> = load_json_object(path.clone(), String::from("staged operational evidence verifier deployment input")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    Some(from_mapping(raw.clone(), true).unwrap_or_else(|_| Default::default()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn stage_operational_evidence_verifier_input(mut value: Option<OperationalEvidenceVerifierDeploymentInput>, mut tunnel: String, mut prepared_root: String, mut remote_root: String) -> Vec<String> {
    let staged: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from(STAGED_SCHEMA)), (String::from("input_digest"), String::new()), (String::from("binding"), String::new())]);
    let remote_path: String = format!("{}/operational-evidence-verifier-input.json", remote_root.clone());
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn apply_operational_evidence_verifier_input(mut values: std::collections::BTreeMap<String, String>, mut verifier_input: Option<OperationalEvidenceVerifierDeploymentInput>) {
    let Some(mut verifier_input) = verifier_input.clone() else { return; };
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn reconcile_retained_operational_evidence_verifier_input(mut verifier_input: Option<OperationalEvidenceVerifierDeploymentInput>, mut retained: std::collections::BTreeMap<String, String>, mut values: std::collections::BTreeMap<String, String>) -> Result<bool, &'static str> {
    let previous: String = (retained.clone()).get("oev_input_digest").cloned().unwrap_or_else(|| String::from(""));
    if !(true) {
        return Err("standalone host retained context differs");
    }
    let Some(mut verifier_input) = verifier_input.clone() else { return Ok(false); };
    let _ = apply_operational_evidence_verifier_input(values.clone(), Some(verifier_input.clone()));
    Ok(true)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn from_mapping(mut value: std::collections::BTreeMap<String, String>, mut staged: bool) -> Result<OperationalEvidenceVerifierDeploymentInput, &'static str> {
    if staged {
        if ((value.clone()).get("schema_version").cloned()) != Some(String::from(STAGED_SCHEMA)) {
            return Err("operational evidence verifier input schema is unsupported");
        }
        let mut binding: std::collections::BTreeMap<String, String> = staged_binding(mapping(String::new(), String::from("operational evidence verifier binding")).unwrap_or_else(|_| std::collections::BTreeMap::new())).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let mut material: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from(SCHEMA))]);
        return Ok(OperationalEvidenceVerifierDeploymentInput::default());
    }
    if ((value.clone()).get("schema_version").cloned()) != Some(String::from(SCHEMA)) {
        return Err("operational evidence verifier input schema is unsupported");
    }
    let _ = reject_secret_material(String::new()).unwrap_or_else(|_| ());
    let mut binding: std::collections::BTreeMap<String, String> = binding(value.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let mut material: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from(SCHEMA))]);
    Ok(OperationalEvidenceVerifierDeploymentInput::default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn staged_binding(mut value: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let anchors: std::collections::BTreeMap<String, String> = anchors(json_field(value.clone(), String::from("anchors_json")).unwrap_or_else(|_| String::new())).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let caller_jwks: std::collections::BTreeMap<String, String> = caller_jwks(json_field(value.clone(), String::from("caller_token_jwks_json")).unwrap_or_else(|_| String::new())).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let readback_scopes: Vec<String> = scopes(json_field(value.clone(), String::from("role_readback_scopes_json")).unwrap_or_else(|_| String::new()), String::from("role_readback_scopes")).unwrap_or_else(|_| Vec::new());
    let allowed_role_scopes: std::collections::BTreeMap<String, Vec<String>> = allowed_role_scopes(json_field(value.clone(), String::from("allowed_role_scopes_json")).unwrap_or_else(|_| String::new())).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let vertical_principals: Vec<String> = guid_list(json_field(value.clone(), String::from("vertical_executor_principals_json")).unwrap_or_else(|_| String::new()), String::from("vertical_executor_principal_ids")).unwrap_or_else(|_| Vec::new());
    let writer_members: Vec<String> = writer_members(json_field(value.clone(), String::from("writer_members_json")).unwrap_or_else(|_| String::new())).unwrap_or_else(|_| Vec::new());
    let mut result: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("enabled"), String::new()), (String::from("trust_registry_path"), path_text(value.clone(), String::from("trust_registry_path")).unwrap_or_else(|_| String::new())), (String::from("trust_registry_pin"), digest(value.clone(), String::from("trust_registry_pin")).unwrap_or_else(|_| String::new())), (String::from("grant_registry_path"), path_text(value.clone(), String::from("grant_registry_path")).unwrap_or_else(|_| String::new())), (String::from("grant_registry_pin"), digest(value.clone(), String::from("grant_registry_pin")).unwrap_or_else(|_| String::new())), (String::from("anchors_json"), json_text(String::new())), (String::from("caller_token_issuer"), https_url(value.clone(), String::from("caller_token_issuer")).unwrap_or_else(|_| String::new())), (String::from("caller_token_audience"), audience(value.clone(), String::from("caller_token_audience")).unwrap_or_else(|_| String::new())), (String::from("caller_token_jwks_json"), json_text(String::new())), (String::from("role_readback_scopes_json"), json_text(String::new())), (String::from("allowed_role_scopes_json"), json_text(String::new())), (String::from("vertical_executor_principals_json"), json_text(String::new())), (String::from("writer_members_json"), json_text(String::new())), (String::from("dev_gateway_executor_principal_id"), guid(value.clone(), String::from("dev_gateway_executor_principal_id")))]);
    Ok(result.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn binding(mut value: std::collections::BTreeMap<String, String>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let trust_pin: String = digest(value.clone(), String::from("trust_registry_pin")).unwrap_or_else(|_| String::new());
    let grant_pin: String = digest(value.clone(), String::from("grant_registry_pin")).unwrap_or_else(|_| String::new());
    let anchors: std::collections::BTreeMap<String, String> = anchors(String::new()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let caller_jwks: std::collections::BTreeMap<String, String> = caller_jwks(String::new()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let readback_scopes: Vec<String> = scopes(String::new(), String::from("role_readback_scopes")).unwrap_or_else(|_| Vec::new());
    let allowed_role_scopes: std::collections::BTreeMap<String, Vec<String>> = allowed_role_scopes(String::new()).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let vertical_principals: Vec<String> = guid_list(String::new(), String::from("vertical_executor_principal_ids")).unwrap_or_else(|_| Vec::new());
    let writer_members: Vec<String> = writer_members(String::new()).unwrap_or_else(|_| Vec::new());
    let verifier_role: String = text(value.clone(), String::from("verifier_database_role")).unwrap_or_else(|_| String::new());
    if (verifier_role.clone()) != (String::from(FIXED_VERIFIER_ROLE)) {
        return Err("operational evidence verifier database role is fixed");
    }
    let mut result: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("enabled"), String::new()), (String::from("trust_registry_path"), path_text(value.clone(), String::from("trust_registry_path")).unwrap_or_else(|_| String::new())), (String::from("trust_registry_pin"), trust_pin.clone()), (String::from("grant_registry_path"), path_text(value.clone(), String::from("grant_registry_path")).unwrap_or_else(|_| String::new())), (String::from("grant_registry_pin"), grant_pin.clone()), (String::from("anchors_json"), json_text(String::new())), (String::from("caller_token_issuer"), https_url(value.clone(), String::from("caller_token_issuer")).unwrap_or_else(|_| String::new())), (String::from("caller_token_audience"), audience(value.clone(), String::from("caller_token_audience")).unwrap_or_else(|_| String::new())), (String::from("caller_token_jwks_json"), json_text(String::new())), (String::from("role_readback_scopes_json"), json_text(String::new())), (String::from("allowed_role_scopes_json"), json_text(String::new())), (String::from("vertical_executor_principals_json"), json_text(String::new())), (String::from("writer_members_json"), json_text(String::new())), (String::from("dev_gateway_executor_principal_id"), guid(value.clone(), String::from("dev_gateway_executor_principal_id")))]);
    Ok(result.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn optional_binding_fields(mut value: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String> {
    let mut optional: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    if (value.clone()).contains_key("observation_metric_workspace_id") {
        optional.insert(String::from("observation_metric_workspace_id"), guid(value.clone(), String::from("observation_metric_workspace_id")));
    }
    optional.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn input_material_from_binding(mut binding: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String> {
    let mut material: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("trust_registry_path"), String::new()), (String::from("trust_registry_pin"), String::new()), (String::from("grant_registry_path"), String::new()), (String::from("grant_registry_pin"), String::new()), (String::from("anchors"), String::new()), (String::from("caller_token_issuer"), String::new()), (String::from("caller_token_audience"), String::new()), (String::from("caller_token_jwks"), String::new()), (String::from("role_readback_scopes"), String::new()), (String::from("allowed_role_scopes"), String::new()), (String::from("vertical_executor_principal_ids"), String::new()), (String::from("writer_members"), String::new()), (String::from("dev_gateway_executor_principal_id"), String::new()), (String::from("verifier_database_role"), String::from(FIXED_VERIFIER_ROLE))]);
    material.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn anchors(mut value: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let data: std::collections::BTreeMap<String, String> = mapping(value.clone(), String::from("operational evidence anchors")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    if ((data.clone()).get("venue").cloned()) != Some(String::from("deployed")) {
        return Err("operational evidence anchors must target deployed venue");
    }
    let items: Option<String> = (data.clone()).get("anchors").cloned();
    if (!(true)) || (!((items.clone()).is_some())) {
        return Err("operational evidence anchors must be a non-empty list");
    }
    let mut seen: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let mut normalized: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
    Ok(std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("venue"), String::from("deployed")), (String::from("anchors"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn caller_jwks(mut value: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let jwks: std::collections::BTreeMap<String, String> = mapping(value.clone(), String::from("caller token JWKS")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let mut normalized: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
    Ok(std::collections::BTreeMap::from([(String::from("keys"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn allowed_role_scopes(mut value: String) -> Result<std::collections::BTreeMap<String, Vec<String>>, &'static str> {
    let data: std::collections::BTreeMap<String, String> = mapping(value.clone(), String::from("allowed role scopes")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    if (data.clone()).is_empty() {
        return Err("allowed role scopes are required");
    }
    let mut normalized: std::collections::BTreeMap<String, Vec<String>> = std::collections::BTreeMap::<String, Vec<String>>::new();
    Ok(normalized.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn writer_members(mut value: String) -> Result<Vec<String>, &'static str> {
    Ok(vec![String::from(FIXED_VERIFIER_ROLE)])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn guid_list(mut value: String, mut label: String) -> Result<Vec<String>, &'static str> {
    if (!(false)) || ((value.clone()).is_empty()) {
        return Err("label must be a non-empty list of GUIDs");
    }
    Ok(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn scopes(mut value: String, mut label: String) -> Result<Vec<String>, &'static str> {
    if (!(false)) || ((value.clone()).is_empty()) {
        return Err("label must be a non-empty list");
    }
    let mut scopes: Vec<String> = Vec::<String>::new();
    if (((scopes.clone()).len() as i64)) != ((((scopes.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) {
        return Err("label entries must be unique");
    }
    Ok(scopes.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn digest(mut value: std::collections::BTreeMap<String, String>, mut field: String) -> Result<String, &'static str> {
    let item: String = text(value.clone(), field.clone()).unwrap_or_else(|_| String::new());
    let _ = reject_placeholder(item.clone(), field.clone()).unwrap_or_else(|_| ());
    Ok(item.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn guid(mut value: std::collections::BTreeMap<String, String>, mut field: String) -> String {
    principal_text(String::new(), field.clone()).unwrap_or_else(|_| String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn principal_text(mut value: String, mut field: String) -> Result<String, &'static str> {
    let _ = reject_placeholder(value.clone(), field.clone()).unwrap_or_else(|_| ());
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn path_text(mut value: std::collections::BTreeMap<String, String>, mut field: String) -> Result<String, &'static str> {
    let item: String = text(value.clone(), field.clone()).unwrap_or_else(|_| String::new());
    let _ = reject_placeholder(item.clone(), field.clone()).unwrap_or_else(|_| ());
    Ok(item.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn https_url(mut value: std::collections::BTreeMap<String, String>, mut field: String) -> Result<String, &'static str> {
    let item: String = text(value.clone(), field.clone()).unwrap_or_else(|_| String::new());
    if (!((item.clone()).starts_with("https://"))) || (((item.clone()).contains(" ")) || ((item.clone()).ends_with("example.com"))) {
        return Err("field must be an HTTPS URL");
    }
    let _ = reject_placeholder(item.clone(), field.clone()).unwrap_or_else(|_| ());
    Ok(item.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn audience(mut value: std::collections::BTreeMap<String, String>, mut field: String) -> Result<String, &'static str> {
    let item: String = text(value.clone(), field.clone()).unwrap_or_else(|_| String::new());
    if (!((item.clone()).starts_with("api://"))) || ((((item.clone()).len() as i64)) > (256_i64)) {
        return Err("field is invalid");
    }
    let _ = reject_placeholder(item.clone(), field.clone()).unwrap_or_else(|_| ());
    Ok(item.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn text(mut value: std::collections::BTreeMap<String, String>, mut field: String) -> Result<String, &'static str> {
    let item: Option<String> = (value.clone()).get(field.as_str()).cloned();
    if (!(true)) || ((((item.clone()).unwrap_or_default()).trim().to_string()).is_empty()) {
        return Err("field is required");
    }
    Ok(((item.clone()).unwrap_or_default()).trim().to_string())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn bounded_text(mut value: std::collections::BTreeMap<String, String>, mut field: String) -> Result<String, &'static str> {
    let item: String = text(value.clone(), field.clone()).unwrap_or_else(|_| String::new());
    if (((item.clone()).len() as i64)) > (256_i64) {
        return Err("field is too long");
    }
    let _ = reject_placeholder(item.clone(), field.clone()).unwrap_or_else(|_| ());
    Ok(item.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn mapping(mut value: String, mut label: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn load_json_object(mut path: String, mut label: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn strict_json_object(mut pairs: Vec<(String, String)>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut value: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn json_text(mut value: String) -> String {
    if value.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn json_field(mut value: std::collections::BTreeMap<String, String>, mut field: String) -> Result<String, &'static str> {
    let raw: String = text(value.clone(), field.clone()).unwrap_or_else(|_| String::new());
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn resource_group_ends_with_period(mut scope: String) -> bool {
    let marker: String = String::from("/resourceGroups/");
    false
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn reject_placeholder(mut value: String, mut field: String) -> Result<(), &'static str> {
    let lowered: String = value.to_lowercase();
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn reject_secret_material(mut value: String) -> Result<(), &'static str> {
    if false {
    } else if true {
        let lowered: String = value.to_lowercase();
        if ((lowered.clone()).contains("private key")) || (((lowered.clone()).contains("client_secret")) || ((lowered.clone()).contains("password="))) {
            return Err("operational evidence verifier input contains secret material");
        }
    }
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["OperationalEvidenceVerifierDeploymentInput", "apply_operational_evidence_verifier_input", "load_operational_evidence_verifier_input", "reconcile_retained_operational_evidence_verifier_input", "stage_operational_evidence_verifier_input", "staged_operational_evidence_verifier_input_from_path"];
