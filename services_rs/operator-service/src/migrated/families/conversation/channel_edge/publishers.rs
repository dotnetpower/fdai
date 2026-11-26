#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChannelAccessToken {
    pub token: String,
    pub audience: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SlackPublisherConfig {
    pub bot_token: String,
    pub timeout_seconds: f64,
    pub max_response_bytes: i64,
    pub max_request_bytes: i64,
}

pub const SLACK_POST_URL: &str = "https://slack.com/api/chat.postMessage";
pub const SLACK_UPDATE_URL: &str = "https://slack.com/api/chat.update";
pub const TEAMS_BOT_SCOPE: &str = "https://api.botframework.com/.default";
pub const SLACK_RESERVED_KEYS: &[&str] = &["channel", "ts", "thread_ts"];
pub trait ChannelTokenProvider {
    fn get_token(&self, audience: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SlackResponsePublisher {
    pub initialized: bool,
}

impl SlackResponsePublisher {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn send(&self, mut message: String) -> Result<String, &'static str> {
        let acknowledgement: std::collections::BTreeMap<String, String> = acknowledgement(Vec::new(), String::from("Slack")).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let message_id: Option<String> = (acknowledgement.clone()).get("ts").cloned();
        Ok(String::new())
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TeamsResponsePublisher {
    pub initialized: bool,
}

impl TeamsResponsePublisher {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn send(&self, mut message: String) -> Result<String, &'static str> {
        let acknowledgement: std::collections::BTreeMap<String, String> = acknowledgement(Vec::new(), String::from("Teams")).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let message_id: Option<String> = (acknowledgement.clone()).get("id").cloned();
        Ok(String::new())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn bounded_body(mut chunks: Vec<Vec<u8>>, mut maximum: i64, mut provider: String) -> Result<Vec<u8>, &'static str> {
    if chunks.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn acknowledgement(mut body: Vec<u8>, mut provider: String) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    Ok(std::collections::BTreeMap::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn unique_object(mut pairs: Vec<(String, String)>) -> Result<std::collections::BTreeMap<String, String>, &'static str> {
    let mut value: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::<String, String>::new();
    Ok(value.clone())
}

pub const PUBLIC_EXPORTS: &[&str] = &["ChannelAccessToken", "ChannelTokenProvider", "SlackPublisherConfig", "SlackResponsePublisher", "TEAMS_BOT_SCOPE", "TeamsResponsePublisher"];
