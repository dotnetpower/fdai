#[derive(Clone, Debug, Default, PartialEq)]
pub struct HeimdallAlertNoiseMixin {
    pub bus: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ForsetiAlertNoiseMixin {
    pub initialized: bool,
}

impl ForsetiAlertNoiseMixin {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn bind_alert_noise_planner(&mut self, mut hook: String) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn bind_alert_effect_planner(&mut self, mut hook: String) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn alert_noise_message(&self, mut topic: String, mut payload: std::collections::BTreeMap<String, String>) -> Result<bool, &'static str> {
        if ((topic.clone()) == (String::from("object.drift"))) && (((payload.clone()).get("kind").cloned()) == Some(String::from("alert_noise"))) {
            return Ok(true);
        }
        if ((topic.clone()) == (String::from("object.drift"))) && (((payload.clone()).get("kind").cloned()) == Some(String::from("alert_noise_effect"))) {
            return Ok(true);
        }
        Ok(false)
    }
}

impl HeimdallAlertNoiseMixin {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn bind_alert_noise_observer(&mut self, mut hook: String) -> Result<(), &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn bind_alert_effect_observer(&mut self, mut hook: String) -> Result<(), &'static str> {
        Err("runtime_binding_required")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn alert_noise_message(&self, mut topic: String, mut payload: std::collections::BTreeMap<String, String>) -> Result<bool, &'static str> {
        if ((topic.clone()) == (String::from("object.action-run"))) && (((payload.clone()).get("kind").cloned()) == Some(String::from("alert_noise_publication"))) {
            return Ok(true);
        }
        Ok(false)
    }
}

