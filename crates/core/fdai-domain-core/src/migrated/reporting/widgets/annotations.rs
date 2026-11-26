pub const ALLOWED_IMAGE_SCHEMES: &[&str] = &["https", ""];
pub const VALID_NOTE_SEVERITIES: &[&str] = &["info", "warning", "critical", "ok"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FreeTextBuilder {
    pub initialized: bool,
}

impl FreeTextBuilder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(&self, mut spec: String, mut data: String) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("body"), String::new())])
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct NoteBuilder {
    pub initialized: bool,
}

impl NoteBuilder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(&self, mut spec: String, mut data: String) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("body"), String::new()), (String::from("severity"), String::new())])
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ImageBuilder {
    pub initialized: bool,
}

impl ImageBuilder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(&self, mut spec: String, mut data: String) -> std::collections::BTreeMap<String, String> {
        let extension: String = extension(String::new());
        let mut payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("src"), String::new()), (String::from("alt"), String::new())]);
        payload.clone()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct IframeBuilder {
    pub initialized: bool,
}

impl IframeBuilder {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn build(&self, mut spec: String, mut data: String) -> std::collections::BTreeMap<String, String> {
        let mut payload: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("src"), String::new())]);
        payload.clone()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn extension(mut path: String) -> String {
    if path.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["FreeTextBuilder", "IframeBuilder", "ImageBuilder", "NoteBuilder"];
