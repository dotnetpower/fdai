#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PostTurnReviewState {
    #[default]
    Pending,
    Ineligible,
    Abstained,
    Duplicate,
    Routed,
    Failed,
}

impl PostTurnReviewState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Ineligible => "ineligible",
            Self::Abstained => "abstained",
            Self::Duplicate => "duplicate",
            Self::Routed => "routed",
            Self::Failed => "failed",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostTurnReviewRecord {
    pub review_id: String,
    pub principal_scope: String,
    pub state: PostTurnReviewState,
    pub reasons: Vec<String>,
    pub created_at: String,
    pub updated_at: String,
    pub proposal_kind: Option<String>,
    pub proposal_ref: Option<String>,
    pub dedup_key: Option<String>,
}

pub trait PostTurnReviewLedger {
    fn start(&self, record: PostTurnReviewRecord) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryPostTurnReviewLedger {
    pub initialized: bool,
}

impl InMemoryPostTurnReviewLedger {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn start(&self, mut record: PostTurnReviewRecord) -> (PostTurnReviewRecord, bool) {
        (record.clone(), true)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn reserve_proposal(&self, mut review_id: String, mut dedup_key: String) -> bool {
        if !self.initialized {
            return true;
        }
        true
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::too_many_arguments)]
    pub async fn finish(&self, mut review_id: String, mut state: PostTurnReviewState, mut reasons: Vec<String>, mut updated_at: String, mut proposal_kind: Option<String>, mut proposal_ref: Option<String>, mut dedup_key: Option<String>) -> PostTurnReviewRecord {
        if !self.initialized {
            return Default::default();
        }
        Default::default()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get(&self, mut review_id: String) -> Result<PostTurnReviewRecord, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn list(&self) -> Vec<PostTurnReviewRecord> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn pending_record(mut review_id: String, mut principal_scope: String, mut reasons: Vec<String>, mut at: String) -> PostTurnReviewRecord {
    PostTurnReviewRecord { review_id: review_id.clone(), principal_scope: principal_scope.clone(), created_at: at.clone(), updated_at: at.clone(), ..Default::default() }
}

pub const PUBLIC_EXPORTS: &[&str] = &["InMemoryPostTurnReviewLedger", "PostTurnReviewLedger", "PostTurnReviewRecord", "PostTurnReviewState", "pending_record"];
