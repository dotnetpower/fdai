//! CLI entry point for `fdai-sdlc-rs`.

use std::env;
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::process::ExitCode;

#[path = "lib.rs"]
mod sdlc;

use sdlc::{
    check_translations, compute_worktree_digests, count_file_lines, scan_core_fanout,
    scan_installed_venv, verify_snapshot,
};

fn require_arg_value<'a>(args: &'a [String], index: &mut usize, flag: &str) -> Result<&'a str, ()> {
    *index += 1;
    let Some(val) = args.get(*index).map(String::as_str) else {
        eprintln!("{flag}: missing value");
        return Err(());
    };
    if val.is_empty() || val.starts_with("--") {
        eprintln!("{flag}: invalid value '{val}'");
        return Err(());
    }
    Ok(val)
}

fn main() -> ExitCode {
    let args: Vec<String> = env::args().skip(1).collect();
    let Some(subcommand) = args.first().map(String::as_str) else {
        eprintln!(
            "usage: fdai-sdlc-rs <verify-snapshot|installed-digest|worktree-digests|check-translations|count-lines|scan-core-fanout> ..."
        );
        return ExitCode::from(2);
    };
    match subcommand {
        "verify-snapshot" => cmd_verify_snapshot(&args[1..]),
        "installed-digest" => cmd_installed_digest(&args[1..]),
        "worktree-digests" => cmd_worktree_digests(&args[1..]),
        "check-translations" => cmd_check_translations(&args[1..]),
        "count-lines" => cmd_count_lines(&args[1..]),
        "scan-core-fanout" => cmd_scan_core_fanout(&args[1..]),
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
                let Ok(val) = require_arg_value(args, &mut index, "--root") else {
                    return ExitCode::from(2);
                };
                root = Some(val.to_string());
            }
            "--algorithm" => {
                let Ok(val) = require_arg_value(args, &mut index, "--algorithm") else {
                    return ExitCode::from(2);
                };
                algorithm = val.to_string();
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
                let Ok(val) = require_arg_value(args, &mut index, "--root") else {
                    return ExitCode::from(2);
                };
                root = Some(val.to_string());
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

fn cmd_worktree_digests(args: &[String]) -> ExitCode {
    let mut root = None;
    let mut excluded: Vec<PathBuf> = Vec::new();
    let mut index = 0;
    while index < args.len() {
        match args[index].as_str() {
            "--root" => {
                let Ok(val) = require_arg_value(args, &mut index, "--root") else {
                    return ExitCode::from(2);
                };
                root = Some(val.to_string());
            }
            "--exclude" => {
                let Ok(val) = require_arg_value(args, &mut index, "--exclude") else {
                    return ExitCode::from(2);
                };
                excluded.push(PathBuf::from(val));
            }
            other => {
                eprintln!("worktree-digests: unexpected argument: {other}");
                return ExitCode::from(2);
            }
        }
        index += 1;
    }
    let Some(root_str) = root else {
        eprintln!("worktree-digests: --root is required");
        return ExitCode::from(2);
    };
    let mut listed = Vec::new();
    if let Err(err) = io::stdin().read_to_end(&mut listed) {
        eprintln!("OSError: {err}");
        return ExitCode::from(1);
    }
    match compute_worktree_digests(Path::new(&root_str), &excluded, &listed) {
        Ok((content_hex, status_hex)) => {
            println!("{content_hex} {status_hex}");
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
                let Ok(val) = require_arg_value(args, &mut index, "--root") else {
                    return ExitCode::from(2);
                };
                root = Some(val.to_string());
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

fn parse_only_root(args: &[String], cmd: &str) -> Result<String, ExitCode> {
    let mut root = None;
    let mut index = 0;
    while index < args.len() {
        match args[index].as_str() {
            "--root" => {
                let Ok(val) = require_arg_value(args, &mut index, "--root") else {
                    return Err(ExitCode::from(2));
                };
                root = Some(val.to_string());
            }
            other => {
                eprintln!("{cmd}: unexpected argument: {other}");
                return Err(ExitCode::from(2));
            }
        }
        index += 1;
    }
    root.ok_or_else(|| {
        eprintln!("{cmd}: --root is required");
        ExitCode::from(2)
    })
}

fn cmd_count_lines(args: &[String]) -> ExitCode {
    let root_str = match parse_only_root(args, "count-lines") {
        Ok(v) => v,
        Err(code) => return code,
    };
    let mut input = Vec::new();
    if let Err(err) = io::stdin().read_to_end(&mut input) {
        eprintln!("OSError: {err}");
        return ExitCode::from(1);
    }
    match count_file_lines(Path::new(&root_str), &input) {
        Ok(rows) => {
            let mut stdout = io::stdout().lock();
            for (count, rel) in rows {
                let _ = writeln!(stdout, "{count}\t{rel}");
            }
            ExitCode::SUCCESS
        }
        Err(err) => {
            eprintln!("{err}");
            ExitCode::from(1)
        }
    }
}

fn cmd_scan_core_fanout(args: &[String]) -> ExitCode {
    let root_str = match parse_only_root(args, "scan-core-fanout") {
        Ok(v) => v,
        Err(code) => return code,
    };
    let mut input = Vec::new();
    if let Err(err) = io::stdin().read_to_end(&mut input) {
        eprintln!("OSError: {err}");
        return ExitCode::from(1);
    }
    match scan_core_fanout(Path::new(&root_str), &input) {
        Ok(rows) => {
            let mut stdout = io::stdout().lock();
            for (rel, count, subs) in rows {
                let joined = subs.join(",");
                let _ = writeln!(stdout, "{rel}\t{count}\t{joined}");
            }
            ExitCode::SUCCESS
        }
        Err(err) => {
            eprintln!("{err}");
            ExitCode::from(1)
        }
    }
}
