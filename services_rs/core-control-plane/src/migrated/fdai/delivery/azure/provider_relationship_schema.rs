#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureArmIdReference {
    pub source_document: String,
    pub json_pointer: String,
    pub allowed_resource_types: Vec<String>,
    pub unresolved_allowed_resources: Vec<String>,
    pub operation_paths: Vec<String>,
    pub source_resource_types: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureResourceDefinitionEvidence {
    pub source_document: String,
    pub json_pointer: String,
    pub operation_paths: Vec<String>,
    pub source_resource_types: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureProviderRelationshipSchemaSnapshot {
    pub source_revision: String,
    pub provider_schema_digest: String,
    pub extension_document_count: i64,
    pub arm_id_references: Vec<AzureArmIdReference>,
    pub resource_definitions: Vec<AzureResourceDefinitionEvidence>,
    pub evidence_digest: String,
}

pub const REVISION_PATTERN: &str = "^[0-9a-f]{40,64}$";
pub const DIGEST_PATTERN: &str = "^sha256:[0-9a-f]{64}$";
pub const RESOURCE_TYPE_PATTERN: &str = "^[A-Za-z][A-Za-z0-9.]+/[A-Za-z0-9][A-Za-z0-9./-]*$";
pub const HTTP_METHODS: &[&str] = &["delete", "get", "head", "options", "patch", "post", "put"];
impl AzureArmIdReference {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn resolved(&self) -> bool {
        (!(self.allowed_resource_types.clone()).is_empty()) && ((self.unresolved_allowed_resources.clone()).is_empty())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("source_document"), self.source_document.clone()), (String::from("json_pointer"), self.json_pointer.clone()), (String::from("resolution"), String::from("exact\" if self.resolved else \"unresolved")), (String::from("allowed_resource_types"), String::new()), (String::from("unresolved_allowed_resources"), String::new()), (String::from("operation_paths"), String::new()), (String::from("source_resource_types"), String::new())])
    }
}

impl AzureResourceDefinitionEvidence {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("source_document"), self.source_document.clone()), (String::from("json_pointer"), self.json_pointer.clone()), (String::from("operation_paths"), String::new()), (String::from("source_resource_types"), String::new())])
    }
}

impl AzureProviderRelationshipSchemaSnapshot {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn build(mut source_revision: String, mut provider_schema_digest: String, mut extension_document_count: i64, mut arm_id_references: Vec<AzureArmIdReference>, mut resource_definitions: Vec<AzureResourceDefinitionEvidence>) -> Result<AzureProviderRelationshipSchemaSnapshot, &'static str> {
        let material: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("provider"), String::from("azure")), (String::from("source_kind"), String::from("azure-rest-api-specs")), (String::from("source_revision"), source_revision.clone()), (String::from("provider_schema_digest"), provider_schema_digest.clone()), (String::from("extension_document_count"), String::new()), (String::from("arm_id_references"), String::new()), (String::from("resource_definitions"), String::new())]);
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn exact_reference_count(&self) -> i64 {
        0_i64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn unresolved_reference_count(&self) -> i64 {
        0_i64
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_mapping(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("schema_version"), String::from("1.0.0")), (String::from("provider"), String::from("azure")), (String::from("source_kind"), String::from("azure-rest-api-specs")), (String::from("source_revision"), self.source_revision.clone()), (String::from("provider_schema_digest"), self.provider_schema_digest.clone()), (String::from("evidence_digest"), self.evidence_digest.clone()), (String::from("extension_document_count"), String::new()), (String::from("arm_id_reference_count"), String::new()), (String::from("exact_reference_count"), String::new()), (String::from("unresolved_reference_count"), String::new()), (String::from("resource_definition_count"), String::new()), (String::from("arm_id_references"), String::new()), (String::from("resource_definitions"), String::new()), (String::from("grants_authority"), String::new())])
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureRestApiRelationshipSchemaParser {
    pub initialized: bool,
}

impl AzureRestApiRelationshipSchemaParser {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn parse(&self, mut tree_root: String, mut source_revision: String, mut provider_schema_digest: String) -> Result<AzureProviderRelationshipSchemaSnapshot, &'static str> {
        let candidates: Vec<String> = extension_documents(String::new()).unwrap_or_else(|_| Vec::new());
        let mut references: Vec<AzureArmIdReference> = Vec::<AzureArmIdReference>::new();
        let mut definitions: Vec<AzureResourceDefinitionEvidence> = Vec::<AzureResourceDefinitionEvidence>::new();
        for document in candidates.clone() {
            let raw: std::collections::BTreeMap<String, String> = load_document(document.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
            let operations: std::collections::BTreeMap<String, Vec<String>> = operation_definition_index(raw.clone());
        }
        Err("runtime_binding_required")
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct LocalAzureRestApiRelationshipSchemaSource {
    pub initialized: bool,
}

impl LocalAzureRestApiRelationshipSchemaSource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn collect(&self) -> AzureProviderRelationshipSchemaSnapshot {
        if !self.initialized {
            return Default::default();
        }
        Default::default()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct GitAzureRestApiRelationshipSchemaSource {
    pub initialized: bool,
}

impl GitAzureRestApiRelationshipSchemaSource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn collect(&self) -> AzureProviderRelationshipSchemaSnapshot {
        if !self.initialized {
            return Default::default();
        }
        Default::default()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn collect_sync(&self) -> Result<AzureProviderRelationshipSchemaSnapshot, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn extension_documents(mut specification: String) -> Result<Vec<String>, &'static str> {
    let mut candidates: Vec<String> = Vec::<String>::new();
    Ok({ let mut _v = candidates.clone(); _v.sort(); _v })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn load_document(mut path: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn walk(mut value: String, mut pointer: String) -> Vec<(String, std::collections::BTreeMap<String, String>)> {
    if value.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn allowed_resource_types(mut node: std::collections::BTreeMap<String, String>, mut pointer: String) -> Result<(Vec<String>, Vec<String>), &'static str> {
    let details: Option<String> = (node.clone()).get("x-ms-arm-id-details").cloned();
    if !(true) {
        return Err("Azure REST ARM ID details are invalid at pointer");
    }
    let mut resource_types: Vec<String> = Vec::<String>::new();
    let mut unresolved_types: Vec<String> = Vec::<String>::new();
    let normalized: Vec<String> = ((resource_types.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).into_iter().collect::<Vec<String>>();
    let unresolved: Vec<String> = ((unresolved_types.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).into_iter().collect::<Vec<String>>();
    if ((((normalized.clone()).len() as i64)) != (((resource_types.clone()).len() as i64))) || ((((unresolved.clone()).len() as i64)) != (((unresolved_types.clone()).len() as i64))) {
        return Err("Azure REST allowed resource types repeat at pointer");
    }
    Ok((normalized.clone(), unresolved.clone()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn operation_definition_index(mut raw: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, Vec<String>> {
    let paths: Option<String> = (raw.clone()).get("paths").cloned();
    if !(true) {
        return std::collections::BTreeMap::<String, Vec<String>>::new();
    }
    let definitions: std::collections::BTreeMap<String, String> = definitions(raw.clone());
    let indexed: std::collections::BTreeMap<String, std::collections::BTreeSet<String>> = std::collections::BTreeMap::<String, std::collections::BTreeSet<String>>::new();
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn definitions(mut raw: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String> {
    let definitions: Option<String> = (raw.clone()).get("definitions").cloned();
    let components: Option<String> = (raw.clone()).get("components").cloned();
    std::collections::BTreeMap::<String, String>::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn reachable_definitions(mut operation: std::collections::BTreeMap<String, String>, mut definitions: std::collections::BTreeMap<String, String>) -> std::collections::BTreeSet<String> {
    let mut reached: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    reached.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn local_definition_refs(mut value: String) -> Vec<String> {
    if value.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn operation_paths(mut pointer: String, mut index: std::collections::BTreeMap<String, Vec<String>>) -> Vec<String> {
    for (definition, paths) in index.clone() {
        if ((pointer.clone()) == (definition.clone())) || ((pointer.clone()).starts_with((format!("{}/", definition.clone())).as_str())) {
            return paths.clone();
        }
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn resource_types_from_path(mut path: String) -> Vec<String> {
    let mut resource_types: Vec<String> = Vec::<String>::new();
    resource_types.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn escape_pointer(mut value: String) -> String {
    ((value.clone()).replace("~", "~0")).replace("/", "~1")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn unescape_pointer(mut value: String) -> String {
    ((value.clone()).replace("~1", "/")).replace("~0", "~")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn canonical_json(mut value: String) -> Vec<u8> {
    if value.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn canonical_json_text(mut value: String) -> Result<String, &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_git_source(mut repo_url: String, mut revision_ref: String, mut timeout_seconds: f64) -> Result<(), &'static str> {
    if (timeout_seconds) <= (0.0) {
        return Err("provider relationship Git timeout MUST be positive");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn resolve_git_revision(mut repo_url: String, mut revision_ref: String, mut timeout_seconds: f64) -> Result<String, &'static str> {
    if repo_url.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn fetch_git_tree(mut repo_url: String, mut revision: String, mut destination: String, mut timeout_seconds: f64) -> String {
    if repo_url.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["AzureArmIdReference", "AzureProviderRelationshipSchemaSnapshot", "AzureResourceDefinitionEvidence", "AzureRestApiRelationshipSchemaParser", "GitAzureRestApiRelationshipSchemaSource", "LocalAzureRestApiRelationshipSchemaSource"];
