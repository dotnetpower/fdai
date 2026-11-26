#[derive(Clone, Debug, Default, PartialEq)]
pub struct SeedRef {
    pub kind: String,
    pub path: String,
    pub symbol: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Seed {
    pub behavior_id: String,
    pub subject_id: String,
    pub status: String,
    pub owner: String,
    pub aliases: Vec<String>,
    pub english: String,
    pub korean: String,
    pub refs: Vec<SeedRef>,
    pub subject_kind: String,
}

pub const CORE: &str = "services/core-control-plane/src/fdai/";
pub const TEST: &str = "services/core-control-plane/tests/";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn text(mut trigger: String, mut preconditions: String, mut steps: String, mut outcomes: String, mut exclusions: String, mut safety: String) -> String {
    if trigger.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn code(mut path: String, mut symbol: String) -> SeedRef {
    SeedRef::default()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn test(mut path: String, mut symbol: String) -> SeedRef {
    SeedRef::default()
}

