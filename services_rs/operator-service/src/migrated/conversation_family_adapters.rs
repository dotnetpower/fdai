#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresConversationAdapters {
    pub store: String,
    pub test_context_choices: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ConversationEventIterator {
    pub initialized: bool,
}

impl ConversationEventIterator {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn dunder_aiter(&self) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn dunder_anext(&self) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn aclose(&self) {
        if !self.initialized {
            return;
        }
    }
}

impl PostgresConversationAdapters {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read(&self, mut query: String) -> Result<String, &'static str> {
        if query.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn append(&self, mut proposal: String) -> Result<String, &'static str> {
        if proposal.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn open(&self, mut request: String) -> Result<String, &'static str> {
        if request.is_empty() {
            return Err("missing_required_input");
        }
        Err("runtime_binding_required")
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct UnavailableConversationAdapters {
    pub initialized: bool,
}

impl UnavailableConversationAdapters {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read(&self, mut query: String) -> Result<String, &'static str> {
        Err("authoritative conversation projection is unavailable")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn append(&self, mut proposal: String) -> Result<String, &'static str> {
        Err("conversation proposal outbox is unavailable")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn open(&self, mut request: String) -> Result<String, &'static str> {
        Err("conversation event stream is unavailable")
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["PostgresConversationAdapters", "UnavailableConversationAdapters"];
