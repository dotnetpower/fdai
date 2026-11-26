#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SlackIngressQueue {
    pub initialized: bool,
}

impl SlackIngressQueue {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn accept(&self, mut body: Vec<u8>, mut headers: std::collections::BTreeMap<String, String>, mut received_at: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn receive(&self) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn close(&mut self) {
        if !self.initialized {
            return;
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TeamsEndpointRegistry {
    pub initialized: bool,
}

impl TeamsEndpointRegistry {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn bind(&self, mut conversation_id: String, mut service_url: String) -> Result<(), &'static str> {
        if (conversation_id.trim().to_string()).is_empty() {
            return Err("Teams conversation_id is invalid codeinvalid_conversation_id http_status");
        }
        Ok(())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn resolve(&self, mut conversation_id: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TeamsIngressQueue {
    pub initialized: bool,
}

impl TeamsIngressQueue {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn accept(&self, mut body: Vec<u8>, mut authorization: String, mut received_at: String) -> Result<String, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn receive(&self) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn close(&mut self) {
        if !self.initialized {
            return;
        }
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["SlackIngressQueue", "TeamsEndpointRegistry", "TeamsIngressQueue"];
