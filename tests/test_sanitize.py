import unittest

from agent_monitor.sanitize import clean_text, command_activity, file_activity, title_from


class SanitizeTests(unittest.TestCase):
    def test_clean_text_removes_controls_collapses_space_and_bounds(self):
        value = "alpha\x00\n beta\t" + ("x" * 100)
        self.assertEqual(clean_text(value, 20), "alpha beta xxxxxxxx…")

    def test_clean_text_removes_unicode_format_controls(self):
        self.assertEqual(clean_text("safe\u202etext", 40), "safetext")

    def test_title_uses_first_meaningful_bounded_line(self):
        self.assertEqual(title_from("\n  Build the monitor\nignore", "fallback", 18), "Build the monitor")
        self.assertEqual(title_from("", "  fallback preview  ", 40), "fallback preview")
        self.assertEqual(title_from("", "", 40), "Untitled session")

    def test_command_labels_strip_wrappers_and_never_include_payload_or_output(self):
        item = {
            "command": "/bin/bash -lc 'python3 -m unittest discover -s tests -v && cat <<EOF giant secret prompt EOF'",
            "status": "completed",
            "aggregatedOutput": "FAILED (failures=2) secret output",
        }
        activity = command_activity(item)
        self.assertEqual(activity["label"], "python3 -m unittest")
        self.assertEqual(activity["result"], "failed")
        rendered = repr(activity)
        self.assertNotIn("secret", rendered)
        self.assertNotIn("prompt", rendered)
        self.assertNotIn("cat", rendered)

    def test_test_summary_does_not_treat_zero_failures_as_failed(self):
        activity = command_activity({
            "command": "pytest -q",
            "status": "completed",
            "aggregatedOutput": "10 passed, 0 failed in 0.30s",
        })
        self.assertEqual(activity["result"], "passed")

    def test_command_label_reduces_unknown_commands_to_executable(self):
        activity = command_activity({"command": "deploy-tool --payload sensitive-value --message private", "status": "running"})
        self.assertEqual(activity, {"type": "command", "label": "deploy-tool", "status": "running"})

    def test_command_label_discards_environment_assignments(self):
        activity = command_activity({
            "command": "env -i EXAMPLE_SETTING=sensitive-value MODE=private python3 /work/check.py",
            "status": "running",
        })
        self.assertEqual(activity["label"], "python3 check.py")
        self.assertNotIn("secret", repr(activity))
        self.assertNotIn("EXAMPLE_SETTING", repr(activity))

    def test_file_activity_returns_only_basenames_and_a_bounded_count(self):
        changes = [{"path": f"/private/project/folder/file-{index}.py"} for index in range(10)]
        activity = file_activity({"changes": changes, "status": "completed"})
        self.assertEqual(activity["count"], 10)
        self.assertEqual(len(activity["files"]), 5)
        self.assertEqual(activity["files"][0], "file-0.py")
        self.assertNotIn("private", repr(activity))


if __name__ == "__main__":
    unittest.main()
