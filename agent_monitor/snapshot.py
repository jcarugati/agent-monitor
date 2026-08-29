"""Snapshot assembly from procfs truth and safe database projections."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol

from .processes import ProcessSession
from .sanitize import clean_text
from .storage import CodexRepository


class HermesRepositoryLike(Protocol):
    def live_threads(self, *, now: float) -> list[dict[str, Any]]: ...

    def recent_threads(self, active_ids: set[str], limit: int = 8) -> list[dict[str, Any]]: ...


def _iso(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except (ValueError, OSError, OverflowError):
        return None


def abbreviate_path(path: str, user_home: Path) -> str:
    safe = clean_text(path, 320)
    home = str(user_home)
    if safe == home:
        return "~"
    if safe.startswith(home + "/"):
        return "~" + safe[len(home) :]
    return safe


def _summary(activity: list[dict[str, Any]]) -> str:
    for item in reversed(activity):
        if item.get("type") == "message":
            return clean_text(item.get("text"), 180)
    if activity:
        item = activity[-1]
        if item.get("type") == "command":
            return f"Ran {clean_text(item.get('label'), 80)}"
        if item.get("type") == "file":
            count = int(item.get("count") or 0)
            return f"Changed {count} file{'s' if count != 1 else ''}"
    return "Waiting for projected activity"


def _sort_timestamp(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def _prepare_recent(item: dict[str, Any], user_home: Path) -> dict[str, Any]:
    projected = dict(item)
    projected["provider"] = clean_text(projected.get("provider"), 16) or "codex"
    if projected["provider"] == "codex":
        projected["title"] = "Recent Codex session"
    projected["cwd"] = abbreviate_path(projected.get("cwd", ""), user_home) if projected.get("cwd") else ""
    if not isinstance(projected.get("updated_at"), str):
        projected["updated_at"] = _iso(projected.get("updated_at"))
    if not isinstance(projected.get("created_at"), str):
        projected["created_at"] = _iso(projected.get("created_at"))
    return projected


def _prepare_hermes_running(item: dict[str, Any], *, now: float, user_home: Path) -> dict[str, Any]:
    projected = dict(item)
    started = projected.get("started_at")
    updated = projected.get("updated_at")
    projected["provider"] = "hermes"
    projected["cwd"] = abbreviate_path(projected.get("cwd", ""), user_home)
    projected["started_at"] = _iso(started)
    projected["updated_at"] = _iso(updated)
    projected["elapsed_seconds"] = max(0, int(now - started)) if isinstance(started, (int, float)) else None
    projected["last_activity_age_seconds"] = max(0, int(now - updated)) if isinstance(updated, (int, float)) else None
    return projected


def build_snapshot(
    processes: Iterable[ProcessSession],
    repository: CodexRepository,
    *,
    now: float,
    user_home: Path,
    hermes_repository: HermesRepositoryLike | None = None,
) -> dict[str, Any]:
    process_list = list(processes)[:128]
    active_ids = {process.thread_id for process in process_list}
    metadata = repository.metadata_for(active_ids)
    running: list[dict[str, Any]] = []
    for process in process_list:
        details = metadata.get(process.thread_id, {})
        activity = repository.activity_for(process.thread_id, limit=8)
        update_time = details.get("updated_at")
        if activity and activity[-1].get("at") is not None:
            update_time = max(update_time or 0, activity[-1]["at"])
        started = process.started_at if process.started_at is not None else details.get("created_at")
        cwd = abbreviate_path(process.cwd, user_home)
        summary = _summary(activity)
        running.append(
            {
                "id": process.thread_id,
                "provider": "codex",
                "pid": process.pid,
                "project_name": Path(process.cwd).name or "Unknown project",
                "cwd": cwd,
                "branch": details.get("branch") or "No branch",
                "model": details.get("model") or "Unknown model",
                "reasoning_effort": details.get("reasoning_effort") or "Default effort",
                "started_at": _iso(started),
                "updated_at": _iso(update_time),
                "elapsed_seconds": max(0, int(now - started)) if started is not None else None,
                "last_activity_age_seconds": max(0, int(now - update_time)) if update_time is not None else None,
                "title": summary,
                "latest_summary": summary,
                "activity": activity,
            }
        )
    codex_recent = repository.recent_threads(active_ids, limit=8)
    for item in codex_recent:
        item["provider"] = "codex"

    hermes_running: list[dict[str, Any]] = []
    hermes_recent: list[dict[str, Any]] = []
    if hermes_repository is not None:
        hermes_running = [
            _prepare_hermes_running(item, now=now, user_home=user_home)
            for item in hermes_repository.live_threads(now=now)[:128]
        ]
        running.extend(hermes_running)
        hermes_active_ids = {item["id"] for item in hermes_running}
        hermes_recent = hermes_repository.recent_threads(hermes_active_ids, limit=8)

    running.sort(key=lambda item: (item["elapsed_seconds"] is None, -(item["elapsed_seconds"] or 0)))
    all_recent = codex_recent + hermes_recent
    all_recent.sort(key=lambda item: _sort_timestamp(item.get("updated_at")), reverse=True)
    recent = [_prepare_recent(item, user_home) for item in all_recent[:8]]
    codex_recent_count = sum(1 for item in recent if item.get("provider") == "codex")
    hermes_recent_count = sum(1 for item in recent if item.get("provider") == "hermes")
    return {
        "generated_at": _iso(now),
        "running_count": len(running),
        "running_threads": running,
        "recent_count": len(recent),
        "recent_completions": recent,
        "provider_counts": {
            "codex": {"running": len(process_list), "recent": codex_recent_count},
            "hermes": {"running": len(hermes_running), "recent": hermes_recent_count},
        },
    }
