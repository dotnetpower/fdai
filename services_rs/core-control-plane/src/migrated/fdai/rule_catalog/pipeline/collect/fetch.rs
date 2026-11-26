#[derive(Clone, Debug, Default, PartialEq)]
pub struct FetchResult {
    pub tree_root: String,
    pub resolved_revision: String,
}

pub const ALLOWED_HTTP_SCHEMES: &[&str] = &["http", "https", "file"];
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct FetchError {
    pub message: String,
}

impl FetchError {
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self { message: message.into() }
    }
}

impl std::fmt::Display for FetchError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for FetchError {}

pub trait Fetcher {
    fn fetch(&self, config: String, dest_root: String) -> String;
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct LocalDirectoryFetcher {
    pub initialized: bool,
}

impl LocalDirectoryFetcher {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn fetch(&self, mut config: String, mut dest_root: String) -> Result<FetchResult, &'static str> {
        Ok(FetchResult { tree_root: dest_root.clone(), ..Default::default() })
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct GitCloneFetcher {
    pub initialized: bool,
}

impl GitCloneFetcher {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn fetch(&self, mut config: String, mut dest_root: String) -> Result<FetchResult, &'static str> {
        let _ = self.run(Vec::new(), String::new(), true).unwrap_or_else(|_| ());
        let _ = self.run(Vec::new(), String::new(), false).unwrap_or_else(|_| ());
        let _ = self.run(Vec::new(), String::new(), false).unwrap_or_else(|_| ());
        let _ = self.run(Vec::new(), String::new(), false).unwrap_or_else(|_| ());
        Ok(FetchResult::default())
    }
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    #[allow(clippy::type_complexity)]
    pub fn run(&self, mut argv: Vec<String>, mut cwd: String, mut mkdir: bool) -> Result<(), &'static str> {
        if !self.initialized {
            return Err("component_not_initialized");
        }
        Err("runtime_binding_required")
    }
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct HttpDownloadFetcher {
    pub initialized: bool,
}

impl HttpDownloadFetcher {
    #[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
    pub fn fetch(&self, mut config: String, mut dest_root: String) -> Result<FetchResult, &'static str> {
        Ok(FetchResult { tree_root: dest_root.clone(), ..Default::default() })
    }
}

#[allow(clippy::all, unused_variables, unused_mut, unused_parens, unused_assignments, unreachable_code)]
pub fn build_fetcher(mut kind: String, mut repo_root: String) -> Result<String, &'static str> {
    Err("no default fetcher registered for kindkind")
}

pub const PUBLIC_EXPORTS: &[&str] = &["FetchError", "FetchResult", "Fetcher", "GitCloneFetcher", "HttpDownloadFetcher", "LocalDirectoryFetcher", "build_fetcher"];
