//! CLI entry point for `fdai-sdlc-rs`.

use std::env;
use std::io::{self, Read, Write};
use std::path::Path;
use std::process::ExitCode;

#[path = "lib.rs"]
mod sdlc;

use sdlc::{check_translations, scan_installed_venv, verify_snapshot};

fn main() -> ExitCode {
    let args: Vec<String> = env::args().skip(1).collect();
    let Some(subcommand) = args.first().map(String::as_str) else {
        eprintln!("usage: fdai-sdlc-rs <verify-snapshot|installed-digest|check-translations> ...");
        return ExitCode::from(2);
    };
    match subcommand {
        "verify-snapshot" => cmd_verify_snapshot(&args[1..]),
        "installed-digest" => cmd_installed_digest(&args[1..]),
        "check-translations" => cmd_check_translations(&args[1..]),
        other => {
            eprintln!("fdai-sdlc-rs: unknown subcommand: {other}");
            ExitCode::from(2)
        }
    }
}

fn cmd_verify_snapshot(args: &[String]) -> ExitCode {
    let mut root = None;
    let mut algorithm = "sha1".to_string();
    let mut index = 0;
    while index < args.len() {
        match args[index].as_str() {
            "--root" => {
                index += 1;
                root = args.get(index).cloned();
            }
            "--algorithm" => {
                index += 1;
                if let Some(val) = args.get(index) {
                    algorithm = val.clone();
                }
            }
            other => {
                eprintln!("verify-snapshot: unexpected argument: {other}");
                return ExitCode::from(2);
            }
        }
        index += 1;
    }
    let Some(root_str) = root else {
        eprintln!("verify-snapshot: --root is required");
        return ExitCode::from(2);
    };
    let mut ls_tree = Vec::new();
    if let Err(err) = io::stdin().read_to_end(&mut ls_tree) {
        eprintln!("OSError: {err}");
        return ExitCode::from(1);
    }
    match verify_snapshot(Path::new(&root_str), &algorithm, &ls_tree) {
        Ok(count) => {
            println!("ok {count}");
            ExitCode::SUCCESS
        }
        Err(err) => {
            eprintln!("{err}");
            ExitCode::from(1)
        }
    }
}

fn cmd_installed_digest(args: &[String]) -> ExitCode {
    let mut root = None;
    let mut skip_bytecode = false;
    let mut index = 0;
    while index < args.len() {
        match args[index].as_str() {
            "--root" => {
                index += 1;
                root = args.get(index).cloned();
            }
            "--skip-bytecode" => {
                skip_bytecode = true;
            }
            other => {
                eprintln!("installed-digest: unexpected argument: {other}");
                return ExitCode::from(2);
            }
        }
        index += 1;
    }
    let Some(root_str) = root else {
        eprintln!("installed-digest: --root is required");
        return ExitCode::from(2);
    };
    match scan_installed_venv(Path::new(&root_str), skip_bytecode) {
        Ok(records) => {
            let mut stdout = io::stdout().lock();
            for (rel, imode, link, digest) in records {
                let _ = write!(stdout, "{rel}\0{imode}\0{link}\0{digest}\0");
            }
            ExitCode::SUCCESS
        }
        Err(err) => {
            eprintln!("{err}");
            ExitCode::from(1)
        }
    }
}

fn cmd_check_translations(args: &[String]) -> ExitCode {
    let mut root = None;
    let mut index = 0;
    while index < args.len() {
        match args[index].as_str() {
            "--root" => {
                index += 1;
                root = args.get(index).cloned();
            }
            other => {
                eprintln!("check-translations: unexpected argument: {other}");
                return ExitCode::from(2);
            }
        }
        index += 1;
    }
    let Some(root_str) = root else {
        eprintln!("check-translations: --root is required");
        return ExitCode::from(2);
    };
    let mut input = Vec::new();
    if io::stdin().read_to_end(&mut input).is_err() {
        return ExitCode::from(2);
    }
    let mut english_docs = Vec::new();
    let mut korean_docs = Vec::new();
    for raw in input.split(|&b| b == b'\n') {
        let Ok(line) = std::str::from_utf8(raw) else {
            continue;
        };
        if let Some(rest) = line.strip_prefix("EN\t") {
            if !rest.is_empty() {
                english_docs.push(rest.to_string());
            }
        } else if let Some(rest) = line.strip_prefix("KO\t") {
            if !rest.is_empty() {
                korean_docs.push(rest.to_string());
            }
        }
    }
    let (en_count, ko_count, errors) =
        check_translations(Path::new(&root_str), &english_docs, &korean_docs);
    if !errors.is_empty() {
        for err in &errors {
            eprintln!("{err}");
        }
        eprintln!("check-translations: FAILED with {} violation(s).", errors.len());
        return ExitCode::from(1);
    }
    println!(
        "check-translations: OK ({en_count} English docs, {ko_count} translations verified)"
    );
    ExitCode::SUCCESS
}
