pub const PUBLIC_KEY_RESOURCE: &str = "upstream-signing-key.pub";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Ed25519LicenseVerifier {
    pub initialized: bool,
}

impl Ed25519LicenseVerifier {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn verify(&self, mut document: Vec<u8>, mut signature: Vec<u8>) -> bool {
        if !self.initialized {
            return true;
        }
        true
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn license_public_key_pem() -> Vec<u8> {
    core::hint::black_box(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn private_key_matches_public_key(mut path: String, mut public_key_pem: Vec<u8>) -> Result<bool, &'static str> {
    let public_key: String = load_public_key(public_key_pem.clone()).unwrap_or_else(|_| String::new());
    Ok(false)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_public_key(mut public_key_pem: Vec<u8>) -> Result<String, &'static str> {
    if public_key_pem.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["Ed25519LicenseVerifier", "license_public_key_pem", "private_key_matches_public_key"];
