//! Pure-Rust PostgreSQL v3 Wire Protocol + TLS + SCRAM-SHA-256 (RFC 5802) + pgvector Adapter.
use base64::Engine as _;
use ring::{digest, hmac, pbkdf2, rand::SecureRandom as _};
use rustls::pki_types::ServerName;
use std::num::NonZeroU32;
use std::sync::Arc;
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;
use tokio_rustls::TlsConnector;

const PG_IO_TIMEOUT: Duration = Duration::from_secs(15);

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum PgSslMode { Disable, Prefer, Require }

#[derive(Clone, PartialEq, Eq)]
pub struct PgConnectionConfig {
    pub host: String, pub port: u16, pub user: String, pub password: String, pub database: String, pub ssl_mode: PgSslMode,
}

impl std::fmt::Debug for PgConnectionConfig {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("PgConnectionConfig")
            .field("host", &self.host)
            .field("port", &self.port)
            .field("user", &self.user)
            .field("password", &"[REDACTED]")
            .field("database", &self.database)
            .field("ssl_mode", &self.ssl_mode)
            .finish()
    }
}

fn decode_percent_component(raw: &str) -> String {
    let bytes = raw.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0_usize;
    while i < bytes.len() {
        if bytes[i] == b'%' && i + 2 < bytes.len() {
            if let Ok(hex) = std::str::from_utf8(&bytes[i + 1..i + 3]) {
                if let Ok(val) = u8::from_str_radix(hex, 16) {
                    out.push(val);
                    i += 3;
                    continue;
                }
            }
        }
        out.push(bytes[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).to_string()
}

pub fn pg_quote_literal(raw: &str) -> String {
    let mut out = String::with_capacity(raw.len() + 2);
    out.push('\'');
    for ch in raw.chars() {
        if ch == '\0' {
            continue;
        }
        if ch == '\'' {
            out.push('\'');
        }
        out.push(ch);
    }
    out.push('\'');
    out
}

impl PgConnectionConfig {
    pub fn from_dsn(dsn: &str) -> Result<Self, String> {
        let trimmed = dsn.trim();
        let stripped = if let Some((scheme, rest)) = trimmed.split_once("://") {
            let base = scheme.split('+').next().unwrap_or("");
            if base == "postgresql" || base == "postgres" {
                rest
            } else {
                return Err(String::from("DSN must start with postgres:// or postgresql://"));
            }
        } else {
            return Err(String::from("DSN must start with postgres:// or postgresql://"));
        };
        let (main_part, query_part) = stripped.split_once('?').unwrap_or((stripped, ""));
        let (auth_part, host_db) = main_part.rsplit_once('@').unwrap_or(("postgres", main_part));
        let (user_raw, password_raw) = auth_part.split_once(':').unwrap_or((auth_part, ""));
        let (host_port, db) = host_db.split_once('/').unwrap_or((host_db, "postgres"));
        let (host, port) = if let Some(rest) = host_port.strip_prefix('[') {
            let (h, after) = rest.split_once(']').ok_or_else(|| String::from("unclosed IPv6 bracket in postgres DSN"))?;
            let p = match after.strip_prefix(':') {
                Some(ps) => ps.parse::<u16>().map_err(|_| String::from("invalid postgres port"))?,
                None => 5432,
            };
            (h.to_string(), p)
        } else if let Some((h, p)) = host_port.rsplit_once(':') {
            (h.to_string(), p.parse::<u16>().map_err(|_| String::from("invalid postgres port"))?)
        } else {
            (host_port.to_string(), 5432)
        };
        if host.is_empty() { return Err(String::from("postgres DSN host must not be empty")); }
        let mut ssl_mode = PgSslMode::Prefer;
        for kv in query_part.split('&') {
            if let Some(v) = kv.strip_prefix("sslmode=") {
                ssl_mode = match v { "disable" => PgSslMode::Disable, "require" | "verify-ca" | "verify-full" => PgSslMode::Require, _ => PgSslMode::Prefer };
            }
        }
        Ok(Self {
            host,
            port,
            user: decode_percent_component(user_raw),
            password: decode_percent_component(password_raw),
            database: decode_percent_component(db),
            ssl_mode,
        })
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PgQueryResult {
    pub columns: Vec<String>,
    pub rows: Vec<Vec<Option<String>>>,
    pub command_tag: String,
}

enum PgStream {
    Plain(TcpStream),
    Tls(Box<tokio_rustls::client::TlsStream<TcpStream>>),
}

impl PgStream {
    async fn write_all(&mut self, buf: &[u8]) -> Result<(), String> {
        tokio::time::timeout(PG_IO_TIMEOUT, async {
            match self {
                Self::Plain(s) => s.write_all(buf).await.map_err(|e| e.to_string()),
                Self::Tls(s) => s.write_all(buf).await.map_err(|e| e.to_string()),
            }
        })
        .await
        .map_err(|_| String::from("postgres write timeout"))?
    }
    async fn read_exact(&mut self, buf: &mut [u8]) -> Result<(), String> {
        tokio::time::timeout(PG_IO_TIMEOUT, async {
            match self {
                Self::Plain(s) => s.read_exact(buf).await.map(|_| ()).map_err(|e| e.to_string()),
                Self::Tls(s) => s.read_exact(buf).await.map(|_| ()).map_err(|e| e.to_string()),
            }
        })
        .await
        .map_err(|_| String::from("postgres read timeout"))?
    }
    async fn read_u8(&mut self) -> Result<u8, String> {
        let mut b = [0_u8; 1];
        self.read_exact(&mut b).await?;
        Ok(b[0])
    }
}

pub struct PgWireClient {
    stream: PgStream,
}

fn build_tls_connector() -> TlsConnector {
    let mut roots = rustls::RootCertStore::empty();
    roots.extend(webpki_roots::TLS_SERVER_ROOTS.iter().cloned());
    let cfg = rustls::ClientConfig::builder()
        .with_root_certificates(roots)
        .with_no_client_auth();
    TlsConnector::from(Arc::new(cfg))
}

fn encode_startup_message(user: &str, database: &str) -> Vec<u8> {
    let mut body = Vec::new();
    body.extend_from_slice(&196_608_i32.to_be_bytes());
    for (k, v) in [("user", user), ("database", database), ("application_name", "fdai-rust")] {
        body.extend_from_slice(k.as_bytes());
        body.push(0);
        body.extend_from_slice(v.as_bytes());
        body.push(0);
    }
    body.push(0);
    let total_len = (body.len() + 4) as i32;
    let mut frame = Vec::with_capacity(body.len() + 4);
    frame.extend_from_slice(&total_len.to_be_bytes());
    frame.extend_from_slice(&body);
    frame
}

fn encode_typed_msg(tag: u8, payload: &[u8]) -> Vec<u8> {
    let total_len = (payload.len() + 4) as i32;
    let mut out = Vec::with_capacity(payload.len() + 5);
    out.push(tag);
    out.extend_from_slice(&total_len.to_be_bytes());
    out.extend_from_slice(payload);
    out
}

pub fn scram_sha256_client_final(
    password: &str,
    client_nonce: &str,
    client_first_bare: &str,
    server_first: &str,
) -> Result<(String, Vec<u8>), String> {
    let mut r_nonce = "";
    let mut salt_b64 = "";
    let mut iters: u32 = 0;
    for part in server_first.split(',') {
        if let Some(v) = part.strip_prefix("r=") { r_nonce = v; }
        else if let Some(v) = part.strip_prefix("s=") { salt_b64 = v; }
        else if let Some(v) = part.strip_prefix("i=") { iters = v.parse::<u32>().map_err(|_| String::from("invalid scram iterations"))?; }
    }
    if client_nonce.is_empty() || !r_nonce.starts_with(client_nonce) || r_nonce.len() <= client_nonce.len() {
        return Err(String::from("SCRAM server nonce does not extend client_nonce (RFC 5802 §5.1)"));
    }
    if !(4_096..=600_000).contains(&iters) {
        return Err(format!("SCRAM PBKDF2 iterations {iters} outside safe 4096..=600000 range"));
    }
    let Some(nz_iters) = NonZeroU32::new(iters) else { return Err(String::from("scram iterations must be > 0")); };
    let salt = base64::engine::general_purpose::STANDARD.decode(salt_b64).map_err(|e| format!("invalid scram salt: {e}"))?;
    let mut salted_pw = [0_u8; 32];
    pbkdf2::derive(pbkdf2::PBKDF2_HMAC_SHA256, nz_iters, &salt, password.as_bytes(), &mut salted_pw);
    let client_key = hmac::sign(&hmac::Key::new(hmac::HMAC_SHA256, &salted_pw), b"Client Key");
    let stored_key = digest::digest(&digest::SHA256, client_key.as_ref());
    let server_key = hmac::sign(&hmac::Key::new(hmac::HMAC_SHA256, &salted_pw), b"Server Key");
    let client_final_without_proof = format!("c=biws,r={r_nonce}");
    let auth_msg = format!("{client_first_bare},{server_first},{client_final_without_proof}");
    let client_sig = hmac::sign(&hmac::Key::new(hmac::HMAC_SHA256, stored_key.as_ref()), auth_msg.as_bytes());
    let server_sig = hmac::sign(&hmac::Key::new(hmac::HMAC_SHA256, server_key.as_ref()), auth_msg.as_bytes());
    let mut proof = [0_u8; 32];
    for (i, slot) in proof.iter_mut().enumerate() { *slot = client_key.as_ref()[i] ^ client_sig.as_ref()[i]; }
    Ok((format!("{client_final_without_proof},p={}", base64::engine::general_purpose::STANDARD.encode(proof)), server_sig.as_ref().to_vec()))
}

impl PgWireClient {
    pub async fn connect(cfg: &PgConnectionConfig) -> Result<Self, String> {
        let addr = if cfg.host.contains(':') {
            format!("[{}]:{}", cfg.host, cfg.port)
        } else {
            format!("{}:{}", cfg.host, cfg.port)
        };
        let mut tcp = tokio::time::timeout(PG_IO_TIMEOUT, TcpStream::connect(&addr))
            .await
            .map_err(|_| format!("postgres tcp connect timeout ({addr})"))?
            .map_err(|e| format!("postgres tcp connect failed ({addr}): {e}"))?;
        let mut stream = if cfg.ssl_mode != PgSslMode::Disable {
            let ssl_req: [u8; 8] = [0, 0, 0, 8, 0x04, 0xd2, 0x16, 0x2f];
            tokio::time::timeout(PG_IO_TIMEOUT, tcp.write_all(&ssl_req))
                .await
                .map_err(|_| String::from("postgres ssl request timeout"))?
                .map_err(|e| e.to_string())?;
            let mut reply = [0_u8; 1];
            tokio::time::timeout(PG_IO_TIMEOUT, tcp.read_exact(&mut reply))
                .await
                .map_err(|_| String::from("postgres ssl reply timeout"))?
                .map_err(|e| e.to_string())?;
            if reply[0] == b'S' {
                let server_name = ServerName::try_from(cfg.host.clone())
                    .map_err(|_| String::from("invalid postgres TLS SNI host"))?;
                let tls = tokio::time::timeout(PG_IO_TIMEOUT, build_tls_connector().connect(server_name, tcp))
                    .await
                    .map_err(|_| String::from("postgres TLS handshake timeout"))?
                    .map_err(|e| format!("postgres TLS handshake failed: {e}"))?;
                PgStream::Tls(Box::new(tls))
            } else if cfg.ssl_mode == PgSslMode::Require {
                return Err(String::from("postgres server refused required SSL/TLS"));
            } else {
                PgStream::Plain(tcp)
            }
        } else {
            PgStream::Plain(tcp)
        };
        stream.write_all(&encode_startup_message(&cfg.user, &cfg.database)).await?;
        let mut client = Self { stream };
        client.complete_handshake(cfg).await?;
        Ok(client)
    }

    pub async fn terminate(mut self) -> Result<(), String> {
        self.stream.write_all(&encode_typed_msg(b'X', &[])).await
    }

    async fn read_frame(&mut self) -> Result<(u8, Vec<u8>), String> {
        let tag = self.stream.read_u8().await?;
        let mut len_buf = [0_u8; 4];
        self.stream.read_exact(&mut len_buf).await?;
        let len = i32::from_be_bytes(len_buf);
        if !(4..=32 * 1024 * 1024).contains(&len) {
            return Err(format!("invalid PGv3 frame length: {len}"));
        }
        let mut body = vec![0_u8; (len - 4) as usize];
        if !body.is_empty() {
            self.stream.read_exact(&mut body).await?;
        }
        Ok((tag, body))
    }

    async fn complete_handshake(&mut self, cfg: &PgConnectionConfig) -> Result<(), String> {
        let mut client_nonce = String::new();
        let mut scram_client_first_bare = String::new();
        let mut expected_server_sig: Option<Vec<u8>> = None;
        loop {
            let (tag, body) = self.read_frame().await?;
            match tag {
                b'R' => {
                    if body.len() < 4 {
                        return Err(String::from("truncated PGv3 auth frame"));
                    }
                    let code = i32::from_be_bytes([body[0], body[1], body[2], body[3]]);
                    match code {
                        0 => {}
                        3 => {
                            let mut pw = cfg.password.as_bytes().to_vec();
                            pw.push(0);
                            self.stream.write_all(&encode_typed_msg(b'p', &pw)).await?;
                        }
                        10 => {
                            let mut nonce_raw = [0_u8; 18];
                            ring::rand::SystemRandom::new().fill(&mut nonce_raw).map_err(|_| String::from("CSPRNG failed for SCRAM nonce"))?;
                            client_nonce = base64::engine::general_purpose::STANDARD.encode(nonce_raw);
                            scram_client_first_bare = format!("n=,r={client_nonce}");
                            let init_msg = format!("n,,{scram_client_first_bare}");
                            let mut p = Vec::new();
                            p.extend_from_slice(b"SCRAM-SHA-256\0");
                            p.extend_from_slice(&(init_msg.len() as i32).to_be_bytes());
                            p.extend_from_slice(init_msg.as_bytes());
                            self.stream.write_all(&encode_typed_msg(b'p', &p)).await?;
                        }
                        11 => {
                            let srv = String::from_utf8_lossy(&body[4..]).to_string();
                            let (final_msg, srv_sig) = scram_sha256_client_final(&cfg.password, &client_nonce, &scram_client_first_bare, &srv)?;
                            expected_server_sig = Some(srv_sig);
                            self.stream.write_all(&encode_typed_msg(b'p', final_msg.as_bytes())).await?;
                        }
                        12 => {
                            let srv_final = String::from_utf8_lossy(&body[4..]);
                            let v_b64 = srv_final.split(',').find_map(|p| p.strip_prefix("v=")).ok_or_else(|| String::from("SCRAM server final missing v= signature"))?;
                            let got_sig = base64::engine::general_purpose::STANDARD.decode(v_b64.trim()).map_err(|_| String::from("invalid SCRAM server signature base64"))?;
                            let Some(ref exp_sig) = expected_server_sig else { return Err(String::from("unexpected SCRAM final before server-first")); };
                            if !bool::from(subtle::ConstantTimeEq::ct_eq(exp_sig.as_slice(), got_sig.as_slice())) {
                                return Err(String::from("SCRAM server signature mismatch (possible MITM)"));
                            }
                        }
                        other => return Err(format!("unsupported PGv3 auth code: {other}")),
                    }
                }
                b'S' | b'K' | b'N' => {}
                b'Z' => return Ok(()),
                b'E' => return Err(format!("postgres auth error: {}", String::from_utf8_lossy(&body))),
                _ => {}
            }
        }
    }

    pub async fn simple_query(&mut self, sql: &str) -> Result<PgQueryResult, String> {
        let mut payload = sql.as_bytes().to_vec();
        payload.push(0);
        self.stream.write_all(&encode_typed_msg(b'Q', &payload)).await?;
        let mut res = PgQueryResult::default();
        loop {
            let (tag, body) = self.read_frame().await?;
            match tag {
                b'T' if body.len() >= 2 => {
                    let ncols = i16::from_be_bytes([body[0], body[1]]) as usize;
                    let mut pos = 2_usize;
                    for _ in 0..ncols {
                        if let Some(nul) = body[pos..].iter().position(|&b| b == 0) {
                            res.columns.push(String::from_utf8_lossy(&body[pos..pos + nul]).to_string());
                            pos = (pos + nul + 1 + 18).min(body.len());
                        }
                    }
                }
                b'D' if body.len() >= 2 => {
                    let ncols = i16::from_be_bytes([body[0], body[1]]) as usize;
                    let mut pos = 2_usize;
                    let mut row = Vec::with_capacity(ncols);
                    for _ in 0..ncols {
                        if pos + 4 > body.len() { break; }
                        let flen = i32::from_be_bytes([body[pos], body[pos + 1], body[pos + 2], body[pos + 3]]);
                        pos += 4;
                        if flen < 0 {
                            row.push(None);
                        } else {
                            let end = (pos + flen as usize).min(body.len());
                            row.push(Some(String::from_utf8_lossy(&body[pos..end]).to_string()));
                            pos = end;
                        }
                    }
                    res.rows.push(row);
                }
                b'C' => res.command_tag = String::from_utf8_lossy(&body).trim_end_matches('\0').to_string(),
                b'Z' => return Ok(res),
                b'E' => return Err(format!("postgres query error: {}", String::from_utf8_lossy(&body))),
                _ => {}
            }
        }
    }

    pub async fn query_once(cfg: &PgConnectionConfig, sql: &str) -> Result<PgQueryResult, String> {
        let mut client = Self::connect(cfg).await?;
        let res = client.simple_query(sql).await;
        let _ = client.terminate().await;
        res
    }
}

pub fn build_pgvector_cosine_query(table: &str, embedding: &[f32], limit: usize) -> Result<String, &'static str> {
    let safe_table: String = table
        .chars()
        .filter(|c| c.is_ascii_alphanumeric() || *c == '_')
        .collect();
    if safe_table.is_empty() || safe_table != table || safe_table.len() > 63 {
        return Err("invalid pgvector table identifier");
    }
    if embedding.is_empty() || embedding.len() > 4096 || embedding.iter().any(|v| !v.is_finite()) {
        return Err("embedding vector must be non-empty, <= 4096 dims, and finite");
    }
    let vec_lit = embedding.iter().map(|v| format!("{v:.6}")).collect::<Vec<_>>().join(",");
    Ok(format!(
        "SELECT id, 1 - (embedding <=> '[{vec_lit}]'::vector) AS cosine_sim FROM {safe_table} ORDER BY embedding <=> '[{vec_lit}]'::vector LIMIT {}",
        limit.clamp(1, 500)
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::net::TcpListener;

    #[test]
    fn scram_and_pgvector_reject_invalid_inputs() {
        assert!(scram_sha256_client_final("pw", "cnonce", "n=,r=cnonce", "r=wrong,s=AAAA,i=4096").is_err());
        assert!(scram_sha256_client_final("pw", "cnonce", "n=,r=cnonce", "r=cnoncesrv,s=AAAA,i=10").is_err());
        assert!(build_pgvector_cosine_query("bad;drop", &[0.1], 5).is_err());
        assert!(build_pgvector_cosine_query("docs", &[], 5).is_err());
        assert!(build_pgvector_cosine_query("docs", &[0.1, 0.2], 5).is_ok());
        assert!(PgConnectionConfig::from_dsn("postgres://u:p@[::1]:5432/db?sslmode=disable").is_ok());
        let psy = PgConnectionConfig::from_dsn("postgresql+psycopg://u:s%40cret@127.0.0.1:5432/fdai");
        assert!(psy.is_ok());
        if let Ok(cfg) = psy {
            assert_eq!(cfg.password, "s@cret");
            assert!(!format!("{cfg:?}").contains("s@cret"));
            assert!(format!("{cfg:?}").contains("[REDACTED]"));
        }
        assert_eq!(pg_quote_literal("a'b\0c"), "'a''bc'");
        assert!(PgConnectionConfig::from_dsn("postgres://u:p@/db").is_err());
    }

    #[tokio::test]
    async fn pg_wire_client_roundtrips_real_tcp_simple_query() -> Result<(), String> {
        let listener = TcpListener::bind("127.0.0.1:0").await.map_err(|e| e.to_string())?;
        let port = listener.local_addr().map_err(|e| e.to_string())?.port();
        let srv = tokio::spawn(async move {
            if let Ok((mut s, _)) = listener.accept().await {
                let mut hdr = [0_u8; 4];
                if s.read_exact(&mut hdr).await.is_err() { return; }
                let len = i32::from_be_bytes(hdr) as usize;
                let mut body = vec![0_u8; len.saturating_sub(4)];
                let _ = s.read_exact(&mut body).await;
                let _ = s.write_all(&encode_typed_msg(b'R', &0_i32.to_be_bytes())).await;
                let _ = s.write_all(&encode_typed_msg(b'Z', b"I")).await;
                let mut qtag = [0_u8; 5];
                if s.read_exact(&mut qtag).await.is_ok() && qtag[0] == b'Q' {
                    let qlen = i32::from_be_bytes([qtag[1], qtag[2], qtag[3], qtag[4]]) as usize;
                    let mut qbody = vec![0_u8; qlen.saturating_sub(4)];
                    let _ = s.read_exact(&mut qbody).await;
                    let mut row_desc = vec![0_u8, 1];
                    row_desc.extend_from_slice(b"ok\0");
                    row_desc.extend_from_slice(&[0_u8; 18]);
                    let _ = s.write_all(&encode_typed_msg(b'T', &row_desc)).await;
                    let mut data = vec![0_u8, 1];
                    data.extend_from_slice(&1_i32.to_be_bytes());
                    data.push(b'1');
                    let _ = s.write_all(&encode_typed_msg(b'D', &data)).await;
                    let _ = s.write_all(&encode_typed_msg(b'C', b"SELECT 1\0")).await;
                    let _ = s.write_all(&encode_typed_msg(b'Z', b"I")).await;
                }
            }
        });
        let cfg = PgConnectionConfig::from_dsn(&format!("postgres://app:secret@127.0.0.1:{port}/fdai?sslmode=disable"))?;
        let mut client = PgWireClient::connect(&cfg).await?;
        let res = client.simple_query("SELECT 1 AS ok").await?;
        assert_eq!(res.columns, vec![String::from("ok")]);
        assert_eq!(res.rows, vec![vec![Some(String::from("1"))]]);
        client.terminate().await?;
        let _ = srv.await;
        Ok(())
    }
}
