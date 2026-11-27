//! Synthesized Pure-Rust Module (`governance_security_policy`).
//! Layer: L6/L7 | Domain: autonomous_synth/governance_security_policy
//! Goal: FDAI 거버넌스 보안·CVE·알려지지 않은 취약점(0-day) 커버리지 신뢰하한(Wilson LB95), KEV 임계 경보, Shadow→Enforce 승격 게이트 마진 및 KST 감사일자 계산 모듈
#![deny(clippy::all)]

#[derive(Clone, Debug, Default, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct SecurityGovernanceAssurance {
    pub total_cves: u64,
    pub exploited_cves: u64,
    pub runtime_matched_cves: u64,
    pub unknown_lens_count: u64,
    pub hypothesis_count: u64,
    pub wilson_lb95: f64,
}

#[inline]
#[must_use]
pub fn wilson_assurance_lb95(passed: u64, total: u64) -> f64 {
    if total == 0 { return 0.0; } let (k, n, z2) = (passed.min(total) as f64, total as f64, 3.841_458_820_694_124_f64);
    let p = k / n; ((p + z2 / (2.0 * n) - 1.959_963_984_540_054 * ((p * (1.0 - p) + z2 / (4.0 * n)) / n).max(0.0).sqrt()) / (1.0 + z2 / n)).clamp(0.0, 1.0)
}

#[inline]
#[must_use]
pub fn security_coverage_ratio(covered: u64, total: u64) -> f64 {
    if total == 0 { 0.0 } else { (covered as f64 / total as f64).clamp(0.0, 1.0) }
}

#[inline]
#[must_use]
pub fn promotion_gate_margin_passed(observed_score: f64, baseline_score: f64, min_margin: f64) -> bool {
    observed_score.is_finite() && baseline_score.is_finite() && min_margin.is_finite() && (observed_score - baseline_score) >= min_margin
}

#[inline]
#[must_use]
pub fn kev_alert_watermark_triggered(risk_score: f64, watermark: f64, elapsed_secs: u64, cooldown_secs: u64) -> bool {
    risk_score.is_finite() && watermark.is_finite() && risk_score >= watermark && elapsed_secs >= cooldown_secs.max(60)
}

#[inline]
#[must_use]
pub fn coverage_lift_delta(after_ratio: f64, before_ratio: f64) -> f64 {
    if !after_ratio.is_finite() || !before_ratio.is_finite() { 0.0 } else { after_ratio - before_ratio }
}

#[inline]
#[must_use]
pub fn format_kst_ymd_date(unix_secs: u64) -> String {
    let days = ((unix_secs + 32_400) / 86_400) as i64 + 719_468;
    let era = if days >= 0 { days } else { days - 146_096 } / 146_097;
    let doe = (days - era * 146_097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365;
    let y = yoe as i64 + era * 400; let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153; let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 }; let yr = if m <= 2 { y + 1 } else { y };
    format!("{yr:04}-{m:02}-{d:02}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_module_invariants() {
        let s = SecurityGovernanceAssurance::default();
        assert_eq!(s, SecurityGovernanceAssurance::default());
        assert_eq!(wilson_assurance_lb95(0, 0), 0.0);
        assert!(wilson_assurance_lb95(8, 10) > wilson_assurance_lb95(2, 10));
        assert!(promotion_gate_margin_passed(0.85, 0.70, 0.05));
        assert!(!promotion_gate_margin_passed(0.72, 0.70, 0.05));
        assert!(kev_alert_watermark_triggered(90.0_f64, 85.0_f64, 1000_u64, 900_u64));
        assert!(!kev_alert_watermark_triggered(50.0_f64, 85.0_f64, 1000_u64, 900_u64));
        assert!((coverage_lift_delta(0.85, 0.70) - 0.15).abs() < 1e-9);
        assert_eq!(coverage_lift_delta(f64::NAN, 0.50), 0.0);
        assert!(wilson_assurance_lb95(9058, 9058) > 0.99);
        assert!(wilson_assurance_lb95(0, 0) == 0.0);
        assert!(security_coverage_ratio(6304, 8569) > 0.73);
        assert!(promotion_gate_margin_passed(0.95, 0.80, 0.10));
        assert!(!promotion_gate_margin_passed(0.82, 0.80, 0.10));
        assert!(kev_alert_watermark_triggered(9.1, 7.0, 120, 60));
        assert!(coverage_lift_delta(0.75, 0.05) > 0.69);
        assert!(format_kst_ymd_date(1_760_313_600).len() == 10);
    }
}
