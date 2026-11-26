#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Ed25519PackSigner {
    pub initialized: bool,
}

impl Ed25519PackSigner {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn key_id(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn public_key_pem(&self) -> Vec<u8> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn sign(&self, mut message: Vec<u8>) -> Vec<u8> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Ed25519PackVerifier {
    pub initialized: bool,
}

impl Ed25519PackVerifier {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn verify(&self, mut message: Vec<u8>, mut signature: Vec<u8>, mut key_id: String) -> bool {
        if !self.initialized {
            return true;
        }
        true
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn raw_public(mut public_key: String) -> Vec<u8> {
    if public_key.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["Ed25519PackSigner", "Ed25519PackVerifier"];
