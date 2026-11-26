use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ProbeCategory {
    #[default]
    PolicyGuardrail,
    SupplyChainEgress,
    IdentityRbac,
    QuotaCapacity,
    DependencyOrdering,
    SecretConfig,
}

impl ProbeCategory {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::PolicyGuardrail => "policy_guardrail",
            Self::SupplyChainEgress => "supply_chain_egress",
            Self::IdentityRbac => "identity_rbac",
            Self::QuotaCapacity => "quota_capacity",
            Self::DependencyOrdering => "dependency_ordering",
            Self::SecretConfig => "secret_config",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum FindingSeverity {
    #[default]
    Blocking,
    Warning,
}

impl FindingSeverity {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Blocking => "blocking",
            Self::Warning => "warning",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ResolutionKind {
    #[default]
    TerraformToggle,
    RoleAssignment,
    Manual,
    None,
}

impl ResolutionKind {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::TerraformToggle => "terraform_toggle",
            Self::RoleAssignment => "role_assignment",
            Self::Manual => "manual",
            Self::None => "none",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProbeEvidence {
    pub source: String,
    pub detail: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProbeResolution {
    pub kind: ResolutionKind,
    pub autofix: bool,
    pub module: Option<String>,
    pub set_vars: BTreeMap<String, String>,
    pub guidance: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ProbeFinding {
    pub id: String,
    pub category: ProbeCategory,
    pub severity: FindingSeverity,
    pub title: String,
    pub evidence: Box<ProbeEvidence>,
    pub resolution: Box<ProbeResolution>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PreflightTarget {
    pub scope: String,
    pub resource_types: Vec<String>,
    pub egress_hosts: Vec<String>,
    pub required_links: Vec<String>,
}

impl ProbeFinding {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("id"), self.id.clone()), (String::from("category"), String::new()), (String::from("severity"), String::new()), (String::from("title"), self.title.clone()), (String::from("evidence"), String::new()), (String::from("resolution"), String::new())])
    }
}

pub trait FeasibilityProbe {
    fn category(&self) -> ProbeCategory;
    fn evaluate(&self, target: PreflightTarget) -> Vec<ProbeFinding>;
}

