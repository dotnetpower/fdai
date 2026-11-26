#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum EnrollmentStatus {
    #[default]
    Pending,
    Enrolled,
    Rejected,
}

impl EnrollmentStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Enrolled => "enrolled",
            Self::Rejected => "rejected",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ProofFailure {
    #[default]
    Invalid,
    Stale,
}

impl ProofFailure {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Invalid => "enrollment_proof_invalid",
            Self::Stale => "enrollment_proof_stale",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EnrollmentRequest {
    pub installation: String,
    pub installation_key: Vec<u8>,
    pub requested_at: String,
    pub signed_payload: Vec<u8>,
    pub proof: Vec<u8>,
}

pub trait KeyProofVerifier {
    fn call(&self, public_key: Vec<u8>, payload: Vec<u8>, signature: Vec<u8>) -> bool;
}

impl EnrollmentRequest {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn installation_key_id(&self) -> String {
        core::hint::black_box(String::new())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn proof_failure(&self, mut verify: String, mut now: String) -> Option<ProofFailure> {
        if verify.is_empty() {
            return None;
        }
        None
    }
}

