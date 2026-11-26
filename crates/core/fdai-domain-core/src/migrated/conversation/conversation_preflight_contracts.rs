#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SocialAct {
    #[default]
    None,
    Greeting,
    Acknowledgement,
    Thanks,
    Farewell,
    SelfIntroduction,
}

impl SocialAct {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::None => "none",
            Self::Greeting => "greeting",
            Self::Acknowledgement => "acknowledgement",
            Self::Thanks => "thanks",
            Self::Farewell => "farewell",
            Self::SelfIntroduction => "self_introduction",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OperationalSignal {
    #[default]
    None,
    Explicit,
    Contextual,
    Mixed,
}

impl OperationalSignal {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::None => "none",
            Self::Explicit => "explicit",
            Self::Contextual => "contextual",
            Self::Mixed => "mixed",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ContextDependency {
    #[default]
    None,
    SocialContinuity,
    ActiveThread,
    PendingDecision,
    Ambiguous,
}

impl ContextDependency {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::None => "none",
            Self::SocialContinuity => "social_continuity",
            Self::ActiveThread => "active_thread",
            Self::PendingDecision => "pending_decision",
            Self::Ambiguous => "ambiguous",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum GeneralKnowledgeSignal {
    #[default]
    None,
    Explicit,
}

impl GeneralKnowledgeSignal {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::None => "none",
            Self::Explicit => "explicit",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OperationalPreflightFamily {
    #[default]
    None,
    InventoryDocument,
    ResourceCollection,
    ResourceCurrentState,
    SubscriptionScopeIdentity,
    SubscriptionServiceHealth,
    RecentResourceChanges,
    RecentResourceStateChanges,
    ResourceConfigurationChanges,
    GatewayDiagnosticEvidence,
}

impl OperationalPreflightFamily {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::None => "none",
            Self::InventoryDocument => "inventory_document",
            Self::ResourceCollection => "resource_collection",
            Self::ResourceCurrentState => "resource_current_state",
            Self::SubscriptionScopeIdentity => "subscription_scope_identity",
            Self::SubscriptionServiceHealth => "subscription_service_health",
            Self::RecentResourceChanges => "recent_resource_changes",
            Self::RecentResourceStateChanges => "recent_resource_state_changes",
            Self::ResourceConfigurationChanges => "resource_configuration_changes",
            Self::GatewayDiagnosticEvidence => "gateway_diagnostic_evidence",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum RequestTopic {
    #[default]
    ResourceInventory,
    ResourceDiagnostics,
    ChangeActivity,
    EventHealth,
    Incident,
    OntologySchema,
    GovernedDocuments,
    ActionRequest,
    Conversation,
    GeneralKnowledge,
}

impl RequestTopic {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::ResourceInventory => "resource_inventory",
            Self::ResourceDiagnostics => "resource_diagnostics",
            Self::ChangeActivity => "change_activity",
            Self::EventHealth => "event_health",
            Self::Incident => "incident",
            Self::OntologySchema => "ontology_schema",
            Self::GovernedDocuments => "governed_documents",
            Self::ActionRequest => "action_request",
            Self::Conversation => "conversation",
            Self::GeneralKnowledge => "general_knowledge",
        }
    }
}

#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum OperationalWindowMode {
    #[default]
    None,
    PastHour,
    ServerRecentDefault,
}

impl OperationalWindowMode {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::None => "none",
            Self::PastHour => "past_hour",
            Self::ServerRecentDefault => "server_recent_default",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct GeneralKnowledgeDraft {
    pub locale: String,
    pub answer: String,
    pub profile_digest: String,
    pub execution_authority: bool,
}

impl GeneralKnowledgeDraft {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.locale.as_str(), "en" | "ko") { return Err("invalid locale literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConversationPreflightProposal {
    pub schema_version: String,
    pub social_act: SocialAct,
    pub operational_signal: OperationalSignal,
    pub context_dependency: ContextDependency,
    pub knowledge_signal: GeneralKnowledgeSignal,
    #[allow(clippy::type_complexity)]
    pub general_answer: Option<Box<GeneralKnowledgeDraft>>,
    pub operational_family: OperationalPreflightFamily,
    pub operational_window: OperationalWindowMode,
    pub operational_targets: Vec<String>,
    pub operational_facets: Vec<String>,
    pub operational_result_limit: Option<i64>,
    pub request_topics: Vec<RequestTopic>,
    pub confidence: f64,
    pub authority: String,
    pub execution_authority: bool,
}

impl ConversationPreflightProposal {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.authority.as_str(), "candidate_only") { return Err("invalid authority literal"); }
        if self.execution_authority { return Err("execution_authority violated literal bool invariant"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConversationPreflightBinding {
    pub model: String,
    pub model_config_digest: String,
    pub prompt_digest: String,
    pub supports_cancellation: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SocialResponseNarratorBinding {
    pub model: String,
    pub model_config_digest: String,
    pub prompt_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConversationPreflightResult {
    #[allow(clippy::type_complexity)]
    pub proposal: Option<Box<ConversationPreflightProposal>>,
    pub observations: Vec<String>,
    pub attempted: bool,
    pub failure_kind: Option<String>,
    pub input_digest: Option<String>,
    pub proposal_digest: Option<String>,
    pub model_config_digest: Option<String>,
    pub prompt_digest: Option<String>,
    pub direct_response_profile_digest: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SocialResponseNarratorResult {
    pub draft: Option<String>,
    pub observations: Vec<String>,
    pub attempted: bool,
}

impl GeneralKnowledgeDraft {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn answer_is_usable(&self) -> Result<GeneralKnowledgeDraft, &'static str> {
        if (self.answer.clone()) != ((self.answer.clone()).trim().to_string()) {
            return Err("general knowledge answer MUST be trimmed");
        }
        Ok(self.clone())
    }
}

impl ConversationPreflightProposal {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn discard_generic_collection_filter_targets(mut value: String) -> String {
        if value.is_empty() {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn route_is_consistent(&self) -> Result<ConversationPreflightProposal, &'static str> {
        if (((self.operational_facets.clone()).len() as i64)) != ((((self.operational_facets.clone()).into_iter().collect::<std::collections::BTreeSet<String>>()).len() as i64)) {
            return Err("operational preflight facets MUST be unique");
        }
        Ok(self.clone())
    }
}

pub trait ConversationPreflightModel {
    #[allow(clippy::type_complexity)]
    fn preflight(&self, utterance: String, context: Vec<String>, locale: String, direct_response_profile: std::collections::BTreeMap<String, String>, direct_response_profile_digest: String, schema_repair: Vec<std::collections::BTreeMap<String, String>>) -> String;
}

pub trait CancellableConversationPreflightModel {
    #[allow(clippy::type_complexity)]
    #[allow(clippy::too_many_arguments)]
    fn preflight(&self, utterance: String, context: Vec<String>, locale: String, direct_response_profile: std::collections::BTreeMap<String, String>, direct_response_profile_digest: String, schema_repair: Vec<std::collections::BTreeMap<String, String>>, cancelled: Option<String>) -> String;
}

pub trait SocialResponseNarratorModel {
    fn narrate_social(&self, utterance: String, locale: String, social_act: String, continued: bool, direct_response_profile: std::collections::BTreeMap<String, String>, direct_response_profile_digest: String) -> String;
}

