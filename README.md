# Agent Monitor

Agent Monitor is a dependency-free, read-only web dashboard for live [Codex CLI](https://github.com/openai/codex) and Hermes Agent work on a Linux host. It uses `/proc` and provider leases for liveness, then adds a bounded, privacy-filtered projection of local session metadata.

The server is local by default, has no mutation endpoints, and never controls an agent process.

## Quick start

Requirements: Linux with `/proc`, Python 3.11 or newer, and at least one supported provider installed. No Python package or frontend dependency installation is needed.

```bash
git clone https://github.com/jcarugati/agent-monitor.git
cd agent-monitor
python3 server.py
```

Open <http://127.0.0.1:8777>.

## Direct run

The default command binds only to the loopback interface and reads the current user's standard provider directories:

```bash
python3 server.py
```

All server options are explicit and optional:

```bash
python3 server.py \
  --host 127.0.0.1 \
  --port 8777 \
  --codex-home "$HOME/.codex" \
  --hermes-home "$HOME/.hermes" \
  --proc-root /proc
```

The dashboard polls every 30 seconds while visible. The Refresh button requests a snapshot immediately, and the Auto switch can pause scheduled refreshes.

## Install as a user service

`install.sh` creates `~/.config/systemd/user/agent-monitor.service` using the checkout's absolute path, reloads the user manager, and enables the service immediately. It does not require or invoke `sudo`.

```bash
./install.sh
```

Useful options:

```bash
./install.sh --host 127.0.0.2 --port 9123
./install.sh --dry-run
./install.sh --help
```

The installer is idempotent. The distributable template at [`deploy/agent-monitor.service`](deploy/agent-monitor.service) uses generic `%h` placeholders for manual setups.

## Tailscale access

To make the dashboard reachable only on this machine's Tailscale IPv4 address:

```bash
./install.sh --tailscale
```

The installer runs `tailscale ip -4`, validates the result, and binds only that address. It fails if Tailscale is missing, disconnected, or returns no valid IPv4. It never selects `0.0.0.0`; a non-loopback `--host` must be an explicit operator choice.

Agent Monitor has no built-in authentication. Use Tailscale access controls so only intended tailnet members can reach the selected port, and do not expose the service through a public proxy or public firewall rule.

## Uninstall

These commands stop and remove only the Agent Monitor user unit. They do not remove the checkout or any Codex/Hermes data.

```bash
systemctl --user disable --now agent-monitor.service
rm "$HOME/.config/systemd/user/agent-monitor.service"
systemctl --user daemon-reload
```

## Provider requirements

Codex liveness requires all three signals to match:

1. A native process whose executable is named `codex`.
2. An open rollout file descriptor below `~/.codex/sessions`.
3. An open matching writer lock below `~/.codex/thread-writer-locks`.

The optional Codex SQLite files add display metadata only. Stale `inProgress` database rows never make a thread live.

Hermes liveness requires an unexpired `session_turn_leases` row and a live owner PID whose process identifies as Hermes. `sessions.ended_at IS NULL` never makes a turn live by itself. The default `~/.hermes/state.db` and profile databases below `~/.hermes/profiles/*/state.db` are discovered automatically.

If a provider is not installed or its schema is unavailable, its sections remain empty while the other provider can continue to work.

## Privacy guarantees

Agent Monitor applies these boundaries in the backend, before JSON reaches the browser:

- It opens every Codex and Hermes SQLite database through a URI with `mode=ro` and short timeouts.
- It reads process metadata and open file descriptors but never signals, stops, resumes, or writes to a process.
- It never writes to `~/.codex` or `~/.hermes` and exposes no mutation endpoint.
- It never returns user, system, or developer prompts; reasoning; raw tool or command output; full command lines; environment values; credentials; secrets; diffs; or internal query errors.
- It returns only bounded projections: provider, process/session identifiers, PID, project name, abbreviated working path, branch, model/mode, timestamps and elapsed time, generic recent-session labels, bounded agent commentary summaries, compact tool names/statuses, derived test outcomes, and file counts with at most five basenames.
- Codex database titles and previews are not returned. Recent Hermes titles are generic; a live Hermes turn can include its bounded LLM-generated title.
- At most 128 live items per provider, eight activity items per live thread, and eight combined recent sessions are returned.

Treat project names, branches, abbreviated paths, session IDs, PIDs, live Hermes titles, and agent commentary as private operational metadata. Anyone who can connect to the dashboard can see that projection.

## API endpoints

- `GET /api/health` returns `{"status":"ok"}`.
- `GET /api/snapshot` returns generation time, provider counts, privacy-filtered live threads, and up to eight recent inactive sessions.
- `GET /`, `/app.js`, and `/styles.css` serve the dashboard assets.
- Unknown API routes return `404`. Mutation methods such as `POST`, `PUT`, and `DELETE` return `405`.

API responses use `Cache-Control: no-store`. Static assets use short cache lifetimes, and all responses include restrictive content, framing, referrer, permissions, and CSP headers.

## Troubleshooting

- **No active Codex threads:** confirm the native `codex` process has both an open rollout and its matching writer lock. Launcher processes and stale SQLite rows are intentionally ignored.
- **No active Hermes turns:** confirm the turn lease is unexpired and its holder PID is still a Hermes process.
- **Recent sessions are empty:** provider databases may be missing, busy, incompatible, or unreadable. The server logs only error types, not database contents or paths.
- **The user service does not start:** run `systemctl --user status agent-monitor.service` and verify Python 3.11+ and the checkout still exist at the installed path.
- **Tailscale installation fails:** run `tailscale ip -4` and confirm the local Tailscale client is connected before retrying `./install.sh --tailscale`.
- **The page says stale or disconnected:** use Refresh, then verify `curl http://127.0.0.1:8777/api/health` from the same host.

## Development

Run all local gates from the repository root:

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile server.py agent_monitor/*.py tests/*.py
node --check frontend/app.js
bash -n install.sh
git diff --check
```

Tests use temporary `/proc` layouts, homes, and SQLite fixtures; they do not depend on live user data. See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and the [MIT license](LICENSE).
