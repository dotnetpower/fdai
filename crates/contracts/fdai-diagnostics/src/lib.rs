pub mod migrated;
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct ReadinessGate {
    pub opa_verified: bool,
    pub bus_ready: bool,
    pub store_ready: bool,
}

impl ReadinessGate {
    #[must_use]
    pub const fn is_ready(&self) -> bool {
        self.opa_verified && self.bus_ready && self.store_ready
    }
}

#[must_use]
pub fn healthz_json(service_id: &str) -> Vec<u8> {
    fdai_contracts::canonical_kv_jcs_bytes(&[("service", service_id), ("status", "ok")])
}
