pub const MAX_PROFILE_BYTES: i64 = 65536;
pub const MAX_PRIVATE_KEY_BYTES: i64 = 65536;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CatalogReviewDeploymentProfile {
    pub selected: bool,
    pub owner: String,
    pub repo: String,
    pub default_branch: String,
    pub app_client_id: String,
    pub app_installation_id: String,
    pub private_key_path: Option<String>,
    pub private_key_sha256: String,
    pub profile_digest: String,
}

pub const SCHEMA: &str = "fdai.catalog-review-deployment-profile.v1";
pub const STAGED_SCHEMA: &str = "fdai.catalog-review-staged-profile.v1";
pub const NAME: &str = "^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,99})$";
pub const BRANCH: &str = "^[A-Za-z0-9](?:[A-Za-z0-9._/-]{0,254})$";
impl CatalogReviewDeploymentProfile {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn unselected() -> CatalogReviewDeploymentProfile {
        let material: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from(SCHEMA)), (String::from("selected"), String::new())]);
        Default::default()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn staged_mapping(&self) -> std::collections::BTreeMap<String, String> {
        let material: std::collections::BTreeMap<String, String> = self.material(String::from(STAGED_SCHEMA));
        std::collections::BTreeMap::from([(String::from("profile_digest"), self.profile_digest.clone())])
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn private_key_text(&self) -> Result<String, &'static str> {
        if (!(self.selected)) || (self.private_key_path.is_none()) {
            return Err("selected catalog review profile has no private key reference");
        }
        Ok(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn material(&self, mut schema_version: String) -> std::collections::BTreeMap<String, String> {
        if !(self.selected) {
            return std::collections::BTreeMap::from([(String::from("schema_version"), schema_version.clone()), (String::from("selected"), String::new())]);
        }
        std::collections::BTreeMap::from([(String::from("schema_version"), schema_version.clone()), (String::from("selected"), String::new()), (String::from("owner"), self.owner.clone()), (String::from("repo"), self.repo.clone()), (String::from("default_branch"), self.default_branch.clone()), (String::from("app_client_id"), self.app_client_id.clone()), (String::from("app_installation_id"), self.app_installation_id.clone()), (String::from("private_key_sha256"), self.private_key_sha256.clone())])
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_catalog_review_profile(mut path: String) -> Result<CatalogReviewDeploymentProfile, &'static str> {
    let value: std::collections::BTreeMap<String, String> = read_json(path.clone(), String::from("catalog review deployment profile")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let expected: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("schema_version"), String::from("selected"), String::from("owner"), String::from("repo"), String::from("default_branch"), String::from("app_client_id"), String::from("app_installation_id"), String::from("app_private_key_file")]);
    let owner: String = name(value.clone(), String::from("owner")).unwrap_or_else(|_| String::new());
    let repo: String = name(value.clone(), String::from("repo")).unwrap_or_else(|_| String::new());
    let default_branch: Option<String> = (value.clone()).get("default_branch").cloned();
    let client_id: Option<String> = (value.clone()).get("app_client_id").cloned();
    let installation_id: Option<String> = (value.clone()).get("app_installation_id").cloned();
    let key_reference: Option<String> = (value.clone()).get("app_private_key_file").cloned();
    let material: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from(SCHEMA)), (String::from("selected"), String::new()), (String::from("owner"), owner.clone()), (String::from("repo"), repo.clone()), (String::from("default_branch"), (default_branch.clone()).unwrap_or_default()), (String::from("app_client_id"), ((client_id.clone()).unwrap_or_default()).trim().to_string()), (String::from("app_installation_id"), (installation_id.clone()).unwrap_or_default()), (String::from("private_key_sha256"), String::new())]);
    Ok(CatalogReviewDeploymentProfile { selected: true, owner: owner.clone(), repo: repo.clone(), default_branch: (default_branch.clone()).unwrap_or_default(), app_client_id: ((client_id.clone()).unwrap_or_default()).trim().to_string(), app_installation_id: (installation_id.clone()).unwrap_or_default(), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_staged_catalog_review_profile(mut path: String, mut private_key_path: Option<String>) -> Result<CatalogReviewDeploymentProfile, &'static str> {
    let value: std::collections::BTreeMap<String, String> = read_json(path.clone(), String::from("staged catalog review profile")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let expected_fields: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([String::from("schema_version"), String::from("selected"), String::from("owner"), String::from("repo"), String::from("default_branch"), String::from("app_client_id"), String::from("app_installation_id"), String::from("private_key_sha256")]);
    let private_key_sha256: String = (value.clone()).get("private_key_sha256").cloned().unwrap_or_else(|| String::from(""));
    let default_branch: Option<String> = (value.clone()).get("default_branch").cloned();
    let app_client_id: Option<String> = (value.clone()).get("app_client_id").cloned();
    let app_installation_id: Option<String> = (value.clone()).get("app_installation_id").cloned();
    let material: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from(SCHEMA)), (String::from("selected"), String::new()), (String::from("owner"), name(value.clone(), String::from("owner")).unwrap_or_else(|_| String::new())), (String::from("repo"), name(value.clone(), String::from("repo")).unwrap_or_else(|_| String::new())), (String::from("default_branch"), (default_branch.clone()).unwrap_or_default()), (String::from("app_client_id"), ((app_client_id.clone()).unwrap_or_default()).trim().to_string()), (String::from("app_installation_id"), (app_installation_id.clone()).unwrap_or_default()), (String::from("private_key_sha256"), private_key_sha256.clone())]);
    Ok(CatalogReviewDeploymentProfile { selected: true, private_key_path: private_key_path.clone(), private_key_sha256: private_key_sha256.clone(), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn staged_catalog_review_profile_from_paths(mut profile_path: Option<String>, mut private_key_path: Option<String>) -> Result<CatalogReviewDeploymentProfile, &'static str> {
    if profile_path.is_none() {
        if let Some(mut private_key_path) = private_key_path.clone() {
            return Err("catalog review private key requires its reviewed profile");
        }
    }
    Ok(load_staged_catalog_review_profile((profile_path.clone()).unwrap_or_default(), private_key_path.clone()).unwrap_or_else(|_| Default::default()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn catalog_review_terraform_values(mut profile: CatalogReviewDeploymentProfile) -> std::collections::BTreeMap<String, String> {
    let mut values: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("enable_catalog_review"), String::new())]);
    values.clone()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn stage_catalog_review_profile(mut profile: CatalogReviewDeploymentProfile, mut tunnel: String, mut prepared_root: String, mut remote_root: String) -> Result<Vec<String>, &'static str> {
    let remote_profile: String = format!("{}/catalog-review-profile.json", remote_root.clone());
    let remote_key: String = format!("{}/catalog-review-private-key.pem", remote_root.clone());
    if (profile.private_key_path.clone()).is_none() {
        return Err("selected catalog review profile has no private key reference");
    }
    Ok(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn read_json(mut path: String, mut label: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn name(mut value: std::collections::BTreeMap<String, String>, mut field: String) -> Result<String, &'static str> {
    let item: Option<String> = (value.clone()).get(field.as_str()).cloned();
    Ok((item.clone()).unwrap_or_default())
}

pub const PUBLIC_EXPORTS: &[&str] = &["CatalogReviewDeploymentProfile", "catalog_review_terraform_values", "load_catalog_review_profile", "load_staged_catalog_review_profile", "staged_catalog_review_profile_from_paths", "stage_catalog_review_profile"];
