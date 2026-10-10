# Security policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately through GitHub's
**Security → Report a vulnerability** on this repository rather than in a public issue.
Include steps to reproduce and the affected commit. You should get an acknowledgement within a week.

## Scope and design notes

- The dashboard is designed for a single owner and a handful of named users on a private network.
  Put a TLS terminator in front of it before exposing it beyond loopback, and set
  `INVDASH_AUTH_COOKIE_SECURE=1`.
- Personal financial data lives only in the separate data service (`investing-dashboard-db`). It is
  reached with a bearer token over loopback or a private network, and never from the browser. This
  repository and its history contain no personal data. The demo portfolio is invented.
- `INVDASH_AUTH_ENABLED=0` removes the login gate entirely and is meant only for loopback-bound
  development. The server logs a warning at startup when it is off.
- Secrets (`.env`, tokens, API keys) are never committed. `detect-secrets` and a PII scanner run as
  pre-commit hooks and in CI.
