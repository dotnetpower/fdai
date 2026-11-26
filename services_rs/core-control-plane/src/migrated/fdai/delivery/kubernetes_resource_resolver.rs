#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum KubernetesResourceResolutionStatus {
    #[default]
    Resolved,
    NotFound,
    Ambiguous,
    Unavailable,
}

impl KubernetesResourceResolutionStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Resolved => "resolved",
            Self::NotFound => "not_found",
            Self::Ambiguous => "ambiguous",
            Self::Unavailable => "unavailable",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct KubernetesResourceResolution {
    pub status: KubernetesResourceResolutionStatus,
    pub resource: Option<String>,
    pub candidate_count: i64,
    pub complete: bool,
    pub reason: Option<String>,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::too_many_arguments)]
pub fn resolve_kubernetes_resource(mut resources: Vec<String>, mut cluster_ref: String, mut resource_type: String, mut namespace: Option<String>, mut name: String, mut uid: Option<String>, mut resource_version: Option<String>, mut complete: bool) -> Result<KubernetesResourceResolution, &'static str> {
    if !(complete) {
        return Ok(KubernetesResourceResolution { resource: None, candidate_count: 0_i64, complete: false, reason: Some(String::from("inventory_scope_incomplete")), ..Default::default() });
    }
    Ok(KubernetesResourceResolution { candidate_count: 1_i64, complete: true, reason: None, ..Default::default() })
}

pub const PUBLIC_EXPORTS: &[&str] = &["KubernetesResourceResolution", "KubernetesResourceResolutionStatus", "resolve_kubernetes_resource"];
