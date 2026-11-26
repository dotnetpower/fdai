#[derive(Clone, Debug, Default, PartialEq)]
pub struct CreateUploadRequest {
    pub source_name: String,
    pub collection_id: String,
    pub media_type_hint: String,
    pub expected_size: i64,
    pub expected_sha256: String,
    pub storage_mode: String,
    pub purposes: Vec<String>,
    pub access_descriptor_ref: String,
    pub reader_groups: Vec<String>,
    pub retention_policy_version: String,
    pub document_id: Option<String>,
    pub supersedes_version_id: Option<String>,
    pub upload_id: Option<String>,
    pub version_id: Option<String>,
    pub connector_idempotency_key: Option<String>,
    pub disposition: String,
    pub scope_kind: Option<String>,
    pub scope_ref: Option<String>,
    pub promoted_from_version_id: Option<String>,
    pub cloud_knowledge: Option<String>,
    pub replace_existing: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DocumentReplacementResolution {
    pub request: Box<CreateUploadRequest>,
    pub unchanged_session: Option<String>,
}

pub trait DocumentCatalogMetadataStore {
    fn list_collection_versions(&self, collection_id: String, limit: i64) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn resolve_document_replacement(mut metadata: String, mut access: String, mut actor_id: String, mut actor_groups: std::collections::BTreeSet<String>, mut request: CreateUploadRequest, mut id_factory: String) -> Result<DocumentReplacementResolution, &'static str> {
    if is_unchanged(String::new(), String::new(), request.clone()) {
        return Ok(DocumentReplacementResolution::default());
    }
    Ok(DocumentReplacementResolution::default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn is_unchanged(mut previous: String, mut previous_session: String, mut request: CreateUploadRequest) -> bool {
    let mut request_scope_kind: Option<String> = request.scope_kind.clone();
    let mut request_scope_ref: Option<String> = request.scope_ref.clone();
    false
}

