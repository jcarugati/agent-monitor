"""Read-only access to bounded Codex SQLite projections."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .sanitize import clean_text, command_activity, file_activity


LOGGER = logging.getLogger(__name__)
MAX_ACTIVITY = 12
MAX_RECENT = 8


def _timestamp(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    if numeric > 10_000_000_000:
        numeric /= 1000.0
    return numeric if numeric >= 0 else None


class CodexRepository:
    def __init__(self, codex_home: str | Path, timeout: float = 0.2) -> None:
        self.codex_home = Path(codex_home).expanduser()
        self.timeout = timeout

    def _connect(self, filename: str) -> sqlite3.Connection:
        path = (self.codex_home / filename).resolve()
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=self.timeout)
        connection.row_factory = sqlite3.Row
        return connection

    def metadata_for(self, thread_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
        ids = tuple(dict.fromkeys(clean_text(item, 64) for item in thread_ids if clean_text(item, 64)))[:128]
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        try:
            with self._connect("state_5.sqlite") as connection:
                rows = connection.execute(
                    f"""SELECT id, created_at, updated_at, cwd, model,
                               reasoning_effort, git_branch
                        FROM threads WHERE id IN ({placeholders})""",
                    ids,
                ).fetchall()
        except (sqlite3.Error, OSError) as exc:
            LOGGER.warning("Codex metadata unavailable: %s", type(exc).__name__)
            return {}
        return {row["id"]: self._project_metadata(row) for row in rows}

    def _project_metadata(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": clean_text(row["id"], 64),
            "created_at": _timestamp(row["created_at"]),
            "updated_at": _timestamp(row["updated_at"]),
            "cwd": clean_text(row["cwd"], 320),
            "branch": clean_text(row["git_branch"], 80),
            "model": clean_text(row["model"], 48),
            "reasoning_effort": clean_text(row["reasoning_effort"], 24),
        }

    def activity_for(self, thread_id: str, limit: int = 8) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), MAX_ACTIVITY))
        try:
            with self._connect("thread_history_1.sqlite") as connection:
                rows = connection.execute(
                    """SELECT item_type, item_json, created_at_ms
                       FROM thread_items WHERE thread_id = ?
                       ORDER BY rollout_ordinal DESC LIMIT ?""",
                    (clean_text(thread_id, 64), safe_limit * 3),
                ).fetchall()
        except (sqlite3.Error, OSError) as exc:
            LOGGER.warning("Codex activity unavailable: %s", type(exc).__name__)
            return []
        projected: list[dict[str, Any]] = []
        for row in reversed(rows):
            item = self._project_activity(row)
            if item is not None:
                projected.append(item)
        return projected[-safe_limit:]

    def _project_activity(self, row: sqlite3.Row) -> dict[str, Any] | None:
        try:
            payload = json.loads(row["item_json"])
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        item_type = row["item_type"]
        item: dict[str, Any] | None = None
        if item_type == "agentMessage" and payload.get("phase") == "commentary":
            text = clean_text(payload.get("text"), 240)
            if text:
                item = {"type": "message", "text": text}
        elif item_type == "commandExecution":
            item = command_activity(payload)
        elif item_type == "fileChange":
            item = file_activity(payload)
        if item is not None:
            item["at"] = _timestamp(row["created_at_ms"])
        return item

    def recent_threads(self, active_ids: set[str], limit: int = MAX_RECENT) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), MAX_RECENT))
        try:
            with self._connect("state_5.sqlite") as connection:
                rows = connection.execute(
                    """SELECT id, created_at, updated_at, cwd, model,
                              reasoning_effort, git_branch
                       FROM threads WHERE COALESCE(archived, 0) = 0
                       ORDER BY updated_at DESC LIMIT ?""",
                    (safe_limit + min(len(active_ids), 128),),
                ).fetchall()
        except (sqlite3.Error, OSError) as exc:
            LOGGER.warning("Recent Codex sessions unavailable: %s", type(exc).__name__)
            return []
        recent: list[dict[str, Any]] = []
        for row in rows:
            if row["id"] in active_ids:
                continue
            item = self._project_metadata(row)
            cwd = item.pop("cwd", "")
            item["project_name"] = Path(cwd).name or "Unknown project"
            item["title"] = "Recent Codex session"
            recent.append(item)
            if len(recent) >= safe_limit:
                break
        return recent
