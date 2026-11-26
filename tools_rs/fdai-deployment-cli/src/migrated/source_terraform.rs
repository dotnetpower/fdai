pub const MAX_ARCHIVE_BYTES: i64 = 67108864;
pub const MAX_BINARY_BYTES: i64 = 134217728;

pub const RELEASES: &str = "https://releases.hashicorp.com/terraform";
pub const DIGEST: &str = "[0-9a-f]{64}";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NoRedirect {
    pub initialized: bool,
}

impl NoRedirect {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn redirect_request(&self, mut args: Vec<String>, mut kwargs: std::collections::BTreeMap<String, String>) -> Result<(), &'static str> {
        Err("Terraform release redirects are not supported")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn download_pinned_terraform(mut toolchain: std::collections::BTreeMap<String, String>, mut destination: String, mut timeout_seconds: i64) -> Result<String, &'static str> {
    let version: Option<String> = (toolchain.clone()).get("terraform_version").cloned();
    let archive_digest: Option<String> = (toolchain.clone()).get("terraform_sha256").cloned();
    let binary_digest: Option<String> = (toolchain.clone()).get("terraform_binary_sha256").cloned();
    Ok(destination.clone())
}

