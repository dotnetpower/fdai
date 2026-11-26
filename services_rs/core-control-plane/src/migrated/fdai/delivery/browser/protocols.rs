#[derive(Clone, Debug, Default, PartialEq)]
pub struct BrowserDriverRequest {
    pub url: String,
    pub stable_selectors: Vec<String>,
    pub sensitive_region_selectors: Vec<String>,
    pub capture_kinds: Vec<String>,
    pub timeout_seconds: f64,
    pub max_response_bytes: i64,
    pub max_screenshot_bytes: i64,
    pub max_text_chars: i64,
    pub max_snapshot_chars: i64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BrowserDriverResult {
    pub final_url: String,
    #[allow(clippy::type_complexity)]
    pub screenshot: Option<Vec<u8>>,
    pub visible_text: Option<String>,
    pub aria_snapshot: Option<String>,
    pub redacted_selectors: Vec<String>,
    pub browser_version: String,
    pub response_bytes: i64,
    pub popup_detected: bool,
    pub download_detected: bool,
    pub file_chooser_detected: bool,
    pub websocket_detected: bool,
}

pub trait BrowserRequestGate {
    fn authorize(&self, method: String, url: String, redirect_from: Option<String>) -> String;
}

pub trait BrowserAuthStateLoader {
    fn load(&self, auth_profile_ref: String) -> String;
}

pub trait BrowserCaptureDriver {
    #[allow(clippy::type_complexity)]
    fn capture(&self, request: BrowserDriverRequest, gate: String, auth_state: Option<std::collections::BTreeMap<String, String>>) -> String;
}

pub const PUBLIC_EXPORTS: &[&str] = &["BrowserAuthStateLoader", "BrowserCaptureDriver", "BrowserDriverRequest", "BrowserDriverResult", "BrowserRequestGate"];
