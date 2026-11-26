#[derive(Clone, Debug, Default, PartialEq)]
pub struct GitHubKnowledgeSource {
    pub credential_reference: String,
    pub knowledge_read_enabled: bool,
    pub repository_id: i64,
    pub private: bool,
    pub observed_commit: String,
    pub readme_digest: String,
    pub observed_at: String,
    pub request_id: String,
}

impl GitHubKnowledgeSource {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.credential_reference.as_str(), "public" | "deployment-github-app") { return Err("invalid credential_reference literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct GitHubKnowledgeChangeBody {
    pub action: String,
    pub repository_alias: String,
    pub expected_revision: i64,
    pub location: Option<String>,
    pub credential_reference: Option<String>,
}

impl GitHubKnowledgeChangeBody {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.action.as_str(), "connect" | "disconnect") { return Err("invalid action literal"); }
        Ok(())
    }
}

pub const ALIAS_PATTERN: &str = "^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$";
pub const LOCATION_PATTERN: &str = "^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$";
impl GitHubKnowledgeSource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn aware_time(mut value: String) -> Result<String, &'static str> {
        Ok(value.clone())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn public_scope(&self) -> Result<GitHubKnowledgeSource, &'static str> {
        if ((self.credential_reference.clone()) == (String::from("public"))) && (self.private) {
            return Err("anonymous access cannot verify a private repository");
        }
        Ok(self.clone())
    }
}

impl GitHubKnowledgeChangeBody {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn action_fields(&self) -> Result<GitHubKnowledgeChangeBody, &'static str> {
        if (self.action.clone()) == (String::from("connect")) {
            if (self.location.is_none()) || (self.credential_reference.is_none()) {
                return Err("connect requires repository and credential reference");
            }
        } else if (self.location.is_some()) || (self.credential_reference.is_some()) {
            return Err("disconnect takes only alias and expected revision");
        } else if (self.expected_revision) == (0_i64) {
            return Err("disconnect requires an existing revision");
        }
        Ok(self.clone())
    }
}

