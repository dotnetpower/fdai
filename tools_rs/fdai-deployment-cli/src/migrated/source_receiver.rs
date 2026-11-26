pub const MAX_BOOTSTRAP: i64 = 4194304;

pub const CANONICAL_RELATIVE: &str = "packages/service-contracts/src/fdai_service_contracts/catalog_canonical.py";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn prepare_source_receiver(mut snapshot: String, mut work_dir: String, mut snapshot_digest: String) -> Result<String, &'static str> {
    if snapshot.is_empty() {
        return Err("missing_required_input");
    }
    Err("runtime_binding_required")
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn add(mut archive: String, mut name: String, mut content: Vec<u8>) {
    if archive.is_empty() {
        return;
    }
}

