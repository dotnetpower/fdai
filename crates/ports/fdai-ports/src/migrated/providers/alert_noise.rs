pub trait AlertEvidenceSource {
    fn collect(&self, now: String) -> String;
}

pub trait AlertPeriodEvidenceSource {
    fn collect_period(&self, now: String, period_seconds: i64) -> String;
}

pub trait AlertAudienceResolver {
    fn resolve(&self, binding_ref: String, kind: String, private_value: String) -> String;
}

pub trait AlertAuthorityReader {
    fn approvals(&self, plan: String) -> String;
}

pub trait AlertGovernedDispatcher {
    fn submit(&self, plan: String, idempotency_key: String) -> String;
}

pub trait AlertEffectReader {
    fn observe(&self, plan: String, dispatch_ref: String) -> String;
}

pub trait AlertAssessmentPublisher {
    fn publish(&self, assessment: String, principal_ref: String) -> String;
}

pub trait AlertPlanPublisher {
    fn publish(&self, plan: String, changes: std::collections::BTreeMap<String, String>) -> String;
}

pub trait AlertPlanArtifacts {
    fn prepare(&self, plan: String, evidence: String) -> String;
}

