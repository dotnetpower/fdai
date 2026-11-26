pub const MAX_ROWS: i64 = 128;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChangeWindowHistoryRow {
    pub window_id: String,
    pub scope_ref: String,
    pub window_kind: String,
    pub status: String,
    pub effective_from: String,
    pub effective_to: String,
    pub source_revision: String,
    pub document_digest: String,
    pub recorded_at: String,
    pub revision_ref: String,
    pub supersedes_revision_ref: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChangeWindowHistoryCoverage {
    pub source_revision: String,
    pub document_digest: String,
    pub recorded_at: String,
    pub window_count: i64,
    pub watermark: String,
    pub revision_refs: Vec<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ChangeWindowHistoryRead {
    #[allow(clippy::type_complexity)]
    pub coverage: Option<Box<ChangeWindowHistoryCoverage>>,
    pub rows: Vec<ChangeWindowHistoryRow>,
    pub truncated: bool,
    pub source_status: Option<String>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresForecastChangeWindowHistoryConfig {
    pub dsn: String,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresForecastChangeWindowHistoryReader {
    pub initialized: bool,
}

impl PostgresForecastChangeWindowHistoryReader {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn read_history(&self, mut subject_ref: String, mut start_at: String, mut end_at: String, mut known_at: String) -> Result<ChangeWindowHistoryRead, &'static str> {
        if ((subject_ref.clone()).is_empty()) || (((subject_ref.clone()) != (subject_ref.trim().to_string())) || ((((subject_ref.clone()).len() as i64)) > (512_i64))) {
            return Err("forecast change-window history requires one exact subject");
        }
        let mut rows: Vec<ChangeWindowHistoryRow> = Vec::<ChangeWindowHistoryRow>::new();
        let mut truncated: bool = false;
        Ok(ChangeWindowHistoryRead { rows: rows.clone(), truncated: truncated, ..Default::default() })
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn admission_history(mut key: String, mut value: String, mut subject_ref: String, mut start_at: String, mut end_at: String, mut known_at: String, mut snapshot: String) -> Result<ChangeWindowHistoryRead, &'static str> {
    let mut body: String = value.clone();
    let source_revision: String = text(std::collections::BTreeMap::new(), String::from("source_revision")).unwrap_or_else(|_| String::new());
    let document_digest: String = text(std::collections::BTreeMap::new(), String::from("document_digest")).unwrap_or_else(|_| String::new());
    let recorded_at: String = timestamp(std::collections::BTreeMap::new(), String::from("recorded_at")).unwrap_or_else(|_| String::new());
    let body_recorded_at: String = timestamp(std::collections::BTreeMap::new(), String::from("recorded_at")).unwrap_or_else(|_| String::new());
    if (body_recorded_at.clone()) > (recorded_at.clone()) {
        return Err("forecast change-window admission snapshot is from the future");
    }
    Ok(ChangeWindowHistoryRead { coverage: (Some(ChangeWindowHistoryCoverage { source_revision: source_revision.clone(), document_digest: document_digest.clone(), recorded_at: recorded_at.clone(), watermark: key.clone(), ..Default::default() })).map(Box::new), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn coverage(mut value: String) -> Result<ChangeWindowHistoryCoverage, &'static str> {
    if !(false) {
        return Err("forecast change-window coverage is malformed");
    }
    Ok(ChangeWindowHistoryCoverage { source_revision: text(std::collections::BTreeMap::new(), String::from("source_revision")).unwrap_or_else(|_| String::new()), document_digest: text(std::collections::BTreeMap::new(), String::from("document_digest")).unwrap_or_else(|_| String::new()), recorded_at: timestamp(std::collections::BTreeMap::new(), String::from("recorded_at")).unwrap_or_else(|_| String::new()), watermark: text(std::collections::BTreeMap::new(), String::from("watermark")).unwrap_or_else(|_| String::new()), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn row(mut value: String) -> Result<ChangeWindowHistoryRow, &'static str> {
    if !(false) {
        return Err("forecast change-window row is malformed");
    }
    Ok(ChangeWindowHistoryRow { window_id: text(std::collections::BTreeMap::new(), String::from("window_id")).unwrap_or_else(|_| String::new()), scope_ref: text(std::collections::BTreeMap::new(), String::from("scope_ref")).unwrap_or_else(|_| String::new()), window_kind: text(std::collections::BTreeMap::new(), String::from("window_kind")).unwrap_or_else(|_| String::new()), status: text(std::collections::BTreeMap::new(), String::from("status")).unwrap_or_else(|_| String::new()), effective_from: timestamp(std::collections::BTreeMap::new(), String::from("effective_from")).unwrap_or_else(|_| String::new()), effective_to: timestamp(std::collections::BTreeMap::new(), String::from("effective_to")).unwrap_or_else(|_| String::new()), source_revision: text(std::collections::BTreeMap::new(), String::from("source_revision")).unwrap_or_else(|_| String::new()), document_digest: text(std::collections::BTreeMap::new(), String::from("document_digest")).unwrap_or_else(|_| String::new()), recorded_at: timestamp(std::collections::BTreeMap::new(), String::from("recorded_at")).unwrap_or_else(|_| String::new()), revision_ref: text(std::collections::BTreeMap::new(), String::from("revision_ref")).unwrap_or_else(|_| String::new()), ..Default::default() })
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn text(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Result<String, &'static str> {
    let item: Option<String> = (value.clone()).get(key.as_str()).cloned();
    Ok((item.clone()).unwrap_or_default())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn timestamp(mut value: std::collections::BTreeMap<String, String>, mut key: String) -> Result<String, &'static str> {
    let text: String = text(value.clone(), key.clone()).unwrap_or_else(|_| String::new());
    Ok(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn aware(mut value: String) -> bool {
    if value.is_empty() {
        return false;
    }
    false
}

pub const PUBLIC_EXPORTS: &[&str] = &["ChangeWindowHistoryCoverage", "ChangeWindowHistoryRead", "ChangeWindowHistoryRow", "PostgresForecastChangeWindowHistoryConfig", "PostgresForecastChangeWindowHistoryReader"];
