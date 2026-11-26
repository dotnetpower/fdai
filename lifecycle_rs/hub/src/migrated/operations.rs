#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReleasePublicationRequest {
    pub schema_version: String,
    pub request_id: String,
    pub release_id: String,
    pub manifest: String,
    pub manifest_digest: String,
    pub channels: Vec<String>,
    pub reason: String,
    pub confirmation: String,
}

impl ReleasePublicationRequest {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "fdai.release-publication-request.v1") { return Err("invalid schema_version literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CatalogImportRequest {
    pub schema_version: String,
    pub request_id: String,
    pub revision: i64,
    pub sha256: String,
    pub reason: String,
    pub confirmation: String,
}

impl CatalogImportRequest {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "fdai.catalog-import-request.v1") { return Err("invalid schema_version literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RecomputeRequest {
    pub schema_version: String,
    pub request_id: String,
    pub installation_id: String,
    pub catalog_revision: i64,
    pub catalog_sha256: String,
}

impl RecomputeRequest {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "fdai.lifecycle-recompute-request.v1") { return Err("invalid schema_version literal"); }
        Ok(())
    }
}

impl ReleasePublicationRequest {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_request(&self) -> Result<ReleasePublicationRequest, &'static str> {
        Err("runtime_binding_required")
    }
}

impl CatalogImportRequest {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_request(&self) -> Result<CatalogImportRequest, &'static str> {
        if (self.confirmation.clone()) != (format!("approve {} {}", self.revision, self.sha256.clone())) {
            return Err("Catalog import confirmation differs.");
        }
        Ok(self.clone())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn publish_release(mut engine: String, mut key: String, mut request: ReleasePublicationRequest, mut actor: String, mut now: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut mutated: bool = false;
    for channel in request.channels.clone() {
        mutated = true;
    }
    Ok(std::collections::BTreeMap::from([(String::from("schema_version"), String::from("fdai.release-publication-receipt.v1")), (String::from("request_id"), request.request_id.clone()), (String::from("release_id"), request.release_id.clone()), (String::from("manifest_digest"), request.manifest_digest.clone()), (String::from("catalog_revision"), String::new()), (String::from("catalog_sha256"), String::new()), (String::from("catalog_bytes"), String::new()), (String::from("channels"), String::new()), (String::from("effect_verified"), String::new()), (String::from("mutation_performed"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn approve_and_import_catalog(mut catalog: String, mut request: CatalogImportRequest, mut actor: String, mut now: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::from([(String::from("schema_version"), String::from("fdai.catalog-import-receipt.v1")), (String::from("request_id"), request.request_id.clone()), (String::from("catalog_revision"), String::new()), (String::from("catalog_sha256"), request.sha256.clone()), (String::from("effect_verified"), String::new()), (String::from("mutation_performed"), String::new())]))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn recompute_installation(mut store: String, mut catalog: String, mut key: String, mut request: RecomputeRequest, mut now: String) -> Result<(String, std::collections::BTreeMap<String, String>), &'static str> {
    let receipt: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from("fdai.lifecycle-recompute-receipt.v1")), (String::from("request_id"), request.request_id.clone()), (String::from("installation_id"), request.installation_id.clone()), (String::from("catalog_revision"), String::new()), (String::from("catalog_sha256"), request.catalog_sha256.clone()), (String::from("outcome"), String::new()), (String::from("plan_id"), String::new()), (String::from("receipt_digest"), String::new()), (String::from("mutation_performed"), String::new())]);
    Ok((String::new(), std::collections::BTreeMap::new()))
}

pub const PUBLIC_EXPORTS: &[&str] = &["CatalogImportRequest", "RecomputeRequest", "ReleasePublicationRequest", "approve_and_import_catalog", "publish_release", "recompute_installation"];
