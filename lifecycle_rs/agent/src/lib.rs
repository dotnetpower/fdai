pub mod migrated;
pub mod sse_guard;
pub mod strangler_oracle;
pub use fdai_domain_core::GateVerdict;
pub use fdai_ports::TransactionalOutboxPort;

#[must_use]
pub fn build_service_descriptor() -> fdai_contracts::ServiceDescriptor {
    fdai_contracts::ServiceDescriptor {
        service_id: String::from("agent"),
        entrypoint: String::from("fdai-agent"),
        kind: fdai_contracts::ServiceKind::HttpApi,
        executor_authority: false,
    }
}

#[must_use]
pub fn build_service_http_router() -> fdai_contracts::http_compat::Router {
    fdai_contracts::http_compat::Router::new()
}

pub fn build_service_axum_routes() -> fdai_http_runtime::axum::Router {
    fdai_http_runtime::axum::Router::new().route(
        "/migrated/routes",
        fdai_http_runtime::axum::routing::get(|| async {
            let r = build_service_http_router();
            let routes: Vec<fdai_http_runtime::serde_json::Value> = r
                .routes
                .iter()
                .map(|(p, ms)| fdai_http_runtime::serde_json::json!({"path": p, "methods": ms}))
                .collect();
            fdai_http_runtime::axum::Json(fdai_http_runtime::serde_json::json!({
                "bindings": r.total_method_bindings(),
                "routes": routes
            }))
        }),
    )
}

#[must_use]
pub fn probe_healthz() -> Vec<u8> { fdai_diagnostics::healthz_json("agent") }

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
