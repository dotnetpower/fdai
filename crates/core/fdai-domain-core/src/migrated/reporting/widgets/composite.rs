pub const GROUP_LIKE_WIDGET_TYPES: &[&str] = &["group", "tabs"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SplitGraphBuilder {
    pub initialized: bool,
}

impl SplitGraphBuilder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(&self, mut spec: String, mut data: String) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("panels"), String::new())])
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["GROUP_LIKE_WIDGET_TYPES", "SplitGraphBuilder"];
