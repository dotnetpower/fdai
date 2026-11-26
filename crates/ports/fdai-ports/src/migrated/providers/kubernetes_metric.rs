#[derive(Clone, Debug, Default, PartialEq)]
pub struct KubernetesMetricTarget {
    pub cluster_ref: String,
    pub uid: String,
    pub namespace: Option<String>,
}

impl KubernetesMetricTarget {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.cluster_ref.trim().is_empty() { return Err("cluster_ref must be non-empty"); }
        if self.uid.trim().is_empty() { return Err("uid must be non-empty"); }
        Ok(())
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct KubernetesMetricWindowEvidence {
    pub metric_name: String,
    pub target: Box<KubernetesMetricTarget>,
    pub start: String,
    pub end: String,
    pub points: Vec<String>,
    pub source_identity: String,
    pub source_revision: String,
    pub provider_cutoff: Option<String>,
    pub coverage_receipt_ref: Option<String>,
    pub complete: bool,
    pub limitation: Option<String>,
}

impl KubernetesMetricWindowEvidence {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.metric_name.trim().is_empty() { return Err("metric_name must be non-empty"); }
        if self.start.trim().is_empty() { return Err("start must be non-empty"); }
        if self.end.trim().is_empty() { return Err("end must be non-empty"); }
        if self.source_identity.trim().is_empty() { return Err("source_identity must be non-empty"); }
        if self.source_revision.trim().is_empty() { return Err("source_revision must be non-empty"); }
        Ok(())
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["KUBERNETES_DIAGNOSTIC_METRICS", "KubernetesMetricTarget", "KubernetesMetricWindowEvidence"];
