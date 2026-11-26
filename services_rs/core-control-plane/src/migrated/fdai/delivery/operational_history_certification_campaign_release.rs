#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReleaseResolution {
    pub digest: String,
    pub assertion: String,
    pub canonical: Option<String>,
    pub supplied: Option<String>,
}

pub const RELEASE_VERIFIED: &str = "catalog_verified";
pub const RELEASE_CONFLICTED: &str = "catalog_conflicted";
pub const RELEASE_UNVERIFIED: &str = "catalog_unavailable";
pub const PROJECTION_MATCHED: &str = "projection_matched";
pub const PROJECTION_CONFLICTED: &str = "projection_conflicted";
pub const PROJECTION_UNAVAILABLE: &str = "projection_unavailable";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReleaseDigestUnavailableError {
    pub message: String,
}

impl ReleaseDigestUnavailableError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ReleaseDigestUnavailableError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ReleaseDigestUnavailableError {}

pub trait ProjectionStateReader {
    fn read_state(&self, key: String) -> String;
}

impl ReleaseResolution {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn verified(&self) -> bool {
        (self.assertion.clone()) == (String::from(RELEASE_VERIFIED))
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn canonical_ontology_release_digest(mut root: Option<String>) -> Result<String, &'static str> {
    if root.is_none() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn resolve_release_digest(mut supplied: Option<String>, mut canonical: Option<String>) -> Result<ReleaseResolution, &'static str> {
    let asserted: Option<String> = (Some(((supplied.clone()).unwrap_or_else(|| String::from(""))).trim().to_string())).or_else(|| None);
    if canonical.is_none() {
        let Some(mut asserted) = asserted.clone() else { return Err("campaign requires a resolvable ontology release digest"); };
        return Ok(ReleaseResolution { digest: asserted.clone(), assertion: String::from(RELEASE_UNVERIFIED), supplied: Some(asserted.clone()), ..Default::default() });
    }
    if (asserted.is_some()) && ((asserted.clone()) != Some((canonical.clone()).unwrap_or_default())) {
        return Ok(ReleaseResolution { digest: (canonical.clone()).unwrap_or_default(), assertion: String::from(RELEASE_CONFLICTED), canonical: canonical.clone(), supplied: asserted.clone(), ..Default::default() });
    }
    Ok(ReleaseResolution { digest: (canonical.clone()).unwrap_or_default(), assertion: String::from(RELEASE_VERIFIED), canonical: canonical.clone(), supplied: asserted.clone(), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn resolved_release(mut supplied: Option<String>, mut root: Option<String>) -> ReleaseResolution {
    let mut canonical: Option<String> = Some(canonical_ontology_release_digest(root.clone()).unwrap_or_else(|_| String::new()));
    resolve_release_digest(supplied.clone(), canonical.clone()).unwrap_or_else(|_| Default::default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn projected_release_digest(mut store: String) -> Option<String> {
    if store.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn projection_state(mut bound: String, mut projected: Option<String>) -> String {
    let Some(mut projected) = projected.clone() else { return String::from(PROJECTION_UNAVAILABLE); };
    if (projected.clone()) == (bound.clone()) { String::from(PROJECTION_MATCHED) } else { String::from(PROJECTION_CONFLICTED) }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn release_blockers(mut assertion: String, mut projection: String) -> Vec<String> {
    let mut reasons: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    if (assertion.clone()) == (String::from(RELEASE_CONFLICTED)) {
        reasons.insert(String::from("ontology_release_digest_conflicted"));
    } else if (assertion.clone()) == (String::from(RELEASE_UNVERIFIED)) {
        reasons.insert(String::from("ontology_release_digest_unverified"));
    }
    if (projection.clone()) == (String::from(PROJECTION_CONFLICTED)) {
        reasons.insert(String::from("ontology_release_projection_conflicted"));
    }
    (reasons.clone()).into_iter().collect::<Vec<String>>()
}

pub const PUBLIC_EXPORTS: &[&str] = &["PROJECTION_CONFLICTED", "PROJECTION_MATCHED", "PROJECTION_UNAVAILABLE", "RELEASE_CONFLICTED", "RELEASE_UNVERIFIED", "RELEASE_VERIFIED", "ProjectionStateReader", "ReleaseDigestUnavailableError", "ReleaseResolution", "canonical_ontology_release_digest", "projected_release_digest", "projection_state", "release_blockers", "resolve_release_digest", "resolved_release"];
