use ring::digest::{Context, SHA256};
use serde_json::{Map, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

const DEFAULT_MANIFEST_REL: &str = "security/integrity/manifest.json";
const SURFACE_LIST_REL: &str = "scripts/lib/framework-surface.txt";

fn hex_lower(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(bytes.len() * 2);
    for &b in bytes {
        let hi = b >> 4;
        let lo = b & 0x0f;
        out.push(char::from(if hi < 10 { b'0' + hi } else { b'a' + (hi - 10) }));
        out.push(char::from(if lo < 10 { b'0' + lo } else { b'a' + (lo - 10) }));
    }
    out
}

fn sha256_bytes(bytes: &[u8]) -> String {
    let mut ctx = Context::new(&SHA256);
    ctx.update(bytes);
    hex_lower(ctx.finish().as_ref())
}

fn sha256_file(path: &Path) -> Result<String, String> {
    let bytes = fs::read(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    Ok(sha256_bytes(&bytes))
}

fn sha256_git_index(workspace_root: &Path, rel: &str) -> Result<String, String> {
    let spec = format!(":{rel}");
    let out = Command::new("git")
        .args(["show", &spec])
        .current_dir(workspace_root)
        .output()
        .map_err(|e| format!("git show {spec} failed: {e}"))?;
    if !out.status.success() {
        return Err(format!("git show {spec} exited non-zero"));
    }
    Ok(sha256_bytes(&out.stdout))
}

fn utc_now_iso8601() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let days = (secs / 86_400) as i64;
    let rem = secs % 86_400;
    let hour = rem / 3600;
    let min = (rem % 3600) / 60;
    let sec = rem % 60;
    // Howard Hinnant civil-from-days algorithm (UTC)
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = (z - era * 146_097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = (yoe as i64) + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = y + i64::from(m <= 2);
    format!("{year:04}-{m:02}-{d:02}T{hour:02}:{min:02}:{sec:02}Z")
}

fn load_surface_entries(workspace_root: &Path) -> Result<Vec<String>, String> {
    let surface_path = workspace_root.join(SURFACE_LIST_REL);
    let raw = fs::read_to_string(&surface_path)
        .map_err(|e| format!("missing {SURFACE_LIST_REL}: {e}"))?;
    let mut entries = Vec::new();
    for line in raw.lines() {
        let stripped = line.split('#').next().unwrap_or("").trim();
        if !stripped.is_empty() {
            entries.push(stripped.to_string());
        }
    }
    if entries.is_empty() {
        return Err(format!("{SURFACE_LIST_REL} is empty"));
    }
    Ok(entries)
}

fn matches_surface(rel: &str, entries: &[String]) -> bool {
    entries.iter().any(|entry| {
        if entry.ends_with('/') {
            rel.starts_with(entry.as_str())
        } else {
            rel == entry.as_str()
        }
    })
}

fn list_git_tracked_files(workspace_root: &Path) -> Result<Vec<String>, String> {
    let out = Command::new("git")
        .args(["ls-files", "-z"])
        .current_dir(workspace_root)
        .output()
        .map_err(|e| format!("git ls-files failed: {e}"))?;
    if !out.status.success() {
        return Err(format!(
            "git ls-files exited non-zero: {}",
            String::from_utf8_lossy(&out.stderr)
        ));
    }
    let files = out
        .stdout
        .split(|&b| b == 0)
        .filter(|s| !s.is_empty())
        .map(|s| String::from_utf8_lossy(s).into_owned())
        .collect();
    Ok(files)
}

fn collect_disk_sql_files(base: &Path, dir: &Path, out: &mut BTreeSet<String>) {
    let Ok(rd) = fs::read_dir(dir) else { return };
    for entry in rd.flatten() {
        let Ok(ft) = entry.file_type() else { continue };
        if ft.is_symlink() {
            continue;
        }
        let p = entry.path();
        if ft.is_dir() {
            collect_disk_sql_files(base, &p, out);
        } else if p.extension().and_then(|e| e.to_str()) == Some("sql") {
            if let Ok(rel) = p.strip_prefix(base) {
                out.insert(rel.to_string_lossy().replace('\\', "/"));
            }
        }
    }
}

pub fn check_migrations_integrity(workspace_root: &Path) -> Result<usize, String> {
    let mig_root = workspace_root.join("migrations");
    let order_path = mig_root.join("0000_execution_order.json");
    let raw = fs::read_to_string(&order_path)
        .map_err(|e| format!("missing migrations/0000_execution_order.json: {e}"))?;
    let parsed: Value = serde_json::from_str(&raw)
        .map_err(|e| format!("invalid migrations/0000_execution_order.json: {e}"))?;
    let files = parsed
        .get("files")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("migrations/0000_execution_order.json missing files array"))?;
    if files.is_empty() {
        return Err(String::from("migrations/0000_execution_order.json has 0 files"));
    }

    let mut order_set: BTreeSet<String> = BTreeSet::new();
    let mut verified = 0_usize;
    for item in files {
        let rel = item
            .as_str()
            .ok_or_else(|| String::from("non-string migration file entry"))?;
        if rel.contains("..") || rel.starts_with('/') {
            return Err(format!("invalid migration path: {rel}"));
        }
        let full = mig_root.join(rel);
        let sql = fs::read_to_string(&full)
            .map_err(|e| format!("missing migration {}: {e}", full.display()))?;
        if sql.trim().is_empty() {
            return Err(format!("empty SQL migration: {rel}"));
        }
        if sql.contains("VALUES (:name,") || sql.contains("VALUES (:digest,") {
            return Err(format!("unresolved SQL bind placeholder in {rel}"));
        }
        order_set.insert(rel.to_string());
        verified += 1;
    }

    // Symmetric parity check: disk .sql files == execution_order.json == 0000_migration_manifest.json
    let mut disk_sql_files: BTreeSet<String> = BTreeSet::new();
    collect_disk_sql_files(&mig_root, &mig_root, &mut disk_sql_files);
    if disk_sql_files != order_set {
        let missing: Vec<&String> = order_set.difference(&disk_sql_files).collect();
        let orphaned: Vec<&String> = disk_sql_files.difference(&order_set).collect();
        return Err(format!(
            "SQL migration set mismatch: missing_on_disk={missing:?}, orphaned_on_disk={orphaned:?}"
        ));
    }
    let manifest_raw = fs::read_to_string(mig_root.join("0000_migration_manifest.json"))
        .map_err(|e| format!("missing migrations/0000_migration_manifest.json: {e}"))?;
    let manifest_val: Value = serde_json::from_str(&manifest_raw)
        .map_err(|e| format!("invalid 0000_migration_manifest.json: {e}"))?;
    let man_total = manifest_val
        .get("total_sql_files")
        .and_then(Value::as_u64)
        .unwrap_or(0) as usize;
    if man_total != verified {
        return Err(format!(
            "0000_migration_manifest.json total_sql_files ({man_total}) != execution_order ({verified})"
        ));
    }
    Ok(verified)
}

pub fn validate_manifest_shape(manifest: &Value) -> Result<(), String> {
    let obj = manifest
        .as_object()
        .ok_or_else(|| String::from("manifest root is not a JSON object"))?;
    for req in ["version", "algorithm", "file_count", "files", "generated_at", "surface"] {
        if !obj.contains_key(req) {
            return Err(format!("manifest missing required field '{req}'"));
        }
    }
    if obj.get("version").and_then(Value::as_u64) != Some(1) {
        return Err(String::from("manifest version must be 1"));
    }
    if obj.get("algorithm").and_then(Value::as_str) != Some("sha256") {
        return Err(String::from("manifest algorithm must be sha256"));
    }
    let surface = obj
        .get("surface")
        .and_then(Value::as_array)
        .ok_or_else(|| String::from("manifest surface must be an array"))?;
    let surface_strs: Vec<String> = surface
        .iter()
        .filter_map(|v| v.as_str().map(String::from))
        .collect();
    if surface_strs.is_empty() || surface_strs.len() != surface.len() {
        return Err(String::from("manifest surface contains empty or non-string entries"));
    }
    let files = obj
        .get("files")
        .and_then(Value::as_object)
        .ok_or_else(|| String::from("manifest files must be an object"))?;
    let declared_count = obj.get("file_count").and_then(Value::as_u64).unwrap_or(0) as usize;
    if files.is_empty() || files.len() != declared_count {
        return Err(format!(
            "manifest file_count ({declared_count}) != files.len() ({})",
            files.len()
        ));
    }
    for (rel, digest_v) in files {
        let digest = digest_v
            .as_str()
            .ok_or_else(|| format!("non-string digest for {rel}"))?;
        let valid_hex = digest.len() == 64 && digest.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'));
        if !valid_hex || !matches_surface(rel, &surface_strs) {
            return Err(format!("invalid digest or out-of-surface path in manifest: {rel}"));
        }
    }
    Ok(())
}

pub fn run_integrity_manifest(
    workspace_root: &Path,
    check_only: bool,
    out_rel: Option<&str>,
    source: &str,
) -> Result<usize, String> {
    if source != "worktree" && source != "index" {
        return Err(format!(
            "invalid --source '{source}': expected 'worktree' or 'index'"
        ));
    }
    let entries = load_surface_entries(workspace_root)?;
    let tracked = list_git_tracked_files(workspace_root)?;
    let mut files_map: BTreeMap<String, String> = BTreeMap::new();
    for rel in tracked {
        if matches_surface(&rel, &entries) {
            let digest = if source == "index" {
                sha256_git_index(workspace_root, &rel)?
            } else {
                let full = workspace_root.join(&rel);
                if !full.is_file() {
                    return Err(format!("tracked framework-surface file missing on disk: {rel}"));
                }
                sha256_file(&full)?
            };
            files_map.insert(rel, digest);
        }
    }
    if files_map.is_empty() {
        return Err(String::from(
            "no tracked files matched framework-surface.txt; refusing empty manifest",
        ));
    }

    let target_rel = out_rel.unwrap_or(DEFAULT_MANIFEST_REL);
    let target_path = workspace_root.join(target_rel);

    if check_only {
        let existing_raw = fs::read_to_string(&target_path)
            .map_err(|e| format!("cannot read {target_rel}: {e}"))?;
        let existing: Value = serde_json::from_str(&existing_raw)
            .map_err(|e| format!("invalid JSON in {target_rel}: {e}"))?;
        validate_manifest_shape(&existing)?;
        let existing_files = existing
            .get("files")
            .and_then(Value::as_object)
            .ok_or_else(|| format!("{target_rel} missing files object"))?;
        if existing_files.len() != files_map.len() {
            return Err(format!(
                "integrity manifest stale: expected {} files, manifest has {}",
                files_map.len(),
                existing_files.len()
            ));
        }
        for (k, v) in &files_map {
            if existing_files.get(k).and_then(Value::as_str) != Some(v.as_str()) {
                return Err(format!("integrity manifest hash mismatch for {k}"));
            }
        }
        return Ok(files_map.len());
    }

    let mut json_files = Map::new();
    for (k, v) in &files_map {
        json_files.insert(k.clone(), Value::String(v.clone()));
    }
    let surface_arr: Vec<Value> = entries.into_iter().map(Value::String).collect();
    let mut doc = Map::new();
    doc.insert(String::from("algorithm"), Value::String(String::from("sha256")));
    doc.insert(String::from("file_count"), Value::from(files_map.len() as u64));
    doc.insert(String::from("files"), Value::Object(json_files));
    doc.insert(String::from("generated_at"), Value::String(utc_now_iso8601()));
    doc.insert(String::from("surface"), Value::Array(surface_arr));
    doc.insert(String::from("version"), Value::from(1_u64));
    let rendered = serde_json::to_string_pretty(&Value::Object(doc))
        .map_err(|e| format!("serialize manifest: {e}"))?;
    if let Some(parent) = target_path.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("mkdir {}: {e}", parent.display()))?;
    }
    fs::write(&target_path, format!("{rendered}\n"))
        .map_err(|e| format!("write {}: {e}", target_path.display()))?;
    Ok(files_map.len())
}

pub fn check_repo_hygiene(workspace_root: &Path) -> Result<usize, String> {
    let mut scanned = 0_usize;
    let roots: Vec<PathBuf> = [
        "crates",
        "services_rs",
        "lifecycle_rs",
        "extensions_rs",
        "benchmarks_rs",
        "tools_rs",
        "console_rs",
        "deploy_rs",
    ]
    .iter()
    .map(|r| workspace_root.join(r))
    .filter(|p| p.is_dir())
    .collect();

    fn walk_hygiene(dir: &Path, scanned: &mut usize) -> Result<(), String> {
        let Ok(rd) = fs::read_dir(dir) else { return Ok(()) };
        for entry in rd.flatten() {
            let Ok(ft) = entry.file_type() else { continue };
            if ft.is_symlink() {
                continue;
            }
            let p = entry.path();
            let nm = entry.file_name();
            let ns = nm.to_string_lossy();
            if ft.is_dir() {
                if !matches!(ns.as_ref(), "target" | "node_modules" | "dist" | ".git") {
                    walk_hygiene(&p, scanned)?;
                }
                continue;
            }
            if matches!(
                p.extension().and_then(|e| e.to_str()),
                Some("rs" | "toml" | "sh" | "yaml" | "yml")
            ) {
                if let Ok(raw) = fs::read_to_string(&p) {
                    // Reject smart/curly quotes in Rust source & config manifests
                    if matches!(p.extension().and_then(|e| e.to_str()), Some("toml" | "sh"))
                        && (raw.contains('\u{201c}')
                            || raw.contains('\u{201d}')
                            || raw.contains('\u{2018}')
                            || raw.contains('\u{2019}'))
                    {
                        return Err(format!("Curly punctuation detected in {}", p.display()));
                    }
                    *scanned += 1;
                }
            }
        }
        Ok(())
    }

    for r in roots {
        walk_hygiene(&r, &mut scanned)?;
    }
    Ok(scanned)
}

pub fn check_staged_zero_python(workspace_root: &Path) -> Result<usize, String> {
    let out = Command::new("git")
        .args(["diff", "--cached", "--name-only", "--diff-filter=A"])
        .current_dir(workspace_root)
        .output()
        .map_err(|e| format!("git diff --cached failed: {e}"))?;
    if !out.status.success() {
        return Err(String::from("git diff --cached returned non-zero"));
    }
    let text = String::from_utf8_lossy(&out.stdout);
    let mut checked = 0_usize;
    for rel in text.lines().map(str::trim).filter(|s| !s.is_empty()) {
        checked += 1;
        if rel.starts_with("_archive/") || rel.starts_with("rule-catalog/code-security/") {
            continue;
        }
        let is_py = rel.ends_with(".py")
            || rel == "pyproject.toml"
            || rel.ends_with("/pyproject.toml")
            || rel == "uv.lock"
            || rel.ends_with("/uv.lock")
            || rel == "Pipfile"
            || rel.ends_with("/Pipfile")
            || rel.ends_with("requirements.txt");
        if is_py {
            return Err(format!(
                "BLOCKED [Zero-Python Gate]: adding Python file/manifest outside _archive is prohibited: {rel}"
            ));
        }
    }
    Ok(checked)
}
