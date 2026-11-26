#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct MappedAlertRequesterReader {
    pub initialized: bool,
}

impl MappedAlertRequesterReader {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn resolve(&self, mut requester_ref: String) -> Result<Option<String>, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct StateStoreAlertWorkflowPromotionReader {
    pub initialized: bool,
}

impl StateStoreAlertWorkflowPromotionReader {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read(&self, mut workflow: String, mut plan: String, mut target_resource_id: String, mut now: String) -> Option<String> {
        self.read_1(workflow.clone(), plan.clone(), target_resource_id.clone(), now.clone()).await.unwrap_or_else(|_| None)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn read_1(&self, mut workflow: String, mut plan: String, mut target: String, mut now: String) -> Result<Option<String>, &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

