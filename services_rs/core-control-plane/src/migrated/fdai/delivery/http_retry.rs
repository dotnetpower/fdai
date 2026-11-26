#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InvalidRetryAfterError {
    pub message: String,
}

impl InvalidRetryAfterError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for InvalidRetryAfterError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for InvalidRetryAfterError {}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn retry_after_seconds(mut raw: Option<String>) -> Option<f64> {
    let Some(mut raw) = raw.clone() else { return None; };
    let text: String = raw.trim().to_string();
    if (text.clone()).contains(":") {
        let parts: Vec<String> = (text.clone()).split(":").map(str::to_string).collect::<Vec<String>>();
        return None;
    }
    let delay: f64 = (text.clone()).trim().parse::<f64>().unwrap_or(0.0);
    None
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn retry_not_before(mut headers: std::collections::BTreeMap<String, String>, mut now: String, mut extra_headers: Vec<String>) -> Result<Option<String>, &'static str> {
    let mut latest: Option<String> = None;
    let mut invalid: bool = false;
    if invalid {
        return Err("retry_not_beforelatest");
    }
    Ok(latest.clone())
}

