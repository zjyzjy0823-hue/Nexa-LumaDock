use std::time::Duration;

// A frozen Python backend may spend tens of seconds extracting and importing
// dependencies on a cold filesystem, before it can serve the health endpoint.
pub const STARTUP_TIMEOUT: Duration = Duration::from_secs(90);

#[derive(Debug, PartialEq, Eq)]
pub enum StartupOutcome {
    Waiting,
    Ready,
    Cancelled,
    TimedOut,
}

pub fn startup_outcome(elapsed: Duration, healthy: bool, starting: bool) -> StartupOutcome {
    if !starting {
        StartupOutcome::Cancelled
    } else if elapsed >= STARTUP_TIMEOUT {
        StartupOutcome::TimedOut
    } else if healthy {
        StartupOutcome::Ready
    } else {
        StartupOutcome::Waiting
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cold_start_can_become_ready_after_the_previous_25_second_limit() {
        assert_eq!(startup_outcome(Duration::from_secs(30), false, true), StartupOutcome::Waiting);
        assert_eq!(startup_outcome(Duration::from_secs(35), true, true), StartupOutcome::Ready);
    }

    #[test]
    fn startup_still_has_a_bounded_deadline() {
        assert_eq!(startup_outcome(Duration::from_secs(89), false, true), StartupOutcome::Waiting);
        assert_eq!(startup_outcome(Duration::from_secs(90), false, true), StartupOutcome::TimedOut);
        assert_eq!(startup_outcome(Duration::from_secs(91), true, true), StartupOutcome::TimedOut);
    }

    #[test]
    fn an_exit_cancels_startup_even_if_the_last_probe_was_healthy() {
        assert_eq!(startup_outcome(Duration::from_secs(2), true, false), StartupOutcome::Cancelled);
    }
}
