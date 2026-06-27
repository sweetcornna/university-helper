//! Parses the sidecar readiness line emitted by the workstream-D launcher.
//!
//! Contract (locked across workstreams D + E): the `uh-backend` sidecar prints
//! exactly one line `UH_BACKEND_LISTENING <port>` to stdout once uvicorn is bound.

/// Extract the loopback port from a single stdout line.
///
/// Returns `Some(port)` only when the line's first whitespace-delimited token is
/// exactly `UH_BACKEND_LISTENING` and the second token parses as a `u16`.
/// Tolerant of leading/trailing whitespace and `\r\n`; rejects everything else.
pub fn parse_listening_port(line: &str) -> Option<u16> {
    let mut parts = line.split_whitespace();
    if parts.next()? != "UH_BACKEND_LISTENING" {
        return None;
    }
    parts.next()?.parse::<u16>().ok()
}

#[cfg(test)]
mod tests {
    use super::parse_listening_port;

    #[test]
    fn parses_valid_line() {
        assert_eq!(
            parse_listening_port("UH_BACKEND_LISTENING 51763"),
            Some(51763)
        );
    }

    #[test]
    fn tolerates_surrounding_whitespace_and_crlf() {
        assert_eq!(
            parse_listening_port("  UH_BACKEND_LISTENING 8000\r\n"),
            Some(8000)
        );
    }

    #[test]
    fn rejects_unrelated_line() {
        assert_eq!(parse_listening_port("INFO: uvicorn running"), None);
        assert_eq!(parse_listening_port("UH_BACKEND_LISTENING51763"), None);
    }

    #[test]
    fn rejects_missing_port() {
        assert_eq!(parse_listening_port("UH_BACKEND_LISTENING"), None);
    }

    #[test]
    fn rejects_non_numeric_port() {
        assert_eq!(parse_listening_port("UH_BACKEND_LISTENING notaport"), None);
    }

    #[test]
    fn rejects_out_of_range_port() {
        // 70000 > u16::MAX → parse fails (no truncation).
        assert_eq!(parse_listening_port("UH_BACKEND_LISTENING 70000"), None);
    }
}
