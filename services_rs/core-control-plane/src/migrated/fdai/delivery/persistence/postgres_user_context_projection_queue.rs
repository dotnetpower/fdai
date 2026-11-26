#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub async fn enqueue_projection_upsert(mut connection: String, mut projection_kind: String, mut principal_id: String, mut record_id: String) {
    if connection.is_empty() {
        return;
    }
}

pub const PUBLIC_EXPORTS: &[&str] = &["enqueue_projection_upsert"];
