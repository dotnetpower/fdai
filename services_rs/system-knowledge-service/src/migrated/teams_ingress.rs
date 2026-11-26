pub const MAX_BODY_BYTES: i64 = 256000;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct VerifiedKnowledgeTurn {
    pub conversation_id: String,
    pub message_id: String,
    pub sender_id: String,
    pub principal_id: String,
    pub principal_scope_digest: String,
    pub service_url: String,
    pub query: String,
    pub locale: String,
    pub verification_ref: String,
}

impl VerifiedKnowledgeTurn {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.locale.as_str(), "en" | "ko") { return Err("invalid locale literal"); }
        Ok(())
    }
}

impl VerifiedKnowledgeTurn {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn message_key(&self) -> String {
        core::hint::black_box(String::new())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TeamsMentionVerifier {
    pub initialized: bool,
}

impl TeamsMentionVerifier {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn warm(&self) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn parse(&self, mut body: Vec<u8>, mut authorization: String, mut received_at: String) -> Result<Option<VerifiedKnowledgeTurn>, &'static str> {
        if (((body.clone()).len() as i64)) > (MAX_BODY_BYTES) {
            return Err("Teams activity exceeds the configured bound codebody_too_large http_stat");
        }
        let payload: std::collections::BTreeMap<String, String> = decode_teams_activity(body.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let service_url: String = service_url(payload.clone(), String::new(), String::new()).unwrap_or_else(|_| String::new());
        Ok(parse_verified_knowledge_turn(payload.clone(), received_at.clone(), String::new(), None, service_url.clone(), String::new()).unwrap_or_else(|_| None))
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn parse_verified_knowledge_turn(mut payload: std::collections::BTreeMap<String, String>, mut received_at: String, mut settings: String, mut expected_recipient_id: Option<String>, mut service_url: String, mut verification_ref: String) -> Result<Option<VerifiedKnowledgeTurn>, &'static str> {
    if (((payload.clone()).get("type").cloned()) != Some(String::from("message"))) || (((payload.clone()).get("channelId").cloned()) != Some(String::from("msteams"))) {
        return Err("Teams activity type is unsupported codeunsupported_activity http_status4");
    }
    let conversation: std::collections::BTreeMap<String, String> = object(payload.clone(), String::from("conversation")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    if ((conversation.clone()).get("conversationType").cloned()) != Some(String::from("channel")) {
        return Err("Teams conversation type is unsupported codeunsupported_conversation http");
    }
    let channel_data: std::collections::BTreeMap<String, String> = object(payload.clone(), String::from("channelData")).unwrap_or_else(|_| std::collections::BTreeMap::new());
    let mut tenant_ids: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([text(object(channel_data.clone(), String::from("tenant")).unwrap_or_else(|_| std::collections::BTreeMap::new()), String::from("id"), 200_i64).unwrap_or_else(|_| String::new())]);
    let conversation_tenant: Option<String> = (conversation.clone()).get("tenantId").cloned();
    if let Some(mut conversation_tenant) = conversation_tenant.clone() {
        if (!(true)) || ((conversation_tenant.clone()).is_empty()) {
            return Err("Teams conversation tenant is invalid codeinvalid_payload http_status400");
        }
        tenant_ids.insert(conversation_tenant.clone());
    }
    let team_id: String = text(object(channel_data.clone(), String::from("team")).unwrap_or_else(|_| std::collections::BTreeMap::new()), String::from("id"), 256_i64).unwrap_or_else(|_| String::new());
    let channel_id: String = text(object(channel_data.clone(), String::from("channel")).unwrap_or_else(|_| std::collections::BTreeMap::new()), String::from("id"), 256_i64).unwrap_or_else(|_| String::new());
    let recipient_id: String = text(object(payload.clone(), String::from("recipient")).unwrap_or_else(|_| std::collections::BTreeMap::new()), String::from("id"), 256_i64).unwrap_or_else(|_| String::new());
    if (expected_recipient_id.is_some()) && ((recipient_id.clone()) != ((expected_recipient_id.clone()).unwrap_or_default())) {
        return Err("Teams recipient is not the configured bot codeunknown_recipient http_sta");
    }
    let sender_id: String = text(object(payload.clone(), String::from("from")).unwrap_or_else(|_| std::collections::BTreeMap::new()), String::from("aadObjectId"), 200_i64).unwrap_or_else(|_| String::new());
    let mention_texts: Vec<String> = bot_mentions(String::new(), recipient_id.clone()).unwrap_or_else(|_| Vec::new());
    if (mention_texts.clone()).is_empty() {
        return Ok(None);
    }
    let mut query: String = optional_text(payload.clone(), String::from("text"), 16000_i64).unwrap_or_else(|_| String::new());
    for mention_text in mention_texts.clone() {
        query = (query.clone()).replace(mention_text.as_str(), " ");
    }
    Ok(Some(VerifiedKnowledgeTurn { conversation_id: text(conversation.clone(), String::from("id"), 512_i64).unwrap_or_else(|_| String::new()), message_id: text(payload.clone(), String::from("id"), 256_i64).unwrap_or_else(|_| String::new()), sender_id: sender_id.clone(), service_url: service_url.clone(), query: ((query.clone()).split_whitespace().map(str::to_string).collect::<Vec<String>>()).join(" "), locale: if ((optional_text(payload.clone(), String::from("locale"), 32_i64).unwrap_or_else(|_| String::new())).to_lowercase()).starts_with("ko") { String::from("ko") } else { String::from("en") }, verification_ref: verification_ref.clone(), ..Default::default() }))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn decode_teams_activity(mut body: Vec<u8>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    if (((body.clone()).len() as i64)) > (MAX_BODY_BYTES) {
        return Err("Teams activity exceeds the configured bound codebody_too_large http_stat");
    }
    Ok(json_object(body.clone()).unwrap_or_else(|_| std::collections::BTreeMap::new()))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn service_url(mut payload: std::collections::BTreeMap<String, String>, mut token: String, mut settings: String) -> Result<String, &'static str> {
    if payload.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn bot_mentions(mut value: String, mut recipient_id: String) -> Result<Vec<String>, &'static str> {
    if (!(false)) || ((((value.clone()).len() as i64)) > (32_i64)) {
        return Err("Teams mention entities are invalid codeinvalid_payload http_status400");
    }
    let mut mentions: Vec<String> = Vec::<String>::new();
    Ok(Vec::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn json_object(mut body: Vec<u8>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn unique_object(mut pairs: Vec<(String, String)>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut value: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    Ok(value.clone())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn object(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let item: Option<String> = (value.clone()).get(key.as_str()).cloned();
    if !(true) {
        return Err("Teams key is invalid codeinvalid_payload http_status400");
    }
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn text(mut value: std::collections::BTreeMap<String, String>, mut key: String, mut maximum: i64) -> Result<String, &'static str> {
    let item: Option<String> = (value.clone()).get(key.as_str()).cloned();
    Ok((item.clone()).unwrap_or_default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn optional_text(mut value: std::collections::BTreeMap<String, String>, mut key: String, mut maximum: i64) -> Result<String, &'static str> {
    let item: String = (value.clone()).get(key.as_str()).cloned().unwrap_or_else(|| String::from(""));
    if (!(true)) || ((((item.clone()).len() as i64)) > (maximum)) {
        return Err("Teams key is invalid codeinvalid_payload http_status400");
    }
    Ok(item.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["TeamsMentionVerifier", "VerifiedKnowledgeTurn", "decode_teams_activity", "parse_verified_knowledge_turn"];
