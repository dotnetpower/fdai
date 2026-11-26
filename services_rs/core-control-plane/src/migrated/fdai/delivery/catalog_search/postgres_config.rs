pub const EMBEDDING_DIM: i64 = 384;

#[derive(Clone, Debug, Default, PartialEq)]
pub struct PostgresCatalogSemanticIndexConfig {
    pub dsn: String,
    pub statement_timeout_ms: i64,
    pub connect_timeout_s: i64,
    pub ivfflat_probes: i64,
    pub write_batch_size: i64,
    pub embedding_batch_size: i64,
    pub embedding_dimension: i64,
    pub ranking_policy: String,
    pub validation_cache_entries: i64,
    pub validation_cache_bytes: i64,
}

impl PostgresCatalogSemanticIndexConfig {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.dsn.trim().is_empty() { return Err("dsn must be non-empty"); }
        if self.ranking_policy.trim().is_empty() { return Err("ranking_policy must be non-empty"); }
        Ok(())
    }
}

