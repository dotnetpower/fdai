pub trait ArtifactResidueProbe {
    fn artifact_exists(&self, document_id: String, version_id: String) -> String;
}

pub trait SourceResidueProbe {
    fn source_exists(&self, object_key: String) -> String;
}

pub trait DocumentPurgeVerifier {
    fn verify(&self, document_id: String, version_id: String, source_object_keys: Vec<String>) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PurgeVerificationError {
    pub message: String,
}

impl PurgeVerificationError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for PurgeVerificationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for PurgeVerificationError {}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PostgresDocumentPurgeVerifier {
    pub initialized: bool,
}

impl PostgresDocumentPurgeVerifier {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub async fn verify(&self, mut document_id: String, mut version_id: String, mut source_object_keys: Vec<String>) -> Result<String, &'static str> {
        let doc_id: String = format!("governed:{}:{}", document_id.clone(), version_id.clone());
        let mut source_objects: i64 = 0_i64;
        Ok(String::new())
    }
}

