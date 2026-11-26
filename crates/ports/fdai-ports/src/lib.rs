pub mod migrated;
pub use fdai_contracts::RuntimeScopeReceipt;
pub use fdai_domain_core::GateVerdict;

pub trait TransactionalOutboxPort {
    fn stage_outbox_event(&mut self, idempotency_key: &str, topic: &str, payload: &[u8]) -> Result<bool, &'static str>;
}

pub trait EventBusConsumerPort {
    fn commit_offset_after_outbox(&mut self, offset: u64, outbox_ok: bool) -> Result<u64, &'static str>;
}

pub trait KeylessCloudPort {
    fn is_keyless_managed_identity(&self) -> bool;
}

/// Port contract for bitemporal ontology topology, Azure telemetry series,
/// and empirically promoted causal edge persistence.
pub trait TemporalCausalStorePort {
    fn build_topology_as_of_query(
        &self,
        subscription_id: &str,
        as_of_iso: &str,
        effective_iso: &str,
    ) -> Result<String, &'static str>;

    fn build_telemetry_window_query(
        &self,
        resource_id: &str,
        concept: &str,
        from_iso: &str,
        cutoff_iso: &str,
        limit: usize,
    ) -> Result<String, &'static str>;
}
