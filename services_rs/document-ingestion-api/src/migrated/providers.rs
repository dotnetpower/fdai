#[derive(Clone, Debug, Default, PartialEq)]
pub struct DocumentDownload {
    pub version: String,
    pub content: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct StewardshipWebhookResult {
    pub accepted: bool,
    pub reason: String,
    pub changed: bool,
}

pub trait ApplicationFactory {
    fn call(&self, environ: std::collections::BTreeMap<String, String>) -> String;
}

pub trait DocumentDeletionService {
    fn delete(&self, actor_id: String, actor_groups: std::collections::BTreeSet<String>, document_id: String, version_id: String) -> String;
}

pub trait DocumentPreviewService {
    fn preview(&self, actor_id: String, actor_groups: std::collections::BTreeSet<String>, document_id: String, version_id: String) -> String;
}

pub trait DocumentDownloadService {
    fn supports_protected_source_download(&self) -> bool;
    fn download(&self, actor_id: String, actor_groups: std::collections::BTreeSet<String>, document_id: String, version_id: String) -> String;
}

pub trait HandoverArtifact {
    fn to_dict(&self) -> String;
}

pub trait HandoverDraftReader {
    fn get(&self, upload_id: String) -> String;
}

pub trait StewardshipWebhook {
    fn handle(&self, headers: std::collections::BTreeMap<String, String>, body: Vec<u8>) -> String;
}

