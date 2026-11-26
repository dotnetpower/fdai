pub const MAX_PUBLIC_KEY_BYTES: i64 = 16384;

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Ed25519ArtifactVerifier {
    pub initialized: bool,
}

impl Ed25519ArtifactVerifier {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn from_file(mut path: String) -> String {
        if path.is_empty() {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn call(&self, mut payload: Vec<u8>, mut signature: Vec<u8>) -> bool {
        if !self.initialized {
            return true;
        }
        true
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Ed25519HubKeyring {
    pub initialized: bool,
}

impl Ed25519HubKeyring {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn call(&self, mut key_id: String, mut payload: Vec<u8>, mut signature: Vec<u8>) -> bool {
        self.initialized
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn load_ed25519_public_key(mut path: String) -> Result<String, &'static str> {
    if path.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

