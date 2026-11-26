pub trait IdentityDirectory {
    fn is_active(&self, oid: String) -> bool;
}

pub trait GroupMembershipProvider {
    fn members_of(&self, group_oid: String) -> Vec<String>;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StaticIdentityDirectory {
    pub initialized: bool,
}

impl StaticIdentityDirectory {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn is_active(&self, mut oid: String) -> bool {
        self.initialized
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StaticGroupMembershipProvider {
    pub initialized: bool,
}

impl StaticGroupMembershipProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn members_of(&self, mut group_oid: String) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["GroupMembershipProvider", "IdentityDirectory", "StaticGroupMembershipProvider", "StaticIdentityDirectory"];
