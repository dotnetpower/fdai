//! Zero-I/O Pearl Rung 1-3 Causal Ontology & SCM Kernel.
//! Enforces finite numeric invariants, DAG acyclicity, Rung-2 `do(X)` graph surgery,
//! backdoor adjustment discovery, 3-valued `unless` inhibition with separated `uncertain_edges`,
//! Rung-3 SCM Abduction-Action-Prediction counterfactuals, and sliding-window challenger promotion.

use std::collections::{BTreeMap, BTreeSet, VecDeque};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum UnlessVerdict {
    Allow,
    Inhibit,
    Unknown,
}

#[derive(Clone, Debug, PartialEq)]
pub struct CausalEdge {
    pub from: String,
    pub to: String,
    pub weight: f64,
    pub unless_inhibitors: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CausalGraph {
    pub nodes: BTreeSet<String>,
    pub edges: Vec<CausalEdge>,
    pub intercepts: BTreeMap<String, f64>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct InterventionReceipt {
    pub target: String,
    pub do_value: f64,
    pub severed_incoming_edges: usize,
    pub backdoor_adjustment_set: Vec<String>,
    pub post_intervention_values: BTreeMap<String, f64>,
    pub inhibited_edges: usize,
    pub uncertain_edges: usize,
}

#[derive(Clone, Debug, PartialEq)]
pub struct CounterfactualReceipt {
    pub treatment: String,
    pub outcome: String,
    pub factual_outcome: f64,
    pub counterfactual_outcome: f64,
    pub individual_treatment_effect: f64,
    pub abducted_exogenous: BTreeMap<String, f64>,
    pub severed_incoming_edges: usize,
    pub uncertain_edges: usize,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChallengerWindow {
    pub capacity: usize,
    pub outcomes: VecDeque<(bool, f64)>,
}

impl ChallengerWindow {
    #[must_use]
    pub fn new(capacity: usize) -> Self {
        Self {
            capacity: capacity.max(16),
            outcomes: VecDeque::new(),
        }
    }

    pub fn record(&mut self, challenger_won: bool, margin: f64) {
        if !margin.is_finite() {
            return;
        }
        if self.outcomes.len() >= self.capacity {
            let _ = self.outcomes.pop_front();
        }
        self.outcomes.push_back((challenger_won, margin));
    }

    #[must_use]
    pub fn win_rate(&self) -> f64 {
        if self.outcomes.is_empty() {
            return 0.0;
        }
        let wins = self.outcomes.iter().filter(|(w, _)| *w).count();
        wins as f64 / self.outcomes.len() as f64
    }

    #[must_use]
    pub fn should_promote(&self, min_samples: usize, min_win_rate: f64) -> bool {
        min_win_rate.is_finite() && self.outcomes.len() >= min_samples && self.win_rate() >= min_win_rate
    }
}

#[must_use]
pub fn evaluate_unless_inhibition(
    edge: &CausalEdge,
    active_inhibitors: &BTreeMap<String, Option<bool>>,
) -> UnlessVerdict {
    let mut saw_unknown = false;
    for inh in &edge.unless_inhibitors {
        match active_inhibitors.get(inh) {
            Some(Some(true)) => return UnlessVerdict::Inhibit,
            Some(None) => saw_unknown = true,
            _ => {}
        }
    }
    if saw_unknown {
        UnlessVerdict::Unknown
    } else {
        UnlessVerdict::Allow
    }
}

impl CausalGraph {
    pub fn add_edge(&mut self, from: &str, to: &str, weight: f64, unless_inhibitors: &[&str]) {
        if !weight.is_finite() || from.is_empty() || to.is_empty() {
            return;
        }
        self.nodes.insert(from.to_string());
        self.nodes.insert(to.to_string());
        self.edges.push(CausalEdge {
            from: from.to_string(),
            to: to.to_string(),
            weight,
            unless_inhibitors: unless_inhibitors.iter().map(|s| (*s).to_string()).collect(),
        });
    }

    pub fn set_intercept(&mut self, node: &str, intercept: f64) {
        if !intercept.is_finite() || node.is_empty() {
            return;
        }
        self.nodes.insert(node.to_string());
        self.intercepts.insert(node.to_string(), intercept);
    }

    pub fn topological_order(&self) -> Result<Vec<String>, &'static str> {
        let mut indeg: BTreeMap<String, usize> =
            self.nodes.iter().map(|n| (n.clone(), 0)).collect();
        let mut adj: BTreeMap<String, Vec<String>> = BTreeMap::new();
        for e in &self.edges {
            if !e.weight.is_finite() {
                return Err("non-finite causal edge weight rejected");
            }
            *indeg.entry(e.to.clone()).or_insert(0) += 1;
            adj.entry(e.from.clone()).or_default().push(e.to.clone());
        }
        let mut q: VecDeque<String> = indeg
            .iter()
            .filter_map(|(k, &d)| if d == 0 { Some(k.clone()) } else { None })
            .collect();
        let mut order = Vec::with_capacity(self.nodes.len());
        while let Some(u) = q.pop_front() {
            order.push(u.clone());
            if let Some(nbrs) = adj.get(&u) {
                for v in nbrs {
                    if let Some(d) = indeg.get_mut(v) {
                        *d = d.saturating_sub(1);
                        if *d == 0 {
                            q.push_back(v.clone());
                        }
                    }
                }
            }
        }
        if order.len() != self.nodes.len() {
            return Err("causal graph contains a directed cycle");
        }
        Ok(order)
    }

    #[must_use]
    pub fn ancestors(&self, target: &str) -> BTreeSet<String> {
        let mut out = BTreeSet::new();
        let mut q = VecDeque::from([target.to_string()]);
        while let Some(cur) = q.pop_front() {
            for e in &self.edges {
                if e.to == cur && out.insert(e.from.clone()) {
                    q.push_back(e.from.clone());
                }
            }
        }
        out
    }

    /// Collect causal ancestors of `target` without traversing through `excluded`
    /// so instrumental chains `Z -> treatment -> outcome` are not misclassified as backdoor confounders.
    #[must_use]
    pub fn ancestors_excluding(&self, target: &str, excluded: &str) -> BTreeSet<String> {
        let mut out = BTreeSet::new();
        if target == excluded {
            return out;
        }
        let mut q = VecDeque::from([target.to_string()]);
        while let Some(cur) = q.pop_front() {
            for e in &self.edges {
                if e.to == cur && e.from != excluded && out.insert(e.from.clone()) {
                    q.push_back(e.from.clone());
                }
            }
        }
        out
    }

    #[must_use]
    pub fn descendants(&self, source: &str) -> BTreeSet<String> {
        let mut out = BTreeSet::new();
        let mut q = VecDeque::from([source.to_string()]);
        while let Some(cur) = q.pop_front() {
            for e in &self.edges {
                if e.from == cur && out.insert(e.to.clone()) {
                    q.push_back(e.to.clone());
                }
            }
        }
        out
    }

    #[must_use]
    pub fn find_backdoor_adjustment_set(&self, treatment: &str, outcome: &str) -> Vec<String> {
        let desc_t = self.descendants(treatment);
        let anc_t = self.ancestors_excluding(treatment, outcome);
        let anc_y = self.ancestors_excluding(outcome, treatment);
        anc_t
            .intersection(&anc_y)
            .filter(|n| n.as_str() != treatment && n.as_str() != outcome && !desc_t.contains(*n))
            .cloned()
            .collect()
    }

    #[must_use]
    pub fn graph_surgery(&self, target: &str) -> (Self, usize) {
        let mut mutilated = Self {
            nodes: self.nodes.clone(),
            edges: Vec::with_capacity(self.edges.len()),
            intercepts: self.intercepts.clone(),
        };
        let mut severed = 0_usize;
        for e in &self.edges {
            if e.to == target {
                severed += 1;
            } else {
                mutilated.edges.push(e.clone());
            }
        }
        (mutilated, severed)
    }

    pub fn do_intervention(
        &self,
        target: &str,
        do_value: f64,
        outcome_hint: Option<&str>,
        exogenous: &BTreeMap<String, f64>,
        active_inhibitors: &BTreeMap<String, Option<bool>>,
    ) -> Result<InterventionReceipt, &'static str> {
        if !do_value.is_finite() || exogenous.values().any(|v| !v.is_finite()) {
            return Err("non-finite intervention or exogenous value rejected");
        }
        let (mutilated, severed) = self.graph_surgery(target);
        let order = mutilated.topological_order()?;
        let backdoor = outcome_hint
            .map(|y| self.find_backdoor_adjustment_set(target, y))
            .unwrap_or_default();
        let mut vals: BTreeMap<String, f64> = BTreeMap::new();
        let mut inhibited_edges = 0_usize;
        let mut uncertain_edges = 0_usize;
        for node in order {
            if node == target {
                vals.insert(node, do_value);
                continue;
            }
            let base = mutilated.intercepts.get(&node).copied().unwrap_or(0.0)
                + exogenous.get(&node).copied().unwrap_or(0.0);
            let mut sum = base;
            for e in mutilated.edges.iter().filter(|e| e.to == node) {
                match evaluate_unless_inhibition(e, active_inhibitors) {
                    UnlessVerdict::Allow => {
                        let parent_v = vals.get(&e.from).copied().unwrap_or(0.0);
                        sum += e.weight * parent_v;
                    }
                    UnlessVerdict::Inhibit => {
                        inhibited_edges += 1;
                    }
                    UnlessVerdict::Unknown => {
                        uncertain_edges += 1;
                    }
                }
            }
            if !sum.is_finite() {
                return Err("numeric overflow during causal propagation");
            }
            vals.insert(node, sum);
        }
        Ok(InterventionReceipt {
            target: target.to_string(),
            do_value,
            severed_incoming_edges: severed,
            backdoor_adjustment_set: backdoor,
            post_intervention_values: vals,
            inhibited_edges,
            uncertain_edges,
        })
    }

    pub fn evaluate_counterfactual(
        &self,
        observed: &BTreeMap<String, f64>,
        treatment: &str,
        do_value: f64,
        outcome: &str,
        active_inhibitors: &BTreeMap<String, Option<bool>>,
    ) -> Result<CounterfactualReceipt, &'static str> {
        if !do_value.is_finite() || observed.values().any(|v| !v.is_finite()) {
            return Err("non-finite observed or intervention value rejected");
        }
        let order = self.topological_order()?;
        let mut abducted: BTreeMap<String, f64> = BTreeMap::new();
        for node in &order {
            let obs_v = observed.get(node).copied().unwrap_or(0.0);
            let mut structural = self.intercepts.get(node).copied().unwrap_or(0.0);
            for e in self.edges.iter().filter(|e| &e.to == node) {
                if evaluate_unless_inhibition(e, active_inhibitors) == UnlessVerdict::Allow {
                    let pv = observed.get(&e.from).copied().unwrap_or(0.0);
                    structural += e.weight * pv;
                }
            }
            abducted.insert(node.clone(), obs_v - structural);
        }
        let factual_outcome = observed.get(outcome).copied().unwrap_or(0.0);
        let inter = self.do_intervention(
            treatment,
            do_value,
            Some(outcome),
            &abducted,
            active_inhibitors,
        )?;
        let cf_outcome = inter
            .post_intervention_values
            .get(outcome)
            .copied()
            .unwrap_or(factual_outcome);
        Ok(CounterfactualReceipt {
            treatment: treatment.to_string(),
            outcome: outcome.to_string(),
            factual_outcome,
            counterfactual_outcome: cf_outcome,
            individual_treatment_effect: cf_outcome - factual_outcome,
            abducted_exogenous: abducted,
            severed_incoming_edges: inter.severed_incoming_edges,
            uncertain_edges: inter.uncertain_edges,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rung2_graph_surgery_backdoor_and_uncertain_unless_separation() -> Result<(), &'static str> {
        let mut g = CausalGraph::default();
        g.add_edge("traffic_spike", "cpu_saturation", 0.8, &[]);
        g.add_edge("traffic_spike", "latency_ms", 1.5, &[]);
        g.add_edge("cpu_saturation", "latency_ms", 2.0, &["autoscale_active"]);
        assert_eq!(
            g.find_backdoor_adjustment_set("cpu_saturation", "latency_ms"),
            vec![String::from("traffic_spike")]
        );
        let mut inh = BTreeMap::new();
        inh.insert(String::from("autoscale_active"), None);
        let rec = g.do_intervention("cpu_saturation", 1.0, Some("latency_ms"), &BTreeMap::new(), &inh)?;
        assert_eq!(rec.inhibited_edges, 0);
        assert_eq!(rec.uncertain_edges, 1);
        assert!(g.do_intervention("cpu_saturation", f64::NAN, None, &BTreeMap::new(), &BTreeMap::new()).is_err());
        Ok(())
    }

    #[test]
    fn rung3_counterfactual_and_challenger_window_work() -> Result<(), &'static str> {
        let mut g = CausalGraph::default();
        g.add_edge("deploy_change", "error_rate", 0.5, &["canary_rollback"]);
        let mut obs = BTreeMap::new();
        obs.insert(String::from("deploy_change"), 1.0);
        obs.insert(String::from("error_rate"), 0.7);
        let cf = g.evaluate_counterfactual(&obs, "deploy_change", 0.0, "error_rate", &BTreeMap::new())?;
        assert!((cf.counterfactual_outcome - 0.2).abs() < 1e-9);
        assert!((cf.individual_treatment_effect + 0.5).abs() < 1e-9);
        let mut win = ChallengerWindow::new(64);
        for _ in 0..80 {
            win.record(true, 0.15);
        }
        assert_eq!(win.outcomes.len(), 64);
        assert!(win.should_promote(32, 0.8));
        Ok(())
    }
}
