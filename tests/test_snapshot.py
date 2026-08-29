import tempfile
import unittest
from pathlib import Path

from agent_monitor.processes import ProcessSession
from agent_monitor.snapshot import build_snapshot


THREAD_ID = "123e4567-e89b-12d3-a456-426614174000"


class FakeRepository:
    def metadata_for(self, thread_ids):
        return {THREAD_ID: {"id": THREAD_ID, "created_at": 900.0, "updated_at": 990.0, "cwd": "/home/alice/work/monitor", "title": "Monitor work", "branch": "feature/ui", "model": "gpt-5", "reasoning_effort": "high"}}

    def activity_for(self, thread_id, limit=8):
        return [{"type": "message", "text": "Implementing the monitor", "at": 995.0}]

    def recent_threads(self, active_ids, limit=8):
        return [{"id": "recent", "project_name": "other", "cwd": "~/work/other", "title": "Recent work", "branch": "main", "model": "gpt-5", "reasoning_effort": "medium", "updated_at": "1970-01-01T00:16:00Z"}]


class FakeHermesRepository:
    def live_threads(self, *, now):
        return [{
            "id": "hermes:default:session", "provider": "hermes", "pid": 84,
            "project_name": "agent", "cwd": "/home/alice/work/agent", "branch": "main",
            "model": "gpt-5.6-sol", "reasoning_effort": "Agent turn",
            "started_at": 980.0, "updated_at": 998.0, "title": "Reviewing another task",
            "latest_summary": "Running terminal", "activity": [
                {"type": "command", "label": "terminal", "status": "running", "at": 998.0}
            ],
        }]

    def recent_threads(self, active_ids, limit=8):
        return [{
            "id": "hermes:default:recent", "provider": "hermes", "project_name": "agent-old",
            "cwd": "/home/alice/work/agent-old", "title": "Recent Hermes session", "branch": "main",
            "model": "gpt-5.6-sol", "reasoning_effort": "Agent session", "updated_at": 970.0,
            "created_at": 900.0,
        }]


class SnapshotTests(unittest.TestCase):
    def test_snapshot_combines_proc_truth_with_safe_metadata(self):
        process = ProcessSession(THREAD_ID, 42, "/sessions/rollout.jsonl", "/home/alice/work/monitor", 900.0)
        snapshot = build_snapshot([process], FakeRepository(), now=1_000.0, user_home=Path("/home/alice"))
        self.assertEqual(snapshot["running_count"], 1)
        self.assertEqual(snapshot["recent_count"], 1)
        thread = snapshot["running_threads"][0]
        self.assertEqual(thread["elapsed_seconds"], 100)
        self.assertEqual(thread["last_activity_age_seconds"], 5)
        self.assertEqual(thread["cwd"], "~/work/monitor")
        self.assertEqual(thread["project_name"], "monitor")
        self.assertEqual(thread["title"], "Implementing the monitor")
        self.assertEqual(thread["latest_summary"], "Implementing the monitor")
        self.assertNotIn("Monitor work", repr(thread))
        self.assertNotIn("rollout_path", thread)
        self.assertEqual(thread["provider"], "codex")

    def test_snapshot_combines_codex_and_hermes_threads(self):
        process = ProcessSession(THREAD_ID, 42, "/sessions/rollout.jsonl", "/home/alice/work/monitor", 900.0)
        snapshot = build_snapshot(
            [process], FakeRepository(), now=1_000.0, user_home=Path("/home/alice"),
            hermes_repository=FakeHermesRepository(),
        )
        self.assertEqual(snapshot["running_count"], 2)
        self.assertEqual(snapshot["provider_counts"], {
            "codex": {"running": 1, "recent": 1},
            "hermes": {"running": 1, "recent": 1},
        })
        providers = [thread["provider"] for thread in snapshot["running_threads"]]
        self.assertEqual(providers, ["codex", "hermes"])
        hermes = snapshot["running_threads"][1]
        self.assertEqual(hermes["elapsed_seconds"], 20)
        self.assertEqual(hermes["last_activity_age_seconds"], 2)
        self.assertEqual(hermes["cwd"], "~/work/agent")
        self.assertEqual(hermes["title"], "Reviewing another task")
        self.assertEqual(snapshot["recent_count"], 2)
        self.assertEqual({item["provider"] for item in snapshot["recent_completions"]}, {"codex", "hermes"})


if __name__ == "__main__":
    unittest.main()
