#[derive(Clone, Debug, Default, PartialEq)]
pub struct AssignmentWorkflowBindings {
    pub validate: String,
    pub review: String,
    pub materializer: String,
    pub clock: String,
    pub iam_reader: Option<String>,
    pub knowledge_stages: Vec<String>,
    pub semantic_compiler: Option<String>,
    pub semantic_reviewer: Option<String>,
    pub human_access: Option<String>,
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn bind_assignment_workflow(mut agents: std::collections::BTreeMap<String, String>, mut bindings: Option<AssignmentWorkflowBindings>) -> Result<(), &'static str> {
    let Some(mut bindings) = bindings.clone() else { return Ok(()); };
    if ((bindings.semantic_compiler.clone()).is_none()) != ((bindings.semantic_reviewer.clone()).is_none()) {
        return Err("handover semantics requires separate compiler and reviewer bindings");
    }
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["AssignmentWorkflowBindings", "bind_assignment_workflow"];
