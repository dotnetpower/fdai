pub mod ops;

use std::fs;
use std::path::Path;

const FORBIDDEN_CORE_IO: [&str; 8] = [
    "axum", "reqwest", "sqlx", "rdkafka", "azure_", "tokio", "std::net", "std::process::Command",
];
const FORBIDDEN_INTERPRETER_TOKENS: [&str; 11] = [
    "\"python\"", "\"python3\"", "/bin/python", "\"uv\"", "\"pytest\"",
    "\"uvicorn\"", "\"gunicorn\"", "\"alembic\"", "\"poetry\"", "\"pip\"", "\"pip3\"",
];
const ATTRIBUTION_TOKEN_A: [u8; 4] = [98, 111, 114, 105];
const ATTRIBUTION_TOKEN_B: [u8; 9] = [97, 103, 101, 110, 116, 45, 115, 97, 110];
const ATTRIBUTION_TOKEN_C: [u8; 9] = [97, 103, 101, 110, 116, 95, 115, 97, 110];

fn has_ascii_ci_token(hay: &[u8], needle_lower: &[u8], word_bounded: bool) -> bool {
    if needle_lower.is_empty() || hay.len() < needle_lower.len() {
        return false;
    }
    for i in 0..=(hay.len() - needle_lower.len()) {
        let matched = hay[i..i + needle_lower.len()]
            .iter()
            .zip(needle_lower.iter())
            .all(|(a, b)| a.to_ascii_lowercase() == *b);
        if matched {
            if !word_bounded {
                return true;
            }
            let prev_alpha = i > 0 && hay[i - 1].is_ascii_alphabetic();
            let next_alpha = i + needle_lower.len() < hay.len() && hay[i + needle_lower.len()].is_ascii_alphabetic();
            if !prev_alpha && !next_alpha {
                return true;
            }
        }
    }
    false
}

fn check_no_forbidden_attribution(path: &Path, bytes: &[u8]) -> Result<(), String> {
    if has_ascii_ci_token(bytes, &ATTRIBUTION_TOKEN_A, true)
        || has_ascii_ci_token(bytes, &ATTRIBUTION_TOKEN_B, false)
        || has_ascii_ci_token(bytes, &ATTRIBUTION_TOKEN_C, false)
    {
        return Err(format!("Zero-Attribution violation in {}", path.display()));
    }
    Ok(())
}

pub fn verify_workspace_zero_python_and_core_isolation(workspace_root: &Path) -> Result<usize, String> {
    let deny = fs::read_to_string(workspace_root.join("deny.toml")).map_err(|e| e.to_string())?;
    for banned in ["pyo3", "rustpython", "inline-python"] {
        if !deny.contains(banned) {
            return Err(format!("deny.toml missing ban for {banned}"));
        }
    }
    for root_cfg in ["Cargo.toml", "deny.toml", "rust_cutover_manifest.json", ".githooks/zero-python-pre-commit.sh"] {
        let p = workspace_root.join(root_cfg);
        if p.is_file() {
            let bytes = fs::read(&p).map_err(|e| e.to_string())?;
            check_no_forbidden_attribution(&p, &bytes)?;
        }
    }
    let manifest_raw = fs::read_to_string(workspace_root.join("rust_cutover_manifest.json")).unwrap_or_default();
    let enforce_zero_py_all = manifest_raw.contains("\"mode\": \"greenfield\"")
        || manifest_raw.contains("\"cutover_complete\": true");
    let crates_dir = if workspace_root.join("crates_rs/core").is_dir() { "crates_rs" } else { "crates" };
    let mut checked = 0_usize;
    check_core_layer_isolation(&workspace_root.join(format!("{crates_dir}/core")), &mut checked)?;
    check_real_infra_adapters_and_ops(workspace_root, crates_dir, &mut checked)?;
    if enforce_zero_py_all {
        scan_tree_for_bypasses_and_py(workspace_root, true, false, &mut checked)?;
    } else {
        for rdir in ["crates", "crates_rs", "services_rs", "lifecycle_rs", "extensions_rs", "benchmarks_rs", "tools_rs", "migrations", "migrations_rs", "deploy_rs"] {
            let rp = workspace_root.join(rdir);
            if let Ok(meta) = fs::symlink_metadata(&rp) {
                if meta.file_type().is_symlink() {
                    return Err(format!("Forbidden symlink inside workspace: {}", rp.display()));
                }
                if meta.is_dir() {
                    scan_tree_for_bypasses_and_py(&rp, true, false, &mut checked)?;
                }
            }
        }
        for fallback_dir in ["services", "lifecycle", "extensions", "benchmarks", "tools"] {
            let rs_alt = workspace_root.join(format!("{fallback_dir}_rs"));
            let plain = workspace_root.join(fallback_dir);
            if !rs_alt.exists() && plain.is_dir() {
                scan_tree_for_bypasses_and_py(&plain, false, false, &mut checked)?;
            }
        }
    }
    Ok(checked)
}

fn check_real_infra_adapters_and_ops(workspace_root: &Path, crates_dir: &str, checked: &mut usize) -> Result<(), String> {
    let adapters_root = workspace_root.join(format!("{crates_dir}/adapters"));
    if let Ok(rd) = fs::read_dir(&adapters_root) {
        for entry in rd.filter_map(Result::ok) {
            let p = entry.path();
            if !entry.file_type().is_ok_and(|t| !t.is_symlink() && t.is_dir()) {
                continue;
            }
            let toml = fs::read_to_string(p.join("Cargo.toml")).unwrap_or_default();
            if !toml.contains("tokio") && !toml.contains("hyper-rustls") && !toml.contains("axum") {
                return Err(format!("Adapter stub detected without async network driver in {}", p.display()));
            }
            *checked += 1;
        }
    }
    let mig_dir = if workspace_root.join("migrations_rs").is_dir() { "migrations_rs" } else { "migrations" };
    let mig_manifest = workspace_root.join(format!("{mig_dir}/0000_migration_manifest.json"));
    if mig_manifest.is_file() {
        let raw = fs::read(&mig_manifest).map_err(|e| e.to_string())?;
        check_no_forbidden_attribution(&mig_manifest, &raw)?;
        *checked += 1;
    }
    let dockerfile = workspace_root.join("deploy_rs/Dockerfile.distroless");
    if dockerfile.is_file() {
        let raw = fs::read(&dockerfile).map_err(|e| e.to_string())?;
        check_no_forbidden_attribution(&dockerfile, &raw)?;
        *checked += 1;
    }
    check_k8s_yaml_indentation(workspace_root, checked)?;
    check_azure_iam_permission_groups_catalog(workspace_root, checked)?;
    check_promoted_rust_assets(workspace_root, checked)?;
    check_hollow_fn_ratchet(workspace_root, checked)?;
    Ok(())
}

fn check_promoted_rust_assets(workspace_root: &Path, checked: &mut usize) -> Result<(), String> {
    let required_assets = [
        "services_rs/core-control-plane/assets/fdai/delivery/trust/upstream-signing-key.pub",
        "tools_rs/fdai-deployment-cli/assets/trust/deployment-bundle-root.pub",
        "tools_rs/fdai-deployment-cli/assets/trust/deployment-release-root.pub",
        "tools_rs/fdai-deployment-cli/assets/trust/upstream-signing-key.pub",
        "services_rs/core-control-plane/assets/fdai/core/notifications/messages.en.json",
        "services_rs/core-control-plane/assets/fdai/core/notifications/messages.ko.json",
        "console_rs/assets/agent-icons/odin.svg",
        "lifecycle_rs/hub/ui/dist/index.html",
        "lifecycle_rs/release-hub/ui/dist/index.html",
    ];
    for rel in required_assets {
        let p = workspace_root.join(rel);
        if !p.is_file() {
            return Err(format!("Missing promoted Rust runtime asset: {rel}"));
        }
        *checked += 1;
    }
    Ok(())
}

fn check_azure_iam_permission_groups_catalog(
    workspace_root: &Path,
    checked: &mut usize,
) -> Result<(), String> {
    let catalog_path = workspace_root.join("config/azure-iam-permission-groups.json");
    if !catalog_path.is_file() {
        return Err(format!(
            "Missing canonical Azure IAM permission groups catalog: {}",
            catalog_path.display()
        ));
    }
    let raw = fs::read_to_string(&catalog_path).map_err(|e| e.to_string())?;
    check_no_forbidden_attribution(&catalog_path, raw.as_bytes())?;
    let catalog = fdai_contracts::azure_iam_groups::parse_azure_iam_catalog_json(&raw)?;
    fdai_domain_core::azure_iam_catalog::validate_azure_iam_catalog(&catalog)
        .map_err(|errs| format!("Azure IAM catalog validation failed: {}", errs.join("; ")))?;
    *checked += 1;
    Ok(())
}

const MAX_ALLOWED_HOLLOW_FNS: usize = 0;

fn check_k8s_yaml_indentation(workspace_root: &Path, checked: &mut usize) -> Result<(), String> {
    let k8s = workspace_root.join("deploy_rs/k8s-operator-deployment.yaml");
    if k8s.is_file() {
        let raw = fs::read_to_string(&k8s).map_err(|e| e.to_string())?;
        if !raw.contains("\n  name:") || !raw.contains("\n      containers:") {
            return Err(format!("K8s Deployment YAML indentation broken in {}", k8s.display()));
        }
        *checked += 1;
    }
    Ok(())
}

fn check_hollow_fn_ratchet(workspace_root: &Path, checked: &mut usize) -> Result<(), String> {
    let mut hollow_est = 0_usize;
    for rdir in ["services_rs", "lifecycle_rs", "extensions_rs", "benchmarks_rs", "tools_rs", "crates"] {
        let root = workspace_root.join(rdir);
        if root.is_dir() {
            count_hollow_markers(&root, &mut hollow_est);
        }
    }
    if hollow_est > MAX_ALLOWED_HOLLOW_FNS {
        return Err(format!("Hollow function ratchet exceeded: {hollow_est} > {MAX_ALLOWED_HOLLOW_FNS}"));
    }
    *checked += 1;
    Ok(())
}

fn count_hollow_markers(dir: &Path, count: &mut usize) {
    let Ok(rd) = fs::read_dir(dir) else { return };
    for entry in rd.filter_map(Result::ok) {
        let Ok(ft) = entry.file_type() else { continue };
        if ft.is_symlink() { continue; }
        let p = entry.path();
        if ft.is_dir() {
            let nm = entry.file_name();
            if !matches!(nm.to_str(), Some("target" | ".git")) {
                count_hollow_markers(&p, count);
            }
        } else if p.to_string_lossy().contains("/migrated/")
            && p.extension().and_then(|e| e.to_str()) == Some("rs")
        {
            if let Ok(src) = fs::read_to_string(&p) {
                for marker in [
                    "Ok(Default::default())",
                    "self.initialized && false",
                    "let _guard_checked = true;",
                    "let resolved = Default::default();",
                    "let result = Default::default();",
                    "let result = String::new();",
                    "let result = Vec::new();",
                    "let result = None;",
                    "let result = false;",
                ] {
                    *count += src.matches(marker).count();
                }
            }
        }
    }
}

fn check_core_layer_isolation(core_root: &Path, checked: &mut usize) -> Result<(), String> {
    let Ok(rd) = fs::read_dir(core_root) else { return Ok(()) };
    for entry in rd.filter_map(Result::ok) {
        let p = entry.path();
        if let Ok(toml) = fs::read_to_string(p.join("Cargo.toml")) {
            for io_dep in FORBIDDEN_CORE_IO {
                if toml.contains(io_dep) {
                    return Err(format!("Hexagonal violation in {}: depends on {io_dep}", p.display()));
                }
            }
            *checked += 1;
        }
        scan_core_rs_sources(&p.join("src"), checked)?;
    }
    Ok(())
}

fn scan_core_rs_sources(dir: &Path, checked: &mut usize) -> Result<(), String> {
    const CORE_IMPORT_BANS: [&str; 14] = [
        "use axum", "axum::", "use reqwest", "reqwest::", "use sqlx", "sqlx::",
        "use rdkafka", "rdkafka::", "use azure_", "azure_identity::", "use tokio", "tokio::",
        "std::net::", "process::Command",
    ];
    let Ok(rd) = fs::read_dir(dir) else { return Ok(()) };
    for entry in rd.filter_map(Result::ok) {
        let p = entry.path();
        if entry.file_type().is_ok_and(|t| t.is_dir()) {
            scan_core_rs_sources(&p, checked)?;
        } else if p.extension().and_then(|e| e.to_str()) == Some("rs") {
            let src = fs::read_to_string(&p).map_err(|e| e.to_string())?;
            for io_tok in CORE_IMPORT_BANS {
                if src.contains(io_tok) {
                    return Err(format!("Hexagonal core source violation in {}: uses {io_tok}", p.display()));
                }
            }
            *checked += 1;
        }
    }
    Ok(())
}

fn scan_tree_for_bypasses_and_py(dir: &Path, enforce_zero_py: bool, in_xtask: bool, count: &mut usize) -> Result<(), String> {
    let Ok(rd) = fs::read_dir(dir) else { return Ok(()) };
    for entry in rd.filter_map(Result::ok) {
        let Ok(ft) = entry.file_type() else { continue };
        if ft.is_symlink() {
            let p_str = entry.path().to_string_lossy().replace('\\', "/");
            if p_str.contains("/site/src/content/docs/") && p_str.ends_with(".md") {
                continue;
            }
            return Err(format!("Forbidden symlink inside workspace: {}", entry.path().display()));
        }
        let p = entry.path();
        let nm = entry.file_name();
        let Some(ns) = nm.to_str() else { continue };
        if ft.is_dir() {
            if !ns.starts_with('.')
                && ns != "target"
                && ns != "node_modules"
                && ns != "_archive"
            {
                let rel_tail = p.to_string_lossy().replace('\\', "/");
                if rel_tail.ends_with("/rule-catalog/code-security") {
                    continue;
                }
                scan_tree_for_bypasses_and_py(&p, enforce_zero_py, in_xtask || ns.ends_with("-xtask"), count)?;
            }
            continue;
        }
        let is_legacy_py_artifact = [
            ".py", ".pyi", ".pyx", ".pxd", ".pyc", ".pyo", ".pyw", ".whl", ".pth", ".ipynb",
        ]
        .iter()
        .any(|ext| ns.ends_with(ext))
            || matches!(
                ns,
                "pyproject.toml"
                    | "uv.lock"
                    | "Pipfile"
                    | "Pipfile.lock"
                    | "poetry.lock"
                    | "setup.cfg"
                    | ".python-version"
            )
            || (ns.starts_with("requirements") && ns.ends_with(".txt"));
        if enforce_zero_py && is_legacy_py_artifact {
            return Err(format!("Zero-Python violation: legacy file remains at {}", p.display()));
        }
        if [".rs", ".toml", ".sql", ".sh", ".json"].iter().any(|ext| ns.ends_with(ext)) {
            let bytes = fs::read(&p).map_err(|e| e.to_string())?;
            check_no_forbidden_attribution(&p, &bytes)?;
        }
        if ns == "Cargo.toml" {
            let toml = fs::read_to_string(&p).map_err(|e| e.to_string())?;
            for ffi_ban in ["pyo3", "cpython", "libpython", "numpy"] {
                if toml.contains(ffi_ban) {
                    return Err(format!("Zero-Python FFI dependency violation ({ffi_ban}) in {}", p.display()));
                }
            }
        }
        if ns.ends_with(".rs") {
            if !in_xtask {
                let src = fs::read_to_string(&p).map_err(|e| e.to_string())?;
                let spawns_proc = src.contains("Command::new") || src.contains("process::Command");
                if spawns_proc && FORBIDDEN_INTERPRETER_TOKENS.iter().any(|tok| src.contains(tok)) {
                    return Err(format!("Zero-Python subprocess/env bypass detected in {}", p.display()));
                }
            }
            *count += 1;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn enforces_zero_python_zero_attribution_and_hexagonal_core_isolation() {
        let mdir = std::env::var_os("CARGO_MANIFEST_DIR")
            .map_or_else(|| std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")), std::path::PathBuf::from);
        let ws_root = mdir.join("../..");
        assert_eq!(verify_workspace_zero_python_and_core_isolation(&ws_root).err(), None);
    }
}
