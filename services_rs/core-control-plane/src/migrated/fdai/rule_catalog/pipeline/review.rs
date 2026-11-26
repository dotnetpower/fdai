pub const MAX_REVIEW_REF_LENGTH: i64 = 512;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct MirroredSnapshotFile {
    pub relative_path: String,
    pub storage_ref: String,
    pub digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CollectionReviewPackage {
    pub source_id: String,
    pub resolved_revision: String,
    pub content_sha256: String,
    pub license: String,
    pub redistribution: String,
    pub verified_rules: i64,
    pub verified_at: String,
    pub snapshot_files: Vec<MirroredSnapshotFile>,
    pub content_digest: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct CollectionReviewPublicationReceipt {
    pub package_digest: String,
    pub review_ref: String,
    pub already_existed: bool,
}

pub const SHA256: &str = "^[0-9a-f]{64}$";
impl CollectionReviewPackage {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::too_many_arguments)]
    pub fn build(mut source_id: String, mut resolved_revision: String, mut content_sha256: String, mut license: String, mut redistribution: String, mut verified_rules: i64, mut verified_at: String, mut snapshot_files: Vec<MirroredSnapshotFile>) -> Result<CollectionReviewPackage, &'static str> {
        if ((source_id.trim().to_string()).is_empty()) || (((resolved_revision.clone()).trim().to_string()).is_empty()) {
            return Err("collection review package requires a source id and revision");
        }
        let material: std::collections::BTreeMap<String, String> = std::collections::BTreeMap::from([(String::from("source_id"), source_id.clone()), (String::from("resolved_revision"), resolved_revision.clone()), (String::from("content_sha256"), content_sha256.clone()), (String::from("license"), license.clone()), (String::from("redistribution"), redistribution.clone()), (String::from("verified_rules"), String::new()), (String::from("snapshot_files"), String::new())]);
        Err("runtime_binding_required")
    }
}

pub trait CollectionReviewPublisher {
    fn publish(&self, package: CollectionReviewPackage) -> CollectionReviewPublicationReceipt;
}

pub const PUBLIC_EXPORTS: &[&str] = &["CollectionReviewPackage", "CollectionReviewPublicationReceipt", "CollectionReviewPublisher", "MirroredSnapshotFile"];
