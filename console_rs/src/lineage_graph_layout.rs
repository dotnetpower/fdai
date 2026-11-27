//! Synthesized Pure-Rust Module (`lineage_graph_layout`).
//! Layer: L6/L7 | Domain: autonomous_synth/lineage_graph_layout
//! Goal: FDAI 온톨로지 전체 노드 데이터 계통(DAG) 레이아웃 정규화 좌표·커버리지 신뢰하한(Wilson LB95)·단계 비율 계산 모듈
#![deny(clippy::all)]

#[derive(Clone, Debug, Default, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct LineageGraphMetrics {
    pub total_nodes: u64,
    pub total_edges: u64,
    pub total_resources: u64,
    pub cluster_count: u64,
    pub coverage_wilson_lb95: f64,
}

#[inline]
#[must_use]
pub fn lineage_coverage_wilson_lb95(mapped: u64, total: u64) -> f64 {
    if total == 0 { return 0.0; } let (k, n, z2) = (mapped.min(total) as f64, total as f64, 3.841_458_820_694_124_f64);
    let p = k / n; ((p + z2 / (2.0 * n) - 1.959_963_984_540_054 * ((p * (1.0 - p) + z2 / (4.0 * n)) / n).max(0.0).sqrt()) / (1.0 + z2 / n)).clamp(0.0, 1.0)
}

#[inline]
#[must_use]
pub fn lineage_stage_ratio(index: u64, total: u64) -> f64 {
    if total == 0 { 0.0 } else { (index as f64 / total as f64).clamp(0.0, 1.0) }
}

#[inline]
#[must_use]
pub fn lineage_density_delta(full_density: f64, cluster_density: f64) -> f64 {
    if !full_density.is_finite() || !cluster_density.is_finite() { 0.0 } else { full_density - cluster_density }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_module_invariants() {
        let s = LineageGraphMetrics::default();
        assert_eq!(s, LineageGraphMetrics::default());
        assert_eq!(lineage_coverage_wilson_lb95(0, 0), 0.0);
        assert!(lineage_coverage_wilson_lb95(8, 10) > lineage_coverage_wilson_lb95(2, 10));
        assert!((lineage_density_delta(0.85, 0.70) - 0.15).abs() < 1e-9);
        assert_eq!(lineage_density_delta(f64::NAN, 0.50), 0.0);
        assert!(lineage_coverage_wilson_lb95(2213, 2213) > 0.99);
        assert!(lineage_coverage_wilson_lb95(0, 0) == 0.0);
        assert!(lineage_stage_ratio(1, 4) == 0.25);
        assert!(lineage_stage_ratio(10, 0) == 0.0);
        assert!(lineage_density_delta(0.8, 0.2) > 0.59);
    }
}
