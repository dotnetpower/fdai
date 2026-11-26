#[derive(Clone, Debug, Default, PartialEq)]
pub struct AlertNoiseCommand {
    pub schema_version: String,
    pub operation: String,
    pub request_ref: String,
    pub requester_ref: String,
    pub scope_ref: String,
    pub requested_at: String,
    pub expires_at: String,
    pub evidence_digest: Option<String>,
    pub treatment: Option<String>,
    pub execution_authority: String,
    pub period_seconds: Option<String>,
}

impl AlertNoiseCommand {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.0.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.operation.as_str(), "alert_noise.assess" | "alert_noise.propose") { return Err("invalid operation literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AlertNoiseResult {
    pub schema_version: String,
    pub producer: String,
    pub command: Box<AlertNoiseCommand>,
    pub command_digest: String,
    pub recorded_at: String,
    pub status: String,
    pub reason: Option<String>,
    pub assessment: Option<String>,
    pub plan: Option<String>,
    pub detail: Option<String>,
    pub execution_authority: String,
}

impl AlertNoiseResult {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.schema_version.as_str(), "1.1.0") { return Err("invalid schema_version literal"); }
        if !matches!(self.producer.as_str(), "Forseti") { return Err("invalid producer literal"); }
        if !matches!(self.status.as_str(), "assessment_ready" | "proposal_ready" | "held") { return Err("invalid status literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SignedAlertCommand {
    pub command: Box<AlertNoiseCommand>,
    pub signature: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SignedAlertResult {
    pub result: Box<AlertNoiseResult>,
    pub signature: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AlertNoiseReadiness {
    pub kind: String,
    pub scope_refs: Vec<String>,
    pub generated_at: String,
    pub valid_until: String,
    pub execution_authority: String,
}

impl AlertNoiseReadiness {
    pub fn validate(&self) -> Result<(), &'static str> {
        if !matches!(self.kind.as_str(), "alert-noise.readiness") { return Err("invalid kind literal"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct SignedAlertReadiness {
    pub readiness: Box<AlertNoiseReadiness>,
    pub signature: String,
}

pub const ALERT_NOISE_RESULT_TOPIC: &str = "fdai.alert-noise.results";
pub const ALERT_NOISE_EVENT_TYPES: &[&str] = &["alert_noise.assess", "alert_noise.propose"];
impl AlertNoiseCommand {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn shape(&self) -> Result<String, &'static str> {
        if ((self.operation.clone()) != (String::from("alert_noise.assess"))) && (self.period_seconds.is_some()) {
            return Err("alert period selection belongs only to new assessments");
        }
        if ((self.operation.clone()) == (String::from("alert_noise.propose"))) != ((self.evidence_digest.is_some()) && (self.treatment.is_some())) {
            return Err("alert proposal MUST bind evidence and one treatment");
        }
        if ((self.operation.clone()) == (String::from("alert_noise.assess"))) && (((self.evidence_digest.clone()).is_some()) || ((self.treatment.clone()).is_some())) {
            return Err("assessment MUST NOT include proposal data");
        }
        Ok(String::new())
    }
}

impl AlertNoiseResult {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn bindings(&self) -> Result<String, &'static str> {
        if (self.status.clone()) == (String::from("held")) {
            if (self.reason.is_none()) || (self.plan.is_some()) {
                return Err("held alert result MUST explain why and contain no plan");
            }
        } else if (self.reason.is_some()) || (self.assessment.is_none()) {
            return Err("ready alert result MUST contain observed evidence");
        }
        if ((self.status.clone()) == (String::from("proposal_ready"))) != (self.plan.is_some()) {
            return Err("only proposal results may contain a plan");
        }
        Ok(String::new())
    }
}

impl AlertNoiseReadiness {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn lifetime(&self) -> Result<String, &'static str> {
        Err("runtime_binding_required")
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn sign_alert_record(mut record: String, mut key: Vec<u8>) -> Result<String, &'static str> {
    if (((key.clone()).len() as i64)) < (32_i64) {
        return Err("alert transport key MUST contain at least 32 bytes");
    }
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn verify_alert_record(mut record: String, mut signature: String, mut key: Vec<u8>) -> Result<(), &'static str> {
    if record.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn validate_alert_ingress(mut raw: std::collections::BTreeMap<String, String>, mut key: Vec<u8>) -> Result<SignedAlertCommand, &'static str> {
    let payload: Option<String> = (raw.clone()).get("payload").cloned();
    let _ = verify_alert_record(String::new(), String::new(), key.clone()).unwrap_or_else(|_| ());
    Err("runtime_binding_required")
}

pub const PUBLIC_EXPORTS: &[&str] = &["ALERT_NOISE_EVENT_TYPES", "ALERT_NOISE_RESULT_TOPIC", "AlertNoiseCommand", "AlertNoiseReadiness", "AlertNoiseResult", "SignedAlertCommand", "SignedAlertReadiness", "SignedAlertResult", "sign_alert_record", "validate_alert_ingress", "verify_alert_record"];
