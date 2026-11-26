use std::collections::BTreeMap;
#[allow(clippy::enum_variant_names)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum ManualChangeType {
    #[default]
    Upserted,
    Deleted,
}

impl ManualChangeType {
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Upserted => "upserted",
            Self::Deleted => "deleted",
        }
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ManualCandidate {
    pub doc_id: String,
    pub source_ref: String,
    pub title: String,
    pub labels: Vec<String>,
    pub space: String,
    pub tree_path: Vec<String>,
    pub verified: bool,
    pub view_count: i64,
    pub last_edited: String,
    pub inbound_links: i64,
    pub content_sha: String,
    pub metadata: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ManualChange {
    pub change_type: ManualChangeType,
    pub candidate: Box<ManualCandidate>,
}

pub trait ManualSource {
    fn list_candidates(&self) -> Vec<ManualCandidate>;
    fn fetch(&self, doc_id: String) -> Option<String>;
    fn changes(&self, since: String) -> Vec<ManualChange>;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct EmptyManualSource {
    pub initialized: bool,
}

impl EmptyManualSource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn list_candidates(&self) -> Vec<ManualCandidate> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn fetch(&self, mut doc_id: String) -> Option<String> {
        if !self.initialized {
            return None;
        }
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn changes(&self, mut since: String) -> Vec<ManualChange> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DropDirectoryManualSource {
    pub initialized: bool,
}

impl DropDirectoryManualSource {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn iter_files(&self) -> Vec<String> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn rel_id(&self, mut path: String) -> String {
        if !self.initialized {
            return String::new();
        }
        String::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn read(&self, mut path: String) -> (String, String, bool) {
        let mut lossy: bool = false;
        (String::new(), String::new(), false)
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[must_use]
    pub fn candidate(&self, mut path: String) -> ManualCandidate {
        let doc_id: String = self.rel_id(path.clone());
        ManualCandidate { doc_id: doc_id.clone(), last_edited: iso_utc(0.0_f64), ..Default::default() }
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn list_candidates(&self) -> Vec<ManualCandidate> {
        if !self.initialized {
            return Vec::new();
        }
        Vec::new()
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn fetch(&self, mut doc_id: String) -> Option<String> {
        let metadata: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("decode"), String::new())]);
        None
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub async fn changes(&self, mut since: String) -> Result<Vec<ManualChange>, &'static str> {
        let mut out: Vec<ManualChange> = Vec::<ManualChange>::new();
        Ok(out.clone())
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn iso_utc(mut timestamp: f64) -> String {
    core::hint::black_box(String::new())
}

pub const PUBLIC_EXPORTS: &[&str] = &["DropDirectoryManualSource", "EmptyManualSource", "ManualCandidate", "ManualChange", "ManualChangeType", "ManualSource"];
