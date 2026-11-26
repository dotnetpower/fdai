#[derive(Clone, Debug, Default, PartialEq)]
pub struct OnCallResolution {
    pub rotation: String,
    pub primary_oid: Option<String>,
    pub secondary_oid: Option<String>,
    pub from_schedule: bool,
    pub fallback_reason: Option<String>,
}

impl OnCallResolution {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.rotation.trim().is_empty() { return Err("rotation must be non-empty"); }
        Ok(())
    }
}

impl OnCallResolution {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn has_responder(&self) -> bool {
        self.primary_oid.is_some()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct OnCallResolver {
    pub initialized: bool,
}

impl OnCallResolver {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn resolve(&self, mut rotation: String, mut at: String) -> Result<OnCallResolution, &'static str> {
        if (rotation.trim().to_string()).is_empty() {
            return Err("OnCallResolver.rotation MUST be non-empty");
        }
        Ok(OnCallResolution { rotation: rotation.clone(), from_schedule: true, fallback_reason: None, ..Default::default() })
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["OnCallResolution", "OnCallResolver"];
