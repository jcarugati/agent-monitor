"""Privacy boundary helpers for API-safe projected values."""

from __future__ import annotations

import os
import re
import shlex
import unicodedata
from typing import Any


MAX_ACTIVITY_FILES = 5
SAFE_STATUSES = {"running", "completed", "failed", "cancelled", "pending"}


def clean_text(value: Any, limit: int = 160) -> str:
    """Return single-line printable text capped to ``limit`` characters."""
    if not isinstance(value, str) or limit <= 0:
        return ""
    printable = "".join(
        " " if char.isspace() else char
        for char in value
        if char.isspace() or not unicodedata.category(char).startswith("C")
    )
    collapsed = re.sub(r"\s+", " ", printable).strip()
    if len(collapsed) <= limit:
        return collapsed
    if limit == 1:
        return "…"
    return collapsed[: limit - 1].rstrip() + "…"


def title_from(title: Any, preview: Any, limit: int = 120) -> str:
    for candidate in (title, preview):
        if not isinstance(candidate, str):
            continue
        for line in candidate.splitlines():
            safe = clean_text(line, limit)
            if safe:
                return safe
    return "Untitled session"


def _status(value: Any) -> str:
    status = clean_text(value, 16).lower()
    return status if status in SAFE_STATUSES else "unknown"


def _unwrap_shell(command: str) -> str:
    current = command.strip()
    for _ in range(2):
        try:
            parts = shlex.split(current)
        except ValueError:
            return current
        if len(parts) >= 3 and os.path.basename(parts[0]) in {"bash", "sh", "zsh"} and parts[1] in {"-c", "-lc"}:
            current = parts[2]
            continue
        break
    return current


def _skip_environment_prefix(parts: list[str]) -> list[str]:
    """Discard environment-launch syntax without projecting names or values."""
    index = 0
    while index < len(parts) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", parts[index], re.DOTALL):
        index += 1
    if index >= len(parts) or os.path.basename(parts[index]) != "env":
        return parts[index:]
    index += 1
    options_with_values = {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}
    while index < len(parts):
        part = parts[index]
        if part == "--":
            index += 1
            break
        if part in options_with_values:
            index += 2
            continue
        if part.startswith("-"):
            index += 1
            continue
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", part, re.DOTALL):
            index += 1
            continue
        break
    return parts[index:]


def command_label(value: Any) -> str:
    """Derive a non-sensitive category label, never a full command line."""
    command = clean_text(value, 2_000)
    if not command:
        return "command"
    unwrapped = _unwrap_shell(command)
    try:
        parts = shlex.split(unwrapped)
    except ValueError:
        parts = unwrapped.split()
    parts = _skip_environment_prefix(parts)
    if not parts:
        return "command"
    executable = clean_text(os.path.basename(parts[0]), 48) or "command"
    executable_lower = executable.lower()
    arguments = [part.lower() for part in parts[1:]]
    if executable_lower in {"python", "python3"} and arguments[:2] == ["-m", "unittest"]:
        return f"{executable_lower} -m unittest"
    if executable_lower == "pytest" or (
        executable_lower in {"python", "python3"} and arguments[:2] == ["-m", "pytest"]
    ):
        return "pytest"
    if executable_lower == "npm" and arguments[:1] == ["test"]:
        return "npm test"
    if executable_lower == "npm" and arguments[:2] == ["run", "test"]:
        return "npm run test"
    if executable_lower in {"pnpm", "yarn", "cargo", "go"} and arguments[:1] == ["test"]:
        return f"{executable_lower} test"
    if executable == "git" and len(parts) > 1:
        subcommand = clean_text(parts[1], 24).lower()
        if subcommand in {"status", "diff", "log", "show", "add", "commit", "branch", "rev-parse", "check-ignore", "worktree"}:
            return f"git {subcommand}"
    if executable in {"node", "python", "python3"} and len(parts) > 1 and not parts[1].startswith("-"):
        script = clean_text(os.path.basename(parts[1]), 40)
        return f"{executable} {script}" if script else executable
    return executable


def command_activity(item: dict[str, Any]) -> dict[str, Any]:
    status = _status(item.get("status"))
    activity: dict[str, Any] = {
        "type": "command",
        "label": command_label(item.get("command")),
        "status": status,
    }
    label = activity["label"]
    if any(token in label for token in ("test", "unittest", "pytest")):
        output = clean_text(item.get("aggregatedOutput"), 2_000).lower()
        failure_output = re.sub(r"\b0\s+(?:failed|failures|errors)\b|\b(?:failures|errors)\s*=\s*0\b", "", output)
        if status in {"failed", "cancelled"} or re.search(r"\b(failed|failure|failures|error|errors)\b", failure_output):
            activity["result"] = "failed"
        elif status == "completed" and re.search(r"\b(ok|passed|passing|success)\b", output):
            activity["result"] = "passed"
        elif status == "completed":
            activity["result"] = "completed"
    return activity


def file_activity(item: dict[str, Any]) -> dict[str, Any]:
    raw_changes = item.get("changes")
    changes = raw_changes if isinstance(raw_changes, list) else []
    files: list[str] = []
    for change in changes:
        if not isinstance(change, dict):
            continue
        path = change.get("path") or change.get("file")
        if isinstance(path, str):
            basename = clean_text(os.path.basename(path.rstrip("/")), 64)
            if basename and basename not in files:
                files.append(basename)
        if len(files) >= MAX_ACTIVITY_FILES:
            break
    return {
        "type": "file",
        "count": min(len(changes), 999),
        "files": files,
        "status": _status(item.get("status")),
    }
