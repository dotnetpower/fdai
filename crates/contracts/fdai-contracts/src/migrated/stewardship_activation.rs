#[derive(Clone, Debug, Default, PartialEq)]
pub struct StewardshipCandidateActivationBody {
    pub candidate_id: String,
    pub candidate_digest: String,
}

pub const STEWARDSHIP_ACTIVATION_OPERATION: &str = "stewardship.candidate_activation";
pub const CANDIDATE_ID_PATTERN: &str = "^[0-9a-f]{16}$";
pub const CANDIDATE_DIGEST_PATTERN: &str = "^[0-9a-f]{64}$";
pub const PUBLIC_EXPORTS: &[&str] = &["CANDIDATE_DIGEST_PATTERN", "CANDIDATE_ID_PATTERN", "STEWARDSHIP_ACTIVATION_OPERATION", "StewardshipCandidateActivationBody"];
