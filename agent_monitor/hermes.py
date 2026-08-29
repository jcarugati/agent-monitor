"""Read-only Hermes turn discovery and privacy-safe projections."""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

from .sanitize import clean_text
from .storage import _timestamp


LOGGER = logging.getLogger(__name__)
MAX_RECENT = 8
_PID_RE = re.compile(r"(?:^|:)pid=(\d+)(?::|$)")
_TOOL_RE = re.compile(
    r"(?:executing tool|tool running|tool completed|sequential tool running(?: \(\d+s\))?):\s*([A-Za-z0-9_.-]+)",
    re.IGNORECASE,
)
_CONCURRENT_TOOLS_RE = re.compile(
    r"(?:executing \d+ tools concurrently|concurrent tools running \([^:]+\)):\s*([A-Za-z0-9_., -]+)",
    re.IGNORECASE,
)


def _profile_name(database_path: Path, hermes_home: Path) -> str:
    try:
        relative = database_path.relative_to(hermes_home)
    except ValueError:
        return "default"
    if len(relative.parts) >= 3 and relative.parts[0] == "profiles":
        return clean_text(relative.parts[1], 48) or "profile"
    return "default"


def _safe_id(profile: str, session_id: Any) -> str:
    identifier = clean_text(session_id, 96)
    return f"hermes:{profile}:{identifier}" if identifier else ""


def _pid_from_holder(holder: Any) -> int | None:
    if not isinstance(holder, str):
        return None
    match = _PID_RE.search(holder)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _is_live_hermes_process(proc_root: Path, pid: int) -> bool:
    try:
        command = (proc_root / str(pid) / "cmdline").read_bytes().replace(b"\0", b" ").lower()
    except OSError:
        return False
    if not command:
        return False
    return b"hermes_cli.main" in command or b"/hermes-agent/" in command or command.split(maxsplit=1)[0].endswith(b"/hermes")


def _project_activity(description: Any, at: float | None) -> list[dict[str, Any]]:
    text = clean_text(description, 240)
    if not text:
        return []
    match = _TOOL_RE.search(text)
    if match:
        label = clean_text(match.group(1), 48) or "tool"
        completed = text.lower().startswith("tool completed")
        item: dict[str, Any] = {
            "type": "command",
            "label": label,
            "status": "completed" if completed else "running",
        }
    else:
        concurrent = _CONCURRENT_TOOLS_RE.search(text)
        if concurrent:
            names = re.findall(r"[A-Za-z0-9_.-]+", concurrent.group(1))[:3]
            item = {
                "type": "command",
                "label": " + ".join(names) if names else "multiple tools",
                "status": "running",
            }
        elif "compression" in text.lower():
            item = {
                "type": "message",
                "text": "Context compression completed" if "completed" in text.lower() else "Compressing context",
            }
        elif "api" in text.lower() or "model response" in text.lower():
            item = {"type": "message", "text": "Waiting for model response"}
        else:
            item = {"type": "message", "text": "Hermes agent is working"}
    if at is not None:
        item["at"] = at
    return [item]


def _activity_summary(activity: list[dict[str, Any]]) -> str:
    if not activity:
        return "Hermes agent is working"
    item = activity[-1]
    if item.get("type") == "command":
        verb = "Completed" if item.get("status") == "completed" else "Running"
        return f"{verb} {clean_text(item.get('label'), 64) or 'tool'}"
    return clean_text(item.get("text"), 120) or "Hermes agent is working"


class HermesRepository:
    """Project live Hermes turn leases from one Hermes home without mutations."""

    def __init__(
        self,
        hermes_home: str | Path,
        *,
        proc_root: str | Path = "/proc",
        timeout: float = 0.2,
    ) -> None:
        self.hermes_home = Path(hermes_home).expanduser()
        self.proc_root = Path(proc_root)
        self.timeout = timeout

    def _database_paths(self) -> list[Path]:
        paths = [self.hermes_home / "state.db"]
        profiles = self.hermes_home / "profiles"
        try:
            paths.extend(sorted(profiles.glob("*/state.db")))
        except OSError:
            pass
        return paths

    def _connect(self, path: Path) -> sqlite3.Connection:
        resolved = path.resolve()
        connection = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True, timeout=self.timeout)
        connection.row_factory = sqlite3.Row
        return connection

    def live_threads(self, *, now: float) -> list[dict[str, Any]]:
        threads: list[dict[str, Any]] = []
        for database_path in self._database_paths():
            profile = _profile_name(database_path, self.hermes_home)
            try:
                with self._connect(database_path) as connection:
                    rows = connection.execute(
                        """SELECT l.conversation_id, l.holder, l.acquired_at,
                                  s.source, s.model, s.started_at, s.title, s.title_source,
                                  s.cwd, s.git_branch, s.git_repo_root,
                                  s.last_activity_at, s.last_activity_description
                           FROM session_turn_leases AS l
                           JOIN sessions AS s ON s.id = l.conversation_id
                           WHERE l.expires_at > ?
                           ORDER BY l.acquired_at ASC
                           LIMIT 128""",
                        (float(now),),
                    ).fetchall()
            except (sqlite3.Error, OSError) as exc:
                LOGGER.debug("Hermes live state unavailable for %s: %s", profile, type(exc).__name__)
                continue
            for row in rows:
                pid = _pid_from_holder(row["holder"])
                if pid is None or not _is_live_hermes_process(self.proc_root, pid):
                    continue
                thread_id = _safe_id(profile, row["conversation_id"])
                if not thread_id:
                    continue
                cwd = clean_text(row["cwd"] or row["git_repo_root"], 320)
                repo_root = clean_text(row["git_repo_root"], 320)
                project_path = repo_root or cwd
                started_at = _timestamp(row["acquired_at"])
                updated_at = _timestamp(row["last_activity_at"]) or started_at
                activity = _project_activity(row["last_activity_description"], updated_at)
                title = "Hermes agent turn"
                if clean_text(row["title_source"], 24).lower() == "llm":
                    title = clean_text(row["title"], 120) or title
                threads.append(
                    {
                        "id": thread_id,
                        "provider": "hermes",
                        "profile": profile,
                        "pid": pid,
                        "project_name": Path(project_path).name or "Hermes agent",
                        "cwd": cwd,
                        "branch": clean_text(row["git_branch"], 80) or "No branch",
                        "model": clean_text(row["model"], 48) or "Unknown model",
                        "reasoning_effort": "Agent turn",
                        "started_at": started_at,
                        "updated_at": updated_at,
                        "title": title,
                        "latest_summary": _activity_summary(activity),
                        "activity": activity,
                    }
                )
        unique = {item["id"]: item for item in threads}
        return sorted(unique.values(), key=lambda item: (item.get("started_at") or 0, item["id"]))

    def recent_threads(self, active_ids: set[str], limit: int = MAX_RECENT) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), MAX_RECENT))
        recent: list[dict[str, Any]] = []
        for database_path in self._database_paths():
            profile = _profile_name(database_path, self.hermes_home)
            try:
                with self._connect(database_path) as connection:
                    rows = connection.execute(
                        """SELECT id, model, started_at, ended_at, cwd, git_branch,
                                  git_repo_root, last_activity_at
                           FROM sessions
                           WHERE parent_session_id IS NULL
                             AND ended_at IS NOT NULL
                             AND COALESCE(archived, 0) = 0
                             AND COALESCE(hidden, 0) = 0
                           ORDER BY COALESCE(last_activity_at, ended_at, started_at) DESC
                           LIMIT ?""",
                        (safe_limit,),
                    ).fetchall()
            except (sqlite3.Error, OSError) as exc:
                LOGGER.debug("Recent Hermes state unavailable for %s: %s", profile, type(exc).__name__)
                continue
            for row in rows:
                thread_id = _safe_id(profile, row["id"])
                if not thread_id or thread_id in active_ids:
                    continue
                cwd = clean_text(row["cwd"] or row["git_repo_root"], 320)
                project_path = clean_text(row["git_repo_root"], 320) or cwd
                recent.append(
                    {
                        "id": thread_id,
                        "provider": "hermes",
                        "profile": profile,
                        "project_name": Path(project_path).name or "Hermes agent",
                        "cwd": cwd,
                        "title": "Recent Hermes session",
                        "branch": clean_text(row["git_branch"], 80) or "No branch",
                        "model": clean_text(row["model"], 48) or "Unknown model",
                        "reasoning_effort": "Agent session",
                        "updated_at": _timestamp(row["last_activity_at"]) or _timestamp(row["ended_at"]),
                        "created_at": _timestamp(row["started_at"]),
                    }
                )
        recent.sort(key=lambda item: item.get("updated_at") or 0, reverse=True)
        return recent[:safe_limit]
