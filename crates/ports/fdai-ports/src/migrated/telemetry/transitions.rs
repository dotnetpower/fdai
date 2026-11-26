use std::collections::BTreeMap;
pub const MAX_ATTRIBUTE_CHARS: i64 = 200;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct RoutingTransition {
    pub domain: String,
    pub name: String,
    pub outcome: String,
    pub attributes: BTreeMap<String, String>,
}

pub const DOMAINS: &[&str] = &["channel", "extension", "model", "scheduler", "security"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RoutingTransitionEmitter {
    pub initialized: bool,
}

impl RoutingTransitionEmitter {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn emit(&self, mut transition: RoutingTransition) {
        let attributes: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("fdai.transition.domain"), transition.domain.clone()), (String::from("fdai.transition.name"), transition.name.clone()), (String::from("fdai.transition.outcome"), transition.outcome.clone())]);
    }
}

pub trait RoutingTransitionSink {
    fn emit(&self, transition: RoutingTransition) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct InMemoryRoutingTransitionSink {
    pub initialized: bool,
}

impl InMemoryRoutingTransitionSink {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn emit(&self, mut transition: RoutingTransition) {
        if !self.initialized {
            return;
        }
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn default_transition_emitter() -> RoutingTransitionEmitter {
    core::hint::black_box(Default::default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn emit_transition_safely(mut sink: Option<String>, mut transition: RoutingTransition) {
    let Some(mut sink) = sink.clone() else { return; };
}

pub const PUBLIC_EXPORTS: &[&str] = &["InMemoryRoutingTransitionSink", "RoutingTransition", "RoutingTransitionEmitter", "RoutingTransitionSink", "default_transition_emitter", "emit_transition_safely"];
