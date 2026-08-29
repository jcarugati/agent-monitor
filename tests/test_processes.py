import os
import tempfile
import unittest
from pathlib import Path

from agent_monitor.processes import discover_processes


THREAD_ID = "123e4567-e89b-12d3-a456-426614174000"
THREAD_ID_2 = "223e4567-e89b-12d3-a456-426614174001"


class ProcessDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.proc = self.root / "proc"
        self.home = self.root / "codex-home"
        self.rollout = self.home / "sessions/2026/08/29" / f"rollout-2026-08-29-{THREAD_ID}.jsonl"
        self.rollout.parent.mkdir(parents=True)
        self.rollout.write_text("", encoding="utf-8")
        (self.proc).mkdir()
        (self.proc / "uptime").write_text("1000.00 0.00\n", encoding="ascii")
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        (self.bin_dir / "codex").write_text("", encoding="utf-8")
        (self.bin_dir / "node").write_text("", encoding="utf-8")
        self.cwd = self.root / "projects" / "monitor"
        self.cwd.mkdir(parents=True)

    def tearDown(self):
        self.temp.cleanup()

    def add_process(self, pid, executable="codex", rollout=None, *, with_lock=True):
        process = self.proc / str(pid)
        (process / "fd").mkdir(parents=True)
        os.symlink(self.bin_dir / executable, process / "exe")
        os.symlink(self.cwd, process / "cwd")
        # Field 22 is starttime; parentheses in comm are handled by parsing after ')'.
        fields_after_comm = ["S"] + (["0"] * 18) + ["5000"] + (["0"] * 20)
        (process / "stat").write_text(f"{pid} (codex) " + " ".join(fields_after_comm), encoding="ascii")
        rollouts = [] if rollout is None else (rollout if isinstance(rollout, list) else [rollout])
        for index, path in enumerate(rollouts):
            os.symlink(path, process / "fd" / str(7 + index))
            if with_lock:
                thread_id = path.name.removesuffix(".jsonl")[-36:]
                lock = self.home / "thread-writer-locks" / f"{thread_id}.lock"
                lock.parent.mkdir(parents=True, exist_ok=True)
                lock.touch()
                os.symlink(lock, process / "fd" / str(20 + index))

    def test_discovers_native_process_and_maps_rollout_thread_and_cwd(self):
        self.add_process(101, rollout=self.rollout)
        found = discover_processes(self.proc, self.home, now=2_000.0, clock_ticks=100)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].pid, 101)
        self.assertEqual(found[0].thread_id, THREAD_ID)
        self.assertEqual(found[0].rollout_path, str(self.rollout))
        self.assertEqual(found[0].cwd, str(self.cwd))
        self.assertEqual(found[0].started_at, 1_050.0)

    def test_ignores_node_launcher_and_process_without_rollout(self):
        self.add_process(101, executable="node", rollout=self.rollout)
        self.add_process(102, executable="codex")
        self.assertEqual(discover_processes(self.proc, self.home), [])

    def test_deduplicates_same_thread_and_rejects_rollout_outside_home(self):
        self.add_process(101, rollout=self.rollout)
        self.add_process(102, rollout=self.rollout)
        outside = self.root / f"rollout-{THREAD_ID}.jsonl"
        outside.write_text("", encoding="utf-8")
        self.add_process(103, rollout=outside)
        found = discover_processes(self.proc, self.home)
        self.assertEqual([item.pid for item in found], [101])

    def test_maps_every_rollout_with_a_matching_writer_lock_from_one_process(self):
        second = self.home / "sessions/2026/08/29" / f"rollout-2026-08-29-{THREAD_ID_2}.jsonl"
        second.write_text("", encoding="utf-8")
        self.add_process(101, rollout=[self.rollout, second])
        found = discover_processes(self.proc, self.home)
        self.assertEqual([(item.pid, item.thread_id) for item in found], [(101, THREAD_ID), (101, THREAD_ID_2)])

    def test_ignores_rollout_without_matching_writer_lock(self):
        self.add_process(101, rollout=self.rollout, with_lock=False)
        self.assertEqual(discover_processes(self.proc, self.home), [])

    def test_tolerates_pid_race_and_malformed_entries(self):
        (self.proc / "not-a-pid").mkdir()
        (self.proc / "404").mkdir()
        self.assertEqual(discover_processes(self.proc, self.home), [])


if __name__ == "__main__":
    unittest.main()
