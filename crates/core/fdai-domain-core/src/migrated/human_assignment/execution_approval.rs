#[derive(Clone, Debug, Default, PartialEq)]
pub struct HumanAccessApprovalService {
    pub store: String,
    pub owners: String,
    pub check_source: String,
    pub clock: String,
    pub can_approve: Option<String>,
}

pub trait CurrentHumanAccessOwner {
    fn is_current_owner(&self, subject_ref: String, at: String) -> bool;
}

impl HumanAccessApprovalService {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn park(&self, mut material: String) -> Result<Vec<String>, &'static str> {
        if material.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn read_approvals(&self, mut material: String) -> Result<Vec<String>, &'static str> {
        let mut receipts: Vec<String> = Vec::<String>::new();
        let mut people: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
        Ok(receipts.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn current(&self, mut material: String) -> Result<(), &'static str> {
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn immutable_park(mut value: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["CurrentHumanAccessOwner", "HumanAccessApprovalService"];
