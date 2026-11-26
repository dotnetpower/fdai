pub const EXIT_OK: i64 = 0;
pub const EXIT_LOCAL_FAILURE: i64 = 2;
pub const EXIT_HUB_REFUSED: i64 = 3;
pub const EXIT_UNCERTAIN: i64 = 4;

pub const MAX_TIMEOUT_SECONDS: f64 = 60.0;
pub trait EnrollmentSubmitter {
    fn submit_enrollment_request(&self, installation_id: String, signed_payload: Vec<u8>, proof: Vec<u8>) -> String;
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn register_enroll_command(mut commands: String) {
    if commands.is_empty() {
        return;
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn connect_workload_identity_hub(mut url: String, mut scope: String, mut timeout_seconds: f64) -> Vec<String> {
    if url.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn connect_in_cluster_source(mut namespace: String) -> String {
    if namespace.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn run_enroll(mut arguments: String, mut clock: String, mut connect_source: String, mut connect_hub: String) -> Result<i64, &'static str> {
    Ok(EXIT_OK)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn hub_failure(mut error: String) -> i64 {
    EXIT_UNCERTAIN
}

