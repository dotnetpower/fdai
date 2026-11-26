//! Zero-I/O Temporal-Ontology Causal Inference, Azure Change Risk Prediction,
//! Two-Layer Root Cause Analysis, and Horizontal Preventive Gap Abduction Kernel.
//!
//! Enforces strict `as_of` evidence cutoffs (no future-sample leakage), non-stationarity
//! differencing, MAD outlier clamping, nonlinear lagged Granger causality with reverse-direction
//! symmetry checks, multivariate partial-correlation confounder blocking, Pearl d-separation
//! role classification, hierarchical `is_a` x 3-valued `unless` change-risk prediction, and
//! honest abstention when evidence is insufficient.

use crate::causal_ontology::{CausalGraph, UnlessVerdict};
use std::collections::{BTreeMap, BTreeSet};

const MIN_EFFECTIVE_SAMPLES: usize = 8;
const ZERO_VARIANCE_EPS: f64 = 1e-9;
const UNIT_ROOT_AUTOCORR_THRESHOLD: f64 = 0.85;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum CausalEvidenceGrade {
    #[default]
    InsufficientEvidence,
    AssociationOnly,
    Confounded,
    TemporalGrangerSupported,
    QuasiExperimental,
    InterventionalVerified,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ThirdVariableRole {
    Confounder,
    Mediator,
    Collider,
    Neutral,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord)]
pub enum AzureFailureClass {
    #[default]
    ComputeLivenessFailure,
    CapacityExhaustionFailure,
    CredentialOrCertExpiryFailure,
    ObservabilityBlindspot,
    ControlPlaneDriftFailure,
}

impl AzureFailureClass {
    #[must_use]
    pub const fn slug(self) -> &'static str {
        match self {
            Self::ComputeLivenessFailure => "compute_liveness_failure",
            Self::CapacityExhaustionFailure => "capacity_exhaustion_failure",
            Self::CredentialOrCertExpiryFailure => "credential_or_cert_expiry_failure",
            Self::ObservabilityBlindspot => "observability_blindspot",
            Self::ControlPlaneDriftFailure => "control_plane_drift_failure",
        }
    }

    #[must_use]
    pub const fn required_preventive_guard(self) -> &'static str {
        match self {
            Self::ComputeLivenessFailure => "azure_health_probe_and_availability_alert",
            Self::CapacityExhaustionFailure => "azure_capacity_watermark_and_autoscale_guard",
            Self::CredentialOrCertExpiryFailure => "azure_keyvault_expiry_countdown_alert",
            Self::ObservabilityBlindspot => "azure_diagnostic_settings_and_telemetry_watchdog",
            Self::ControlPlaneDriftFailure => "azure_policy_change_gate_and_drift_alert",
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct TelemetryPoint {
    pub valid_at_ms: i64,
    pub value: f64,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct MetricTimeSeries {
    pub concept: String,
    pub points: Vec<TelemetryPoint>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TemporalCausalVerdict {
    pub cause_concept: String,
    pub effect_concept: String,
    pub evidence_cutoff_ms: i64,
    pub aligned_samples: usize,
    pub optimal_lag_steps: usize,
    pub forward_granger_r2_gain: f64,
    pub reverse_granger_r2_gain: f64,
    pub partial_corr_controlled: f64,
    pub differencing_applied: bool,
    pub confounder_blocked: bool,
    pub unmeasured_confounders: Vec<String>,
    pub grade: CausalEvidenceGrade,
    pub reason_code: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AzureChangeRiskPrediction {
    pub resource_id: String,
    pub change_concept: String,
    pub failure_class: AzureFailureClass,
    pub expected_downstream_impact: BTreeMap<String, f64>,
    pub peak_risk_score: f64,
    pub inhibited_edges: usize,
    pub uncertain_edges: usize,
    pub missing_recommended_guard: Option<String>,
    pub requires_review: bool,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct TwoLayerIncidentRca {
    pub resource_id: String,
    pub symptom_concept: String,
    pub physical_root_cause: String,
    pub failure_class: AzureFailureClass,
    pub granger_r2_gain: f64,
    pub do_impact_score: f64,
    pub mttd_ms: u64,
    pub mttd_budget_ms: u64,
    pub blindspot_detected: bool,
    pub why_missed_code: String,
    pub recommended_guard: String,
    pub abstained: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct AzureResourceInventoryItem {
    pub subscription_id: String,
    pub resource_id: String,
    pub resource_type: String,
    pub failure_class: AzureFailureClass,
    pub active_guards: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PreventiveGuardGap {
    pub subscription_id: String,
    pub resource_id: String,
    pub resource_type: String,
    pub failure_class: AzureFailureClass,
    pub missing_guard: String,
    pub reason: String,
}

/// Reject log lines, URLs, file paths, control characters, and overly long strings from
/// entering canonical causal ontology concept identifiers.
#[must_use]
pub fn is_polluted_causal_identifier(label: &str) -> bool {
    let tr = label.trim();
    if tr.is_empty() || tr.len() > 128 {
        return true;
    }
    let low = tr.to_ascii_lowercase();
    low.contains("http://")
        || low.contains("https://")
        || low.contains("://")
        || low.contains("/tmp/")
        || low.contains("/var/")
        || low.contains("/home/")
        || low.contains("mb)")
        || low.contains("mib")
        || tr.chars().any(|c| c.is_control() || matches!(c, ';' | '\'' | '"' | '\\' | ' '))
}

/// Classify an Azure change or failure concept into its upper `AzureFailureClass`.
#[must_use]
pub fn classify_azure_failure_class(concept: &str) -> AzureFailureClass {
    let low = concept.trim().to_ascii_lowercase();
    if low.contains("disk")
        || low.contains("oom")
        || low.contains("mem")
        || low.contains("cpu")
        || low.contains("quota")
        || low.contains("sku")
        || low.contains("pool")
        || low.contains("capacity")
    {
        AzureFailureClass::CapacityExhaustionFailure
    } else if low.contains("tls")
        || low.contains("cert")
        || low.contains("keyvault")
        || low.contains("secret")
        || low.contains("token")
        || low.contains("expir")
    {
        AzureFailureClass::CredentialOrCertExpiryFailure
    } else if low.contains("diagnostic")
        || low.contains("alert")
        || low.contains("probe")
        || low.contains("telemetry")
        || low.contains("blindspot")
        || low.contains("watchdog")
    {
        AzureFailureClass::ObservabilityBlindspot
    } else if low.contains("nsg")
        || low.contains("rbac")
        || low.contains("firewall")
        || low.contains("policy")
        || low.contains("drift")
        || low.contains("rollout")
        || low.contains("route")
    {
        AzureFailureClass::ControlPlaneDriftFailure
    } else {
        AzureFailureClass::ComputeLivenessFailure
    }
}

/// Build the baseline Azure upper failure & change-impact causal ontology graph.
#[must_use]
pub fn build_azure_failure_ontology_graph() -> CausalGraph {
    let mut g = CausalGraph::default();
    let probe_guard = AzureFailureClass::ComputeLivenessFailure.required_preventive_guard();
    let cap_guard = AzureFailureClass::CapacityExhaustionFailure.required_preventive_guard();
    let exp_guard = AzureFailureClass::CredentialOrCertExpiryFailure.required_preventive_guard();
    let obs_guard = AzureFailureClass::ObservabilityBlindspot.required_preventive_guard();
    let drift_guard = AzureFailureClass::ControlPlaneDriftFailure.required_preventive_guard();

    // Concrete Azure changes & faults -> upper failure classes & downstream service impact
    g.add_edge("vm_power_off", "compute_liveness_failure", 0.95, &[]);
    g.add_edge("aks_node_not_ready", "compute_liveness_failure", 0.90, &[]);
    g.add_edge("compute_liveness_failure", "http_5xx_or_zero", 0.92, &[probe_guard]);
    g.add_edge("http_5xx_or_zero", "service_outage", 0.95, &[probe_guard]);

    g.add_edge("sku_downscale", "capacity_exhaustion_failure", 0.85, &[cap_guard]);
    g.add_edge("disk_full", "capacity_exhaustion_failure", 0.90, &[cap_guard]);
    g.add_edge("oom_memory_pressure", "capacity_exhaustion_failure", 0.88, &[cap_guard]);
    g.add_edge("capacity_exhaustion_failure", "p99_latency_ms", 0.85, &[cap_guard]);
    g.add_edge("capacity_exhaustion_failure", "service_outage", 0.80, &[cap_guard]);

    g.add_edge("keyvault_secret_expiry", "credential_or_cert_expiry_failure", 0.92, &[exp_guard]);
    g.add_edge("tls_cert_expiring", "credential_or_cert_expiry_failure", 0.90, &[exp_guard]);
    g.add_edge("credential_or_cert_expiry_failure", "auth_failure_rate", 0.90, &[exp_guard]);
    g.add_edge("auth_failure_rate", "service_outage", 0.85, &[exp_guard]);

    g.add_edge("nsg_rule_change", "control_plane_drift_failure", 0.88, &[drift_guard]);
    g.add_edge("rbac_assignment_change", "control_plane_drift_failure", 0.85, &[drift_guard]);
    g.add_edge("firewall_rule_change", "control_plane_drift_failure", 0.88, &[drift_guard]);
    g.add_edge("control_plane_drift_failure", "connection_failures", 0.85, &[drift_guard]);
    g.add_edge("connection_failures", "service_outage", 0.82, &[drift_guard]);

    g.add_edge("diagnostic_settings_disabled", "observability_blindspot", 0.95, &[obs_guard]);
    g.add_edge("alert_rule_disabled", "observability_blindspot", 0.90, &[obs_guard]);
    g.add_edge("observability_blindspot", "unattended_outage_duration", 0.95, &[obs_guard]);
    g.add_edge("service_outage", "unattended_outage_duration", 0.85, &[probe_guard]);
    g
}

/// Classify a third variable's Pearl d-separation role for `(cause, effect)` in `graph`.
#[must_use]
pub fn classify_third_variable_role(
    graph: &CausalGraph,
    cause: &str,
    effect: &str,
    candidate: &str,
) -> ThirdVariableRole {
    if candidate == cause || candidate == effect {
        return ThirdVariableRole::Neutral;
    }
    let backdoor = graph.find_backdoor_adjustment_set(cause, effect);
    if backdoor.iter().any(|b| b == candidate) {
        return ThirdVariableRole::Confounder;
    }
    let desc_cause = graph.descendants(cause);
    let anc_effect = graph.ancestors(effect);
    if desc_cause.contains(candidate) && anc_effect.contains(candidate) {
        return ThirdVariableRole::Mediator;
    }
    let desc_effect = graph.descendants(effect);
    if desc_cause.contains(candidate) && desc_effect.contains(candidate) {
        return ThirdVariableRole::Collider;
    }
    ThirdVariableRole::Neutral
}

fn filter_and_sort_as_of(points: &[TelemetryPoint], cutoff_ms: i64) -> Vec<TelemetryPoint> {
    let mut clean: Vec<TelemetryPoint> = points
        .iter()
        .copied()
        .filter(|p| p.valid_at_ms <= cutoff_ms && p.value.is_finite())
        .collect();
    clean.sort_by_key(|p| p.valid_at_ms);
    clean
}

fn align_as_of_series(
    cause: &[TelemetryPoint],
    effect: &[TelemetryPoint],
    max_skew_ms: i64,
) -> (Vec<f64>, Vec<f64>, Vec<i64>) {
    let mut xs = Vec::with_capacity(effect.len());
    let mut ys = Vec::with_capacity(effect.len());
    let mut ts = Vec::with_capacity(effect.len());
    if cause.is_empty() || effect.is_empty() {
        return (xs, ys, ts);
    }
    let mut c_idx = 0_usize;
    for ep in effect {
        while c_idx + 1 < cause.len() && cause[c_idx + 1].valid_at_ms <= ep.valid_at_ms {
            c_idx += 1;
        }
        let cp = cause[c_idx];
        if cp.valid_at_ms <= ep.valid_at_ms && ep.valid_at_ms.saturating_sub(cp.valid_at_ms) <= max_skew_ms {
            xs.push(cp.value);
            ys.push(ep.value);
            ts.push(ep.valid_at_ms);
        }
    }
    (xs, ys, ts)
}

fn align_confounder_to_timestamps(
    conf: &[TelemetryPoint],
    target_ts: &[i64],
    max_skew_ms: i64,
) -> Option<Vec<f64>> {
    if conf.is_empty() || target_ts.is_empty() {
        return None;
    }
    let mut out = Vec::with_capacity(target_ts.len());
    let mut idx = 0_usize;
    for &t in target_ts {
        while idx + 1 < conf.len() && conf[idx + 1].valid_at_ms <= t {
            idx += 1;
        }
        let p = conf[idx];
        if p.valid_at_ms <= t && t.saturating_sub(p.valid_at_ms) <= max_skew_ms {
            out.push(p.value);
        } else {
            return None;
        }
    }
    Some(out)
}

fn median_of(vals: &[f64]) -> f64 {
    if vals.is_empty() {
        return 0.0;
    }
    let mut sorted: Vec<f64> = vals.iter().copied().filter(|v| v.is_finite()).collect();
    if sorted.is_empty() {
        return 0.0;
    }
    sorted.sort_by(f64::total_cmp);
    let mid = sorted.len() / 2;
    if sorted.len() % 2 == 1 {
        sorted[mid]
    } else {
        0.5 * (sorted[mid - 1] + sorted[mid])
    }
}

fn mad_clamp_series(vals: &[f64]) -> Vec<f64> {
    if vals.len() < 6 {
        return vals.to_vec();
    }
    let med = median_of(vals);
    let abs_dev: Vec<f64> = vals.iter().map(|v| (v - med).abs()).collect();
    let mad = median_of(&abs_dev);
    if !mad.is_finite() || mad <= 1e-9 {
        return vals.to_vec();
    }
    let limit = 6.0 * 1.4826 * mad;
    vals.iter()
        .map(|&v| (v - med).clamp(-limit, limit) + med)
        .collect()
}

fn variance_of(vals: &[f64]) -> f64 {
    if vals.len() < 2 {
        return 0.0;
    }
    let n = vals.len() as f64;
    let mean = vals.iter().sum::<f64>() / n;
    vals.iter().map(|v| (v - mean) * (v - mean)).sum::<f64>() / n
}

fn pearson_corr(xs: &[f64], ys: &[f64]) -> f64 {
    let n = xs.len().min(ys.len());
    if n < 3 {
        return 0.0;
    }
    let nf = n as f64;
    let mx = xs[..n].iter().sum::<f64>() / nf;
    let my = ys[..n].iter().sum::<f64>() / nf;
    let mut num = 0.0_f64;
    let mut dx2 = 0.0_f64;
    let mut dy2 = 0.0_f64;
    for i in 0..n {
        let a = xs[i] - mx;
        let b = ys[i] - my;
        num += a * b;
        dx2 += a * a;
        dy2 += b * b;
    }
    let denom = (dx2 * dy2).sqrt();
    if !denom.is_finite() || denom <= 1e-12 {
        0.0
    } else {
        (num / denom).clamp(-1.0, 1.0)
    }
}

fn lag1_autocorr(vals: &[f64]) -> f64 {
    if vals.len() < 4 {
        return 0.0;
    }
    pearson_corr(&vals[..vals.len() - 1], &vals[1..])
}

fn first_difference(vals: &[f64]) -> Vec<f64> {
    if vals.len() < 2 {
        return Vec::new();
    }
    vals.windows(2).map(|w| w[1] - w[0]).collect()
}

fn solve_linear_system(mut a: Vec<Vec<f64>>, mut b: Vec<f64>) -> Option<Vec<f64>> {
    let n = b.len();
    if n == 0 || a.len() != n {
        return None;
    }
    for i in 0..n {
        let mut piv = i;
        let mut max_abs = a[i][i].abs();
        for (r, row) in a.iter().enumerate().skip(i + 1) {
            if row[i].abs() > max_abs {
                max_abs = row[i].abs();
                piv = r;
            }
        }
        if !max_abs.is_finite() || max_abs < 1e-12 {
            return None;
        }
        if piv != i {
            a.swap(i, piv);
            b.swap(i, piv);
        }
        let diag = a[i][i];
        for r in (i + 1)..n {
            let factor = a[r][i] / diag;
            a[r][i] = 0.0;
            for c in (i + 1)..n {
                a[r][c] -= factor * a[i][c];
            }
            b[r] -= factor * b[i];
        }
    }
    let mut x = vec![0.0_f64; n];
    for i in (0..n).rev() {
        let mut sum = b[i];
        for c in (i + 1)..n {
            sum -= a[i][c] * x[c];
        }
        let v = sum / a[i][i];
        if !v.is_finite() {
            return None;
        }
        x[i] = v;
    }
    Some(x)
}

fn ols_sse(features: &[Vec<f64>], targets: &[f64]) -> Option<f64> {
    let n = targets.len();
    if n < MIN_EFFECTIVE_SAMPLES || features.len() != n {
        return None;
    }
    let p = features.first().map_or(0, Vec::len);
    if p == 0 || n <= p + 2 {
        return None;
    }
    let mut xtx = vec![vec![0.0_f64; p]; p];
    let mut xty = vec![0.0_f64; p];
    for i in 0..n {
        for j in 0..p {
            xty[j] += features[i][j] * targets[i];
            for k in 0..p {
                xtx[j][k] += features[i][j] * features[i][k];
            }
        }
    }
    // Tiny ridge regularizer prevents collinearity collapse without distorting genuine signal
    for (j, row) in xtx.iter_mut().enumerate() {
        row[j] += 1e-8;
    }
    let beta = solve_linear_system(xtx, xty)?;
    let mut sse = 0.0_f64;
    for i in 0..n {
        let pred: f64 = features[i].iter().zip(beta.iter()).map(|(f, w)| f * w).sum();
        let err = targets[i] - pred;
        sse += err * err;
    }
    sse.is_finite().then_some(sse.max(0.0))
}

fn residualize_against(target: &[f64], controls: &[Vec<f64>]) -> Vec<f64> {
    let n = target.len();
    if controls.is_empty() || n < MIN_EFFECTIVE_SAMPLES {
        return target.to_vec();
    }
    // Include contemporary and lagged (0, 1, 2) confounder basis so delayed common causes
    // (e.g., Z_{t-1} -> X_t and Z_{t-2} -> Y_t) are properly projected out before Granger tests.
    let lag_depth = if n >= 20 { 2_usize } else { 1_usize };
    let mut feats = Vec::with_capacity(n);
    for i in 0..n {
        let mut row = Vec::with_capacity(controls.len() * (lag_depth + 1) + 1);
        row.push(1.0);
        for c in controls {
            for lag in 0..=lag_depth {
                let idx = i.saturating_sub(lag);
                row.push(c.get(idx).copied().unwrap_or(0.0));
            }
        }
        feats.push(row);
    }
    let p = feats[0].len();
    if n <= p + 2 {
        return target.to_vec();
    }
    let mut xtx = vec![vec![0.0_f64; p]; p];
    let mut xty = vec![0.0_f64; p];
    for i in 0..n {
        for j in 0..p {
            xty[j] += feats[i][j] * target[i];
            for k in 0..p {
                xtx[j][k] += feats[i][j] * feats[i][k];
            }
        }
    }
    for (j, row) in xtx.iter_mut().enumerate() {
        row[j] += 1e-8;
    }
    let Some(beta) = solve_linear_system(xtx, xty) else {
        return target.to_vec();
    };
    let mut res = Vec::with_capacity(n);
    for i in 0..n {
        let pred: f64 = feats[i].iter().zip(beta.iter()).map(|(f, w)| f * w).sum();
        res.push(target[i] - pred);
    }
    res
}

/// Compute partial correlation between `xs` and `ys` after linearly controlling for `controls`.
#[must_use]
pub fn compute_partial_correlation_controlled(
    xs: &[f64],
    ys: &[f64],
    controls: &[Vec<f64>],
) -> f64 {
    let rx = residualize_against(xs, controls);
    let ry = residualize_against(ys, controls);
    pearson_corr(&rx, &ry)
}

fn best_nonlinear_granger_gain(cause: &[f64], effect: &[f64], max_lag: usize) -> (usize, f64) {
    let n = cause.len().min(effect.len());
    let capped_lag = max_lag.clamp(1, 6);
    if n < capped_lag + MIN_EFFECTIVE_SAMPLES {
        return (0, 0.0);
    }
    let mean_x = cause[..n].iter().sum::<f64>() / (n as f64);
    let std_x = variance_of(&cause[..n]).sqrt().max(1e-6);
    let mean_y = effect[..n].iter().sum::<f64>() / (n as f64);
    let std_y = variance_of(&effect[..n]).sqrt().max(1e-6);
    let zx: Vec<f64> = cause[..n].iter().map(|v| (v - mean_x) / std_x).collect();
    let zy: Vec<f64> = effect[..n].iter().map(|v| (v - mean_y) / std_y).collect();

    let mut best_lag = 0_usize;
    let mut best_gain = 0.0_f64;

    for lag in 1..=capped_lag {
        let start = lag.max(2);
        if n <= start + MIN_EFFECTIVE_SAMPLES {
            continue;
        }
        let eff_n = n - start;
        let mut r_feats = Vec::with_capacity(eff_n);
        let mut u_feats = Vec::with_capacity(eff_n);
        let mut targets = Vec::with_capacity(eff_n);
        for t in start..n {
            let y_lag1 = zy[t - 1];
            let y_lag2 = zy[t - 2];
            let x_lag = zx[t - lag];
            r_feats.push(vec![1.0, y_lag1, y_lag2]);
            u_feats.push(vec![1.0, y_lag1, y_lag2, x_lag, x_lag * x_lag]);
            targets.push(zy[t]);
        }
        let (Some(sse_r), Some(sse_u)) = (ols_sse(&r_feats, &targets), ols_sse(&u_feats, &targets)) else {
            continue;
        };
        if sse_r <= 1e-12 || sse_u >= sse_r {
            continue;
        }
        let raw_gain = ((sse_r - sse_u) / sse_r).clamp(0.0, 1.0);
        // F-statistic significance check with df1 = 2, df2 = eff_n - 5
        let df2 = (eff_n as f64) - 5.0;
        let f_stat = if sse_u <= 1e-12 {
            100.0
        } else {
            ((sse_r - sse_u) / 2.0) / (sse_u / df2.max(1.0))
        };
        // Multiple-lag Bonferroni-conservative F threshold
        let f_threshold = 3.2 + 0.45 * (capped_lag as f64);
        if f_stat >= f_threshold && raw_gain > best_gain {
            best_gain = raw_gain;
            best_lag = lag;
        }
    }
    (best_lag, (best_gain * 10_000.0).round() / 10_000.0)
}

/// Execute Rung 1.5 temporal-causal verification strictly bounded by `evidence_cutoff_ms`.
#[must_use]
pub fn infer_temporal_causal_verdict(
    cause_series: &MetricTimeSeries,
    effect_series: &MetricTimeSeries,
    observed_confounders: &[MetricTimeSeries],
    graph: &CausalGraph,
    evidence_cutoff_ms: i64,
    max_skew_ms: i64,
    max_lag: usize,
) -> TemporalCausalVerdict {
    let mut verdict = TemporalCausalVerdict {
        cause_concept: cause_series.concept.clone(),
        effect_concept: effect_series.concept.clone(),
        evidence_cutoff_ms,
        ..Default::default()
    };
    if is_polluted_causal_identifier(&cause_series.concept)
        || is_polluted_causal_identifier(&effect_series.concept)
    {
        verdict.reason_code = String::from("polluted_concept_identifier_rejected");
        return verdict;
    }

    let c_pts = filter_and_sort_as_of(&cause_series.points, evidence_cutoff_ms);
    let e_pts = filter_and_sort_as_of(&effect_series.points, evidence_cutoff_ms);
    let (raw_x, raw_y, aligned_ts) = align_as_of_series(&c_pts, &e_pts, max_skew_ms.max(1_000));
    verdict.aligned_samples = raw_x.len();
    if raw_x.len() < MIN_EFFECTIVE_SAMPLES + 2 {
        verdict.reason_code = String::from("insufficient_as_of_samples");
        return verdict;
    }

    let mut xs = mad_clamp_series(&raw_x);
    let mut ys = mad_clamp_series(&raw_y);
    if variance_of(&xs) <= ZERO_VARIANCE_EPS || variance_of(&ys) <= ZERO_VARIANCE_EPS {
        verdict.reason_code = String::from("zero_variance_constant_signal");
        return verdict;
    }

    // Identify required backdoor confounders from ontology graph and separate measured vs unmeasured
    let required_backdoor = graph.find_backdoor_adjustment_set(&cause_series.concept, &effect_series.concept);
    let mut measured_controls: Vec<Vec<f64>> = Vec::new();
    let mut measured_names = BTreeSet::new();
    for conf in observed_confounders {
        let role = classify_third_variable_role(graph, &cause_series.concept, &effect_series.concept, &conf.concept);
        // Protect mediators and colliders from over-control / collider bias
        if matches!(role, ThirdVariableRole::Mediator | ThirdVariableRole::Collider) {
            continue;
        }
        let conf_pts = filter_and_sort_as_of(&conf.points, evidence_cutoff_ms);
        if let Some(aligned_c) = align_confounder_to_timestamps(&conf_pts, &aligned_ts, max_skew_ms.max(1_000)) {
            measured_controls.push(mad_clamp_series(&aligned_c));
            measured_names.insert(conf.concept.clone());
        }
    }
    for req in required_backdoor {
        if !measured_names.contains(&req) {
            verdict.unmeasured_confounders.push(req);
        }
    }

    // Automatic first-differencing guard against spurious unit-root trends
    let non_stationary = lag1_autocorr(&xs).abs() >= UNIT_ROOT_AUTOCORR_THRESHOLD
        && lag1_autocorr(&ys).abs() >= UNIT_ROOT_AUTOCORR_THRESHOLD;
    if non_stationary {
        xs = first_difference(&xs);
        ys = first_difference(&ys);
        measured_controls = measured_controls.into_iter().map(|c| first_difference(&c)).collect();
        verdict.differencing_applied = true;
    }
    if variance_of(&xs) <= ZERO_VARIANCE_EPS || variance_of(&ys) <= ZERO_VARIANCE_EPS {
        verdict.reason_code = String::from("zero_variance_after_differencing");
        return verdict;
    }

    // Residualize against valid measured confounders before Granger & partial-correlation checks
    let ctrl_x = residualize_against(&xs, &measured_controls);
    let ctrl_y = residualize_against(&ys, &measured_controls);
    let (fwd_lag, fwd_gain) = best_nonlinear_granger_gain(&ctrl_x, &ctrl_y, max_lag);
    let (_rev_lag, rev_gain) = best_nonlinear_granger_gain(&ctrl_y, &ctrl_x, max_lag);
    let lag_for_corr = fwd_lag.max(1);
    let pcorr = if ctrl_x.len() > lag_for_corr {
        pearson_corr(&ctrl_x[..ctrl_x.len() - lag_for_corr], &ctrl_y[lag_for_corr..])
    } else {
        0.0
    };

    verdict.optimal_lag_steps = fwd_lag;
    verdict.forward_granger_r2_gain = fwd_gain;
    verdict.reverse_granger_r2_gain = rev_gain;
    verdict.partial_corr_controlled = (pcorr * 10_000.0).round() / 10_000.0;

    // Check if controlling confounders collapsed apparent association
    if !measured_controls.is_empty() && fwd_gain < 0.10 {
        verdict.confounder_blocked = true;
        verdict.grade = CausalEvidenceGrade::Confounded;
        verdict.reason_code = String::from("spurious_association_collapsed_after_confounder_control");
        return verdict;
    }
    if !verdict.unmeasured_confounders.is_empty() {
        verdict.grade = CausalEvidenceGrade::AssociationOnly;
        verdict.reason_code = String::from("unmeasured_backdoor_confounders_present");
        return verdict;
    }
    if fwd_gain >= 0.12 && fwd_gain > rev_gain + 0.05 {
        verdict.grade = CausalEvidenceGrade::TemporalGrangerSupported;
        verdict.reason_code = String::from("directional_lagged_granger_verified");
    } else if fwd_gain >= 0.05 || rev_gain >= 0.10 {
        verdict.grade = CausalEvidenceGrade::AssociationOnly;
        verdict.reason_code = if rev_gain >= fwd_gain {
            String::from("reverse_or_symmetric_association_only")
        } else {
            String::from("weak_association_below_granger_threshold")
        };
    } else {
        verdict.grade = CausalEvidenceGrade::InsufficientEvidence;
        verdict.reason_code = String::from("no_significant_lagged_causal_signal");
    }
    verdict
}

/// Rung 2: Predict downstream operational risk of a proposed or detected Azure resource change
/// via `do(change_concept)` graph surgery honoring 3-valued `unless` mitigation guards.
#[must_use]
pub fn predict_azure_change_risk(
    resource_id: &str,
    change_concept: &str,
    change_intensity: f64,
    active_guards: &BTreeMap<String, Option<bool>>,
    graph: &CausalGraph,
) -> AzureChangeRiskPrediction {
    let failure_class = classify_azure_failure_class(change_concept);
    let required_guard = failure_class.required_preventive_guard();
    let guard_state = active_guards.get(required_guard).copied().flatten();
    let missing_recommended_guard = if guard_state == Some(true) {
        None
    } else {
        Some(required_guard.to_string())
    };
    let safe_intensity = if change_intensity.is_finite() {
        change_intensity.clamp(0.0, 10.0)
    } else {
        1.0
    };
    let exogenous = BTreeMap::new();
    match graph.do_intervention(change_concept, safe_intensity, Some("service_outage"), &exogenous, active_guards) {
        Ok(receipt) => {
            let mut downstream = BTreeMap::new();
            let mut peak = 0.0_f64;
            for (k, v) in receipt.post_intervention_values {
                if k != change_concept && v.abs() > 1e-6 {
                    let rounded = (v * 10_000.0).round() / 10_000.0;
                    peak = peak.max(rounded.abs());
                    downstream.insert(k, rounded);
                }
            }
            let requires_review = peak >= 0.50
                || receipt.uncertain_edges > 0
                || missing_recommended_guard.is_some();
            AzureChangeRiskPrediction {
                resource_id: resource_id.to_string(),
                change_concept: change_concept.to_string(),
                failure_class,
                expected_downstream_impact: downstream,
                peak_risk_score: (peak * 10_000.0).round() / 10_000.0,
                inhibited_edges: receipt.inhibited_edges,
                uncertain_edges: receipt.uncertain_edges,
                missing_recommended_guard,
                requires_review,
            }
        }
        Err(_) => AzureChangeRiskPrediction {
            resource_id: resource_id.to_string(),
            change_concept: change_concept.to_string(),
            failure_class,
            missing_recommended_guard,
            requires_review: true,
            ..Default::default()
        },
    }
}

/// Two-Layer Incident RCA: Layer 1 (Physical/Change root cause with honest abstention) +
/// Layer 2 (Observability blindspot & missing preventive guard analysis).
#[must_use]
#[allow(clippy::too_many_arguments)]
pub fn diagnose_azure_incident_two_layer(
    resource_id: &str,
    symptom_series: &MetricTimeSeries,
    candidate_causes: &[MetricTimeSeries],
    graph: &CausalGraph,
    evidence_cutoff_ms: i64,
    t_fail_ms: u64,
    t_detect_ms: u64,
    mttd_budget_ms: u64,
    active_guards: &BTreeMap<String, Option<bool>>,
) -> TwoLayerIncidentRca {
    let mut best_cause = String::from("abstain_insufficient_causal_evidence");
    let mut best_gain = 0.0_f64;
    let mut best_do = 0.0_f64;
    let mut best_score = 0.0_f64;
    let mut found = false;

    for (idx, cand) in candidate_causes.iter().enumerate() {
        if cand.points.len() < 2 || symptom_series.points.len() < 2 {
            continue;
        }
        let backdoor = graph.find_backdoor_adjustment_set(&cand.concept, &symptom_series.concept);
        let sibling_confs: Vec<MetricTimeSeries> = candidate_causes
            .iter()
            .enumerate()
            .filter(|(j, s)| *j != idx && backdoor.iter().any(|b| b == &s.concept))
            .map(|(_, s)| s.clone())
            .collect();
        let verdict = infer_temporal_causal_verdict(
            cand,
            symptom_series,
            &sibling_confs,
            graph,
            evidence_cutoff_ms,
            600_000,
            4,
        );
        let pred = predict_azure_change_risk(resource_id, &cand.concept, 1.0, active_guards, graph);
        let impact = pred
            .expected_downstream_impact
            .get(&symptom_series.concept)
            .or_else(|| pred.expected_downstream_impact.get("service_outage"))
            .copied()
            .unwrap_or(0.0)
            .abs();
        let supported = !verdict.confounder_blocked
            && verdict.unmeasured_confounders.is_empty()
            && (verdict.grade == CausalEvidenceGrade::TemporalGrangerSupported
                || (verdict.aligned_samples >= MIN_EFFECTIVE_SAMPLES + 2
                    && verdict.forward_granger_r2_gain >= 0.12)
                || (verdict.aligned_samples >= 2
                    && impact >= 0.50
                    && verdict.grade != CausalEvidenceGrade::Confounded
                    && verdict.reason_code != "zero_variance_constant_signal"));
        let score = verdict.forward_granger_r2_gain + 0.35 * impact;
        if supported && score > best_score {
            best_score = score;
            best_cause = cand.concept.clone();
            best_gain = verdict.forward_granger_r2_gain;
            best_do = impact;
            found = true;
        }
    }

    let failure_class = if found {
        classify_azure_failure_class(&best_cause)
    } else {
        classify_azure_failure_class(&symptom_series.concept)
    };
    let required_guard = failure_class.required_preventive_guard();
    let has_guard = active_guards.get(required_guard).copied().flatten() == Some(true);
    let mttd_ms = t_detect_ms.saturating_sub(t_fail_ms);
    let blindspot_detected = mttd_ms > mttd_budget_ms || !has_guard;
    let why_missed_code = if !has_guard {
        format!("missing_preventive_guard:{required_guard}")
    } else if mttd_ms > mttd_budget_ms {
        String::from("mttd_budget_exceeded")
    } else {
        String::from("within_mttd_budget")
    };

    TwoLayerIncidentRca {
        resource_id: resource_id.to_string(),
        symptom_concept: symptom_series.concept.clone(),
        physical_root_cause: best_cause,
        failure_class,
        granger_r2_gain: best_gain,
        do_impact_score: best_do,
        mttd_ms,
        mttd_budget_ms,
        blindspot_detected,
        why_missed_code,
        recommended_guard: required_guard.to_string(),
        abstained: !found,
    }
}

/// Horizontally abduce preventive guard gaps across all Azure inventory resources sharing
/// the same upper `AzureFailureClass` (proactive pre-incident risk prediction).
#[must_use]
pub fn abduce_horizontal_preventive_gaps(
    target_class: AzureFailureClass,
    inventory: &[AzureResourceInventoryItem],
) -> Vec<PreventiveGuardGap> {
    let required = target_class.required_preventive_guard();
    let mut gaps = Vec::new();
    for item in inventory {
        if item.failure_class != target_class {
            continue;
        }
        let covered = item
            .active_guards
            .iter()
            .any(|g| g.eq_ignore_ascii_case(required));
        if !covered {
            gaps.push(PreventiveGuardGap {
                subscription_id: item.subscription_id.clone(),
                resource_id: item.resource_id.clone(),
                resource_type: item.resource_type.clone(),
                failure_class: target_class,
                missing_guard: required.to_string(),
                reason: format!(
                    "resource shares failure_class={} without required guard {}",
                    target_class.slug(),
                    required
                ),
            });
        }
    }
    gaps
}

/// Evaluate an edge's `unless` inhibitors while surfacing `Unknown` explicitly.
#[must_use]
pub fn guard_verdict_for_class(
    failure_class: AzureFailureClass,
    active_guards: &BTreeMap<String, Option<bool>>,
) -> UnlessVerdict {
    match active_guards.get(failure_class.required_preventive_guard()) {
        Some(Some(true)) => UnlessVerdict::Inhibit,
        Some(None) => UnlessVerdict::Unknown,
        _ => UnlessVerdict::Allow,
    }
}

/// Deterministic natural-experiment / recovery-reversal evidence grade bridge:
/// bridges `TemporalGrangerSupported` -> `QuasiExperimental` (canary / regional isolation)
/// or `InterventionalVerified` (controlled reversal / bounded chaos confirmation with >= 2 independent lineages).
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InterventionEvidenceInput {
    pub independent_lineage_keys: Vec<String>,
    pub controlled_reversal_observed: bool,
    pub canary_or_isolation_cohort_matched: bool,
    pub shadow_or_unapproved_run: bool,
    pub competing_hypotheses_unresolved: bool,
}

#[must_use]
pub fn deduplicate_independent_lineages(keys: &[String]) -> usize {
    let uniq: BTreeSet<String> = keys
        .iter()
        .map(|k| k.trim().to_ascii_lowercase())
        .filter(|k| !k.is_empty())
        .collect();
    uniq.len()
}

#[must_use]
pub fn promote_causal_evidence_grade(
    base: CausalEvidenceGrade,
    input: &InterventionEvidenceInput,
) -> CausalEvidenceGrade {
    if input.shadow_or_unapproved_run
        || matches!(
            base,
            CausalEvidenceGrade::InsufficientEvidence | CausalEvidenceGrade::Confounded
        )
    {
        return base;
    }
    let indep_count = deduplicate_independent_lineages(&input.independent_lineage_keys);
    if input.controlled_reversal_observed
        && !input.competing_hypotheses_unresolved
        && indep_count >= 2
    {
        CausalEvidenceGrade::InterventionalVerified
    } else if input.canary_or_isolation_cohort_matched
        && base == CausalEvidenceGrade::TemporalGrangerSupported
        && indep_count >= 1
    {
        CausalEvidenceGrade::QuasiExperimental
    } else {
        base
    }
}

/// Entity-level bitemporal version chain that preserves the latest `valid_at_ms` head
/// even when late-arriving historical observations arrive with a newer `ingested_at_ms`.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BitemporalEntityVersion {
    pub valid_at_ms: i64,
    pub ingested_at_ms: i64,
    pub state_digest: String,
    pub status: String,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct BitemporalEntityChain {
    pub entity_id: String,
    pub versions: Vec<BitemporalEntityVersion>,
}

impl BitemporalEntityChain {
    #[must_use]
    pub fn new(entity_id: impl Into<String>) -> Self {
        Self {
            entity_id: entity_id.into(),
            versions: Vec::new(),
        }
    }

    /// Append an observation without allowing a late-arriving older `valid_at_ms` event to
    /// overwrite the current valid head; returns `true` if the event was late-arriving.
    pub fn record(&mut self, ver: BitemporalEntityVersion) -> bool {
        let prev_max_valid = self.versions.iter().map(|v| v.valid_at_ms).max();
        let is_late = prev_max_valid.is_some_and(|max_v| ver.valid_at_ms < max_v);
        self.versions.push(ver);
        self.versions
            .sort_by_key(|v| (v.valid_at_ms, v.ingested_at_ms));
        is_late
    }

    #[must_use]
    pub fn latest_valid_head(&self) -> Option<&BitemporalEntityVersion> {
        self.versions.last()
    }

    #[must_use]
    pub fn state_as_of(&self, as_of_ingested_ms: i64, effective_valid_ms: i64) -> Option<&BitemporalEntityVersion> {
        self.versions
            .iter()
            .filter(|v| v.ingested_at_ms <= as_of_ingested_ms && v.valid_at_ms <= effective_valid_ms)
            .max_by_key(|v| (v.valid_at_ms, v.ingested_at_ms))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn mk_series(concept: &str, vals: &[f64]) -> MetricTimeSeries {
        MetricTimeSeries {
            concept: concept.to_string(),
            points: vals
                .iter()
                .enumerate()
                .map(|(i, &v)| TelemetryPoint {
                    valid_at_ms: 1_700_000_000_000 + (i as i64) * 60_000,
                    value: v,
                })
                .collect(),
        }
    }

    #[test]
    fn scenarios_16_temporal_causal_and_azure_risk_invariants() {
        let g = build_azure_failure_ontology_graph();
        let cutoff = 1_700_000_000_000 + 60 * 60_000;

        // 1. Forward lagged causality (X_{t-1} -> Y_t)
        let mut x_vals = Vec::new();
        let mut y_vals = Vec::new();
        for t in 0..32_usize {
            let x = ((t as f64) * 0.7).sin() * 2.0 + ((t as f64) * 1.9).cos();
            let y = if t == 0 {
                0.0
            } else {
                1.6 * x_vals[t - 1] + 0.1 * ((t as f64) * 0.3).cos()
            };
            x_vals.push(x);
            y_vals.push(y);
        }
        let v_fwd = infer_temporal_causal_verdict(
            &mk_series("nsg_rule_change", &x_vals),
            &mk_series("connection_failures", &y_vals),
            &[],
            &g,
            cutoff,
            60_000,
            3,
        );
        assert_eq!(v_fwd.grade, CausalEvidenceGrade::TemporalGrangerSupported);
        assert!(v_fwd.forward_granger_r2_gain > 0.50);

        // 2. Reverse causality rejected (Y -> X must not claim X -> Y)
        let v_rev = infer_temporal_causal_verdict(
            &mk_series("connection_failures", &y_vals),
            &mk_series("nsg_rule_change", &x_vals),
            &[],
            &g,
            cutoff,
            60_000,
            3,
        );
        assert_ne!(v_rev.grade, CausalEvidenceGrade::TemporalGrangerSupported);

        // 3. Common confounder Z -> X, Z -> Y blocked when controlled
        let mut cg = CausalGraph::default();
        cg.add_edge("traffic_surge", "app_cpu", 0.9, &[]);
        cg.add_edge("traffic_surge", "db_latency", 0.9, &[]);
        let mut z_v = Vec::new();
        let mut cx_v = Vec::new();
        let mut cy_v = Vec::new();
        for t in 0..36_usize {
            let z = ((t as f64) * 0.65).sin() * 3.0 + ((t as f64) * 1.3).cos();
            z_v.push(z);
            cx_v.push(if t == 0 { 0.0 } else { 0.9 * z_v[t - 1] + 0.05 * ((t as f64) * 2.1).sin() });
            cy_v.push(if t < 2 { 0.0 } else { 0.95 * z_v[t - 2] + 0.05 * ((t as f64) * 1.7).cos() });
        }
        let v_conf = infer_temporal_causal_verdict(
            &mk_series("app_cpu", &cx_v),
            &mk_series("db_latency", &cy_v),
            &[mk_series("traffic_surge", &z_v)],
            &cg,
            cutoff,
            60_000,
            3,
        );
        assert!(v_conf.confounder_blocked || v_conf.grade != CausalEvidenceGrade::TemporalGrangerSupported);

        // 4, 5, 6. Pearl d-separation roles: Confounder, Mediator, Collider, and Z -> X -> Y instrument
        let mut dg = CausalGraph::default();
        dg.add_edge("instrument_z", "treatment_x", 0.8, &[]);
        dg.add_edge("treatment_x", "mediator_m", 0.8, &[]);
        dg.add_edge("mediator_m", "outcome_y", 0.8, &[]);
        dg.add_edge("treatment_x", "collider_c", 0.7, &[]);
        dg.add_edge("outcome_y", "collider_c", 0.7, &[]);
        dg.add_edge("true_confounder", "treatment_x", 0.6, &[]);
        dg.add_edge("true_confounder", "outcome_y", 0.6, &[]);
        assert_eq!(
            dg.find_backdoor_adjustment_set("treatment_x", "outcome_y"),
            vec![String::from("true_confounder")]
        );
        assert_eq!(
            classify_third_variable_role(&dg, "treatment_x", "outcome_y", "true_confounder"),
            ThirdVariableRole::Confounder
        );
        assert_eq!(
            classify_third_variable_role(&dg, "treatment_x", "outcome_y", "mediator_m"),
            ThirdVariableRole::Mediator
        );
        assert_eq!(
            classify_third_variable_role(&dg, "treatment_x", "outcome_y", "collider_c"),
            ThirdVariableRole::Collider
        );
        assert_eq!(
            classify_third_variable_role(&dg, "treatment_x", "outcome_y", "instrument_z"),
            ThirdVariableRole::Neutral
        );

        // 7. Non-stationary unit-root spurious trend blocked via first-differencing
        let trend_x: Vec<f64> = (0..36).map(|t| (t as f64) * 2.5 + 1.0).collect();
        let trend_y: Vec<f64> = (0..36).map(|t| (t as f64) * 4.0 + 10.0).collect();
        let v_trend = infer_temporal_causal_verdict(
            &mk_series("trend_a", &trend_x),
            &mk_series("trend_b", &trend_y),
            &[],
            &g,
            cutoff,
            60_000,
            3,
        );
        assert!(v_trend.differencing_applied);
        assert_ne!(v_trend.grade, CausalEvidenceGrade::TemporalGrangerSupported);

        // 8. MAD outlier defense preserves genuine signal despite single huge spike
        let mut spike_x = x_vals.clone();
        spike_x[15] = 9999.0;
        let v_mad = infer_temporal_causal_verdict(
            &mk_series("nsg_rule_change", &spike_x),
            &mk_series("connection_failures", &y_vals),
            &[],
            &g,
            cutoff,
            60_000,
            3,
        );
        assert_eq!(v_mad.grade, CausalEvidenceGrade::TemporalGrangerSupported);

        // 9. Constant zero-variance signal honestly abstains
        let flat = vec![1.0; 24];
        let v_flat = infer_temporal_causal_verdict(
            &mk_series("const_metric", &flat),
            &mk_series("connection_failures", &y_vals[..24]),
            &[],
            &g,
            cutoff,
            60_000,
            3,
        );
        assert_eq!(v_flat.grade, CausalEvidenceGrade::InsufficientEvidence);

        // 10. Future samples past `as_of` cutoff are strictly excluded
        let early_cutoff = 1_700_000_000_000 + 3 * 60_000;
        let v_cut = infer_temporal_causal_verdict(
            &mk_series("nsg_rule_change", &x_vals),
            &mk_series("connection_failures", &y_vals),
            &[],
            &g,
            early_cutoff,
            60_000,
            3,
        );
        assert_eq!(v_cut.aligned_samples, 4);
        assert_eq!(v_cut.grade, CausalEvidenceGrade::InsufficientEvidence);

        // 11. Nonlinear quadratic lagged causality (Y_t = X_{t-1}^2)
        let nl_x: Vec<f64> = (0..36).map(|t| ((t as f64) * 0.85).sin() * 2.5).collect();
        let mut nl_y = vec![0.0; 36];
        for t in 1..36 {
            nl_y[t] = nl_x[t - 1] * nl_x[t - 1] + 0.05 * ((t as f64) * 0.4).cos();
        }
        let v_nl = infer_temporal_causal_verdict(
            &mk_series("sku_downscale", &nl_x),
            &mk_series("p99_latency_ms", &nl_y),
            &[],
            &g,
            cutoff,
            60_000,
            3,
        );
        assert_eq!(v_nl.grade, CausalEvidenceGrade::TemporalGrangerSupported);

        // 12. Rung 2 `do(Azure Change)` + 3-valued `unless` (Allow vs Inhibit vs Unknown)
        let no_guards = BTreeMap::new();
        let pred_unprotected = predict_azure_change_risk("sub/rg/vm-01", "vm_power_off", 1.0, &no_guards, &g);
        assert!(pred_unprotected.peak_risk_score > 0.70);
        assert!(pred_unprotected.requires_review);

        let mut protected = BTreeMap::new();
        protected.insert(
            AzureFailureClass::ComputeLivenessFailure.required_preventive_guard().to_string(),
            Some(true),
        );
        let pred_protected = predict_azure_change_risk("sub/rg/vm-01", "vm_power_off", 1.0, &protected, &g);
        assert!(pred_protected.inhibited_edges > 0);
        assert!(pred_protected.missing_recommended_guard.is_none());

        let mut unknown_guards = BTreeMap::new();
        unknown_guards.insert(
            AzureFailureClass::ComputeLivenessFailure.required_preventive_guard().to_string(),
            None,
        );
        let pred_unknown = predict_azure_change_risk("sub/rg/vm-01", "vm_power_off", 1.0, &unknown_guards, &g);
        assert!(pred_unknown.uncertain_edges > 0);
        assert!(pred_unknown.requires_review);

        // 13 & 14. Two-layer RCA detects physical cause + blindspot, and abstains on insufficient evidence
        let rca = diagnose_azure_incident_two_layer(
            "sub/rg/vnet-01",
            &mk_series("connection_failures", &y_vals),
            &[mk_series("nsg_rule_change", &x_vals)],
            &g,
            cutoff,
            0,
            900_000,
            300_000,
            &no_guards,
        );
        assert!(!rca.abstained);
        assert_eq!(rca.physical_root_cause, "nsg_rule_change");
        assert!(rca.blindspot_detected);
        assert_eq!(
            rca.recommended_guard,
            AzureFailureClass::ControlPlaneDriftFailure.required_preventive_guard()
        );

        let rca_abstain = diagnose_azure_incident_two_layer(
            "sub/rg/vnet-01",
            &mk_series("connection_failures", &[1.0]),
            &[mk_series("nsg_rule_change", &[1.0])],
            &g,
            cutoff,
            0,
            100_000,
            300_000,
            &no_guards,
        );
        assert!(rca_abstain.abstained);
        assert_eq!(rca_abstain.physical_root_cause, "abstain_insufficient_causal_evidence");

        // 15. Horizontal preventive gap abduction across same upper failure class
        let inv = vec![
            AzureResourceInventoryItem {
                subscription_id: String::from("sub-prod"),
                resource_id: String::from("/subscriptions/sub-prod/rg-a/vm-1"),
                resource_type: String::from("Microsoft.Compute/virtualMachines"),
                failure_class: AzureFailureClass::ComputeLivenessFailure,
                active_guards: vec![String::from("azure_health_probe_and_availability_alert")],
            },
            AzureResourceInventoryItem {
                subscription_id: String::from("sub-prod"),
                resource_id: String::from("/subscriptions/sub-prod/rg-b/vm-2"),
                resource_type: String::from("Microsoft.Compute/virtualMachines"),
                failure_class: AzureFailureClass::ComputeLivenessFailure,
                active_guards: vec![],
            },
        ];
        let gaps = abduce_horizontal_preventive_gaps(AzureFailureClass::ComputeLivenessFailure, &inv);
        assert_eq!(gaps.len(), 1);
        assert_eq!(gaps[0].resource_id, "/subscriptions/sub-prod/rg-b/vm-2");

        // 16. Polluted identifier guard
        assert!(is_polluted_causal_identifier("https://portal.azure.com/foo"));
        assert!(is_polluted_causal_identifier("/tmp/dump.json"));
        assert!(is_polluted_causal_identifier("worker.service (anon=1200mb)"));
        assert!(!is_polluted_causal_identifier("nsg_rule_change"));

        // 17. Evidence grade promotion bridge & independent-lineage echo-chamber deduplication
        let dup_input = InterventionEvidenceInput {
            independent_lineage_keys: vec![String::from("arg-snap-1"), String::from("arg-snap-1")],
            controlled_reversal_observed: true,
            canary_or_isolation_cohort_matched: true,
            shadow_or_unapproved_run: false,
            competing_hypotheses_unresolved: false,
        };
        assert_eq!(deduplicate_independent_lineages(&dup_input.independent_lineage_keys), 1);
        assert_eq!(
            promote_causal_evidence_grade(CausalEvidenceGrade::TemporalGrangerSupported, &dup_input),
            CausalEvidenceGrade::QuasiExperimental
        );
        let indep_input = InterventionEvidenceInput {
            independent_lineage_keys: vec![String::from("arg-snap-1"), String::from("monitor-metric-2")],
            controlled_reversal_observed: true,
            canary_or_isolation_cohort_matched: true,
            shadow_or_unapproved_run: false,
            competing_hypotheses_unresolved: false,
        };
        assert_eq!(
            promote_causal_evidence_grade(CausalEvidenceGrade::TemporalGrangerSupported, &indep_input),
            CausalEvidenceGrade::InterventionalVerified
        );

        // 18. Bitemporal entity chain protects latest valid head from late-arriving historical events
        let mut chain = BitemporalEntityChain::new("/subscriptions/sub-1/rg/vm-1");
        assert!(!chain.record(BitemporalEntityVersion {
            valid_at_ms: 2_000,
            ingested_at_ms: 2_100,
            state_digest: String::from("sha256:head_new"),
            status: String::from("running"),
        }));
        assert!(chain.record(BitemporalEntityVersion {
            valid_at_ms: 1_000,
            ingested_at_ms: 2_500,
            state_digest: String::from("sha256:late_old"),
            status: String::from("provisioning"),
        }));
        assert_eq!(
            chain.latest_valid_head().map(|v| v.status.as_str()),
            Some("running")
        );
        assert_eq!(
            chain.state_as_of(2_600, 1_500).map(|v| v.status.as_str()),
            Some("provisioning")
        );
    }
}
