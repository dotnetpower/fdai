pub const MAX_RECORDS: i64 = 50000;
pub const MAX_BYTES: i64 = 67108864;

pub const CHECKPOINT_KEY: &str = "pantheon/saga/audit-chain/verified-head";
#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn migrate_saga_audit_chain(mut store: String, mut expected_plan_digest: Option<String>, mut legacy_writers_quiesced: bool, mut preserve_detached_histories: bool) -> Result<String, &'static str> {
    if (expected_plan_digest.is_some()) && (!(legacy_writers_quiesced)) {
        return Err("stop legacy Saga writers before applying the reviewed migration");
    }
    Ok(String::new())
}

