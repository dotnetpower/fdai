pub mod migrated;
pub mod sse_guard;
pub mod strangler_oracle;
pub use fdai_domain_core::GateVerdict;
pub use fdai_ports::TransactionalOutboxPort;

#[must_use]
pub fn build_service_descriptor() -> fdai_contracts::ServiceDescriptor {
    fdai_contracts::ServiceDescriptor {
        service_id: String::from("code-assurance"),
        entrypoint: String::from("fdai-code-assurance"),
        kind: fdai_contracts::ServiceKind::HttpApi,
        executor_authority: false,
    }
}

#[must_use]
pub fn build_service_http_router() -> fdai_contracts::http_compat::Router {
    fdai_contracts::http_compat::Router::new()
}

#[must_use]
pub fn probe_healthz() -> Vec<u8> { fdai_diagnostics::healthz_json("code-assurance") }

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;
    #[test]
    fn descriptor_and_sse_drop_cancellation_safety_hold() {
        assert_eq!(build_service_descriptor().validate(), Ok(()));
        let _ = build_service_http_router();
        let leases = Arc::new(AtomicUsize::new(0));
        { let _g = sse_guard::SseLeaseDropGuard::acquire(Arc::clone(&leases)); assert_eq!(leases.load(Ordering::SeqCst), 1); }
        assert_eq!(leases.load(Ordering::SeqCst), 0);
    }
}
