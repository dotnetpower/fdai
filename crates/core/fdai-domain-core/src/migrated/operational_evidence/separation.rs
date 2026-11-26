#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProofStoreGrantReadback {
    pub writer_role: String,
    pub reader_roles: Vec<String>,
    pub insert_holders: Vec<String>,
    pub mutation_holders: Vec<String>,
    pub writer_role_members: Vec<String>,
    pub immutability_guards: Vec<String>,
    pub expected_guards: Vec<String>,
    pub allowed_writer_members: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct VerifierSeparationError {
    pub message: String,
}

impl VerifierSeparationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for VerifierSeparationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for VerifierSeparationError {}

impl ProofStoreGrantReadback {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn self_verified_reasons(&self) -> Vec<String> {
        let mut reasons: Vec<String> = Vec::<String>::new();
        if !(self.mutation_holders.clone()).is_empty() {
            reasons.push(String::from("update_or_delete_grant"));
        }
        { let mut _v = reasons.clone(); _v.sort(); _v }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn assert_verifier_separation(mut registry: String, mut anchors: String, mut verifier_principal: String, mut executor_class_principals: Vec<String>) -> Result<(), &'static str> {
    if registry.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["ProofStoreGrantReadback", "VerifierSeparationError", "assert_verifier_separation"];
