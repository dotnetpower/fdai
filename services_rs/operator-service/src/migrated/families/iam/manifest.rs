#[derive(Clone, Debug, Default, PartialEq)]
pub struct IamRouteManifestEntry {
    pub method: String,
    pub path: String,
    pub name: String,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn iam_family_manifest(mut policy_administration: bool) -> Vec<IamRouteManifestEntry> {
    core::hint::black_box(Vec::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["IAM_FAMILY_MANIFEST", "IAM_POLICY_ADMINISTRATION_MANIFEST", "IamRouteManifestEntry", "iam_family_manifest"];
