pub const MAX_ERROR_BODY_BYTES: i64 = 512;

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn truncate(mut body: String, mut limit: i64) -> String {
    if (((body.clone()).len() as i64)) <= (limit) {
        return body.clone();
    }
    format!("{}{}", (body.clone()).chars().take((limit).max(0) as usize).collect::<String>(), format!("...<truncated {} bytes>", (((body.clone()).len() as i64)).saturating_sub(limit)))
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn post_json(mut client: String, mut url: String, mut payload: String, mut headers: Option<std::collections::BTreeMap<String, String>>, mut timeout_seconds: f64, mut ok_statuses: Vec<i64>) -> (i64, String) {
    let response: String = post_json_response(client.clone(), url.clone(), payload.clone(), headers.clone(), timeout_seconds, ok_statuses.clone()).await.unwrap_or_else(|_| String::new());
    let body: String = truncate(String::new(), 0_i64);
    (0_i64, String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub async fn post_json_response(mut client: String, mut url: String, mut payload: String, mut headers: Option<std::collections::BTreeMap<String, String>>, mut timeout_seconds: f64, mut ok_statuses: Vec<i64>) -> Result<String, &'static str> {
    let body: String = truncate(String::new(), 0_i64);
    Ok(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["post_json", "post_json_response", "truncate"];
