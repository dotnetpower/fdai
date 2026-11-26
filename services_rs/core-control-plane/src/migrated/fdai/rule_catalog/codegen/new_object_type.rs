#[derive(Clone, Debug, Default, PartialEq)]
pub struct PropertySpec {
    pub name: String,
    pub r#type: String,
    pub required: bool,
    pub description: Option<String>,
    pub access_scope: String,
    pub purpose_binding: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ObjectTypeSpec {
    pub name: String,
    pub key: String,
    pub properties: Vec<PropertySpec>,
    pub description: Option<String>,
    pub version: String,
    pub schema_version: String,
    pub header_comment: Vec<String>,
}

pub const PASCAL_CASE: &str = "^[A-Z][A-Za-z0-9]{0,63}\\Z";
pub const LOWER_SNAKE_KEBAB: &str = "^[a-z][a-z0-9_-]{0,63}\\Z";
pub const ALLOWED_SCOPES: &[&str] = &["reader", "contributor", "approver", "owner"];
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_property(mut prop: PropertySpec) -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn render_object_type_yaml(mut spec: ObjectTypeSpec) -> String {
    let mut doc: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), spec.schema_version.clone()), (String::from("name"), spec.name.clone()), (String::from("version"), spec.version.clone()), (String::from("key"), spec.key.clone())]);
    if (spec.description.clone()).is_some() {
        doc.insert(String::from("description"), (spec.description.clone()).unwrap_or_default());
    }
    let mut properties: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>> = std::collections::BTreeMap::<String, std::collections::BTreeMap<String, String>>::new();
    for prop in spec.properties.clone() {
        let mut entry: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("type"), prop.r#type.clone())]);
        if (prop.description.clone()).is_some() {
            entry.insert(String::from("description"), (prop.description.clone()).unwrap_or_default());
        }
        if (prop.access_scope.clone()) != (String::from("reader")) {
            entry.insert(String::from("access_scope"), prop.access_scope.clone());
        }
        properties.insert(prop.name.clone(), entry.clone());
    }
    let header: String = render_header(spec.clone());
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn render_header(mut spec: ObjectTypeSpec) -> String {
    if (spec.header_comment.clone()).is_empty() {
        return String::from("");
    }
    String::from("\n\".join(f\"# {line}\" for line in spec.header_comment) + \"\n")
}

pub const PUBLIC_EXPORTS: &[&str] = &["ObjectTypeSpec", "PropertySpec", "render_object_type_yaml"];
