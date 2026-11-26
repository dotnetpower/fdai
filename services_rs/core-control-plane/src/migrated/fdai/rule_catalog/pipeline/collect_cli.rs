#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn repo_root() -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
pub fn build_parser() -> String {
    core::hint::black_box(String::new())
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[allow(clippy::type_complexity)]
pub fn main(mut argv: Option<Vec<String>>) -> Result<i64, &'static str> {
    let mut summary: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("source_id"), String::new()), (String::from("resolved_revision"), String::new()), (String::from("content_sha256"), String::new()), (String::from("file_count"), String::new()), (String::from("parser"), String::new()), (String::from("license"), String::new()), (String::from("redistribution"), String::new()), (String::from("snapshot_dir"), String::new()), (String::from("mismatch"), String::new()), (String::from("dry_run"), String::new())]);
    let mut exit_code: i64 = 0_i64;
    Ok(exit_code)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn run_land(mut report_snapshot_dir: String, mut parser_name: String, mut resolved_revision: String, mut output_root: String, mut dry_run: bool) -> (std::collections::BTreeMap<String, String>, i64) {
    if dry_run {
        return (std::collections::BTreeMap::from([(String::from("skipped"), String::from("dry-run"))]), 0_i64);
    }
    if (parser_name.clone()) != (String::from("azure-policy-json")) {
        let message: String = format!("landing supports only azure-policy-json sources, not {}", parser_name.clone());
        return (std::collections::BTreeMap::from([(String::from("error"), message.clone())]), 2_i64);
    }
    (std::collections::BTreeMap::from([(String::from("landed"), String::new()), (String::from("written"), String::new()), (String::from("unchanged"), String::new()), (String::from("withdrawn"), String::new()), (String::from("skipped_collisions"), String::new())]), 0_i64)
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
#[must_use]
#[allow(clippy::type_complexity)]
pub fn run_verify(mut report_snapshot_dir: String, mut parser_name: String, mut catalog_root: String, mut dry_run: bool) -> (std::collections::BTreeMap<String, String>, i64) {
    if dry_run {
        return (std::collections::BTreeMap::from([(String::from("skipped"), String::from("dry-run")), (String::from("issues"), String::new())]), 0_i64);
    }
    let parser_impl: String = build_parser();
    let summary: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("parser"), parser_name.clone()), (String::from("parsed"), String::new()), (String::from("verified"), String::new()), (String::from("issues"), String::new())]);
    (std::collections::BTreeMap::new(), 0_i64)
}

pub const PUBLIC_EXPORTS: &[&str] = &["main"];
