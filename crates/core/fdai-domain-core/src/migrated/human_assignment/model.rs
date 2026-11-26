pub const MAX_IDENTIFIER_CHARS: i64 = 256;
pub const MAX_JUSTIFICATION_CHARS: i64 = 2000;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AssignmentState {
    #[default]
    Draft,
    PendingReview,
    Approved,
    OwnershipPrOpen,
    OwnershipMerged,
    IamApplying,
    IamRevoked,
    Active,
    Revoked,
    Rejected,
    Degraded,
    Superseded,
}

impl AssignmentState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Draft => "draft",
            Self::PendingReview => "pending_review",
            Self::Approved => "approved",
            Self::OwnershipPrOpen => "ownership_pr_open",
            Self::OwnershipMerged => "ownership_merged",
            Self::IamApplying => "iam_applying",
            Self::IamRevoked => "iam_revoked",
            Self::Active => "active",
            Self::Revoked => "revoked",
            Self::Rejected => "rejected",
            Self::Degraded => "degraded",
            Self::Superseded => "superseded",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ReviewDecision {
    #[default]
    Approve,
    Reject,
}

impl ReviewDecision {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Approve => "approve",
            Self::Reject => "reject",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum EffectKind {
    #[default]
    Ownership,
    Iam,
}

impl EffectKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Ownership => "ownership",
            Self::Iam => "iam",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProviderSubject {
    pub provider: String,
    pub subject_id: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct DutyBinding {
    pub agent_name: String,
    pub duty: String,
    pub scope_ref: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AssignmentIntent {
    pub idempotency_key: String,
    pub subject: Box<ProviderSubject>,
    pub requested_role: String,
    pub duty_bindings: Vec<DutyBinding>,
    pub goal_refs: Vec<String>,
    pub requester_ref: String,
    pub justification: String,
    pub revocation: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ReviewReceipt {
    pub reviewer_ref: String,
    pub decision: ReviewDecision,
    pub reviewed_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct EffectReceipt {
    pub kind: EffectKind,
    pub receipt_ref: String,
    pub digest: String,
    pub received_at: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AssignmentCase {
    pub case_id: String,
    pub intent: Box<AssignmentIntent>,
    pub state: AssignmentState,
    pub revision: i64,
    pub reviews: Vec<ReviewReceipt>,
    pub effect_receipts: Vec<EffectReceipt>,
    pub degraded_reason: Option<String>,
    pub superseded_by: Option<String>,
    pub command_receipts: Vec<String>,
    pub revocation_case_id: Option<String>,
    pub iam_preparation: Option<String>,
    pub iam_recovery_preparation: Option<String>,
    #[allow(clippy::type_complexity)]
    pub iam_recovery_effect: Option<Box<EffectReceipt>>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AssignmentModelError {
    pub message: String,
}

impl AssignmentModelError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for AssignmentModelError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for AssignmentModelError {}

impl ProviderSubject {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("provider"), self.provider.clone()), (String::from("subject_id"), self.subject_id.clone())])
    }
}

impl DutyBinding {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("agent_name"), self.agent_name.clone()), (String::from("duty"), String::new()), (String::from("scope_ref"), self.scope_ref.clone())])
    }
}

impl AssignmentIntent {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("idempotency_key"), self.idempotency_key.clone()), (String::from("subject"), String::new()), (String::from("requested_role"), String::new()), (String::from("duty_bindings"), String::new()), (String::from("goal_refs"), String::new()), (String::from("requester_ref"), self.requester_ref.clone()), (String::from("justification"), self.justification.clone())])
    }
}

impl ReviewReceipt {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("reviewer_ref"), self.reviewer_ref.clone()), (String::from("decision"), String::new()), (String::from("reviewed_at"), String::new())])
    }
}

impl EffectReceipt {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("kind"), String::new()), (String::from("receipt_ref"), self.receipt_ref.clone()), (String::from("digest"), self.digest.clone()), (String::from("received_at"), String::new())])
    }
}

impl AssignmentCase {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn effect_kinds(&self) -> std::collections::BTreeSet<EffectKind> {
        std::collections::BTreeSet::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn has_required_effects(&self) -> bool {
        core::hint::black_box(false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("case_id"), self.case_id.clone()), (String::from("intent"), String::new()), (String::from("state"), String::new()), (String::from("revision"), String::new()), (String::from("reviews"), String::new()), (String::from("effect_receipts"), String::new()), (String::from("degraded_reason"), (self.degraded_reason.clone()).unwrap_or_default()), (String::from("superseded_by"), (self.superseded_by.clone()).unwrap_or_default()), (String::from("command_receipts"), String::new())])
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn from_dict(mut value: std::collections::BTreeMap<String, String>) -> AssignmentCase {
        let raw_intent: std::collections::BTreeMap<String, String> = mapping(value.clone(), String::from("intent")).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let raw_subject: std::collections::BTreeMap<String, String> = mapping(raw_intent.clone(), String::from("subject")).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let intent: AssignmentIntent = AssignmentIntent { idempotency_key: string(raw_intent.clone(), String::from("idempotency_key")), subject: Box::new(ProviderSubject { provider: string(raw_subject.clone(), String::from("provider")), subject_id: string(raw_subject.clone(), String::from("subject_id")), ..Default::default() }), requester_ref: string(raw_intent.clone(), String::from("requester_ref")), justification: string(raw_intent.clone(), String::from("justification")), ..Default::default() };
        Default::default()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn identifier(mut value: String, mut name: String) -> Result<String, &'static str> {
    if !(true) {
        return Err("name MUST be a string");
    }
    let normalized: String = value.trim().to_string();
    if (((normalized.clone()).len() as i64)) > (MAX_IDENTIFIER_CHARS) {
        return Err("name MUST be at most _MAX_IDENTIFIER_CHARS characters");
    }
    Ok(normalized.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn aware(mut value: String, mut name: String) -> Result<(), &'static str> {
    if value.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn mapping(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let item: Option<String> = (value.clone()).get(key.as_str()).cloned();
    if !(true) {
        return Err("stored assignment key MUST be an object");
    }
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn mapping_list(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Result<Vec<std::collections::BTreeMap<String, String>>, &'static str> {
    let items: Option<String> = (value.clone()).get(key.as_str()).cloned();
    Ok(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn string_list(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Result<Vec<String>, &'static str> {
    let items: Option<String> = (value.clone()).get(key.as_str()).cloned();
    Ok(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn string(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> String {
    string_value(String::new(), key.clone()).unwrap_or_else(|_| String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn string_value(mut value: String, mut name: String) -> Result<String, &'static str> {
    if (!(true)) || ((value.clone()).is_empty()) {
        return Err("stored assignment name MUST be a string");
    }
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn optional_string(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Option<String> {
    let item: Option<String> = (value.clone()).get(key.as_str()).cloned();
    let Some(mut item) = item.clone() else { return None; };
    Some(string_value(item.clone(), key.clone()).unwrap_or_else(|_| String::new()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn integer(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Result<i64, &'static str> {
    let item: Option<String> = (value.clone()).get(key.as_str()).cloned();
    if (!(true)) || (true) {
        return Err("stored assignment key MUST be an integer");
    }
    Ok(0_i64)
}

pub const PUBLIC_EXPORTS: &[&str] = &["AssignmentCase", "AssignmentIntent", "AssignmentModelError", "AssignmentState", "DutyBinding", "EffectKind", "EffectReceipt", "ProviderSubject", "ReviewDecision", "ReviewReceipt"];
