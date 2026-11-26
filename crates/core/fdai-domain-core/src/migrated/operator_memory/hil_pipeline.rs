use std::collections::BTreeMap;
pub const DEFAULT_SECOND_APPROVAL_WINDOW_SECONDS: i64 = 3600;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct HilRejectMaterial {
    pub scope_kind: String,
    pub scope_ref: String,
    pub category: String,
    pub source_ref: String,
    pub ttl_seconds: Option<i64>,
    pub approval_window_seconds: i64,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct HilMaterializationError {
    pub message: String,
}

impl HilMaterializationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for HilMaterializationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for HilMaterializationError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct HilRejectMaterializer {
    pub initialized: bool,
}

impl HilRejectMaterializer {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn materialize(&self, mut hil_response: String, mut second_approver: String, mut material: HilRejectMaterial) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn entry_id(&self, mut hil_response: String, mut second_approver: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn reject_stale_approval(&self, mut hil_response: String, mut material: HilRejectMaterial) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn now(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn reject_pipeline_violations(mut hil_response: String, mut second_approver: String) -> Result<(), &'static str> {
        if ((second_approver.clone()).is_empty()) || (((second_approver.clone()).trim().to_string()).is_empty()) {
            return Err("missing_second_approver second_approver MUST be a non-empty principal");
        }
        Ok(())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn normalize(mut principal: String) -> String {
    (principal.trim().to_string()).to_lowercase()
}

pub const PUBLIC_EXPORTS: &[&str] = &["DEFAULT_SECOND_APPROVAL_WINDOW_SECONDS", "HilMaterializationError", "HilRejectMaterial", "HilRejectMaterializer"];
