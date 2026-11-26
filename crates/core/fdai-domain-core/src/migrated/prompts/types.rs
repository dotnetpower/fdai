use std::collections::BTreeMap;
pub const MAX_AGENT_CHARS: i64 = 128;
pub const MAX_QUERY_CHARS: i64 = 4096;
pub const MAX_TOOL_ID_CHARS: i64 = 128;
pub const MAX_SKILL_NAME_CHARS: i64 = 128;
pub const MAX_REFERENCE_PATH_CHARS: i64 = 255;
pub const MAX_SELECTED_SKILLS: i64 = 4;
pub const MAX_SELECTED_BUNDLES: i64 = 2;
pub const MAX_INDEX_BUDGET_CHARS: i64 = 32768;
pub const MAX_BODY_BUDGET_CHARS: i64 = 262144;
pub const MAX_REFERENCE_BUDGET_BYTES: i64 = 262144;
pub const MAX_ASSEMBLY_KEYS: i64 = 128;

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PromptLayer {
    #[default]
    Base,
    Pack,
    Critic,
    Judge,
    Rubric,
    Tool,
    RoleHeader,
    OperatorMemory,
    SkillIndex,
    SkillBody,
    SkillReference,
    SkillBundle,
    Recovery,
    AdapterSchema,
}

impl PromptLayer {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Base => "base",
            Self::Pack => "pack",
            Self::Critic => "critic",
            Self::Judge => "judge",
            Self::Rubric => "rubric",
            Self::Tool => "tool",
            Self::RoleHeader => "role-header",
            Self::OperatorMemory => "operator-memory",
            Self::SkillIndex => "skill-index",
            Self::SkillBody => "skill-body",
            Self::SkillReference => "skill-reference",
            Self::SkillBundle => "skill-bundle",
            Self::Recovery => "recovery",
            Self::AdapterSchema => "adapter-schema",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PromptMode {
    #[default]
    Shadow,
    Enforce,
}

impl PromptMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Shadow => "shadow",
            Self::Enforce => "enforce",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PromptAblationProfileName {
    #[default]
    None,
    Packs,
    Tools,
    OperatorMemory,
    Skills,
    OptionalContext,
}

impl PromptAblationProfileName {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::None => "none",
            Self::Packs => "packs",
            Self::Tools => "tools",
            Self::OperatorMemory => "operator-memory",
            Self::Skills => "skills",
            Self::OptionalContext => "optional-context",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PromptAssemblyMode {
    #[default]
    Selected,
    Complete,
}

impl PromptAssemblyMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Selected => "selected",
            Self::Complete => "complete",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SkillSelectionStatus {
    #[default]
    Selected,
    Rejected,
}

impl SkillSelectionStatus {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Selected => "selected",
            Self::Rejected => "rejected",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PromptAblationProfile {
    pub name: PromptAblationProfileName,
    pub disabled_layers: Vec<PromptLayer>,
    pub disabled_artifact_ids: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PromptArtifact {
    pub id: String,
    pub version: i64,
    pub layer: PromptLayer,
    pub body: String,
    pub applies_to: Vec<String>,
    pub token_budget: Option<i64>,
    pub default_mode: PromptMode,
    pub provenance_source: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct LayerRef {
    pub id: String,
    pub version: i64,
    pub layer: PromptLayer,
    pub token_estimate: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AblatedLayerRef {
    pub id: String,
    pub version: i64,
    pub layer: PromptLayer,
    pub reason: String,
}

impl AblatedLayerRef {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.reason.as_str(), "profile_layer" | "profile_artifact") { return Err("invalid reason literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PromptAssemblyReceipt {
    pub mode: PromptAssemblyMode,
    pub keys: Vec<String>,
    pub unselected_layers: Vec<LayerRef>,
    pub covered_keys: Vec<String>,
    pub governed_keys: Vec<String>,
    pub digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SkillDisclosureRequest {
    pub agent: String,
    pub available_tools: Vec<String>,
    pub query: String,
    pub selected_skill_names: Vec<String>,
    pub selected_bundle_names: Vec<String>,
    pub reference_selection: Option<String>,
    pub index_budget_chars: i64,
    pub body_budget_chars: i64,
    pub reference_budget_bytes: i64,
}

impl SkillDisclosureRequest {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.agent.trim().is_empty() { return Err("agent must be non-empty"); }
        if self.query.trim().is_empty() { return Err("query must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SkillReplayRecord {
    pub operation: String,
    pub name: String,
    pub version: Option<String>,
    pub raw_markdown_sha256: Option<String>,
    pub body_sha256: Option<String>,
    pub reference_path: Option<String>,
    pub reference_sha256: Option<String>,
    pub status: SkillSelectionStatus,
    pub rejection_reason: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SkillBundleMemberReplayRecord {
    pub name: String,
    pub version: String,
    pub raw_markdown_sha256: String,
    pub body_sha256: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SkillBundleReplayRecord {
    pub operation: String,
    pub name: String,
    pub version: Option<String>,
    pub manifest_sha256: Option<String>,
    pub digest: Option<String>,
    pub members: Vec<SkillBundleMemberReplayRecord>,
    pub status: SkillSelectionStatus,
    pub rejection_reason: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PromptReplayManifest {
    pub system_text_sha256: String,
    pub layer_manifest: Vec<LayerRef>,
    pub token_estimate: i64,
    pub profile_id: Option<String>,
    pub profile_version: Option<i64>,
    pub profile_digest: Option<String>,
    pub system_token_budget: Option<i64>,
    pub request_token_budget: Option<i64>,
    pub reserved_output_tokens: Option<i64>,
    pub ablation_profile: PromptAblationProfileName,
    pub ablated_layers: Vec<AblatedLayerRef>,
    pub canary_tokens: Vec<String>,
    pub skill_records: Vec<SkillReplayRecord>,
    pub skill_bundle_records: Vec<SkillBundleReplayRecord>,
    #[allow(clippy::type_complexity)]
    pub assembly: Option<Box<PromptAssemblyReceipt>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PromptProfileEvidence {
    pub profile_id: String,
    pub profile_version: i64,
    pub profile_digest: String,
    pub system_text_sha256: String,
    pub system_token_budget: i64,
    pub request_token_budget: i64,
    pub reserved_output_tokens: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ComposedPrompt {
    pub system_text: String,
    pub layer_manifest: Vec<LayerRef>,
    pub token_estimate: i64,
    pub profile_id: Option<String>,
    pub profile_version: Option<i64>,
    pub profile_digest: Option<String>,
    pub system_token_budget: Option<i64>,
    pub request_token_budget: Option<i64>,
    pub reserved_output_tokens: Option<i64>,
    pub ablation_profile: PromptAblationProfileName,
    pub ablated_layers: Vec<AblatedLayerRef>,
    pub canary_tokens: BTreeMap<String, String>,
    pub skill_records: Vec<SkillReplayRecord>,
    pub skill_bundle_records: Vec<SkillBundleReplayRecord>,
    #[allow(clippy::type_complexity)]
    pub assembly: Option<Box<PromptAssemblyReceipt>>,
}

pub const PROMPT_COMPONENT_ID: &str = "^[a-z0-9][a-z0-9.\\-:]{0,127}$";
pub const PROMPT_LAYER_ID: &str = "^[a-z0-9][a-z0-9._/\\-:]{0,511}$";
pub const SHA256_DIGEST: &str = "^sha256:[a-f0-9]{64}$";
pub const ASSEMBLY_KEY: &str = "^(topic|intent|shape|posture|document):[a-z0-9][a-z0-9_.\\-]{0,127}$";
impl PromptAblationProfile {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn reviewed(mut name: String) -> PromptAblationProfile {
        if name.is_empty() {
            return Default::default();
        }
        Default::default()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn disables(&self, mut layer: PromptLayer, mut artifact_id: String) -> Result<bool, &'static str> {
        Ok(false)
    }
}

impl PromptArtifact {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn matches(&self, mut capability_id: String) -> bool {
        if (self.applies_to.clone()).is_empty() {
            return true;
        }
        (self.applies_to.clone()).contains(&(capability_id.clone()))
    }
}

impl PromptAssemblyReceipt {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn uncovered(&self, mut result_keys: Vec<String>) -> Vec<String> {
        let covered: std::collections::BTreeSet<String> = (self.covered_keys.clone()).into_iter().collect::<std::collections::BTreeSet<String>>();
        let governed: std::collections::BTreeSet<String> = (self.governed_keys.clone()).into_iter().collect::<std::collections::BTreeSet<String>>();
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn trace_projection(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("mode"), String::new()), (String::from("keys"), String::new()), (String::from("unselected_layers"), String::new()), (String::from("digest"), self.digest.clone())])
    }
}

impl PromptReplayManifest {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn trace_projection(&self) -> std::collections::BTreeMap<String, String> {
        let mut projection: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("system_text_sha256"), self.system_text_sha256.clone()), (String::from("layers"), String::new()), (String::from("token_estimate"), String::new()), (String::from("profile_id"), (self.profile_id.clone()).unwrap_or_default()), (String::from("profile_version"), String::new()), (String::from("profile_digest"), (self.profile_digest.clone()).unwrap_or_default()), (String::from("system_token_budget"), String::new()), (String::from("request_token_budget"), String::new()), (String::from("reserved_output_tokens"), String::new())]);
        projection.clone()
    }
}

impl PromptProfileEvidence {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn from_manifest(mut manifest: PromptReplayManifest) -> Result<PromptProfileEvidence, &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn to_dict(&self) -> std::collections::BTreeMap<String, String> {
        std::collections::BTreeMap::from([(String::from("profile_id"), self.profile_id.clone()), (String::from("profile_version"), String::new()), (String::from("profile_digest"), self.profile_digest.clone()), (String::from("system_text_sha256"), self.system_text_sha256.clone()), (String::from("system_token_budget"), String::new()), (String::from("request_token_budget"), String::new()), (String::from("reserved_output_tokens"), String::new())])
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn from_mapping(mut value: std::collections::BTreeMap<String, String>) -> PromptProfileEvidence {
        if value.is_empty() {
            return Default::default();
        }
        Default::default()
    }
}

impl ComposedPrompt {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn replay_manifest(&self) -> PromptReplayManifest {
        PromptReplayManifest { layer_manifest: self.layer_manifest.clone(), token_estimate: self.token_estimate, profile_id: self.profile_id.clone(), profile_version: self.profile_version.clone(), profile_digest: self.profile_digest.clone(), system_token_budget: self.system_token_budget.clone(), request_token_budget: self.request_token_budget.clone(), reserved_output_tokens: self.reserved_output_tokens.clone(), ablation_profile: self.ablation_profile.clone(), ablated_layers: self.ablated_layers.clone(), skill_records: self.skill_records.clone(), skill_bundle_records: self.skill_bundle_records.clone(), assembly: (self.assembly.clone().map(|_b| *_b)).map(Box::new), ..Default::default() }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_assembly_keys(mut keys: Vec<String>, mut name: String) -> Result<(), &'static str> {
    if (!(true)) || ((((keys.clone()).len() as i64)) > (MAX_ASSEMBLY_KEYS)) {
        return Err("prompt assembly name MUST be a bounded tuple");
    }
    if ((((keys.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) != (((keys.clone()).len() as i64)) {
        return Err("prompt assembly name MUST be unique");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_budget(mut name: String, mut value: i64, mut maximum: i64) -> Result<(), &'static str> {
    if (!(true)) || ((false) || (!(((1_i64) <= (value)) && ((value) <= (maximum))))) {
        return Err("skill disclosure name MUST be between 1 and maximum");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn validate_profile_replay_fields(mut profile_id: Option<String>, mut profile_version: Option<i64>, mut profile_digest: Option<String>, mut system_token_budget: Option<i64>, mut request_token_budget: Option<i64>, mut reserved_output_tokens: Option<i64>) -> Result<(), &'static str> {
    if profile_id.is_none() {
        return Ok(());
    }
    if (!(true)) || (true) {
        return Err("prompt replay profile version MUST be an integer");
    }
    Ok(())
}

pub const PUBLIC_EXPORTS: &[&str] = &["AblatedLayerRef", "ComposedPrompt", "LayerRef", "PromptAssemblyMode", "PromptAssemblyReceipt", "validate_assembly_keys", "PromptProfileEvidence", "PromptReplayManifest", "PromptArtifact", "PromptAblationProfile", "PromptAblationProfileName", "PromptLayer", "PromptMode", "SkillDisclosureRequest", "SkillBundleMemberReplayRecord", "SkillBundleReplayRecord", "SkillReplayRecord", "SkillSelectionStatus"];
