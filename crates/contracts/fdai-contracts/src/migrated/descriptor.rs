#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ServiceKind {
    #[default]
    HttpApi,
    EventConsumer,
    ControlPlane,
}

impl ServiceKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::HttpApi => "http-api",
            Self::EventConsumer => "event-consumer",
            Self::ControlPlane => "control-plane",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ServiceDescriptor {
    pub service_id: String,
    pub distribution: String,
    pub image: String,
    pub entrypoint: String,
    pub kind: ServiceKind,
    pub distribution_version: String,
    pub previous_distribution_version: Option<String>,
    pub release_label: String,
    pub contract_set_version: String,
    pub executor_authority: bool,
}

impl ServiceDescriptor {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.service_id.trim().is_empty() { return Err("service_id must be non-empty"); }
        if self.distribution.trim().is_empty() { return Err("distribution must be non-empty"); }
        if self.image.trim().is_empty() { return Err("image must be non-empty"); }
        if self.entrypoint.trim().is_empty() { return Err("entrypoint must be non-empty"); }
        if self.distribution_version.trim().is_empty() { return Err("distribution_version must be non-empty"); }
        if self.contract_set_version.trim().is_empty() { return Err("contract_set_version must be non-empty"); }
        if !matches!(self.release_label.as_str(), "N-1" | "N") { return Err("invalid release_label literal"); }
        if self.service_id == "isolated-executor" && !self.executor_authority { return Err("isolated executor must declare executor authority"); }
        if self.service_id != "isolated-executor" && self.executor_authority { return Err("only isolated executor may declare executor authority"); }
        Ok(())
    }
}

