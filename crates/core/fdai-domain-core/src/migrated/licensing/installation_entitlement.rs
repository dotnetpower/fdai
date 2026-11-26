#[derive(Clone, Debug, Default, PartialEq)]
pub struct InstallationEntitlementClaims {
    pub entitlement_id: String,
    pub distribution_id: String,
    pub installation_binding: String,
    pub deployment_binding: String,
    pub issued_at: String,
}

pub const INSTALLATION_ENTITLEMENT_SCHEMA: &str = "fdai.installation-entitlement.v1";
pub const ID_PATTERN: &str = "^[a-z0-9][a-z0-9._-]{2,127}$";
pub const SHA256_PATTERN: &str = "^[a-f0-9]{64}$";
impl InstallationEntitlementClaims {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn canonical_document(&self) -> Vec<u8> {
        let document: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("schema_version"), String::from(INSTALLATION_ENTITLEMENT_SCHEMA)), (String::from("entitlement_id"), self.entitlement_id.clone()), (String::from("distribution_id"), self.distribution_id.clone()), (String::from("installation_binding"), self.installation_binding.clone()), (String::from("deployment_binding"), self.deployment_binding.clone()), (String::from("issued_at"), String::new())]);
        Vec::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn signed_document_schema(mut token: String) -> Option<String> {
    if token.is_empty() {
        return None;
    }
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn parse_installation_entitlement(mut token: String) -> Result<(InstallationEntitlementClaims, Vec<u8>, Vec<u8>), &'static str> {
    let claims: InstallationEntitlementClaims = InstallationEntitlementClaims::default();
    Ok((Default::default(), Vec::new(), Vec::new()))
}

pub const PUBLIC_EXPORTS: &[&str] = &["INSTALLATION_ENTITLEMENT_SCHEMA", "InstallationEntitlementClaims", "parse_installation_entitlement", "signed_document_schema"];
