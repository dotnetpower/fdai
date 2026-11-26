#[derive(Clone, Debug, Default, PartialEq)]
pub struct ResolvedIdentity {
    pub oid: String,
    pub kind: String,
}

pub trait PersonDirectory {
    fn resolve(&self, display_name: String) -> Option<ResolvedIdentity>;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StaticPersonDirectory {
    pub initialized: bool,
}

impl StaticPersonDirectory {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn resolve(&self, mut display_name: String) -> Option<ResolvedIdentity> {
        if (!(true)) || ((display_name.trim().to_string()).is_empty()) {
            return None;
        }
        None
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NullPersonDirectory {
    pub initialized: bool,
}

impl NullPersonDirectory {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn resolve(&self, mut display_name: String) -> Option<ResolvedIdentity> {
        if !self.initialized {
            return None;
        }
        None
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["NullPersonDirectory", "PersonDirectory", "ResolvedIdentity", "StaticPersonDirectory"];
