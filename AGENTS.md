# AGENTS.md

## Product

`agent-monitor` is a local, read-only web dashboard for observing Codex CLI and Hermes Agent threads running on this Linux host.

## Non-negotiable rules

- Monitoring only: never signal, stop, resume, mutate, or write into Codex/Hermes processes, `~/.codex`, or `~/.hermes`.
- Treat `/proc` open rollout file descriptors as the source of truth for actually running Codex sessions. SQLite `inProgress` rows can be stale.
- Treat unexpired Hermes `session_turn_leases` owned by a live Hermes PID as the source of truth for actually running Hermes turns. `sessions.ended_at IS NULL` can be stale.
- Open Codex and Hermes SQLite databases read-only.
- Do not expose developer/system messages, reasoning, full prompts, raw command output, secrets, environment variables, or full command lines through the API.
- Use Python standard library only for the backend unless a dependency is clearly necessary.
- Keep the UI responsive, accessible, and useful at a glance. Every control must be wired.
- Tests must not depend on the user's live Codex or Hermes data; use temporary fixtures and injectable roots/paths.
