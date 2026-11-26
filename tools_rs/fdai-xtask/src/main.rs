fn main() {
    let cwd = std::env::current_dir().unwrap_or_else(|_| std::path::PathBuf::from("."));
    let mdir = std::env::var_os("CARGO_MANIFEST_DIR").map_or_else(
        || std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")),
        std::path::PathBuf::from,
    );
    let root = if cwd.join("deny.toml").is_file() {
        cwd
    } else {
        mdir.join("../..")
    };
    let args: Vec<String> = std::env::args().skip(1).collect();
    let cmd = args.first().map(String::as_str).unwrap_or("verify");

    let res: Result<String, String> = match cmd {
        "verify" => fdai_xtask::verify_workspace_zero_python_and_core_isolation(&root)
            .map(|n| format!("Zero-Python & Hexagonal Core gate PASS ({n} items verified)")),
        "check-migrations" => fdai_xtask::ops::check_migrations_integrity(&root)
            .map(|n| format!("SQL migrations integrity PASS ({n} files verified)")),
        "integrity-manifest" => {
            let check_only = args.iter().any(|a| a == "--check");
            let out_rel = args
                .windows(2)
                .find(|w| w[0] == "--out")
                .map(|w| w[1].as_str());
            let source = args
                .windows(2)
                .find(|w| w[0] == "--source")
                .map(|w| w[1].as_str())
                .unwrap_or("worktree");
            fdai_xtask::ops::run_integrity_manifest(&root, check_only, out_rel, source)
                .map(|n| format!("Integrity manifest OK ({n} framework-surface files hashed, source={source})"))
        }
        "check-hygiene" => fdai_xtask::ops::check_repo_hygiene(&root)
            .map(|n| format!("Pure-Rust hygiene gate PASS ({n} files verified)")),
        "pre-commit" => {
            fdai_xtask::ops::check_staged_zero_python(&root).and_then(|staged| {
                let verified =
                    fdai_xtask::verify_workspace_zero_python_and_core_isolation(&root)?;
                let migs = fdai_xtask::ops::check_migrations_integrity(&root)?;
                let hygiene = fdai_xtask::ops::check_repo_hygiene(&root)?;
                Ok(format!(
                    "Pre-commit Rust gate PASS (staged={staged}, verified={verified}, migrations={migs}, hygiene={hygiene})"
                ))
            })
        }
        "pre-push" => {
            fdai_xtask::verify_workspace_zero_python_and_core_isolation(&root).and_then(|verified| {
                let migs = fdai_xtask::ops::check_migrations_integrity(&root)?;
                let hygiene = fdai_xtask::ops::check_repo_hygiene(&root)?;
                Ok(format!(
                    "Pre-push Rust gate PASS (verified={verified}, migrations={migs}, hygiene={hygiene})"
                ))
            })
        }
        other => Err(format!(
            "unknown fdai-xtask subcommand: {other} (supported: verify, check-migrations, check-hygiene, integrity-manifest, pre-commit, pre-push)"
        )),
    };

    match res {
        Ok(msg) => println!("{msg}"),
        Err(e) => {
            eprintln!("fdai-xtask failed: {e}");
            std::process::exit(1);
        }
    }
}
