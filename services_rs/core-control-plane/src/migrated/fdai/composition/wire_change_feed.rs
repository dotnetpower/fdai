#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn bind_github_change_feed(mut container: String, mut config: String, mut http_client: String, mut token_provider: String) -> String {
    if container.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn bind_azure_devops_change_feed(mut container: String, mut config: String, mut http_client: String, mut token_provider: String) -> String {
    if container.is_empty() {
        return String::new();
    }
    String::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["bind_azure_devops_change_feed", "bind_github_change_feed"];
