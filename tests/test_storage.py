import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_monitor.storage import CodexRepository


RUNNING_ID = "123e4567-e89b-12d3-a456-426614174000"
RECENT_ID = "223e4567-e89b-12d3-a456-426614174001"


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        state = sqlite3.connect(self.home / "state_5.sqlite")
        state.execute("""CREATE TABLE threads (
            id TEXT PRIMARY KEY, rollout_path TEXT, created_at INTEGER, updated_at INTEGER,
            cwd TEXT, title TEXT, preview TEXT, model TEXT, reasoning_effort TEXT,
            git_branch TEXT, tokens_used INTEGER, source TEXT, thread_source TEXT,
            archived INTEGER
        )""")
        state.executemany(
            "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (RUNNING_ID, "/sessions/run.jsonl", 100, 190, "/private/work/alpha", "\nBuild monitor", "prompt body", "gpt-5", "high", "feature/live", 10, "cli", "cli", 0),
                (RECENT_ID, "/sessions/done.jsonl", 80, 180, "/private/work/beta", "Finished task", "private preview", "gpt-5", "medium", "main", 20, "cli", "cli", 0),
                ("archived", "/sessions/archive.jsonl", 10, 200, "/work/old", "Archive", "", "gpt-5", "low", "main", 2, "cli", "cli", 1),
            ],
        )
        # A stale inProgress row must never create an active session. The repository
        # deliberately has no API that reads this table for liveness.
        state.execute("CREATE TABLE thread_turns (thread_id TEXT, status TEXT)")
        state.execute("INSERT INTO thread_turns VALUES (?, 'inProgress')", (RECENT_ID,))
        state.commit()
        state.close()

        history = sqlite3.connect(self.home / "thread_history_1.sqlite")
        history.execute("""CREATE TABLE thread_items (
            thread_id TEXT, turn_id TEXT, item_id TEXT, rollout_ordinal INTEGER,
            created_at_ms INTEGER, item_json TEXT, item_type TEXT,
            updated_at_ordinal INTEGER
        )""")
        items = [
            ("1", 1, "reasoning", {"text": "hidden chain of thought"}),
            ("2", 2, "agentMessage", {"text": "Safe progress update", "phase": "commentary"}),
            ("3", 3, "agentMessage", {"text": "User-facing final", "phase": "final_answer"}),
            ("4", 4, "commandExecution", {"command": "bash -lc 'python3 -m unittest -v'", "status": "completed", "aggregatedOutput": "OK secret logs"}),
            ("5", 5, "fileChange", {"changes": [{"path": "/private/repo/server.py"}], "status": "completed"}),
            ("6", 6, "userMessage", {"text": "giant original prompt"}),
        ]
        history.executemany(
            "INSERT INTO thread_items VALUES (?, 'turn', ?, ?, ?, ?, ?, ?)",
            [(RUNNING_ID, item_id, ordinal, ordinal * 1000, json.dumps(payload), item_type, ordinal) for item_id, ordinal, item_type, payload in items],
        )
        history.commit()
        history.close()
        self.repo = CodexRepository(self.home)

    def tearDown(self):
        self.temp.cleanup()

    def test_loads_allowlisted_metadata_and_recent_excludes_running_and_archived(self):
        metadata = self.repo.metadata_for([RUNNING_ID])
        self.assertEqual(metadata[RUNNING_ID]["branch"], "feature/live")
        self.assertNotIn("title", metadata[RUNNING_ID])
        self.assertNotIn("preview", metadata[RUNNING_ID])
        recent = self.repo.recent_threads({RUNNING_ID}, limit=8)
        self.assertEqual([item["id"] for item in recent], [RECENT_ID])
        self.assertEqual(recent[0]["title"], "Recent Codex session")
        self.assertNotIn("private preview", repr(recent))
        self.assertNotIn("Finished task", repr(recent))

    def test_activity_includes_only_safe_projected_types(self):
        activity = self.repo.activity_for(RUNNING_ID, limit=8)
        self.assertEqual([item["type"] for item in activity], ["message", "command", "file"])
        rendered = repr(activity)
        self.assertIn("Safe progress update", rendered)
        self.assertIn("passed", rendered)
        self.assertIn("server.py", rendered)
        for forbidden in ("chain of thought", "User-facing final", "original prompt", "secret logs", "/private/repo"):
            self.assertNotIn(forbidden, rendered)

    def test_missing_or_busy_databases_return_safe_empty_results(self):
        missing = CodexRepository(self.home / "missing")
        with self.assertLogs("agent_monitor.storage", level="WARNING"):
            self.assertEqual(missing.metadata_for([RUNNING_ID]), {})
            self.assertEqual(missing.activity_for(RUNNING_ID), [])
            self.assertEqual(missing.recent_threads(set()), [])


if __name__ == "__main__":
    unittest.main()
