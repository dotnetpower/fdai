use crate::temporal_causal::{
    build_azure_failure_ontology_graph, classify_azure_failure_class,
    predict_azure_change_risk, AzureChangeRiskPrediction,
};
use std::collections::BTreeMap;

pub trait AdaptiveTelemetryInvestigator {
    fn investigate(
        &self,
        incident_id: String,
        resource_ref: String,
        event_type: String,
        resource_type: Option<String>,
        evidence_cutoff: String,
        correlation_id: String,
    ) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ControlLoopRcaMixin {
    pub initialized: bool,
}

fn fnv1a64_hex(input: &str) -> String {
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for b in input.as_bytes() {
        h ^= u64::from(*b);
        h = h.wrapping_mul(0x0100_0000_01b3);
    }
    format!("{h:016x}")
}

fn infer_concept_from_event(event: &str) -> &'static str {
    let low = event.to_ascii_lowercase();
    if low.contains("nsg") {
        "nsg_rule_change"
    } else if low.contains("rbac") || low.contains("role") {
        "rbac_assignment_change"
    } else if low.contains("firewall") {
        "firewall_rule_change"
    } else if low.contains("keyvault") || low.contains("secret") {
        "keyvault_secret_expiry"
    } else if low.contains("tls") || low.contains("cert") {
        "tls_cert_expiring"
    } else if low.contains("sku") || low.contains("downscale") {
        "sku_downscale"
    } else if low.contains("disk") {
        "disk_full"
    } else if low.contains("oom") || low.contains("memory") {
        "oom_memory_pressure"
    } else if low.contains("diagnostic") {
        "diagnostic_settings_disabled"
    } else if low.contains("aks") || low.contains("node") {
        "aks_node_not_ready"
    } else {
        "vm_power_off"
    }
}

fn format_risk_chain_json(inc_id: &str, pred: &AzureChangeRiskPrediction) -> String {
    let downstream: Vec<String> = pred
        .expected_downstream_impact
        .iter()
        .map(|(k, v)| format!("\"{k}\":{v:.4}"))
        .collect();
    let guard = pred
        .missing_recommended_guard
        .as_deref()
        .unwrap_or("none");
    format!(
        "{{\"incident_id\":\"{inc_id}\",\"change_concept\":\"{}\",\"failure_class\":\"{}\",\"peak_risk_score\":{:.4},\"requires_review\":{},\"missing_guard\":\"{guard}\",\"downstream\":{{{}}}}}",
        pred.change_concept,
        pred.failure_class.slug(),
        pred.peak_risk_score,
        pred.requires_review,
        downstream.join(",")
    )
}

impl ControlLoopRcaMixin {
    #[must_use]
    pub fn correlate_incident_id(&self, event: String) -> Option<String> {
        let tr = event.trim();
        if tr.is_empty() {
            return None;
        }
        let concept = infer_concept_from_event(tr);
        Some(format!("inc-{concept}-{}", fnv1a64_hex(tr)))
    }

    pub async fn analyze_and_audit_rca(
        &self,
        event: String,
        finding: String,
        rule: String,
        resource_type: Option<String>,
        incident_id: Option<String>,
    ) {
        let _ev = finding_impact_evidence(
            finding,
            rule,
            resource_type.unwrap_or_else(|| String::from("azure_resource")),
        );
        let _ = self.analyze_and_audit_t1_causal_chain(event, incident_id).await;
    }

    pub async fn analyze_and_audit_t1_causal_chain(
        &self,
        event: String,
        incident_id: Option<String>,
    ) -> Option<String> {
        let inc_id = incident_id.or_else(|| self.correlate_incident_id(event.clone()))?;
        let concept = infer_concept_from_event(&event);
        let graph = build_azure_failure_ontology_graph();
        let active_guards = BTreeMap::new();
        let pred = predict_azure_change_risk(&inc_id, concept, 1.0, &active_guards, &graph);
        Some(format_risk_chain_json(&inc_id, &pred))
    }

    pub async fn analyze_and_audit_temporal_causality(
        &self,
        event: String,
        incident_id: Option<String>,
    ) {
        if self.initialized
            && !event.is_empty()
            && !incident_id.as_deref().is_some_and(str::is_empty)
        {
            core::sync::atomic::compiler_fence(core::sync::atomic::Ordering::SeqCst);
        }
    }

    pub async fn analyze_t2_rca_on_abstain(
        &self,
        event: String,
        decision: String,
        incident_id: Option<String>,
        prior_rca: Option<String>,
    ) -> Option<String> {
        let inc_id = incident_id.or_else(|| self.correlate_incident_id(event.clone()))?;
        let concept = infer_concept_from_event(&event);
        let class = classify_azure_failure_class(concept);
        let has_prior = prior_rca.as_deref().is_some_and(|p| !p.trim().is_empty());
        Some(format!(
            "{{\"incident_id\":\"{inc_id}\",\"decision\":\"{}\",\"abstain_t2_failure_class\":\"{}\",\"recommended_guard\":\"{}\",\"prior_rca_present\":{has_prior}}}",
            decision.trim(),
            class.slug(),
            class.required_preventive_guard()
        ))
    }
}

#[must_use]
pub fn finding_impact_evidence(
    finding: String,
    rule: String,
    resource_type: String,
) -> Vec<BTreeMap<String, String>> {
    if finding.trim().is_empty() && rule.trim().is_empty() {
        return Vec::new();
    }
    let concept = infer_concept_from_event(&format!("{finding} {rule}"));
    let graph = build_azure_failure_ontology_graph();
    let pred = predict_azure_change_risk(&resource_type, concept, 1.0, &BTreeMap::new(), &graph);
    let mut row = BTreeMap::new();
    row.insert(String::from("rule"), rule);
    row.insert(String::from("resource_type"), resource_type);
    row.insert(String::from("change_concept"), pred.change_concept);
    row.insert(String::from("failure_class"), pred.failure_class.slug().to_string());
    row.insert(String::from("peak_risk_score"), format!("{:.4}", pred.peak_risk_score));
    row.insert(
        String::from("recommended_guard"),
        pred.missing_recommended_guard
            .unwrap_or_else(|| String::from("covered")),
    );
    vec![row]
}

#[must_use]
pub fn incident_summary(event: String, decision: String) -> String {
    let concept = infer_concept_from_event(&event);
    let class = classify_azure_failure_class(concept);
    let graph = build_azure_failure_ontology_graph();
    let pred = predict_azure_change_risk("azure_resource", concept, 1.0, &BTreeMap::new(), &graph);
    format!(
        "{{\"decision\":\"{}\",\"concept\":\"{concept}\",\"failure_class\":\"{}\",\"peak_risk_score\":{:.4},\"requires_review\":{},\"recommended_guard\":\"{}\"}}",
        decision.trim(),
        class.slug(),
        pred.peak_risk_score,
        pred.requires_review,
        class.required_preventive_guard()
    )
}

pub const PUBLIC_EXPORTS: &[&str] = &["AdaptiveTelemetryInvestigator", "ControlLoopRcaMixin"];

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn control_loop_rca_produces_causal_risk_evidence_and_summaries() {
        let rca = ControlLoopRcaMixin { initialized: true };
        let id = rca.correlate_incident_id(String::from("azure nsg_rule_change on prod-vnet"));
        assert!(id.as_deref().is_some_and(|s| s.starts_with("inc-nsg_rule_change-")));
        let ev = finding_impact_evidence(
            String::from("keyvault secret expiring in 3 days"),
            String::from("KV-EXPIRY-01"),
            String::from("Microsoft.KeyVault/vaults"),
        );
        assert_eq!(ev.len(), 1);
        assert_eq!(
            ev[0].get("failure_class").map(String::as_str),
            Some("credential_or_cert_expiry_failure")
        );
        let summary = incident_summary(String::from("vm_power_off detected"), String::from("hil_review"));
        assert!(summary.contains("compute_liveness_failure"));
        assert!(summary.contains("azure_health_probe_and_availability_alert"));
    }
}
