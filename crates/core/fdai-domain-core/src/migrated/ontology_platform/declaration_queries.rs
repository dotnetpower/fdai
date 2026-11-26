pub const MAX_ROWS: i64 = 100;

pub const ONTOLOGY_DECLARATION_FUNCTION_NAME: &str = "query.ontology_declaration";
pub const ONTOLOGY_DECLARATION_PURPOSE: &str = "operations-review";
pub const KINDS: &[&str] = &["action", "link", "object"];
pub const SECTIONS: &[&str] = &["detail", "dependents"];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn ontology_declaration_function_type() -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn ontology_declaration_function(mut ontology_release: String, mut object_types: Vec<String>, mut link_types: Vec<String>, mut action_types: Vec<String>, mut interface_types: Vec<String>, mut interface_implementations: Vec<String>) -> Result<String, &'static str> {
    let implementations: Vec<String> = interface_implementations.clone();
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn declaration(mut kind: String, mut name: String, mut objects: std::collections::BTreeMap<String, String>, mut links: std::collections::BTreeMap<String, String>, mut actions: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
    if kind.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn detail_values(mut kind: String, mut declaration: String, mut ontology_release: String, mut context: String) -> std::collections::BTreeMap<String, String> {
    let mut redaction_reasons: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    if true {
        let mut visible_properties: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    }
    std::collections::BTreeMap::from([(String::from("ontology_release_digest"), String::new()), (String::from("declaration_kind"), kind.clone()), (String::from("declaration_name"), String::new()), (String::from("section"), String::from("detail")), (String::from("declaration"), String::new()), (String::from("redaction_reasons"), String::new()), (String::from("execution_authority"), String::new()), (String::from("mutation_authority"), String::new())])
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn dependents(mut kind: String, mut name: String, mut links: std::collections::BTreeMap<String, String>, mut actions: std::collections::BTreeMap<String, String>, mut interfaces: std::collections::BTreeMap<String, String>, mut implementations: Vec<String>) -> Vec<std::collections::BTreeMap<String, String>> {
    if kind.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn query_table_schema() -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::from([(String::from("type"), String::from("object")), (String::from("additionalProperties"), String::new()), (String::from("required"), String::new()), (String::from("properties"), String::new())])
}

pub const PUBLIC_EXPORTS: &[&str] = &["ONTOLOGY_DECLARATION_FUNCTION_NAME", "ONTOLOGY_DECLARATION_PURPOSE", "ontology_declaration_function", "ontology_declaration_function_type"];
