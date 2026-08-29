import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent_monitor.hermes import HermesRepository


class HermesRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.hermes_home = self.root / "hermes"
        self.proc_root = self.root / "proc"
        self.hermes_home.mkdir()
        self.proc_root.mkdir()
        database = sqlite3.connect(self.hermes_home / "state.db")
        database.executescript(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                source TEXT,
                model TEXT,
                system_prompt TEXT,
                parent_session_id TEXT,
                started_at REAL,
                ended_at REAL,
                title TEXT,
                cwd TEXT,
                archived INTEGER DEFAULT 0,
                hidden INTEGER DEFAULT 0,
                git_branch TEXT,
                git_repo_root TEXT,
                session_key TEXT,
                last_activity_at REAL,
                last_activity_description TEXT,
                last_activity_provenance TEXT,
                title_source TEXT
            );
            CREATE TABLE session_turn_leases (
                conversation_id TEXT PRIMARY KEY,
                holder TEXT NOT NULL,
                acquired_at REAL NOT NULL,
                expires_at REAL NOT NULL
            );
            """
        )
        rows = [
            (
                "live-session", "discord", "gpt-5.6-sol", "PRIVATE SYSTEM PROMPT", None,
                800.0, None, "Monitor Hermes work", "/home/alice/work/monitor", 0, 0,
                "feature/hermes", "/home/alice/work/monitor", "agent:main:discord:thread:123:123",
                995.0, "executing tool: terminal", "unknown", "llm",
            ),
            (
                "expired-session", "discord", "secret-model", "PRIVATE", None,
                700.0, None, "Expired private work", "/private/expired", 0, 0,
                "main", "/private/expired", "agent:main:discord:thread:456:456",
                998.0, "executing tool: web_search with SECRET QUERY", "unknown", "llm",
            ),
            (
                "recent-session", "discord", "gpt-5.6-sol", "PRIVATE", None,
                600.0, 900.0, "Private recent prompt title", "/home/alice/work/recent", 0, 0,
                "main", "/home/alice/work/recent", "agent:main:discord:thread:789:789",
                900.0, "tool completed: terminal", "unknown", "llm",
            ),
        ]
        database.executemany(
            """INSERT INTO sessions (
                id, source, model, system_prompt, parent_session_id, started_at, ended_at,
                title, cwd, archived, hidden, git_branch, git_repo_root, session_key,
                last_activity_at, last_activity_description, last_activity_provenance, title_source
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        database.executemany(
            "INSERT INTO session_turn_leases VALUES (?,?,?,?)",
            [
                ("live-session", "pid=42:turn=live:platform=discord", 990.0, 1_200.0),
                ("expired-session", "pid=43:turn=expired:platform=discord", 990.0, 999.0),
                ("missing-session", "pid=44:turn=missing:platform=discord", 990.0, 1_200.0),
                ("reused-pid-session", "pid=45:turn=reused:platform=discord", 990.0, 1_200.0),
            ],
        )
        database.commit()
        database.close()
        self._make_process(42, b"/venv/bin/python\0-m\0hermes_cli.main\0gateway\0run\0")
        self._make_process(43, b"/venv/bin/python\0-m\0hermes_cli.main\0gateway\0run\0")
        self._make_process(45, b"/usr/bin/python\0unrelated.py\0")

    def tearDown(self):
        self.temp.cleanup()

    def _make_process(self, pid: int, cmdline: bytes) -> None:
        process = self.proc_root / str(pid)
        process.mkdir()
        (process / "cmdline").write_bytes(cmdline)

    def test_live_threads_require_unexpired_lease_and_live_hermes_owner(self):
        repository = HermesRepository(self.hermes_home, proc_root=self.proc_root)
        threads = repository.live_threads(now=1_000.0)
        self.assertEqual(len(threads), 1)
        thread = threads[0]
        self.assertEqual(thread["id"], "hermes:default:live-session")
        self.assertEqual(thread["provider"], "hermes")
        self.assertEqual(thread["pid"], 42)
        self.assertEqual(thread["cwd"], "/home/alice/work/monitor")
        self.assertEqual(thread["branch"], "feature/hermes")
        self.assertEqual(thread["model"], "gpt-5.6-sol")
        self.assertEqual(thread["title"], "Monitor Hermes work")
        self.assertEqual(thread["started_at"], 990.0)
        self.assertEqual(thread["updated_at"], 995.0)
        self.assertEqual(thread["activity"], [{"type": "command", "label": "terminal", "status": "running", "at": 995.0}])
        self.assertNotIn("PRIVATE SYSTEM PROMPT", repr(thread))
        self.assertNotIn("SECRET QUERY", repr(thread))
        self.assertNotIn("holder", thread)
        self.assertNotIn("session_key", thread)

    def test_recent_threads_are_bounded_generic_and_exclude_live(self):
        repository = HermesRepository(self.hermes_home, proc_root=self.proc_root)
        recent = repository.recent_threads({"hermes:default:live-session"}, limit=8)
        self.assertEqual([item["id"] for item in recent], ["hermes:default:recent-session"])
        self.assertEqual(recent[0]["provider"], "hermes")
        self.assertEqual(recent[0]["title"], "Recent Hermes session")
        self.assertNotIn("Private recent prompt title", repr(recent))
        self.assertNotIn("PRIVATE", repr(recent))

    def test_missing_or_legacy_profile_tables_are_ignored(self):
        legacy = self.hermes_home / "profiles" / "legacy"
        legacy.mkdir(parents=True)
        sqlite3.connect(legacy / "state.db").close()
        repository = HermesRepository(self.hermes_home, proc_root=self.proc_root)
        self.assertEqual(len(repository.live_threads(now=1_000.0)), 1)


if __name__ == "__main__":
    unittest.main()
