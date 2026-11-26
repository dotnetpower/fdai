use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

pub struct SseLeaseDropGuard { active_leases: Arc<AtomicUsize> }
impl SseLeaseDropGuard {
    #[must_use]
    pub fn acquire(active_leases: Arc<AtomicUsize>) -> Self {
        active_leases.fetch_add(1, Ordering::SeqCst);
        Self { active_leases }
    }
}
impl Drop for SseLeaseDropGuard {
    fn drop(&mut self) { self.active_leases.fetch_sub(1, Ordering::SeqCst); }
}
