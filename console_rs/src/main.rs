//! Pure-Rust Axum binary for FDAI Console v4 (`fdai-console-v4`).
//! Default bind: 127.0.0.1:5290 (keeps existing console/ untouched on :5273).

use fdai_console_v4::{build_router, domains, AppState};
use std::net::SocketAddr;
use std::path::PathBuf;

fn detect_repo_root() -> PathBuf {
    if let Ok(env_root) = std::env::var("FDAI_REPO_ROOT") {
        let p = PathBuf::from(env_root);
        if p.is_dir() {
            return p;
        }
    }
    if let Ok(cwd) = std::env::current_dir() {
        for anc in cwd.ancestors() {
            if anc.join("Cargo.toml").is_file() && anc.join("console_rs").is_dir() {
                return anc.to_path_buf();
            }
        }
    }
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut host = std::env::var("FDAI_CONSOLE_V4_HOST").unwrap_or_else(|_| "127.0.0.1".to_string());
    let mut port: u16 = std::env::var("FDAI_CONSOLE_V4_PORT")
        .ok()
        .and_then(|v| v.parse::<u16>().ok())
        .unwrap_or(5290);
    let mut operator_url = std::env::var("FDAI_OPERATOR_URL")
        .unwrap_or_else(|_| "http://127.0.0.1:8010".to_string());
    let mut check_only = false;

    let args: Vec<String> = std::env::args().collect();
    let mut i = 1_usize;
    while i < args.len() {
        match args[i].as_str() {
            "--host" if i + 1 < args.len() => {
                host = args[i + 1].clone();
                i += 2;
            }
            "--port" if i + 1 < args.len() => {
                if let Ok(p) = args[i + 1].parse::<u16>() {
                    port = p;
                }
                i += 2;
            }
            "--operator-url" if i + 1 < args.len() => {
                operator_url = args[i + 1].clone();
                i += 2;
            }
            "--check" => {
                check_only = true;
                i += 1;
            }
            _ => {
                i += 1;
            }
        }
    }

    let repo_root = detect_repo_root();
    let stencil_policy = fdai_console_v4::stencil::StencilPolicy::from_current_env_checked()
        .map_err(|err| format!("invalid Stencil configuration (fail-closed): {err}"))?;
    let state = AppState::from_repo_root_with_local_db(repo_root, operator_url.clone())
        .with_stencil(stencil_policy);

    if check_only {
        println!(
            "fdai-console-v4 --check ok: domains=8 panels={} enabled_panels={} stencil_source={} db_configured={} operator_url={}",
            domains::all_panel_ids().len(),
            state.stencil.enabled_panels.len(),
            state.stencil.source,
            state.db.is_configured(),
            operator_url
        );
        return Ok(());
    }

    let addr: SocketAddr = format!("{host}:{port}").parse()?;
    let db_configured = state.db.is_configured();
    let app = build_router(state);
    let listener = tokio::net::TcpListener::bind(addr).await?;
    println!("fdai-console-v4 listening on http://{addr} (db_configured={db_configured} operator_url={operator_url})");
    axum::serve(listener, app).await?;
    Ok(())
}
