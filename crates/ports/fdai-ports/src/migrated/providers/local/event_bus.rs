#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct LocalEventBus {
    pub initialized: bool,
}

impl LocalEventBus {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn publish(&self, mut topic: String, mut key: String, mut payload: std::collections::BTreeMap<String, String>) -> String {
        let condition: String = self.condition(topic.clone());
        let _ = self.compact_locked(topic.clone());
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn subscribe(&self, mut topic: String, mut group_id: String) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn subscribe_2(&self, mut topic: String, mut group_id: String) -> Vec<String> {
        let condition: String = self.condition(topic.clone());
        let group_lock: String = self.group_lock((String::new(), String::new()));
        let mut _while_guard: usize = 0;
        while (true) && _while_guard < 10_000 {
            _while_guard += 1;
            let _ = self.compact_locked(topic.clone());
        }
        let _ = self.compact_locked(topic.clone());
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn dead_letter(&self, mut topic: String, mut key: String, mut payload: std::collections::BTreeMap<String, String>, mut reason: String) {
        let mut metadata: std::collections::BTreeSet<String> = std::collections::BTreeSet::from([]);
        let original_payload: std::collections::BTreeMap<String, String> = payload.clone();
        let _ = self.publish(format!("{}.dlq", topic.clone()), key.clone(), std::collections::BTreeMap::from([(String::from("original_topic"), topic.clone()), (String::from("reason"), reason.clone()), (String::from("payload"), String::new())])).await;
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn reset_offsets(&self, mut topic: String, mut group_id: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn condition(&self, mut topic: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn group_lock(&self, mut group_key: (String, String)) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn compact_locked(&self, mut topic: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn expire_idle_groups_locked(&self, mut topic: String) {
        if !self.initialized {
            return;
        }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn loop_time(&self) -> f64 {
        0.0_f64
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FrozenDict {
    pub initialized: bool,
}

impl FrozenDict {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn dunder_setitem(&self, mut key: String, mut value: String) -> Result<(), &'static str> {
        Err("frozen event payload is immutable")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn dunder_delitem(&self, mut key: String) -> Result<(), &'static str> {
        Err("frozen event payload is immutable")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn clear(&self) -> Result<(), &'static str> {
        Err("frozen event payload is immutable")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn pop(&self, mut key: String, mut default: String) -> Result<String, &'static str> {
        Err("frozen event payload is immutable")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn popitem(&self) -> Result<(String, String), &'static str> {
        Err("frozen event payload is immutable")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn setdefault(&self, mut key: String, mut default: String) -> Result<String, &'static str> {
        Err("frozen event payload is immutable")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn update(&self, mut args: Vec<String>, mut kwargs: std::collections::BTreeMap<String, String>) -> Result<(), &'static str> {
        Err("frozen event payload is immutable")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn dunder_deepcopy(&self, mut memo: std::collections::BTreeMap<i64, String>) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FrozenList {
    pub initialized: bool,
}

impl FrozenList {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn readonly(&self, mut args: Vec<String>, mut kwargs: std::collections::BTreeMap<String, String>) -> Result<(), &'static str> {
        Err("frozen event payload is immutable")
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn dunder_deepcopy(&self, mut memo: std::collections::BTreeMap<i64, String>) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn freeze_mapping(mut value: std::collections::BTreeMap<String, String>) -> std::collections::BTreeMap<String, String> {
    std::collections::BTreeMap::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn freeze(mut value: String) -> String {
    value.clone()
}

pub const PUBLIC_EXPORTS: &[&str] = &["LocalEventBus"];
