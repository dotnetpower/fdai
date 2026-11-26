//! Zero-unsafe shared Axum 0.8 compatible router & JSON value types.
use std::collections::BTreeMap;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct StatusCode(pub u16);

impl StatusCode {
    pub const OK: Self = Self(200);
    pub const CREATED: Self = Self(201);
    pub const ACCEPTED: Self = Self(202);
    pub const NO_CONTENT: Self = Self(204);
    pub const BAD_REQUEST: Self = Self(400);
    pub const UNAUTHORIZED: Self = Self(401);
    pub const FORBIDDEN: Self = Self(403);
    pub const NOT_FOUND: Self = Self(404);
    pub const CONFLICT: Self = Self(409);
    pub const PAYLOAD_TOO_LARGE: Self = Self(413);
    pub const UNPROCESSABLE_ENTITY: Self = Self(422);
    pub const INTERNAL_SERVER_ERROR: Self = Self(500);
    pub const BAD_GATEWAY: Self = Self(502);
    pub const SERVICE_UNAVAILABLE: Self = Self(503);
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Path<T>(pub T);

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Query<T>(pub T);

#[derive(Clone, Debug, PartialEq)]
pub struct Json<T>(pub T);

#[derive(Clone, Debug, Default, PartialEq)]
pub enum Value {
    #[default]
    Null,
    Bool(bool),
    Int(i64),
    Float(f64),
    Str(String),
    Array(Vec<Self>),
    Object(BTreeMap<String, Self>),
}

#[must_use]
pub fn json_kv(pairs: &[(&str, &str)]) -> Value {
    let mut map = BTreeMap::new();
    for &(k, v) in pairs {
        map.insert(k.to_string(), Value::Str(v.to_string()));
    }
    Value::Object(map)
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct MethodRouter {
    pub methods: Vec<&'static str>,
}

impl MethodRouter {
    #[must_use]
    pub fn with_method(mut self, method: &'static str) -> Self {
        if !self.methods.contains(&method) {
            self.methods.push(method);
        }
        self
    }
    #[must_use] pub fn get<F>(self, _f: F) -> Self { self.with_method("GET") }
    #[must_use] pub fn post<F>(self, _f: F) -> Self { self.with_method("POST") }
    #[must_use] pub fn put<F>(self, _f: F) -> Self { self.with_method("PUT") }
    #[must_use] pub fn delete<F>(self, _f: F) -> Self { self.with_method("DELETE") }
    #[must_use] pub fn patch<F>(self, _f: F) -> Self { self.with_method("PATCH") }
    #[must_use] pub fn head<F>(self, _f: F) -> Self { self.with_method("HEAD") }
    #[must_use] pub fn options<F>(self, _f: F) -> Self { self.with_method("OPTIONS") }
}

pub mod routing {
    use super::MethodRouter;
    #[must_use] pub fn get<F>(f: F) -> MethodRouter { MethodRouter::default().get(f) }
    #[must_use] pub fn post<F>(f: F) -> MethodRouter { MethodRouter::default().post(f) }
    #[must_use] pub fn put<F>(f: F) -> MethodRouter { MethodRouter::default().put(f) }
    #[must_use] pub fn delete<F>(f: F) -> MethodRouter { MethodRouter::default().delete(f) }
    #[must_use] pub fn patch<F>(f: F) -> MethodRouter { MethodRouter::default().patch(f) }
    #[must_use] pub fn head<F>(f: F) -> MethodRouter { MethodRouter::default().head(f) }
    #[must_use] pub fn options<F>(f: F) -> MethodRouter { MethodRouter::default().options(f) }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Router {
    pub routes: BTreeMap<String, Vec<&'static str>>,
}

impl Router {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    #[must_use]
    pub fn route(mut self, path: &str, mr: MethodRouter) -> Self {
        let entry = self.routes.entry(path.to_string()).or_default();
        for m in mr.methods {
            if !entry.contains(&m) {
                entry.push(m);
            }
        }
        self
    }

    #[must_use]
    pub fn merge(mut self, other: Self) -> Self {
        for (path, methods) in other.routes {
            let entry = self.routes.entry(path).or_default();
            for m in methods {
                if !entry.contains(&m) {
                    entry.push(m);
                }
            }
        }
        self
    }

    #[must_use]
    pub fn nest(mut self, prefix: &str, sub: Self) -> Self {
        let clean_pfx = prefix.trim_end_matches('/');
        for (sub_p, methods) in sub.routes {
            let full = if sub_p == "/" {
                clean_pfx.to_string()
            } else {
                format!("{clean_pfx}/{}", sub_p.trim_start_matches('/'))
            };
            let entry = self.routes.entry(full).or_default();
            for m in methods {
                if !entry.contains(&m) {
                    entry.push(m);
                }
            }
        }
        self
    }

    #[must_use]
    pub fn total_method_bindings(&self) -> usize {
        self.routes.values().map(Vec::len).sum()
    }

    #[must_use]
    pub fn matches_route(&self, method: &str, req_path: &str) -> bool {
        let method_up = method.to_ascii_uppercase();
        if let Some(methods) = self.routes.get(req_path) {
            if methods.iter().any(|m| m.eq_ignore_ascii_case(&method_up)) {
                return true;
            }
        }
        for (pattern, methods) in &self.routes {
            if methods.iter().any(|m| m.eq_ignore_ascii_case(&method_up))
                && route_pattern_matches(pattern, req_path)
            {
                return true;
            }
        }
        false
    }
}

fn route_pattern_matches(pattern: &str, req_path: &str) -> bool {
    let p_segs: Vec<&str> = pattern.trim_matches('/').split('/').filter(|s| !s.is_empty()).collect();
    let r_segs: Vec<&str> = req_path.trim_matches('/').split('/').filter(|s| !s.is_empty()).collect();
    for (idx, p_seg) in p_segs.iter().enumerate() {
        if p_seg.starts_with('{') && p_seg.ends_with('}') {
            if p_seg.contains(":path") {
                return r_segs.len() >= idx;
            }
            if idx >= r_segs.len() {
                return false;
            }
            continue;
        }
        if r_segs.get(idx) != Some(p_seg) {
            return false;
        }
    }
    p_segs.len() == r_segs.len()
}
