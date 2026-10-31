//! Pure-Rust (`std`-only) accelerator for FDAI local SDLC validation and gates.

use std::collections::BTreeSet;
use std::fs;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::{MetadataExt, PermissionsExt};
use std::path::{Component, Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Mutex;
use std::thread;

const HEX_CHARS: &[u8; 16] = b"0123456789abcdef";

fn to_hex(bytes: &[u8]) -> String {
    let mut out = Vec::with_capacity(bytes.len() * 2);
    for &b in bytes {
        out.push(HEX_CHARS[(b >> 4) as usize]);
        out.push(HEX_CHARS[(b & 0x0f) as usize]);
    }
    // SAFETY: HEX_CHARS contains only ASCII hex digits.
    String::from_utf8(out).unwrap_or_default()
}

/// FIPS 180-4 SHA-1 implementation for Git `blob <len>\0` object hashing.
#[derive(Clone)]
pub struct Sha1 {
    state: [u32; 5],
    buffer: [u8; 64],
    buffer_len: usize,
    total_len: u64,
}

impl Default for Sha1 {
    fn default() -> Self {
        Self::new()
    }
}

impl Sha1 {
    pub fn new() -> Self {
        Self {
            state: [0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476, 0xc3d2e1f0],
            buffer: [0u8; 64],
            buffer_len: 0,
            total_len: 0,
        }
    }

    pub fn update(&mut self, mut data: &[u8]) {
        self.total_len = self.total_len.wrapping_add(data.len() as u64);
        if self.buffer_len > 0 {
            let take = (64 - self.buffer_len).min(data.len());
            self.buffer[self.buffer_len..self.buffer_len + take].copy_from_slice(&data[..take]);
            self.buffer_len += take;
            data = &data[take..];
            if self.buffer_len == 64 {
                let block = self.buffer;
                self.compress(&block);
                self.buffer_len = 0;
            }
        }
        while data.len() >= 64 {
            self.compress(&data[..64]);
            data = &data[64..];
        }
        if !data.is_empty() {
            self.buffer[..data.len()].copy_from_slice(data);
            self.buffer_len = data.len();
        }
    }

    pub fn finalize_hex(mut self) -> String {
        let bit_len = self.total_len.wrapping_mul(8);
        self.buffer[self.buffer_len] = 0x80;
        self.buffer_len += 1;
        if self.buffer_len > 56 {
            for b in &mut self.buffer[self.buffer_len..64] {
                *b = 0;
            }
            let block = self.buffer;
            self.compress(&block);
            self.buffer_len = 0;
        }
        for b in &mut self.buffer[self.buffer_len..56] {
            *b = 0;
        }
        self.buffer[56..64].copy_from_slice(&bit_len.to_be_bytes());
        let block = self.buffer;
        self.compress(&block);

        let mut digest = [0u8; 20];
        for (i, word) in self.state.iter().enumerate() {
            digest[i * 4..(i + 1) * 4].copy_from_slice(&word.to_be_bytes());
        }
        to_hex(&digest)
    }

    fn compress(&mut self, block: &[u8]) {
        let mut w = [0u32; 80];
        for (i, word) in w.iter_mut().take(16).enumerate() {
            let offset = i * 4;
            *word = u32::from_be_bytes([
                block[offset],
                block[offset + 1],
                block[offset + 2],
                block[offset + 3],
            ]);
        }
        for i in 16..80 {
            w[i] = (w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16]).rotate_left(1);
        }
        let mut a = self.state[0];
        let mut b = self.state[1];
        let mut c = self.state[2];
        let mut d = self.state[3];
        let mut e = self.state[4];

        for (i, &wi) in w.iter().enumerate() {
            let (f, k) = match i {
                0..=19 => ((b & c) | ((!b) & d), 0x5a827999u32),
                20..=39 => (b ^ c ^ d, 0x6ed9eba1u32),
                40..=59 => ((b & c) | (b & d) | (c & d), 0x8f1bbcdcu32),
                _ => (b ^ c ^ d, 0xca62c1d6u32),
            };
            let temp = a
                .rotate_left(5)
                .wrapping_add(f)
                .wrapping_add(e)
                .wrapping_add(k)
                .wrapping_add(wi);
            e = d;
            d = c;
            c = b.rotate_left(30);
            b = a;
            a = temp;
        }
        self.state[0] = self.state[0].wrapping_add(a);
        self.state[1] = self.state[1].wrapping_add(b);
        self.state[2] = self.state[2].wrapping_add(c);
        self.state[3] = self.state[3].wrapping_add(d);
        self.state[4] = self.state[4].wrapping_add(e);
    }
}

/// FIPS 180-4 SHA-256 implementation.
#[derive(Clone)]
pub struct Sha256 {
    state: [u32; 8],
    buffer: [u8; 64],
    buffer_len: usize,
    total_len: u64,
}

const SHA256_K: [u32; 64] = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
    0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
    0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
    0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
    0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
    0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
    0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
    0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
    0xc67178f2,
];

impl Default for Sha256 {
    fn default() -> Self {
        Self::new()
    }
}

impl Sha256 {
    pub fn new() -> Self {
        Self {
            state: [
                0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c,
                0x1f83d9ab, 0x5be0cd19,
            ],
            buffer: [0u8; 64],
            buffer_len: 0,
            total_len: 0,
        }
    }

    pub fn update(&mut self, mut data: &[u8]) {
        self.total_len = self.total_len.wrapping_add(data.len() as u64);
        if self.buffer_len > 0 {
            let take = (64 - self.buffer_len).min(data.len());
            self.buffer[self.buffer_len..self.buffer_len + take].copy_from_slice(&data[..take]);
            self.buffer_len += take;
            data = &data[take..];
            if self.buffer_len == 64 {
                let block = self.buffer;
                self.compress(&block);
                self.buffer_len = 0;
            }
        }
        while data.len() >= 64 {
            self.compress(&data[..64]);
            data = &data[64..];
        }
        if !data.is_empty() {
            self.buffer[..data.len()].copy_from_slice(data);
            self.buffer_len = data.len();
        }
    }

    pub fn finalize_bytes(mut self) -> [u8; 32] {
        let bit_len = self.total_len.wrapping_mul(8);
        self.buffer[self.buffer_len] = 0x80;
        self.buffer_len += 1;
        if self.buffer_len > 56 {
            for b in &mut self.buffer[self.buffer_len..64] {
                *b = 0;
            }
            let block = self.buffer;
            self.compress(&block);
            self.buffer_len = 0;
        }
        for b in &mut self.buffer[self.buffer_len..56] {
            *b = 0;
        }
        self.buffer[56..64].copy_from_slice(&bit_len.to_be_bytes());
        let block = self.buffer;
        self.compress(&block);

        let mut digest = [0u8; 32];
        for (i, word) in self.state.iter().enumerate() {
            digest[i * 4..(i + 1) * 4].copy_from_slice(&word.to_be_bytes());
        }
        digest
    }

    pub fn finalize_hex(self) -> String {
        to_hex(&self.finalize_bytes())
    }

    fn compress(&mut self, block: &[u8]) {
        let mut w = [0u32; 64];
        for (i, word) in w.iter_mut().take(16).enumerate() {
            let offset = i * 4;
            *word = u32::from_be_bytes([
                block[offset],
                block[offset + 1],
                block[offset + 2],
                block[offset + 3],
            ]);
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }
        let mut a = self.state[0];
        let mut b = self.state[1];
        let mut c = self.state[2];
        let mut d = self.state[3];
        let mut e = self.state[4];
        let mut f = self.state[5];
        let mut g = self.state[6];
        let mut h = self.state[7];

        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ ((!e) & g);
            let temp1 = h
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(SHA256_K[i])
                .wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let temp2 = s0.wrapping_add(maj);

            h = g;
            g = f;
            f = e;
            e = d.wrapping_add(temp1);
            d = c;
            c = b;
            b = a;
            a = temp1.wrapping_add(temp2);
        }
        self.state[0] = self.state[0].wrapping_add(a);
        self.state[1] = self.state[1].wrapping_add(b);
        self.state[2] = self.state[2].wrapping_add(c);
        self.state[3] = self.state[3].wrapping_add(d);
        self.state[4] = self.state[4].wrapping_add(e);
        self.state[5] = self.state[5].wrapping_add(f);
        self.state[6] = self.state[6].wrapping_add(g);
        self.state[7] = self.state[7].wrapping_add(h);
    }
}

pub fn sha256_hex(data: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(data);
    hasher.finalize_hex()
}

pub fn git_blob_hex(algorithm: &str, data: &[u8]) -> Result<String, String> {
    let header = format!("blob {}\0", data.len());
    match algorithm {
        "sha1" => {
            let mut hasher = Sha1::new();
            hasher.update(header.as_bytes());
            hasher.update(data);
            Ok(hasher.finalize_hex())
        }
        "sha256" => {
            let mut hasher = Sha256::new();
            hasher.update(header.as_bytes());
            hasher.update(data);
            Ok(hasher.finalize_hex())
        }
        other => Err(format!("unsupported git object format: {other}")),
    }
}

fn normalize_lexical(path: &Path) -> PathBuf {
    let mut normalized = PathBuf::new();
    for comp in path.components() {
        match comp {
            Component::CurDir => {}
            Component::ParentDir => {
                normalized.pop();
            }
            other => normalized.push(other.as_os_str()),
        }
    }
    normalized
}

/// Resolve a path much like Python `Path.resolve()`, following chained symlinks even when
/// the final target does not exist on disk.
pub fn resolve_like_python(path: &Path) -> Result<PathBuf, String> {
    if let Ok(canon) = fs::canonicalize(path) {
        return Ok(canon);
    }
    let mut current = PathBuf::new();
    for comp in path.components() {
        current.push(comp.as_os_str());
        if let Ok(canon) = fs::canonicalize(&current) {
            current = canon;
            continue;
        }
        let mut hops = 0usize;
        while let Ok(target) = fs::read_link(&current) {
            hops += 1;
            if hops > 40 {
                return Err("OSError: symlink loop detected".to_string());
            }
            let joined = if target.is_absolute() {
                target
            } else {
                current
                    .parent()
                    .unwrap_or_else(|| Path::new("/"))
                    .join(target)
            };
            current = normalize_lexical(&joined);
            if let Ok(canon) = fs::canonicalize(&current) {
                current = canon;
                break;
            }
        }
        current = normalize_lexical(&current);
    }
    Ok(current)
}

/// Verify `git ls-tree -rz --full-tree` entries in parallel against materialized files in `root`.
pub fn verify_snapshot(root: &Path, algorithm: &str, ls_tree: &[u8]) -> Result<usize, String> {
    if algorithm != "sha1" && algorithm != "sha256" {
        return Err(format!(
            "ValueError: unsupported git object format: {algorithm}"
        ));
    }
    let root_resolved = fs::canonicalize(root).map_err(|e| format!("OSError: {e}"))?;
    let mut entries: Vec<(&str, &str, &str, &str)> = Vec::new();
    for raw in ls_tree.split(|&b| b == 0) {
        if raw.is_empty() {
            continue;
        }
        let text =
            std::str::from_utf8(raw).map_err(|e| format!("ValueError: UTF8Error: {e}"))?;
        let (meta, rel) = text
            .split_once('\t')
            .ok_or_else(|| "ValueError: malformed ls-tree entry".to_string())?;
        let mut parts = meta.split_whitespace();
        let mode = parts
            .next()
            .ok_or_else(|| "ValueError: missing mode".to_string())?;
        let kind = parts
            .next()
            .ok_or_else(|| "ValueError: missing kind".to_string())?;
        let expected = parts
            .next()
            .ok_or_else(|| "ValueError: missing object id".to_string())?;
        entries.push((mode, kind, expected, rel));
    }

    let workers = thread::available_parallelism()
        .map(|n| n.get().min(16))
        .unwrap_or(4)
        .min(entries.len().max(1));
    let next_index = AtomicUsize::new(0);
    let first_error: Mutex<Option<(usize, String)>> = Mutex::new(None);

    thread::scope(|scope| {
        for _ in 0..workers {
            scope.spawn(|| loop {
                let idx = next_index.fetch_add(1, Ordering::Relaxed);
                if idx >= entries.len() {
                    break;
                }
                if let Ok(guard) = first_error.lock() {
                    if let Some((err_idx, _)) = *guard {
                        if err_idx < idx {
                            break;
                        }
                    }
                }
                let (mode, kind, expected, rel) = entries[idx];
                if let Err(msg) =
                    verify_one_entry(&root_resolved, algorithm, mode, kind, expected, rel)
                {
                    if let Ok(mut guard) = first_error.lock() {
                        match &*guard {
                            Some((prev_idx, _)) if *prev_idx <= idx => {}
                            _ => *guard = Some((idx, msg)),
                        }
                    }
                }
            });
        }
    });

    if let Some((_, err)) = first_error.into_inner().unwrap_or(None) {
        return Err(err);
    }
    Ok(entries.len())
}

fn verify_one_entry(
    root_resolved: &Path,
    algorithm: &str,
    mode: &str,
    kind: &str,
    expected: &str,
    rel: &str,
) -> Result<(), String> {
    let expected_len = if algorithm == "sha1" { 40 } else { 64 };
    if expected.len() != expected_len
        || !expected
            .bytes()
            .all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'))
    {
        return Err("ValueError: invalid object id in ls-tree entry".to_string());
    }
    if kind != "blob" {
        return Err("ValueError: snapshot contains an unsupported external input".to_string());
    }
    let rel_path = Path::new(rel);
    if rel_path.components().any(|c| {
        matches!(
            c,
            Component::ParentDir | Component::RootDir | Component::Prefix(_)
        )
    }) {
        return Err("ValueError: snapshot contains an unsupported external input".to_string());
    }
    let path = root_resolved.join(rel_path);
    let resolved = resolve_like_python(&path)?;
    if !resolved.starts_with(root_resolved) {
        return Err("ValueError: snapshot contains an unsupported external input".to_string());
    }
    let meta = fs::symlink_metadata(&path).map_err(|e| format!("OSError: {e}"))?;
    let file_type = meta.file_type();
    let data: Vec<u8> = if mode == "120000" && file_type.is_symlink() {
        let link_target = fs::read_link(&path).map_err(|e| format!("OSError: {e}"))?;
        link_target.as_os_str().as_bytes().to_vec()
    } else if (mode == "100644" || mode == "100755") && file_type.is_file() {
        let is_exec = (meta.permissions().mode() & 0o100) != 0;
        let expect_exec = mode == "100755";
        if is_exec != expect_exec {
            return Err(
                "ValueError: snapshot executable mode differs from committed content".to_string(),
            );
        }
        fs::read(&path).map_err(|e| format!("OSError: {e}"))?
    } else {
        return Err("ValueError: snapshot file type differs from committed content".to_string());
    };
    let actual = git_blob_hex(algorithm, &data)?;
    if actual != expected {
        return Err("ValueError: snapshot bytes differ from committed content".to_string());
    }
    Ok(())
}

/// Collect and hash installed files under a virtualenv root in parallel.
/// Returns sorted `(rel_posix_path, st_mode_imode, symlink_target, sha256_hex)` records.
pub fn scan_installed_venv(
    root: &Path,
    skip_bytecode: bool,
) -> Result<Vec<(String, u32, String, String)>, String> {
    if !root.join("bin/python").is_file() {
        return Err("ValueError: validation Python environment is missing".to_string());
    }
    let root_resolved = fs::canonicalize(root).map_err(|e| format!("OSError: {e}"))?;
    let mut files: Vec<(String, PathBuf)> = Vec::new();
    collect_venv_files(root, &root_resolved, Path::new(""), skip_bytecode, &mut files)?;
    files.sort_by(|a, b| a.0.cmp(&b.0));

    let workers = thread::available_parallelism()
        .map(|n| n.get().min(16))
        .unwrap_or(4)
        .min(files.len().max(1));
    let next_index = AtomicUsize::new(0);
    let mut results: Vec<Option<Result<(String, u32, String, String), String>>> =
        (0..files.len()).map(|_| None).collect();
    let results_mutex = Mutex::new(&mut results);

    thread::scope(|scope| {
        for _ in 0..workers {
            scope.spawn(|| loop {
                let idx = next_index.fetch_add(1, Ordering::Relaxed);
                if idx >= files.len() {
                    break;
                }
                let (ref rel, ref full_path) = files[idx];
                let item = hash_venv_file(rel, full_path);
                if let Ok(mut guard) = results_mutex.lock() {
                    guard[idx] = Some(item);
                }
            });
        }
    });

    let mut out = Vec::with_capacity(files.len());
    for slot in results.into_iter().flatten() {
        out.push(slot?);
    }
    Ok(out)
}

fn collect_venv_files(
    root: &Path,
    root_resolved: &Path,
    rel_dir: &Path,
    skip_bytecode: bool,
    out: &mut Vec<(String, PathBuf)>,
) -> Result<(), String> {
    let dir_path = if rel_dir.as_os_str().is_empty() {
        root.to_path_buf()
    } else {
        root.join(rel_dir)
    };
    let read_dir = fs::read_dir(&dir_path).map_err(|e| format!("OSError: {e}"))?;
    let mut entries: Vec<fs::DirEntry> = Vec::new();
    for entry in read_dir {
        entries.push(entry.map_err(|e| format!("OSError: {e}"))?);
    }
    entries.sort_by_key(|e| e.file_name());

    for entry in entries {
        let name = entry.file_name();
        let name_str = name.to_string_lossy();
        let rel_path = if rel_dir.as_os_str().is_empty() {
            PathBuf::from(&name)
        } else {
            rel_dir.join(&name)
        };
        let full_path = root.join(&rel_path);
        let lstat = fs::symlink_metadata(&full_path).map_err(|e| format!("OSError: {e}"))?;
        let is_symlink = lstat.file_type().is_symlink();
        // Follow symlinks via fs::metadata, matching Python Path.is_dir().
        let is_dir = fs::metadata(&full_path)
            .map(|m| m.is_dir())
            .unwrap_or(false);
        if is_dir {
            if is_symlink {
                let resolved = resolve_like_python(&full_path)?;
                if !resolved.starts_with(root_resolved) {
                    return Err(
                        "ValueError: installed directory escapes the verified environment"
                            .to_string(),
                    );
                }
                // Note: Python Path.rglob("*") does not recurse into symlinked directories,
                // so we validate containment and do not recurse into symlinked directories.
                continue;
            }
            if skip_bytecode && name_str == "__pycache__" {
                continue;
            }
            collect_venv_files(root, root_resolved, &rel_path, skip_bytecode, out)?;
        } else {
            if skip_bytecode
                && rel_path
                    .components()
                    .any(|c| c.as_os_str() == "__pycache__")
            {
                continue;
            }
            let rel_posix = rel_path
                .components()
                .map(|c| c.as_os_str().to_string_lossy())
                .collect::<Vec<_>>()
                .join("/");
            out.push((rel_posix, full_path));
        }
    }
    Ok(())
}

fn hash_venv_file(
    rel: &str,
    full_path: &Path,
) -> Result<(String, u32, String, String), String> {
    let lstat = fs::symlink_metadata(full_path).map_err(|e| format!("OSError: {e}"))?;
    let link_target = if lstat.file_type().is_symlink() {
        fs::read_link(full_path)
            .map_err(|e| format!("OSError: {e}"))?
            .to_string_lossy()
            .into_owned()
    } else {
        String::new()
    };
    let stat = fs::metadata(full_path).map_err(|e| format!("OSError: {e}"))?;
    let imode = stat.permissions().mode() & 0o7777;
    let bytes = fs::read(full_path).map_err(|e| format!("OSError: {e}"))?;
    let digest = sha256_hex(&bytes);
    Ok((rel.to_string(), imode, link_target, digest))
}

/// Extract `translation_of` and `translation_source_sha` from leading YAML front-matter.
fn parse_translation_front_matter(text: &str) -> Option<(Option<String>, Option<String>)> {
    let trimmed = text.strip_prefix('\u{feff}').unwrap_or(text);
    let mut lines = trimmed.lines();
    if lines.next()? != "---" {
        return None;
    }
    let mut fm_lines = Vec::new();
    let mut closed = false;
    for line in lines {
        if line == "---" {
            closed = true;
            break;
        }
        fm_lines.push(line);
    }
    if !closed || fm_lines.is_empty() {
        return None;
    }
    let mut translation_of = None;
    let mut recorded_sha = None;
    for line in fm_lines {
        let stripped = line.trim();
        if stripped.is_empty() || stripped.starts_with('#') {
            continue;
        }
        if let Some((k, v)) = line.split_once(':') {
            let key = k.trim();
            let val = v.trim().trim_matches(|c| c == '"' || c == '\'').to_string();
            if key == "translation_of" {
                translation_of = Some(val);
            } else if key == "translation_source_sha" {
                recorded_sha = Some(val);
            }
        }
    }
    Some((translation_of, recorded_sha))
}

/// Compute `(content_hex, status_hex)` for `changed_test_inputs.py::worktree_digests` in parallel.
pub fn compute_worktree_digests(
    root: &Path,
    excluded: &[PathBuf],
    listed: &[u8],
) -> Result<(String, String), String> {
    let mut unique_paths: BTreeSet<&[u8]> = BTreeSet::new();
    for raw in listed.split(|&b| b == 0) {
        if !raw.is_empty() {
            unique_paths.insert(raw);
        }
    }
    let mut selected: Vec<(&[u8], PathBuf)> = Vec::with_capacity(unique_paths.len());
    for raw in unique_paths {
        let rel_os = std::ffi::OsStr::from_bytes(raw);
        let full = root.join(rel_os);
        if excluded.iter().any(|prefix| full.starts_with(prefix)) {
            continue;
        }
        selected.push((raw, full));
    }

    let workers = thread::available_parallelism()
        .map(|n| n.get().min(16))
        .unwrap_or(4)
        .min(selected.len().max(1));
    let next_index = AtomicUsize::new(0);
    let mut chunks: Vec<Option<Result<(Vec<u8>, Vec<u8>), String>>> =
        (0..selected.len()).map(|_| None).collect();
    let chunks_mutex = Mutex::new(&mut chunks);

    thread::scope(|scope| {
        for _ in 0..workers {
            scope.spawn(|| loop {
                let idx = next_index.fetch_add(1, Ordering::Relaxed);
                if idx >= selected.len() {
                    break;
                }
                let (raw_path, ref full_path) = selected[idx];
                let item = hash_worktree_entry(raw_path, full_path);
                if let Ok(mut guard) = chunks_mutex.lock() {
                    guard[idx] = Some(item);
                }
            });
        }
    });

    let mut content = Sha256::new();
    let mut status = Sha256::new();
    for slot in chunks.into_iter().flatten() {
        let (c_bytes, s_bytes) = slot?;
        content.update(&c_bytes);
        status.update(&s_bytes);
    }
    Ok((content.finalize_hex(), status.finalize_hex()))
}

fn hash_worktree_entry(raw_path: &[u8], full_path: &Path) -> Result<(Vec<u8>, Vec<u8>), String> {
    let mut content_chunk = Vec::with_capacity(raw_path.len() + 48);
    let mut status_chunk = Vec::with_capacity(raw_path.len() + 64);
    content_chunk.extend_from_slice(raw_path);
    content_chunk.push(0);
    status_chunk.extend_from_slice(raw_path);
    status_chunk.push(0);

    let meta = match fs::symlink_metadata(full_path) {
        Ok(m) => m,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            content_chunk.extend_from_slice(b"missing\0");
            status_chunk.extend_from_slice(b"missing\0");
            return Ok((content_chunk, status_chunk));
        }
        Err(e) => return Err(format!("OSError: {e}")),
    };
    let mtime_ns = (meta.mtime() as i128) * 1_000_000_000 + (meta.mtime_nsec() as i128);
    let ctime_ns = (meta.ctime() as i128) * 1_000_000_000 + (meta.ctime_nsec() as i128);
    status_chunk.extend_from_slice(format!("{}\0{}\0{}\0", meta.ino(), mtime_ns, ctime_ns).as_bytes());

    let ft = meta.file_type();
    if ft.is_symlink() {
        let link = fs::read_link(full_path).map_err(|e| format!("OSError: {e}"))?;
        content_chunk.extend_from_slice(b"link\0");
        content_chunk.extend_from_slice(link.as_os_str().as_bytes());
        content_chunk.push(0);
    } else if ft.is_file() {
        let mode_byte = if (meta.permissions().mode() & 0o100) != 0 {
            b'x'
        } else {
            b'-'
        };
        let bytes = fs::read(full_path).map_err(|e| format!("OSError: {e}"))?;
        let mut file_hasher = Sha256::new();
        file_hasher.update(&bytes);
        let file_digest = file_hasher.finalize_bytes();
        content_chunk.extend_from_slice(b"file\0");
        content_chunk.push(mode_byte);
        content_chunk.extend_from_slice(&file_digest);
    } else {
        content_chunk.extend_from_slice(b"other\0");
    }
    Ok((content_chunk, status_chunk))
}

/// Verify English/Korean doc pairs in parallel (Rules 1-4 of `check-translations.sh`).
pub fn check_translations(
    root: &Path,
    english_docs: &[String],
    korean_docs: &[String],
) -> (usize, usize, Vec<String>) {
    let en_set: BTreeSet<String> = english_docs
        .iter()
        .filter(|p| root.join(p).is_file())
        .cloned()
        .collect();
    let ko_set: BTreeSet<String> = korean_docs
        .iter()
        .filter(|p| root.join(p).is_file())
        .cloned()
        .collect();

    let en_vec: Vec<String> = en_set.iter().cloned().collect();
    let workers = thread::available_parallelism()
        .map(|n| n.get().min(16))
        .unwrap_or(4)
        .min(en_vec.len().max(1));
    let next_index = AtomicUsize::new(0);
    let mut per_doc_errors: Vec<Vec<String>> = (0..en_vec.len()).map(|_| Vec::new()).collect();
    let errors_mutex = Mutex::new(&mut per_doc_errors);

    thread::scope(|scope| {
        for _ in 0..workers {
            scope.spawn(|| loop {
                let idx = next_index.fetch_add(1, Ordering::Relaxed);
                if idx >= en_vec.len() {
                    break;
                }
                let src = &en_vec[idx];
                let doc_errs = check_one_translation_pair(root, src);
                if !doc_errs.is_empty() {
                    if let Ok(mut guard) = errors_mutex.lock() {
                        guard[idx] = doc_errs;
                    }
                }
            });
        }
    });

    let mut errors: Vec<String> = per_doc_errors.into_iter().flatten().collect();

    // Rule 4: no orphan -ko.md files.
    for ko in &ko_set {
        let src = format!("{}.md", ko.strip_suffix("-ko.md").unwrap_or(ko));
        if !root.join(&src).is_file() {
            errors.push(format!(
                "check-translations: orphan translation: {ko} has no English source {src}"
            ));
            continue;
        }
        if ko != "README-ko.md" && !ko.starts_with("docs/") {
            errors.push(format!(
                "check-translations: out-of-scope translation file: {ko} (only root README-ko.md and docs/**/-ko.md are allowed)"
            ));
        }
    }

    (en_set.len(), ko_set.len(), errors)
}

fn check_one_translation_pair(root: &Path, src: &str) -> Vec<String> {
    let mut errors = Vec::new();
    let ko = format!("{}-ko.md", src.strip_suffix(".md").unwrap_or(src));
    let ko_path = root.join(&ko);
    if !ko_path.is_file() {
        errors.push(format!(
            "check-translations: missing translation: {ko} (English source: {src})"
        ));
        return errors;
    }
    let ko_bytes = match fs::read(&ko_path) {
        Ok(b) => b,
        Err(_) => {
            errors.push(format!(
                "check-translations: {ko}: missing YAML front-matter (need translation_of + translation_source_sha)"
            ));
            return errors;
        }
    };
    let ko_text = String::from_utf8_lossy(&ko_bytes);
    let (translation_of, recorded_sha) = match parse_translation_front_matter(&ko_text) {
        Some(pair) => pair,
        None => {
            errors.push(format!(
                "check-translations: {ko}: missing YAML front-matter (need translation_of + translation_source_sha)"
            ));
            return errors;
        }
    };
    let to_val = translation_of.unwrap_or_default();
    let sha_val = recorded_sha.unwrap_or_default();
    if to_val.is_empty() {
        errors.push(format!(
            "check-translations: {ko}: front-matter missing translation_of"
        ));
    }
    if sha_val.is_empty() {
        errors.push(format!(
            "check-translations: {ko}: front-matter missing translation_source_sha"
        ));
        return errors;
    }
    let src_base = Path::new(src)
        .file_name()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_default();
    if !to_val.is_empty() && to_val != src_base {
        errors.push(format!(
            "check-translations: {ko}: translation_of='{to_val}' does not match sibling English file '{src_base}'"
        ));
    }
    let src_bytes = match fs::read(root.join(src)) {
        Ok(b) => b,
        Err(_) => {
            errors.push(format!(
                "check-translations: {src}: unreadable English source"
            ));
            return errors;
        }
    };
    let current_sha = match git_blob_hex("sha1", &src_bytes) {
        Ok(s) => s,
        Err(e) => {
            errors.push(format!("check-translations: {src}: {e}"));
            return errors;
        }
    };
    if sha_val != current_sha {
        errors.push(format!(
            "check-translations: {ko}: stale translation. recorded_sha={sha_val}, current sha of {src}={current_sha}. Update the translation and refresh translation_source_sha."
        ));
    }
    errors
}

/// Count newline (`\n`) bytes across NUL-delimited relative file paths in parallel.
pub fn count_file_lines(root: &Path, input: &[u8]) -> Result<Vec<(usize, String)>, String> {
    let mut paths: Vec<&str> = Vec::new();
    for raw in input.split(|&b| b == 0) {
        if raw.is_empty() {
            continue;
        }
        let rel = std::str::from_utf8(raw).map_err(|e| format!("ValueError: UTF8Error: {e}"))?;
        let rel_path = Path::new(rel);
        if rel_path.components().any(|c| {
            matches!(
                c,
                Component::ParentDir | Component::RootDir | Component::Prefix(_)
            )
        }) {
            return Err("ValueError: unsafe path in count-lines".to_string());
        }
        paths.push(rel);
    }
    if paths.is_empty() {
        return Ok(Vec::new());
    }
    let workers = thread::available_parallelism()
        .map(|n| n.get().min(16))
        .unwrap_or(4)
        .min(paths.len().max(1));
    let next_index = AtomicUsize::new(0);
    let results: Mutex<Vec<Option<(usize, String)>>> = Mutex::new(vec![None; paths.len()]);
    let first_error: Mutex<Option<String>> = Mutex::new(None);

    thread::scope(|scope| {
        for _ in 0..workers {
            scope.spawn(|| loop {
                let idx = next_index.fetch_add(1, Ordering::Relaxed);
                if idx >= paths.len() {
                    break;
                }
                let rel = paths[idx];
                match fs::read(root.join(rel)) {
                    Ok(bytes) => {
                        let count = bytes.iter().filter(|&&b| b == b'\n').count();
                        if let Ok(mut guard) = results.lock() {
                            guard[idx] = Some((count, rel.to_string()));
                        }
                    }
                    Err(err) => {
                        if let Ok(mut guard) = first_error.lock() {
                            if guard.is_none() {
                                *guard = Some(format!("OSError: {err}"));
                            }
                        }
                    }
                }
            });
        }
    });

    if let Some(err) = first_error.into_inner().unwrap_or(None) {
        return Err(err);
    }
    let guard = results
        .into_inner()
        .map_err(|_| "ValueError: mutex poisoned".to_string())?;
    Ok(guard.into_iter().flatten().collect())
}

fn extract_core_subsystems(text: &str, own: &str) -> Vec<String> {
    let mut subs = BTreeSet::new();
    let bytes = text.as_bytes();
    let mut i = 0usize;
    while i < bytes.len() {
        let kw_len = if bytes[i..].starts_with(b"from")
            && bytes
                .get(i + 4)
                .is_some_and(|b| b.is_ascii_whitespace())
        {
            4
        } else if bytes[i..].starts_with(b"import")
            && bytes
                .get(i + 6)
                .is_some_and(|b| b.is_ascii_whitespace())
        {
            6
        } else {
            i += 1;
            continue;
        };
        let mut j = i + kw_len;
        while j < bytes.len() && bytes[j].is_ascii_whitespace() {
            j += 1;
        }
        const PREFIX: &[u8] = b"fdai.core.";
        if bytes[j..].starts_with(PREFIX) {
            let start = j + PREFIX.len();
            if let Some(&first) = bytes.get(start) {
                if first.is_ascii_alphabetic() || first == b'_' {
                    let mut end = start + 1;
                    while end < bytes.len()
                        && (bytes[end].is_ascii_alphanumeric() || bytes[end] == b'_')
                    {
                        end += 1;
                    }
                    if let Ok(sub) = std::str::from_utf8(&bytes[start..end]) {
                        if sub != own {
                            subs.insert(sub.to_string());
                        }
                    }
                    i = end;
                    continue;
                }
            }
        }
        i = j;
    }
    subs.into_iter().collect()
}

/// Scan `services/core-control-plane/src/fdai/core/**/*.py` files in parallel for sibling subsystem fanout.
pub fn scan_core_fanout(
    root: &Path,
    input: &[u8],
) -> Result<Vec<(String, usize, Vec<String>)>, String> {
    let mut paths: Vec<&str> = Vec::new();
    for raw in input.split(|&b| b == 0) {
        if raw.is_empty() {
            continue;
        }
        let rel = std::str::from_utf8(raw).map_err(|e| format!("ValueError: UTF8Error: {e}"))?;
        let rel_path = Path::new(rel);
        if rel_path.components().any(|c| {
            matches!(
                c,
                Component::ParentDir | Component::RootDir | Component::Prefix(_)
            )
        }) {
            return Err("ValueError: unsafe path in scan-core-fanout".to_string());
        }
        paths.push(rel);
    }
    if paths.is_empty() {
        return Ok(Vec::new());
    }
    let workers = thread::available_parallelism()
        .map(|n| n.get().min(16))
        .unwrap_or(4)
        .min(paths.len().max(1));
    let next_index = AtomicUsize::new(0);
    let results: Mutex<Vec<Option<(String, usize, Vec<String>)>>> =
        Mutex::new(vec![None; paths.len()]);
    let first_error: Mutex<Option<String>> = Mutex::new(None);

    thread::scope(|scope| {
        for _ in 0..workers {
            scope.spawn(|| loop {
                let idx = next_index.fetch_add(1, Ordering::Relaxed);
                if idx >= paths.len() {
                    break;
                }
                let rel = paths[idx];
                let trimmed = rel
                    .strip_prefix("services/core-control-plane/src/fdai/core/")
                    .unwrap_or(rel);
                let own = match trimmed.split_once('/') {
                    Some((first, _)) => first,
                    None => trimmed.strip_suffix(".py").unwrap_or(""),
                };
                match fs::read(root.join(rel)) {
                    Ok(bytes) => {
                        let text = String::from_utf8_lossy(&bytes);
                        let subs = extract_core_subsystems(&text, own);
                        let count = subs.len();
                        if let Ok(mut guard) = results.lock() {
                            guard[idx] = Some((rel.to_string(), count, subs));
                        }
                    }
                    Err(err) => {
                        if let Ok(mut guard) = first_error.lock() {
                            if guard.is_none() {
                                *guard = Some(format!("OSError: {err}"));
                            }
                        }
                    }
                }
            });
        }
    });

    if let Some(err) = first_error.into_inner().unwrap_or(None) {
        return Err(err);
    }
    let guard = results
        .into_inner()
        .map_err(|_| "ValueError: mutex poisoned".to_string())?;
    Ok(guard.into_iter().flatten().collect())
}

/// Fast byte pre-filter for caller-supplied ASCII markers or NUL bytes.
pub fn contains_any_token_or_nul(data: &[u8], tokens: &[&[u8]]) -> bool {
    if data.contains(&0) {
        return true;
    }
    tokens
        .iter()
        .any(|needle| !needle.is_empty() && data.windows(needle.len()).any(|w| w == *needle))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_sha1_and_git_blob_vectors() {
        let mut s = Sha1::new();
        s.update(b"");
        assert_eq!(s.finalize_hex(), "da39a3ee5e6b4b0d3255bfef95601890afd80709");

        // `git hash-object` of empty file: "blob 0\0"
        assert_eq!(
            git_blob_hex("sha1", b"").unwrap(),
            "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
        );
        // 55-byte and 56-byte padding boundary tests for SHA-1
        for len in [0usize, 1, 55, 56, 57, 63, 64, 65, 128, 1000] {
            let payload = vec![b'a'; len];
            let digest = git_blob_hex("sha1", &payload).unwrap();
            assert_eq!(digest.len(), 40);
        }
    }

    #[test]
    fn test_sha256_vectors() {
        assert_eq!(
            sha256_hex(b""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
        assert_eq!(
            sha256_hex(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        // Multi-block 56-byte boundary test:
        assert_eq!(
            sha256_hex(b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"),
            "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"
        );
    }

    #[test]
    fn test_parse_translation_front_matter() {
        let valid = "\u{feff}---\n# comment\ntranslation_of: guide.md\n\ntranslation_source_sha: 0123456789abcdef0123456789abcdef01234567\n---\n# Title\n";
        let (to, sha) = parse_translation_front_matter(valid).unwrap();
        assert_eq!(to.as_deref(), Some("guide.md"));
        assert_eq!(
            sha.as_deref(),
            Some("0123456789abcdef0123456789abcdef01234567")
        );
        assert!(parse_translation_front_matter("no front matter").is_none());
        assert!(parse_translation_front_matter("---\nunclosed: true\n").is_none());
    }

    #[test]
    fn test_extract_core_subsystems_and_token_filter() {
        let code = "from fdai.core.executor import X\nimport fdai.core.audit\nfrom fdai.core.foo.bar import Y\n";
        let subs = extract_core_subsystems(code, "foo");
        assert_eq!(subs, vec!["audit".to_string(), "executor".to_string()]);
        let needles: [&[u8]; 2] = [b"MARKER_ALPHA", b"MARKER_BETA"];
        assert!(!contains_any_token_or_nul(b"normal python code\n", &needles));
        assert!(contains_any_token_or_nul(b"x = 'MARKER_ALPHA'\n", &needles));
        assert!(contains_any_token_or_nul(b"u\x00t\x00f\x001\x006\x00", &needles));
    }
}
