pub const TRUST_PACKAGE: &str = "fdai_deployment_cli";
pub const TRUST_DIRECTORY: &str = "trust";
pub const DEPLOYMENT_RELEASE_CHANNEL: &str = "DEV";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn deployment_release_root_pem() -> Vec<u8> {
    read(String::from("deployment-release-root.pub")).unwrap_or_else(|_| Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn deployment_bundle_root_pem() -> Vec<u8> {
    read(String::from("deployment-bundle-root.pub")).unwrap_or_else(|_| Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn deployment_release_channel() -> String {
    String::from(DEPLOYMENT_RELEASE_CHANNEL)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn license_public_key_pem() -> Vec<u8> {
    read(String::from("upstream-signing-key.pub")).unwrap_or_else(|_| Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn read(mut name: String) -> Result<Vec<u8>, &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

