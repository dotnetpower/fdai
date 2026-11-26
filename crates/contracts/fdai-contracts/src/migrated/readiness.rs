#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum AdapterReadinessState {
    #[default]
    Ready,
    Unavailable,
}

impl AdapterReadinessState {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Ready => "ready",
            Self::Unavailable => "unavailable",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AdapterReadiness {
    pub adapter: String,
    pub state: AdapterReadinessState,
    pub evidence: String,
    pub live_verified: bool,
    pub reason: Option<String>,
}

impl AdapterReadiness {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.evidence.as_str(), "configuration" | "live") { return Err("invalid evidence literal"); }
        Ok(())
    }
}

impl AdapterReadiness {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn validate_evidence(&self) -> Result<AdapterReadiness, &'static str> {
        if ((self.evidence.clone()) == (String::from("configuration"))) && (self.live_verified) {
            return Err("configuration readiness cannot claim live verification");
        }
        Ok(self.clone())
    }
}

pub trait AdapterReadinessProvider {
    fn readiness(&self) -> String;
}

pub trait AdapterLiveReadinessProvider {
    fn probe_readiness(&self) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn configured_readiness(mut adapter: String) -> AdapterReadiness {
    AdapterReadiness { adapter: adapter.clone(), evidence: String::from("configuration"), live_verified: false, ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn unavailable_readiness(mut adapter: String, mut reason: String) -> AdapterReadiness {
    AdapterReadiness { adapter: adapter.clone(), evidence: String::from("configuration"), live_verified: false, reason: Some(reason.clone()), ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn live_readiness(mut adapter: String) -> AdapterReadiness {
    AdapterReadiness { adapter: adapter.clone(), evidence: String::from("live"), live_verified: true, ..Default::default() }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn live_unavailable_readiness(mut adapter: String, mut reason: String) -> AdapterReadiness {
    AdapterReadiness { adapter: adapter.clone(), evidence: String::from("live"), live_verified: false, reason: Some(reason.clone()), ..Default::default() }
}

