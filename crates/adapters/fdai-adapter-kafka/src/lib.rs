//! Pure-Rust Kafka Binary Wire Protocol (+TLS, Produce/Fetch/OffsetCommit, Timeouts) Adapter.
use fdai_ports::EventBusConsumerPort;
use rustls::pki_types::ServerName;
use std::sync::Arc;
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpStream;
use tokio_rustls::TlsConnector;

const KAFKA_IO_TIMEOUT: Duration = Duration::from_secs(15);

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct KafkaBrokerConfig { pub broker_addr: String, pub client_id: String, pub dlq_topic: String, pub use_tls: bool }

enum KafkaStream { Plain(TcpStream), Tls(Box<tokio_rustls::client::TlsStream<TcpStream>>) }

impl KafkaStream {
    async fn write_all(&mut self, buf: &[u8]) -> Result<(), String> {
        tokio::time::timeout(KAFKA_IO_TIMEOUT, async {
            match self { Self::Plain(s) => s.write_all(buf).await.map_err(|e| e.to_string()), Self::Tls(s) => s.write_all(buf).await.map_err(|e| e.to_string()) }
        }).await.map_err(|_| String::from("kafka write timeout"))?
    }
    async fn read_exact(&mut self, buf: &mut [u8]) -> Result<(), String> {
        tokio::time::timeout(KAFKA_IO_TIMEOUT, async {
            match self { Self::Plain(s) => s.read_exact(buf).await.map(|_| ()).map_err(|e| e.to_string()), Self::Tls(s) => s.read_exact(buf).await.map(|_| ()).map_err(|e| e.to_string()) }
        }).await.map_err(|_| String::from("kafka read timeout"))?
    }
}

pub struct KafkaWireClient {
    stream: KafkaStream,
    client_id: String,
    corr_id: i32,
}

fn ieee_crc32(data: &[u8]) -> u32 {
    let mut crc: u32 = 0xffff_ffff;
    for &b in data {
        crc ^= u32::from(b);
        for _ in 0..8 {
            crc = if crc & 1 != 0 { (crc >> 1) ^ 0xedb8_8320 } else { crc >> 1 };
        }
    }
    !crc
}

fn push_kstr(buf: &mut Vec<u8>, s: &str) -> Result<(), String> {
    let len = i16::try_from(s.len()).map_err(|_| String::from("kafka string exceeds i16::MAX"))?;
    buf.extend_from_slice(&len.to_be_bytes());
    buf.extend_from_slice(s.as_bytes());
    Ok(())
}

fn push_kbytes(buf: &mut Vec<u8>, b: &[u8]) -> Result<(), String> {
    let len = i32::try_from(b.len()).map_err(|_| String::from("kafka bytes exceed i32::MAX"))?;
    buf.extend_from_slice(&len.to_be_bytes());
    buf.extend_from_slice(b);
    Ok(())
}

impl KafkaWireClient {
    pub async fn connect(cfg: &KafkaBrokerConfig) -> Result<Self, String> {
        let tcp = tokio::time::timeout(KAFKA_IO_TIMEOUT, TcpStream::connect(&cfg.broker_addr))
            .await
            .map_err(|_| format!("kafka tcp connect timeout ({})", cfg.broker_addr))?
            .map_err(|e| format!("kafka tcp connect failed ({}): {e}", cfg.broker_addr))?;
        let stream = if cfg.use_tls {
            let host = cfg.broker_addr.rsplit_once(':').map_or(cfg.broker_addr.as_str(), |(h, _)| h);
            let mut roots = rustls::RootCertStore::empty();
            roots.extend(webpki_roots::TLS_SERVER_ROOTS.iter().cloned());
            let tls_cfg = rustls::ClientConfig::builder()
                .with_root_certificates(roots)
                .with_no_client_auth();
            let sni = ServerName::try_from(host.to_string()).map_err(|_| String::from("invalid kafka TLS SNI host"))?;
            let tls = tokio::time::timeout(KAFKA_IO_TIMEOUT, TlsConnector::from(Arc::new(tls_cfg)).connect(sni, tcp))
                .await
                .map_err(|_| String::from("kafka TLS handshake timeout"))?
                .map_err(|e| format!("kafka TLS handshake failed: {e}"))?;
            KafkaStream::Tls(Box::new(tls))
        } else {
            KafkaStream::Plain(tcp)
        };
        Ok(Self { stream, client_id: cfg.client_id.clone(), corr_id: 1 })
    }

    async fn roundtrip(&mut self, api_key: i16, api_version: i16, body: &[u8]) -> Result<Vec<u8>, String> {
        let cid = self.corr_id;
        self.corr_id = self.corr_id.wrapping_add(1);
        let mut req = Vec::with_capacity(body.len() + 32);
        req.extend_from_slice(&api_key.to_be_bytes());
        req.extend_from_slice(&api_version.to_be_bytes());
        req.extend_from_slice(&cid.to_be_bytes());
        push_kstr(&mut req, &self.client_id)?;
        req.extend_from_slice(body);
        let req_len = i32::try_from(req.len()).map_err(|_| String::from("kafka request frame too large"))?;
        let mut frame = Vec::with_capacity(req.len() + 4);
        frame.extend_from_slice(&req_len.to_be_bytes());
        frame.extend_from_slice(&req);
        self.stream.write_all(&frame).await?;
        let mut len_buf = [0_u8; 4];
        self.stream.read_exact(&mut len_buf).await?;
        let rlen = i32::from_be_bytes(len_buf);
        if !(4..=16 * 1024 * 1024).contains(&rlen) {
            return Err(format!("invalid kafka response frame length: {rlen}"));
        }
        let mut resp = vec![0_u8; rlen as usize];
        self.stream.read_exact(&mut resp).await?;
        let got_cid = i32::from_be_bytes([resp[0], resp[1], resp[2], resp[3]]);
        if got_cid != cid {
            return Err(format!("kafka correlation_id mismatch: expected {cid}, got {got_cid}"));
        }
        Ok(resp[4..].to_vec())
    }

    pub async fn api_versions(&mut self) -> Result<i16, String> {
        let resp = self.roundtrip(18, 0, &[]).await?;
        if resp.len() < 2 {
            return Err(String::from("truncated ApiVersions response"));
        }
        let error_code = i16::from_be_bytes([resp[0], resp[1]]);
        if error_code != 0 {
            return Err(format!("kafka ApiVersions broker error_code={error_code}"));
        }
        Ok(error_code)
    }

    pub async fn produce_v0(&mut self, topic: &str, partition: i32, key: &[u8], payload: &[u8]) -> Result<Vec<u8>, String> {
        let mut msg_body = vec![0_u8, 0_u8];
        push_kbytes(&mut msg_body, key)?;
        push_kbytes(&mut msg_body, payload)?;
        let crc = ieee_crc32(&msg_body);
        let mut message = Vec::with_capacity(msg_body.len() + 4);
        message.extend_from_slice(&crc.to_be_bytes());
        message.extend_from_slice(&msg_body);
        let msg_len = i32::try_from(message.len()).map_err(|_| String::from("kafka message too large"))?;
        let mut msg_set = Vec::new();
        msg_set.extend_from_slice(&0_i64.to_be_bytes());
        msg_set.extend_from_slice(&msg_len.to_be_bytes());
        msg_set.extend_from_slice(&message);
        let mut body = Vec::new();
        body.extend_from_slice(&(-1_i16).to_be_bytes());
        body.extend_from_slice(&5_000_i32.to_be_bytes());
        body.extend_from_slice(&1_i32.to_be_bytes());
        push_kstr(&mut body, topic)?;
        body.extend_from_slice(&1_i32.to_be_bytes());
        body.extend_from_slice(&partition.to_be_bytes());
        push_kbytes(&mut body, &msg_set)?;
        let resp = self.roundtrip(0, 0, &body).await?;
        if resp.len() >= 2 {
            let error_code = i16::from_be_bytes([resp[0], resp[1]]);
            if error_code != 0 {
                return Err(format!("kafka produce broker error_code={error_code}"));
            }
        }
        Ok(resp)
    }

    pub async fn fetch_v0(&mut self, topic: &str, partition: i32, offset: i64, max_bytes: i32) -> Result<Vec<u8>, String> {
        let mut body = Vec::new();
        body.extend_from_slice(&(-1_i32).to_be_bytes());
        body.extend_from_slice(&500_i32.to_be_bytes());
        body.extend_from_slice(&1_i32.to_be_bytes());
        body.extend_from_slice(&1_i32.to_be_bytes());
        push_kstr(&mut body, topic)?;
        body.extend_from_slice(&1_i32.to_be_bytes());
        body.extend_from_slice(&partition.to_be_bytes());
        body.extend_from_slice(&offset.to_be_bytes());
        body.extend_from_slice(&max_bytes.clamp(1024, 8 * 1024 * 1024).to_be_bytes());
        let resp = self.roundtrip(1, 0, &body).await?;
        if resp.len() >= 2 {
            let error_code = i16::from_be_bytes([resp[0], resp[1]]);
            if error_code != 0 {
                return Err(format!("kafka fetch broker error_code={error_code}"));
            }
        }
        Ok(resp)
    }

    pub async fn commit_offset_v0(&mut self, group_id: &str, topic: &str, partition: i32, offset: i64) -> Result<Vec<u8>, String> {
        let mut body = Vec::new();
        push_kstr(&mut body, group_id)?;
        body.extend_from_slice(&1_i32.to_be_bytes());
        push_kstr(&mut body, topic)?;
        body.extend_from_slice(&1_i32.to_be_bytes());
        body.extend_from_slice(&partition.to_be_bytes());
        body.extend_from_slice(&offset.to_be_bytes());
        push_kstr(&mut body, "outbox-committed")?;
        self.roundtrip(8, 0, &body).await
    }

    pub async fn list_offsets_v0(&mut self, topic: &str, partition: i32, time_ms: i64) -> Result<i64, String> {
        let mut body = Vec::new();
        body.extend_from_slice(&(-1_i32).to_be_bytes());
        body.extend_from_slice(&1_i32.to_be_bytes());
        push_kstr(&mut body, topic)?;
        body.extend_from_slice(&1_i32.to_be_bytes());
        body.extend_from_slice(&partition.to_be_bytes());
        body.extend_from_slice(&time_ms.to_be_bytes());
        body.extend_from_slice(&1_i32.to_be_bytes());
        let resp = self.roundtrip(2, 0, &body).await?;
        let mut pos = 0_usize;
        let t_cnt = read_be_i32(&resp, &mut pos)?;
        if t_cnt <= 0 {
            return Err(String::from("kafka ListOffsets returned 0 topics"));
        }
        let _t_name = read_kstr(&resp, &mut pos)?;
        let p_cnt = read_be_i32(&resp, &mut pos)?;
        if p_cnt <= 0 {
            return Err(String::from("kafka ListOffsets returned 0 partitions"));
        }
        let _part = read_be_i32(&resp, &mut pos)?;
        let err_code = read_be_i16(&resp, &mut pos)?;
        if err_code != 0 {
            return Err(format!("kafka ListOffsets error_code={err_code}"));
        }
        let off_cnt = read_be_i32(&resp, &mut pos)?;
        if off_cnt <= 0 {
            return Ok(0);
        }
        read_be_i64(&resp, &mut pos)
    }

    pub async fn fetch_records_v0(
        &mut self,
        topic: &str,
        partition: i32,
        offset: i64,
        max_bytes: i32,
    ) -> Result<KafkaFetchBatch, String> {
        let mut body = Vec::new();
        body.extend_from_slice(&(-1_i32).to_be_bytes());
        body.extend_from_slice(&250_i32.to_be_bytes());
        body.extend_from_slice(&1_i32.to_be_bytes());
        body.extend_from_slice(&1_i32.to_be_bytes());
        push_kstr(&mut body, topic)?;
        body.extend_from_slice(&1_i32.to_be_bytes());
        body.extend_from_slice(&partition.to_be_bytes());
        body.extend_from_slice(&offset.to_be_bytes());
        body.extend_from_slice(&max_bytes.clamp(1024, 2 * 1024 * 1024).to_be_bytes());
        let resp = self.roundtrip(1, 0, &body).await?;
        parse_fetch_v0_response(&resp, offset)
    }

    pub async fn fetch_records_v4(
        &mut self,
        topic: &str,
        partition: i32,
        offset: i64,
        max_bytes: i32,
    ) -> Result<KafkaFetchBatch, String> {
        let capped = max_bytes.clamp(1024, 2 * 1024 * 1024);
        let mut body = Vec::new();
        body.extend_from_slice(&(-1_i32).to_be_bytes()); // replica_id
        body.extend_from_slice(&250_i32.to_be_bytes());  // max_wait_ms
        body.extend_from_slice(&1_i32.to_be_bytes());    // min_bytes
        body.extend_from_slice(&capped.to_be_bytes());   // max_bytes (v3+)
        body.push(0_u8);                                 // isolation_level (v4: READ_UNCOMMITTED)
        body.extend_from_slice(&1_i32.to_be_bytes());    // topics.len
        push_kstr(&mut body, topic)?;
        body.extend_from_slice(&1_i32.to_be_bytes());    // partitions.len
        body.extend_from_slice(&partition.to_be_bytes());
        body.extend_from_slice(&offset.to_be_bytes());
        body.extend_from_slice(&capped.to_be_bytes());
        let resp = self.roundtrip(1, 4, &body).await?;
        parse_fetch_v4_response(&resp, offset)
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct KafkaFetchedRecord {
    pub offset: i64,
    pub key: Vec<u8>,
    pub value: Vec<u8>,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct KafkaFetchBatch {
    pub high_watermark: i64,
    pub next_offset: i64,
    pub records: Vec<KafkaFetchedRecord>,
}

fn read_be_i16(buf: &[u8], pos: &mut usize) -> Result<i16, String> {
    if *pos + 2 > buf.len() {
        return Err(String::from("truncated kafka i16"));
    }
    let v = i16::from_be_bytes([buf[*pos], buf[*pos + 1]]);
    *pos += 2;
    Ok(v)
}

fn read_be_i32(buf: &[u8], pos: &mut usize) -> Result<i32, String> {
    if *pos + 4 > buf.len() {
        return Err(String::from("truncated kafka i32"));
    }
    let v = i32::from_be_bytes([buf[*pos], buf[*pos + 1], buf[*pos + 2], buf[*pos + 3]]);
    *pos += 4;
    Ok(v)
}

fn read_be_i64(buf: &[u8], pos: &mut usize) -> Result<i64, String> {
    if *pos + 8 > buf.len() {
        return Err(String::from("truncated kafka i64"));
    }
    let v = i64::from_be_bytes([
        buf[*pos],
        buf[*pos + 1],
        buf[*pos + 2],
        buf[*pos + 3],
        buf[*pos + 4],
        buf[*pos + 5],
        buf[*pos + 6],
        buf[*pos + 7],
    ]);
    *pos += 8;
    Ok(v)
}

fn read_kstr<'a>(buf: &'a [u8], pos: &mut usize) -> Result<&'a str, String> {
    let len = read_be_i16(buf, pos)?;
    if len < 0 {
        return Ok("");
    }
    let ulen = len as usize;
    if *pos + ulen > buf.len() {
        return Err(String::from("truncated kafka string"));
    }
    let s = std::str::from_utf8(&buf[*pos..*pos + ulen]).unwrap_or("");
    *pos += ulen;
    Ok(s)
}

fn read_varint_zigzag(buf: &[u8], pos: &mut usize) -> Result<i64, String> {
    let mut raw: u64 = 0;
    let mut shift: u32 = 0;
    while *pos < buf.len() && shift <= 63 {
        let b = buf[*pos];
        *pos += 1;
        raw |= u64::from(b & 0x7f) << shift;
        if (b & 0x80) == 0 {
            let signed = ((raw >> 1) as i64) ^ -((raw & 1) as i64);
            return Ok(signed);
        }
        shift += 7;
    }
    Err(String::from("truncated or overflowing kafka varint"))
}

pub fn parse_fetch_v4_response(resp: &[u8], req_offset: i64) -> Result<KafkaFetchBatch, String> {
    let mut pos = 0_usize;
    let _throttle_ms = read_be_i32(resp, &mut pos)?;
    let t_cnt = read_be_i32(resp, &mut pos)?;
    if t_cnt <= 0 {
        return Ok(KafkaFetchBatch {
            high_watermark: req_offset,
            next_offset: req_offset,
            records: Vec::new(),
        });
    }
    let _topic = read_kstr(resp, &mut pos)?;
    let p_cnt = read_be_i32(resp, &mut pos)?;
    if p_cnt <= 0 {
        return Ok(KafkaFetchBatch {
            high_watermark: req_offset,
            next_offset: req_offset,
            records: Vec::new(),
        });
    }
    let _part = read_be_i32(resp, &mut pos)?;
    let err_code = read_be_i16(resp, &mut pos)?;
    if err_code != 0 {
        return Err(format!("kafka FetchResponse v4 partition error_code={err_code}"));
    }
    let high_watermark = read_be_i64(resp, &mut pos)?;
    let _last_stable_offset = read_be_i64(resp, &mut pos)?;
    let aborted_cnt = read_be_i32(resp, &mut pos)?;
    if aborted_cnt > 0 {
        let skip = (aborted_cnt as usize).saturating_mul(16);
        if pos + skip > resp.len() {
            return Err(String::from("truncated kafka aborted_transactions"));
        }
        pos += skip;
    }
    let set_len = read_be_i32(resp, &mut pos)?;
    decode_record_set_slice(resp, pos, set_len, high_watermark, req_offset)
}

pub fn parse_fetch_v0_response(resp: &[u8], req_offset: i64) -> Result<KafkaFetchBatch, String> {
    let mut pos = 0_usize;
    let t_cnt = read_be_i32(resp, &mut pos)?;
    if t_cnt <= 0 {
        return Ok(KafkaFetchBatch {
            high_watermark: req_offset,
            next_offset: req_offset,
            records: Vec::new(),
        });
    }
    let _topic = read_kstr(resp, &mut pos)?;
    let p_cnt = read_be_i32(resp, &mut pos)?;
    if p_cnt <= 0 {
        return Ok(KafkaFetchBatch {
            high_watermark: req_offset,
            next_offset: req_offset,
            records: Vec::new(),
        });
    }
    let _part = read_be_i32(resp, &mut pos)?;
    let err_code = read_be_i16(resp, &mut pos)?;
    if err_code != 0 {
        return Err(format!("kafka FetchResponse partition error_code={err_code}"));
    }
    let high_watermark = read_be_i64(resp, &mut pos)?;
    let set_len = read_be_i32(resp, &mut pos)?;
    decode_record_set_slice(resp, pos, set_len, high_watermark, req_offset)
}

fn decode_record_set_slice(
    resp: &[u8],
    pos: usize,
    set_len: i32,
    high_watermark: i64,
    req_offset: i64,
) -> Result<KafkaFetchBatch, String> {
    if set_len <= 0 {
        return Ok(KafkaFetchBatch {
            high_watermark,
            next_offset: req_offset,
            records: Vec::new(),
        });
    }
    let set_end = (pos + set_len as usize).min(resp.len());
    let set_bytes = &resp[pos..set_end];
    let mut records = Vec::new();
    let mut next_offset = req_offset;
    let mut cur = 0_usize;
    while cur + 12 <= set_bytes.len() && records.len() < 256 {
        let base_or_rec_off = read_be_i64(set_bytes, &mut cur)?;
        let item_len = read_be_i32(set_bytes, &mut cur)?;
        if item_len <= 0 || cur + item_len as usize > set_bytes.len() {
            break;
        }
        let item_end = cur + item_len as usize;
        let payload = &set_bytes[cur..item_end];
        cur = item_end;
        if payload.len() >= 5 && payload[4] == 2 && payload.len() >= 49 {
            // Kafka RecordBatch v2 (magic == 2)
            let attrs = i16::from_be_bytes([payload[9], payload[10]]);
            let last_delta = i32::from_be_bytes([payload[11], payload[12], payload[13], payload[14]]);
            let rec_cnt = i32::from_be_bytes([payload[45], payload[46], payload[47], payload[48]]);
            let batch_next = base_or_rec_off.saturating_add(i64::from(last_delta)).saturating_add(1);
            if batch_next > next_offset {
                next_offset = batch_next;
            }
            if rec_cnt > 0 {
                let codec = attrs & 0x07;
                let decoded_buf: Option<Vec<u8>> = if codec == 0 {
                    None
                } else if codec == 2 {
                    decompress_snappy_kafka(&payload[49..], 4 * 1024 * 1024).ok()
                } else {
                    Some(Vec::new())
                };
                let rec_bytes: &[u8] = match (&decoded_buf, codec) {
                    (None, 0) => &payload[49..],
                    (Some(buf), 2) if !buf.is_empty() => buf.as_slice(),
                    _ => &[],
                };
                let mut rpos = 0_usize;
                for _ in 0..rec_cnt.min(256) {
                    if rpos >= rec_bytes.len() { break; }
                    let rlen = match read_varint_zigzag(rec_bytes, &mut rpos) {
                        Ok(n) if n > 0 => n as usize,
                        _ => break,
                    };
                    let rend = (rpos + rlen).min(rec_bytes.len());
                    let rslice = &rec_bytes[rpos..rend];
                    rpos = rend;
                    let mut rp = 1_usize; // skip attributes byte
                    if rp > rslice.len() { continue; }
                    let _ts_delta = read_varint_zigzag(rslice, &mut rp).unwrap_or(0);
                    let off_delta = read_varint_zigzag(rslice, &mut rp).unwrap_or(0);
                    let klen = read_varint_zigzag(rslice, &mut rp).unwrap_or(-1);
                    let key = if klen > 0 && rp + klen as usize <= rslice.len() {
                        let k = rslice[rp..rp + klen as usize].to_vec();
                        rp += klen as usize;
                        k
                    } else {
                        Vec::new()
                    };
                    let vlen = read_varint_zigzag(rslice, &mut rp).unwrap_or(-1);
                    let value = if vlen > 0 && rp + vlen as usize <= rslice.len() {
                        rslice[rp..rp + vlen as usize].to_vec()
                    } else {
                        Vec::new()
                    };
                    let rec_off = base_or_rec_off.saturating_add(off_delta);
                    if rec_off >= req_offset {
                        records.push(KafkaFetchedRecord { offset: rec_off, key, value });
                    }
                }
            }
        } else if payload.len() >= 14 {
            // MessageSet v0 / v1 (crc:4, magic:1, attrs:1, [ts:8 if v1], key, value)
            let magic = payload[4];
            let mut mp = if magic == 1 { 14_usize } else { 6_usize };
            if mp + 4 <= payload.len() {
                let klen = read_be_i32(payload, &mut mp)?;
                let key = if klen > 0 && mp + klen as usize <= payload.len() {
                    let k = payload[mp..mp + klen as usize].to_vec();
                    mp += klen as usize;
                    k
                } else {
                    Vec::new()
                };
                if mp + 4 <= payload.len() {
                    let vlen = read_be_i32(payload, &mut mp)?;
                    let value = if vlen > 0 && mp + vlen as usize <= payload.len() {
                        payload[mp..mp + vlen as usize].to_vec()
                    } else {
                        Vec::new()
                    };
                    if base_or_rec_off >= req_offset {
                        records.push(KafkaFetchedRecord {
                            offset: base_or_rec_off,
                            key,
                            value,
                        });
                    }
                }
            }
            let cand = base_or_rec_off.saturating_add(1);
            if cand > next_offset {
                next_offset = cand;
            }
        }
    }
    Ok(KafkaFetchBatch {
        high_watermark,
        next_offset,
        records,
    })
}

fn decompress_snappy_kafka(input: &[u8], max_out: usize) -> Result<Vec<u8>, String> {
    const XERIAL_MAGIC: [u8; 8] = [0x82, b'S', b'N', b'A', b'P', b'P', b'Y', 0x00];
    if input.len() >= 16 && input[..8] == XERIAL_MAGIC {
        let mut pos = 16_usize;
        let mut out = Vec::new();
        while pos + 4 <= input.len() {
            let clen = u32::from_be_bytes([input[pos], input[pos + 1], input[pos + 2], input[pos + 3]]) as usize;
            pos += 4;
            if clen == 0 || pos + clen > input.len() {
                return Err(String::from("truncated xerial snappy chunk"));
            }
            let chunk = decompress_snappy_raw(&input[pos..pos + clen], max_out.saturating_sub(out.len()))?;
            out.extend_from_slice(&chunk);
            pos += clen;
        }
        Ok(out)
    } else {
        decompress_snappy_raw(input, max_out)
    }
}

fn decompress_snappy_raw(input: &[u8], max_out: usize) -> Result<Vec<u8>, String> {
    let mut pos = 0_usize;
    let mut expected_len: usize = 0;
    let mut shift: u32 = 0;
    loop {
        if pos >= input.len() || shift > 28 {
            return Err(String::from("invalid snappy varint length"));
        }
        let b = input[pos];
        pos += 1;
        expected_len |= ((b & 0x7f) as usize) << shift;
        if (b & 0x80) == 0 {
            break;
        }
        shift += 7;
    }
    if expected_len > max_out {
        return Err(String::from("snappy decompressed size exceeds cap"));
    }
    let mut out = Vec::with_capacity(expected_len);
    while pos < input.len() {
        let tag = input[pos];
        pos += 1;
        let kind = tag & 0x03;
        if kind == 0 {
            let n = (tag >> 2) as usize;
            let lit_len = if n < 60 {
                n + 1
            } else {
                let extra = n - 59;
                if pos + extra > input.len() {
                    return Err(String::from("truncated snappy literal length"));
                }
                let mut v = 0_usize;
                for i in 0..extra {
                    v |= (input[pos + i] as usize) << (8 * i);
                }
                pos += extra;
                v + 1
            };
            if pos + lit_len > input.len() || out.len() + lit_len > max_out {
                return Err(String::from("snappy literal out of bounds"));
            }
            out.extend_from_slice(&input[pos..pos + lit_len]);
            pos += lit_len;
        } else {
            let (copy_len, offset) = match kind {
                1 => {
                    if pos >= input.len() {
                        return Err(String::from("truncated snappy copy1"));
                    }
                    let len = (((tag >> 2) & 0x07) as usize) + 4;
                    let off = ((((tag >> 5) & 0x07) as usize) << 8) | (input[pos] as usize);
                    pos += 1;
                    (len, off)
                }
                2 => {
                    if pos + 2 > input.len() {
                        return Err(String::from("truncated snappy copy2"));
                    }
                    let len = ((tag >> 2) as usize) + 1;
                    let off = (input[pos] as usize) | ((input[pos + 1] as usize) << 8);
                    pos += 2;
                    (len, off)
                }
                _ => {
                    if pos + 4 > input.len() {
                        return Err(String::from("truncated snappy copy4"));
                    }
                    let len = ((tag >> 2) as usize) + 1;
                    let off = u32::from_le_bytes([input[pos], input[pos + 1], input[pos + 2], input[pos + 3]]) as usize;
                    pos += 4;
                    (len, off)
                }
            };
            if offset == 0 || offset > out.len() || out.len() + copy_len > max_out {
                return Err(String::from("snappy copy offset/length out of bounds"));
            }
            for _ in 0..copy_len {
                let b = out[out.len() - offset];
                out.push(b);
            }
        }
    }
    if out.len() != expected_len {
        return Err(String::from("snappy decompressed length mismatch"));
    }
    Ok(out)
}

#[derive(Default)]
pub struct ManualCommitKafkaAdapter {
    pub poison_halted: bool,
    pub committed_offset: u64,
    pub dlq_routed_count: u64,
}

impl ManualCommitKafkaAdapter {
    pub fn route_poison_to_dlq(&mut self) {
        self.poison_halted = true;
        self.dlq_routed_count += 1;
    }
}

impl EventBusConsumerPort for ManualCommitKafkaAdapter {
    fn commit_offset_after_outbox(&mut self, off: u64, outbox_ok: bool) -> Result<u64, &'static str> {
        if self.poison_halted { return Err("poison-pill halt active"); }
        if !outbox_ok { return Err("outbox must commit before offset"); }
        self.committed_offset = off;
        Ok(off)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::net::TcpListener;

    #[tokio::test]
    async fn kafka_wire_client_roundtrips_api_versions_produce_and_fetch() -> Result<(), String> {
        let listener = TcpListener::bind("127.0.0.1:0").await.map_err(|e| e.to_string())?;
        let addr = listener.local_addr().map_err(|e| e.to_string())?.to_string();
        let srv = tokio::spawn(async move {
            if let Ok((mut s, _)) = listener.accept().await {
                for _ in 0..3 {
                    let mut lb = [0_u8; 4];
                    if s.read_exact(&mut lb).await.is_err() { break; }
                    let rlen = i32::from_be_bytes(lb) as usize;
                    let mut req = vec![0_u8; rlen];
                    if s.read_exact(&mut req).await.is_err() { break; }
                    let cid = [req[4], req[5], req[6], req[7]];
                    let mut resp = Vec::new();
                    resp.extend_from_slice(&cid);
                    resp.extend_from_slice(&0_i16.to_be_bytes());
                    let mut out = Vec::new();
                    out.extend_from_slice(&(resp.len() as i32).to_be_bytes());
                    out.extend_from_slice(&resp);
                    let _ = s.write_all(&out).await;
                }
            }
        });
        let cfg = KafkaBrokerConfig {
            broker_addr: addr,
            client_id: String::from("fdai-rust-test"),
            dlq_topic: String::from("fdai.dlq"),
            use_tls: false,
        };
        let mut client = KafkaWireClient::connect(&cfg).await?;
        assert_eq!(client.api_versions().await?, 0);
        assert_eq!(client.produce_v0("fdai.events", 0, b"k1", b"{\"ok\":true}").await?, vec![0, 0]);
        assert_eq!(client.fetch_v0("fdai.events", 0, 0, 4096).await?, vec![0, 0]);
        let _ = srv.await;
        Ok(())
    }

    #[test]
    fn parse_fetch_v0_response_decodes_v0_message_set() -> Result<(), String> {
        let mut msg_body = vec![0_u8, 0_u8];
        push_kbytes(&mut msg_body, b"k1")?;
        push_kbytes(&mut msg_body, b"{\"stage\":\"audit\"}")?;
        let crc = ieee_crc32(&msg_body);
        let mut msg = Vec::new();
        msg.extend_from_slice(&crc.to_be_bytes());
        msg.extend_from_slice(&msg_body);
        let mut msg_set = Vec::new();
        msg_set.extend_from_slice(&7_i64.to_be_bytes());
        msg_set.extend_from_slice(&(msg.len() as i32).to_be_bytes());
        msg_set.extend_from_slice(&msg);

        let mut resp = Vec::new();
        resp.extend_from_slice(&1_i32.to_be_bytes());
        push_kstr(&mut resp, "fdai.pipeline.stages")?;
        resp.extend_from_slice(&1_i32.to_be_bytes());
        resp.extend_from_slice(&0_i32.to_be_bytes());
        resp.extend_from_slice(&0_i16.to_be_bytes());
        resp.extend_from_slice(&8_i64.to_be_bytes());
        resp.extend_from_slice(&(msg_set.len() as i32).to_be_bytes());
        resp.extend_from_slice(&msg_set);

        let batch = parse_fetch_v0_response(&resp, 7)?;
        assert_eq!(batch.high_watermark, 8);
        assert_eq!(batch.next_offset, 8);
        assert_eq!(batch.records.len(), 1);
        assert_eq!(batch.records[0].offset, 7);
        assert_eq!(batch.records[0].value, b"{\"stage\":\"audit\"}");
        Ok(())
    }

    #[test]
    fn snappy_raw_block_decodes_literals_and_copies() -> Result<(), String> {
        // Uncompressed "abcabcabc" (len 9): literal "abc" (tag=2<<2=0x08), copy1 len=6 off=3 (tag=(2<<2)|1=0x09, off=0x03)
        let compressed: [u8; 7] = [0x09, 0x08, b'a', b'b', b'c', 0x09, 0x03];
        let out = decompress_snappy_kafka(&compressed, 1024)?;
        assert_eq!(out, b"abcabcabc");
        assert!(decompress_snappy_kafka(&compressed, 4).is_err());
        Ok(())
    }
}
