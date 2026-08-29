#!/usr/bin/env bash
set -euo pipefail

PROGRAM_NAME=${0##*/}
BIND_HOST=127.0.0.1
PORT=8777
USE_TAILSCALE=false
HOST_WAS_SET=false
DRY_RUN=false

usage() {
  printf '%s\n' \
    "Usage: $PROGRAM_NAME [OPTIONS]" \
    "" \
    "Install Agent Monitor as a systemd user service." \
    "" \
    "Options:" \
    "  --host ADDRESS  Bind to ADDRESS (default: 127.0.0.1)" \
    "  --port PORT     Listen on PORT, 1-65535 (default: 8777)" \
    "  --tailscale     Bind only to the IPv4 reported by 'tailscale ip -4'" \
    "  --dry-run       Print the generated unit without writing or enabling it" \
    "  --help          Show this help"
}

fail() {
  printf 'Error: %s\n' "$1" >&2
  exit 1
}

require_value() {
  local option=$1
  local count=$2
  (( count >= 2 )) || fail "$option requires a value"
}

while (( $# > 0 )); do
  case "$1" in
    --host)
      require_value "$1" "$#"
      BIND_HOST=$2
      HOST_WAS_SET=true
      shift 2
      ;;
    --port)
      require_value "$1" "$#"
      PORT=$2
      shift 2
      ;;
    --tailscale)
      USE_TAILSCALE=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    --)
      shift
      (( $# == 0 )) || fail "unexpected positional arguments"
      ;;
    *)
      fail "unknown option: $1"
      ;;
  esac
done

[[ "$PORT" =~ ^[0-9]+$ ]] || fail "port must be a number from 1 to 65535"
PORT=$((10#$PORT))
(( PORT >= 1 && PORT <= 65535 )) || fail "port must be a number from 1 to 65535"

if [[ "$USE_TAILSCALE" == true && "$HOST_WAS_SET" == true ]]; then
  fail "--host and --tailscale cannot be used together"
fi

valid_ipv4() {
  local address=$1
  local first second third fourth extra
  IFS=. read -r first second third fourth extra <<< "$address"
  [[ -z ${extra:-} && -n ${first:-} && -n ${second:-} && -n ${third:-} && -n ${fourth:-} ]] || return 1
  local part
  for part in "$first" "$second" "$third" "$fourth"; do
    [[ "$part" =~ ^[0-9]{1,3}$ ]] || return 1
    (( 10#$part <= 255 )) || return 1
  done
}

if [[ "$USE_TAILSCALE" == true ]]; then
  command -v tailscale >/dev/null 2>&1 || fail "Tailscale CLI is unavailable; install and connect Tailscale first"
  tailscale_output=$(tailscale ip -4 2>/dev/null) || fail "Tailscale could not report an IPv4 address; confirm it is connected"
  IFS=$'\n' read -r BIND_HOST _ <<< "$tailscale_output"
  valid_ipv4 "$BIND_HOST" || fail "Tailscale did not return a valid IPv4 address"
fi

[[ -n "$BIND_HOST" ]] || fail "host must not be empty"
[[ "$BIND_HOST" != *[$'\n\r\t ']* ]] || fail "host must not contain whitespace"

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
[[ -f "$SCRIPT_DIR/server.py" ]] || fail "server.py was not found beside the installer"
[[ "$SCRIPT_DIR" != *[[:cntrl:]]* ]] || fail "the checkout path must not contain control characters"

systemd_escape() {
  local value=$1
  value=${value//%/%%}
  value=${value//\\/\\\\}
  value=${value//\"/\\\"}
  value=${value// /\\x20}
  printf '%s' "$value"
}

escaped_root=$(systemd_escape "$SCRIPT_DIR")
escaped_host=$(systemd_escape "$BIND_HOST")
unit_content="[Unit]
Description=Agent Monitor read-only local dashboard

[Service]
Type=simple
WorkingDirectory=$escaped_root
ExecStart=/usr/bin/python3 \"$escaped_root/server.py\" --host \"$escaped_host\" --port \"$PORT\" --codex-home \"%h/.codex\" --hermes-home \"%h/.hermes\" --proc-root /proc
Environment=PYTHONDONTWRITEBYTECODE=1
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
UMask=0077

[Install]
WantedBy=default.target
"

unit_dir=$HOME/.config/systemd/user
unit_path=$unit_dir/agent-monitor.service

if [[ "$DRY_RUN" == true ]]; then
  printf 'Dry run: would write %s and enable it with systemd.\n\n%s' "$unit_path" "$unit_content"
  exit 0
fi

command -v systemctl >/dev/null 2>&1 || fail "systemctl is unavailable; a systemd user service cannot be installed"
mkdir -p -- "$unit_dir"
temp_unit=$(mktemp "$unit_dir/.agent-monitor.service.XXXXXX")
trap 'rm -f -- "$temp_unit"' EXIT
printf '%s' "$unit_content" > "$temp_unit"
chmod 0600 "$temp_unit"
if [[ ! -f "$unit_path" ]] || ! cmp -s -- "$temp_unit" "$unit_path"; then
  mv -f -- "$temp_unit" "$unit_path"
  temp_unit=$unit_path
else
  rm -f -- "$temp_unit"
  temp_unit=$unit_path
fi
trap - EXIT

systemctl --user daemon-reload
systemctl --user enable --now agent-monitor.service
printf 'Installed Agent Monitor at http://%s:%s\n' "$BIND_HOST" "$PORT"
