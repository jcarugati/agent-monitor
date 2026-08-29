"""Native Codex process discovery using injectable procfs paths."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path


THREAD_ID_PATTERN = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
THREAD_ID_RE = re.compile(rf"({THREAD_ID_PATTERN})\.jsonl$")
LOCK_THREAD_ID_RE = re.compile(rf"^({THREAD_ID_PATTERN})\.lock$")


@dataclass(frozen=True, slots=True)
class ProcessSession:
    thread_id: str
    pid: int
    rollout_path: str
    cwd: str
    started_at: float | None


def _read_start_time(process_dir: Path, proc_root: Path, now: float, clock_ticks: int) -> float | None:
    try:
        uptime = float((proc_root / "uptime").read_text(encoding="ascii").split()[0])
        stat = (process_dir / "stat").read_text(encoding="ascii")
        tail = stat[stat.rfind(")") + 2 :].split()
        start_ticks = int(tail[19])
        return max(0.0, now - uptime + (start_ticks / clock_ticks))
    except (OSError, ValueError, IndexError, ZeroDivisionError):
        return None


def _rollouts_for(process_dir: Path, sessions_root: Path, locks_root: Path) -> list[tuple[str, str]]:
    try:
        safe_sessions_root = sessions_root.resolve()
    except OSError:
        safe_sessions_root = sessions_root.absolute()
    try:
        safe_locks_root = locks_root.resolve()
    except OSError:
        safe_locks_root = locks_root.absolute()
    try:
        descriptors = sorted(
            (process_dir / "fd").iterdir(),
            key=lambda item: int(item.name) if item.name.isdigit() else item.name,
        )
    except OSError:
        return []
    rollouts: list[tuple[str, str]] = []
    locked_threads: set[str] = set()
    for descriptor in descriptors:
        try:
            raw_target = os.readlink(descriptor)
            if raw_target.endswith(" (deleted)"):
                raw_target = raw_target[:-10]
            target = Path(raw_target)
            resolved = target.resolve(strict=False)
            if resolved.is_relative_to(safe_sessions_root):
                match = THREAD_ID_RE.search(resolved.name)
                if match:
                    rollouts.append((str(resolved), match.group(1).lower()))
            elif resolved.parent == safe_locks_root:
                match = LOCK_THREAD_ID_RE.fullmatch(resolved.name)
                if match:
                    locked_threads.add(match.group(1).lower())
        except (OSError, ValueError):
            continue
    return [(rollout, thread_id) for rollout, thread_id in rollouts if thread_id in locked_threads]


def discover_processes(
    proc_root: str | Path = "/proc",
    codex_home: str | Path = "~/.codex",
    *,
    now: float | None = None,
    clock_ticks: int | None = None,
) -> list[ProcessSession]:
    proc_path = Path(proc_root)
    home_path = Path(codex_home).expanduser()
    current_time = time.time() if now is None else now
    ticks = clock_ticks or int(os.sysconf("SC_CLK_TCK"))
    found: dict[str, ProcessSession] = {}
    try:
        entries = sorted((entry for entry in proc_path.iterdir() if entry.name.isdigit()), key=lambda item: int(item.name))
    except OSError:
        return []
    for process_dir in entries:
        try:
            executable = (process_dir / "exe").resolve(strict=True)
            if executable.name != "codex":
                continue
            mapped_rollouts = _rollouts_for(
                process_dir,
                home_path / "sessions",
                home_path / "thread-writer-locks",
            )
            if not mapped_rollouts:
                continue
            cwd = str((process_dir / "cwd").resolve(strict=True))
            pid = int(process_dir.name)
            started_at = _read_start_time(process_dir, proc_path, current_time, ticks)
            for rollout, thread_id in mapped_rollouts:
                session = ProcessSession(
                    thread_id=thread_id,
                    pid=pid,
                    rollout_path=rollout,
                    cwd=cwd,
                    started_at=started_at,
                )
                found.setdefault(thread_id, session)
        except (OSError, ValueError):
            continue
    return sorted(found.values(), key=lambda session: (session.pid, session.thread_id))
