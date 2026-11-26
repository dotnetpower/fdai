#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChannelAccessToken {
    pub token: String,
    pub audience: String,
}

pub const BOT_SCOPE: &str = "https://api.botframework.com/.default";
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TeamsPublishError {
    pub message: String,
}

impl TeamsPublishError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for TeamsPublishError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for TeamsPublishError {}

pub trait ChannelTokenProvider {
    fn get_token(&self, audience: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureChannelTokenProvider {
    pub initialized: bool,
}

impl AzureChannelTokenProvider {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn get_token(&self, mut audience: String) -> Result<ChannelAccessToken, &'static str> {
        Ok(ChannelAccessToken { audience: audience.clone(), ..Default::default() })
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn aclose(&self) {
        if !self.initialized {
            return;
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TeamsPublisher {
    pub initialized: bool,
}

impl TeamsPublisher {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn send(&self, mut conversation_id: String, mut service_url: String, mut payload: std::collections::BTreeMap<String, String>) -> Result<String, &'static str> {
        let acknowledgement: std::collections::BTreeMap<String, String> = json_object(Vec::new()).unwrap_or_else(|_| std::collections::BTreeMap::new());
        let activity_id: Option<String> = (acknowledgement.clone()).get("id").cloned();
        Ok((activity_id.clone()).unwrap_or_default())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn aclose(&self) {
        if !self.initialized {
            return;
        }
    }
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
pub async fn bounded_body(mut chunks: Vec<Vec<u8>>, mut maximum: i64) -> Result<Vec<u8>, &'static str> {
    if chunks.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["AzureChannelTokenProvider", "ChannelAccessToken", "ChannelTokenProvider", "TeamsPublishError", "TeamsPublisher"];
