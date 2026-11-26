#[tokio::main]
async fn main() {
    let desc = fdai_deployment_cli::build_service_descriptor();
    if desc.validate().is_err() {
        std::process::exit(1);
    }
    let health = fdai_deployment_cli::probe_healthz();
    let router = fdai_deployment_cli::build_service_http_router();
    let args: Vec<String> = std::env::args().skip(1).collect();

    if args.iter().any(|a| a == "--check" || a == "status") {
        println!(
            "CLI_CHECK_OK service={} health_bytes={} routes={}",
            desc.service_id,
            health.len(),
            router.total_method_bindings()
        );
        return;
    }

    if args.iter().any(|a| a == "verify-assets") {
        let base = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("assets/trust");
        let required = [
            "capabilities.json",
            "deployment-bundle-root.pub",
            "deployment-release-root.pub",
            "upstream-signing-key.pub",
        ];
        for f in required {
            let p = base.join(f);
            if !p.is_file() {
                eprintln!("missing deployment trust asset: {}", p.display());
                std::process::exit(1);
            }
        }
        println!("DEPLOY_ASSETS_OK count={} dir={}", required.len(), base.display());
        return;
    }

    if args.iter().any(|a| a == "--serve") {
        let cfg = fdai_http_runtime::ServerRuntimeConfig::from_env_and_args(
            "fdai-deployment-cli",
            8031,
            false,
            &args,
        );
        if let Err(err) = fdai_http_runtime::serve_axum_http(cfg, router).await {
            eprintln!("axum server error ({}): {err}", desc.service_id);
            std::process::exit(1);
        }
        return;
    }
    println!(
        "CLI_READY service={} health_bytes={} routes={}",
        desc.service_id,
        health.len(),
        router.total_method_bindings()
    );
}
