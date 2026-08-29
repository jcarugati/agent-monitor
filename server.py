#!/usr/bin/env python3
"""Agent Monitor command-line server."""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from agent_monitor.hermes import HermesRepository
from agent_monitor.http import create_server
from agent_monitor.processes import discover_processes
from agent_monitor.snapshot import build_snapshot
from agent_monitor.storage import CodexRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only local dashboard for live Codex and Hermes threads")
    parser.add_argument("--host", default="127.0.0.1", help="listen address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8777, help="listen port (default: 8777)")
    parser.add_argument("--codex-home", type=Path, default=Path("~/.codex"), help="Codex data directory")
    parser.add_argument("--hermes-home", type=Path, default=Path("~/.hermes"), help="Hermes data directory")
    parser.add_argument("--proc-root", type=Path, default=Path("/proc"), help="procfs root")
    return parser.parse_args()


def make_snapshot_provider(codex_home: Path, hermes_home: Path, proc_root: Path):
    codex_path = codex_home.expanduser()
    repository = CodexRepository(codex_path)
    hermes_repository = HermesRepository(hermes_home.expanduser(), proc_root=proc_root)

    def provide() -> dict:
        now = time.time()
        processes = discover_processes(proc_root, codex_path, now=now)
        return build_snapshot(
            processes,
            repository,
            now=now,
            user_home=Path.home(),
            hermes_repository=hermes_repository,
        )

    return provide


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    static_root = Path(__file__).resolve().parent / "frontend"
    server = create_server(
        args.host,
        args.port,
        static_root,
        make_snapshot_provider(args.codex_home, args.hermes_home, args.proc_root),
    )
    display_host = "localhost" if args.host in {"127.0.0.1", "::1"} else args.host
    print(f"Agent Monitor listening at http://{display_host}:{server.server_address[1]}", flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
