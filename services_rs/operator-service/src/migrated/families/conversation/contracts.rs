pub const MAX_IDENTIFIER_CHARS: i64 = 256;
pub const MAX_OPERATION_CHARS: i64 = 128;
pub const MAX_ROLES: i64 = 16;
pub const MAX_BODY_BYTES: i64 = 1048576;
pub const MAX_QUERY_BYTES: i64 = 8192;
pub const MAX_RESPONSE_BYTES: i64 = 16777216;
pub const MAX_STREAM_EVENT_BYTES: i64 = 262144;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PrincipalScope {
    pub subject_id: String,
    pub roles: Vec<String>,
    pub principal_kind: String,
    pub groups: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ActionConfirmationBody {
    pub action_type: String,
    pub arguments: String,
    pub session_id: Option<String>,
    pub idempotency_key: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConversationQuery {
    pub operation: String,
    pub scope: Box<PrincipalScope>,
    pub query: String,
    pub path_params: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConversationProposal {
    pub operation: String,
    pub scope: Box<PrincipalScope>,
    pub idempotency_key: String,
    pub body: String,
    pub query: String,
    pub path_params: String,
    pub confirmed: bool,
    pub cancellation: bool,
    pub authentication_receipt: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConversationResponse {
    pub body: Option<String>,
    pub status_code: i64,
    pub media_type: String,
    pub headers: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct OutboxReceipt {
    pub proposal_id: String,
    pub duplicate: bool,
    pub response: Box<ConversationResponse>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ConversationStreamRequest {
    pub operation: String,
    pub scope: Box<PrincipalScope>,
    pub body: String,
    pub query: String,
    pub path_params: String,
    pub after_event_id: Option<String>,
    pub idempotency_key: Option<String>,
    pub proposal_id: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StreamEvent {
    pub event: Option<String>,
    pub data: String,
    pub event_id: Option<String>,
    pub retry_ms: Option<i64>,
}

pub trait ConversationAuthorizer {
    fn authorize(&self, request: String, operation: String) -> String;
}

pub trait ConversationReceiptAuthorizer {
    fn authorize_with_receipt(&self, request: String, operation: String) -> String;
}

pub trait ConversationProjectionReader {
    fn read(&self, query: ConversationQuery) -> String;
}

pub trait ConversationProposalOutbox {
    fn append(&self, proposal: ConversationProposal) -> String;
}

pub trait ConversationEventStream {
    fn dunder_aiter(&self) -> String;
}

pub trait ConversationStreamReader {
    fn open(&self, request: ConversationStreamRequest) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ConversationBoundaryError {
    pub message: String,
}

impl ConversationBoundaryError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ConversationBoundaryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ConversationBoundaryError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ConversationUnavailableError {
    pub message: String,
}

impl ConversationUnavailableError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for ConversationUnavailableError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ConversationUnavailableError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn bounded_text(mut name: String, mut value: String, mut maximum: i64, mut allow_empty: bool) -> Result<(), &'static str> {
    let invalid: bool = (!(true)) || ((!(allow_empty)) && (((value.clone()).trim().to_string()).is_empty()));
    if (invalid) || ((((value.clone()).len() as i64)) > (maximum)) {
        let qualifier: String = if allow_empty { String::from("bounded") } else { String::from("non-empty bounded") };
        return Err("name MUST be a qualifier string");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn single_line(mut name: String, mut value: String, mut maximum: i64) -> Result<(), &'static str> {
    let _ = bounded_text(name.clone(), value.clone(), maximum, false).unwrap_or_else(|_| ());
    if ((value.clone()).contains("\r")) || ((value.clone()).contains("\n")) {
        return Err("name MUST be a single line");
    }
    Ok(())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn bounded_json(mut name: String, mut value: String, mut maximum: i64) -> Result<(), &'static str> {
    if name.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["ConversationAuthorizer", "ConversationBoundaryError", "ConversationEventStream", "ConversationProjectionReader", "ConversationProposal", "ConversationProposalOutbox", "ConversationQuery", "ConversationResponse", "ConversationStreamReader", "ConversationStreamRequest", "ConversationUnavailableError", "JsonObject", "JsonValue", "OutboxReceipt", "PrincipalScope", "StreamEvent"];
