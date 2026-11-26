use std::collections::BTreeMap;
#[derive(Clone, Debug, Default, PartialEq)]
pub struct AssignmentRevocation {
    pub case_id: String,
    pub revision: i64,
    pub replacement_revisions: BTreeMap<String, i64>,
}

impl AssignmentRevocation {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("case_id"), self.case_id.clone()), (String::from("revision"), String::new()), (String::from("replacement_revisions"), String::new())])
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn from_dict(mut value: std::collections::BTreeMap<String, String>) -> Result<AssignmentRevocation, &'static str> {
        if value.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn case_id(mut value: String) -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn revision(mut value: String) -> Result<(), &'static str> {
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["AssignmentRevocation"];
