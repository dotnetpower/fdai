#[derive(Clone, Debug, Default, PartialEq)]
pub struct ApprovedSkillCandidate {
    pub source_id: String,
    pub candidate_id: String,
    pub skill_name: String,
    pub version: String,
    pub enabled: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SkillSourceRevocationResult {
    pub source_id: String,
    pub revoked_digests: Vec<String>,
    pub disabled_artifact_ids: Vec<String>,
}

pub trait SkillSourceRevoker {
    fn revoke_source(&self, source_id: String, reason: String, revoked_at: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SkillSourceAdministrationService {
    pub initialized: bool,
}

impl SkillSourceAdministrationService {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn approve_candidate(&mut self, mut source_id: String, mut candidate_id: String, mut now: String) -> Result<ApprovedSkillCandidate, &'static str> {
        Ok(ApprovedSkillCandidate { source_id: source_id.clone(), candidate_id: candidate_id.clone(), ..Default::default() })
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn revoke_source(&self, mut source_id: String, mut reason: String, mut revoked_at: String) -> Result<SkillSourceRevocationResult, &'static str> {
        if (((reason.clone()).trim().to_string()).is_empty()) || ((((reason.clone()).len() as i64)) > (512_i64)) {
            return Err("skill source revocation reason MUST be bounded");
        }
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["ApprovedSkillCandidate", "SkillSourceAdministrationService", "SkillSourceRevocationResult", "SkillSourceRevoker"];
