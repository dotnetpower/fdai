#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScopedDutySubject {
    pub kind: String,
    pub r#ref: String,
}

impl ScopedDutySubject {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "user" | "group" | "schedule") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScopedDutyDeclaration {
    pub subject: Box<ScopedDutySubject>,
    pub agent_name: String,
    pub scope_ref: String,
    pub duty: String,
    pub effective_from: String,
    pub effective_until: String,
    #[allow(clippy::type_complexity)]
    pub fallback: Option<Box<ScopedDutySubject>>,
}

impl ScopedDutyDeclaration {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.agent_name.as_str(), "Odin" | "Thor" | "Forseti" | "Huginn" | "Heimdall" | "Vidar" | "Var" | "Bragi" | "Saga" | "Mimir" | "Muninn" | "Norns" | "Njord" | "Freyr" | "Loki") { return Err("invalid agent_name literal"); }
        if !matches!(self.duty.as_str(), "primary" | "backup" | "escalation") { return Err("invalid duty literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScopedDutyRequest {
    pub schema_version: String,
    pub source_revision: String,
    pub bindings: Vec<ScopedDutyDeclaration>,
    pub supersedes_case_id: Option<String>,
}

impl ScopedDutyRequest {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        Ok(())
    }
}

impl ScopedDutySubject {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn normalized_reference(mut value: String) -> Result<String, &'static str> {
        if (value.clone()) != (value.to_lowercase()) {
            return Err("scoped subject reference MUST already be normalized");
        }
        Ok(value.clone())
    }
}

impl ScopedDutyDeclaration {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn explicit_time(mut value: String) -> Result<String, &'static str> {
        if !(true) {
            return Err("scoped duty time MUST be explicit offset-aware timestamp text");
        }
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn utc_time(mut value: String) -> Result<String, &'static str> {
        if value.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn bounded_declaration(&self) -> Result<ScopedDutyDeclaration, &'static str> {
        if (self.effective_from.clone()) >= (self.effective_until.clone()) {
            return Err("scoped duty interval MUST be nonempty and half-open");
        }
        Ok(self.clone())
    }
}

impl ScopedDutyRequest {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn nonoverlapping_declarations(&self) -> Result<ScopedDutyRequest, &'static str> {
        Err("runtime_binding_required")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["AgentName", "ExactRef", "ScopedDutyDeclaration", "ScopedDutyRequest", "ScopedDutySubject"];
