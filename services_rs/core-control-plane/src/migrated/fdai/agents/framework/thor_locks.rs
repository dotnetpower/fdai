#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ReentrantAsyncLock {
    pub initialized: bool,
}

pub const PUBLIC_EXPORTS: &[&str] = &["_ReentrantAsyncLock"];
