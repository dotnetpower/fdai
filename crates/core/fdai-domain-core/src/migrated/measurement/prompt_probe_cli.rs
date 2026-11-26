pub const ENV_CATALOG_ROOT: &str = "FDAI_CATALOG_ROOT";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn resolve_catalog_root() -> Result<String, &'static str> {
    Err("could not locate rule-catalog. Set FDAI_CATALOG_ROOT to point at the tre")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn run_from_catalog(mut catalog_root: String, mut responder: String) -> String {
    if catalog_root.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn row_to_json_line(mut row: String) -> String {
    if row.is_empty() {
        return String::new();
    }
    String::new()
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn main() -> i64 {
    let catalog_root: String = resolve_catalog_root().unwrap_or_else(|_| String::new());
    let report: String = run_from_catalog(catalog_root.clone(), String::new()).await;
    0_i64
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn main_fn() -> i64 {
    0_i64
}

