use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct HandoverIdentityFacts {
    pub subject_ref: String,
    pub roles: Vec<String>,
    pub group_ids: Vec<String>,
    pub observed_at: String,
    pub expires_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CurrentHandoverIdentityReader {
    pub subjects: String,
    pub directory: String,
    pub role_group_ids: BTreeMap<String, String>,
    pub clock: String,
}

impl HandoverIdentityFacts {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn current(&self, mut at: String) -> Result<bool, &'static str> {
        Ok(((self.observed_at.clone()) <= (at.clone())) && ((at.clone()) < (self.expires_at.clone())))
    }
}

pub trait HandoverIdentityReader {
    fn read(&self, subject_ref: String) -> Option<HandoverIdentityFacts>;
}

impl CurrentHandoverIdentityReader {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read(&self, mut subject_ref: String) -> Option<HandoverIdentityFacts> {
        Some(HandoverIdentityFacts::default())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["CurrentHandoverIdentityReader", "HandoverIdentityFacts", "HandoverIdentityReader"];
