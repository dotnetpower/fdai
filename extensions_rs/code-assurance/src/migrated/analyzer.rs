#[derive(Clone, Debug, Default, PartialEq)]
pub struct Rule {
    pub rule_id: String,
    pub severity: String,
    pub category: String,
    pub pattern: String,
    pub message: String,
    pub profiles: Vec<String>,
    pub excluded_pattern: Option<String>,
}

pub const HUNK: &str = "^@@ -\\d+(?:,\\d+)? \\+(\\d+)(?:,\\d+)? @@";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn analyze_snapshot(mut snapshot: String, mut profile: String) -> String {
    let mut findings: Vec<String> = Vec::<String>::new();
    let mut omitted: Vec<String> = Vec::<String>::new();
    let mut reviewed_files: i64 = 0_i64;
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn added_lines(mut patch: String) -> Vec<(i64, String)> {
    let mut next_line: Option<i64> = None;
    Vec::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn evaluate_line(mut path: String, mut line_number: i64, mut line: String, mut profile: String) -> Vec<String> {
    if path.is_empty() {
        return Vec::new();
    }
    Vec::new()
}

pub const PUBLIC_EXPORTS: &[&str] = &["analyze_snapshot"];
