pub const KNOWN_SEVERITIES: &[&str] = &["critical", "high", "medium", "low", "info"];
pub const KNOWN_CHECK_STATUSES: &[&str] = &["ok", "warn", "fail", "unknown"];
pub const KNOWN_HEALTHS: &[&str] = &["healthy", "degraded", "unhealthy", "unknown"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SloSummaryBuilder {
    pub initialized: bool,
}

impl SloSummaryBuilder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(&self, mut spec: String, mut data: String) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::new()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AlertStatusBuilder {
    pub initialized: bool,
}

impl AlertStatusBuilder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(&self, mut spec: String, mut data: String) -> std::collections::BTreeMap<String, String> {
        let mut active: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
        std::collections::BTreeMap::from([(String::from("active"), String::new()), (String::from("counts_by_severity"), String::new()), (String::from("total"), String::new())])
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CheckStatusBuilder {
    pub initialized: bool,
}

impl CheckStatusBuilder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(&self, mut spec: String, mut data: String) -> std::collections::BTreeMap<String, String> {
        let mut checks: Vec<std::collections::BTreeMap<String, String>> = Vec::<std::collections::BTreeMap<String, String>>::new();
        std::collections::BTreeMap::from([(String::from("checks"), String::new()), (String::from("summary"), String::new())])
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ServiceSummaryBuilder {
    pub initialized: bool,
}

impl ServiceSummaryBuilder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(&self, mut spec: String, mut data: String) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("service"), String::new()), (String::from("red"), String::new()), (String::from("health"), String::new()), (String::from("measured"), String::new())])
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FlameGraphBuilder {
    pub initialized: bool,
}

impl FlameGraphBuilder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(&self, mut spec: String, mut data: String) -> std::collections::BTreeMap<String, String> {
        let nodes: std::collections::BTreeMap<String, std::collections::BTreeMap<String, String>> = std::collections::BTreeMap::<String, std::collections::BTreeMap<String, String>>::new();
        let parent_of: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
        let mut child_names: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
        for (child_name, parent_name) in parent_of.clone() {
            if closes_cycle(child_name.clone(), parent_name.clone(), parent_of.clone()) {
                continue;
            }
            child_names.insert(child_name.clone());
        }
        std::collections::BTreeMap::from([(String::from("roots"), String::new())])
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn closes_cycle(mut child: String, mut parent: String, mut parent_of: std::collections::BTreeMap<String, String>) -> bool {
    let mut seen: std::collections::BTreeSet<String> = std::collections::BTreeSet::<String>::new();
    let mut cursor: Option<String> = Some(parent.clone());
    let mut _while_guard: usize = 0;
    while (cursor.is_some()) && _while_guard < 10_000 {
        _while_guard += 1;
        if ((cursor.clone()) == Some(child.clone())) || ((seen.clone()).contains(((cursor.clone()).unwrap_or_default()).as_str())) {
            return true;
        }
        seen.insert((cursor.clone()).unwrap_or_default());
        cursor = (parent_of.clone()).get(((cursor.clone()).unwrap_or_default()).as_str()).cloned();
    }
    false
}

pub const PUBLIC_EXPORTS: &[&str] = &["AlertStatusBuilder", "CheckStatusBuilder", "FlameGraphBuilder", "ServiceSummaryBuilder", "SloSummaryBuilder"];
