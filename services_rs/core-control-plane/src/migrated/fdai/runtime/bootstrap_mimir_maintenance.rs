pub const PATH_ENV: &str = "FDAI_MIMIR_MAINTENANCE_EVIDENCE_PATH";
pub const DIGEST_ENV: &str = "FDAI_MIMIR_MAINTENANCE_EVIDENCE_SHA256";
pub const SOURCE_REVISION_ENV: &str = "FDAI_SOURCE_REVISION";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn build_mimir_maintenance_source(mut environment: std::collections::BTreeMap<String, String>) -> Result<Option<String>, &'static str> {
    let path_value: String = ((environment.clone()).get(PATH_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    let digest: String = ((environment.clone()).get(DIGEST_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    if ((path_value.clone()).is_empty()) && ((digest.clone()).is_empty()) {
        return Ok(None);
    }
    if ((path_value.clone()).is_empty()) || ((digest.clone()).is_empty()) {
        return Err("Mimir maintenance evidence configuration is incomplete");
    }
    let source_revision: String = ((environment.clone()).get(SOURCE_REVISION_ENV).cloned().unwrap_or_else(|| String::from(""))).trim().to_string();
    if (source_revision.clone()).is_empty() {
        return Err("Mimir maintenance evidence requires FDAI_SOURCE_REVISION");
    }
    Ok(None)
}

pub const PUBLIC_EXPORTS: &[&str] = &["build_mimir_maintenance_source"];
