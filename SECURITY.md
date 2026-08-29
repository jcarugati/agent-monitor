# Security Policy

## Reporting a vulnerability

Please use the repository's private security-advisory reporting feature. Do not open a public issue for a suspected vulnerability and do not include real prompts, command output, credentials, database contents, hostnames, addresses, or local paths in a report.

Include a minimal reproduction built from synthetic fixtures, the affected revision, and the expected privacy or read-only boundary. Maintainers will acknowledge the report, assess impact, and coordinate a fix and disclosure through the private advisory.

## Supported versions

Security fixes target the latest revision on the default branch. Older snapshots are not maintained as separate release lines.

## Security boundaries

Agent Monitor is a read-only observability tool, not an authentication proxy. It binds to `127.0.0.1` by default. Operators who bind a non-loopback address are responsible for access control at the network layer.

The systemd service intentionally avoids mount-namespace isolation (`PrivateTmp`, `ProtectHome`, and `ProtectSystem`) because it must resolve peer-process procfs magic links to establish Codex liveness. Non-mount-namespace hardening remains enabled. This does not change the application security boundary: the API is GET-only, SQLite databases are opened with `mode=ro`, and Agent Monitor never writes provider data or controls provider processes.

The project's core security contract is documented in the README. Changes that add process control, mutation endpoints, writable database access, prompt exposure, raw output exposure, or implicit wildcard network binding are out of scope and should be rejected.
