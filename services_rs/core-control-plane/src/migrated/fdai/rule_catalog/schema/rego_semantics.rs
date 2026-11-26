pub const MAX_POLICY_BYTES: i64 = 1000000;
pub const MAX_AST_BYTES: i64 = 8000000;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RegoSemantics {
    pub package: String,
    pub decision_path: String,
    pub rule_id: String,
    pub title: String,
    pub description: String,
    pub severity: String,
    pub category: String,
    pub property_paths: Vec<String>,
    pub content_digest: String,
    pub normalized_semantic_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RegoSemanticsError {
    pub message: String,
}

impl RegoSemanticsError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for RegoSemanticsError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for RegoSemanticsError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_rego_semantics(mut path: String, mut opa_binary: String, mut timeout_seconds: f64) -> Result<RegoSemantics, &'static str> {
    let mut source_annotation: Option<std::collections::BTreeMap<String, String>> = None;
    let package: String = package(String::new()).unwrap_or_else(|_| String::new());
    let rule_id: String = required_text(std::collections::BTreeMap::new(), String::from("rule_id")).unwrap_or_else(|_| String::new());
    let title: String = required_text(std::collections::BTreeMap::new(), String::from("title")).unwrap_or_else(|_| String::new());
    let description: String = required_text(std::collections::BTreeMap::new(), String::from("description")).unwrap_or_else(|_| String::new());
    let severity: String = required_text(std::collections::BTreeMap::new(), String::from("severity")).unwrap_or_else(|_| String::new());
    let category: String = required_text(std::collections::BTreeMap::new(), String::from("category")).unwrap_or_else(|_| String::new());
    let properties: Vec<String> = ((property_paths(String::new())).into_iter().collect::<std::collections::BTreeSet<String>>()).into_iter().collect::<Vec<String>>();
    if (properties.clone()).is_empty() {
        return Err("Rego policy MUST read at least one input.resource.props path");
    }
    let decision_path: String = format!("data.{}.deny", package.clone());
    if !((rule_names(std::collections::BTreeMap::new())).contains("deny")) {
        return Err("Rego policy MUST declare the deny decision entrypoint");
    }
    Ok(RegoSemantics { package: package.clone(), decision_path: decision_path.clone(), rule_id: rule_id.clone(), title: title.clone(), description: description.clone(), severity: severity.clone(), category: category.clone(), property_paths: properties.clone(), normalized_semantic_digest: normalized_semantic_digest(std::collections::BTreeMap::new()), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn property_ref(mut resource_type: String, mut path: String) -> Result<String, &'static str> {
    if ((resource_type.clone()).is_empty()) || ((path.clone()).is_empty()) {
        return Err("property resource_type and path MUST be non-empty");
    }
    Ok(format!("property.{}.{}", resource_type.clone(), path.clone()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn property_path(mut resource_type: String, mut reference: String) -> Result<String, &'static str> {
    let prefix: String = format!("property.{}.", resource_type.clone());
    if (!((reference.clone()).starts_with(prefix.as_str()))) || ((((reference.clone()).len() as i64)) == (((prefix.clone()).len() as i64))) {
        return Err("invalid Property reference for resource_typer: referencer");
    }
    Ok((reference.clone()).strip_prefix(prefix.as_str()).unwrap_or("").to_string())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn package(mut raw: String) -> Result<String, &'static str> {
    if !(false) {
        return Err("Rego package MUST be present");
    }
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn package_annotation(mut raw: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if (!(false)) || (true) {
        return Err("Rego package metadata MUST be present");
    }
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn source_package_annotation(mut source: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut metadata_lines: Vec<String> = Vec::<String>::new();
    if (metadata_lines.clone()).is_empty() {
        return Err("Rego package metadata MUST be present");
    }
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn parse_module_ast(mut source: String, mut filename: String, mut opa_binary: String, mut timeout_seconds: f64) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn property_paths(mut value: String) -> Vec<String> {
    if value.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn rule_names(mut ast: std::collections::BTreeMap<String, String>) -> std::collections::BTreeSet<String> {
    let rules: Option<String> = (ast.clone()).get("rules").cloned();
    if (!(true)) || (true) {
        return std::collections::BTreeSet::<String>::new();
    }
    let mut names: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    std::collections::BTreeSet::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn normalized_semantic_digest(mut ast: std::collections::BTreeMap<String, String>) -> String {
    let normalized: String = without_nonsemantic_ast_fields(String::new());
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn without_nonsemantic_ast_fields(mut value: String) -> String {
    value.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn term_text(mut raw: String) -> Result<String, &'static str> {
    if raw.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn required_text(mut raw: std::collections::BTreeMap<String, String>, mut key: String) -> Result<String, &'static str> {
    let value: Option<String> = (raw.clone()).get(key.as_str()).cloned();
    Ok(((value.clone()).unwrap_or_default()).trim().to_string())
}

pub const PUBLIC_EXPORTS: &[&str] = &["RegoSemantics", "RegoSemanticsError", "load_rego_semantics", "property_path", "property_ref"];
