#[tokio::main]
async fn main() {
    let desc = fdai_core_control_plane::build_service_descriptor();
    if desc.validate().is_err() { std::process::exit(1); }
    let health = fdai_core_control_plane::probe_healthz();
    let router = fdai_core_control_plane::build_service_http_router();
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.iter().any(|a| a == "--check" || a == "--self-test") {
        let auth_mode = fdai_http_runtime::OperatorAuthenticator::from_env()
            .map(|a| a.mode_label())
            .unwrap_or("config-error");
        println!("SERVICE_READY service={} runtime=axum-0.8 auth={} health_bytes={} routes={}", desc.service_id, auth_mode, health.len(), router.total_method_bindings());
        return;
    }
    let cfg = fdai_http_runtime::ServerRuntimeConfig::from_env_and_args(
        "core-control-plane",
        8014,
        false,
        &args,
    );
    let service_routes = fdai_core_control_plane::build_service_axum_routes();
    if let Err(err) = fdai_http_runtime::serve_axum_http_with_routes(cfg, router, service_routes).await {
        eprintln!("axum server error ({}): {err}", desc.service_id);
        std::process::exit(1);
    }
}
