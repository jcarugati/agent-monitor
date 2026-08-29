import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.bin = self.root / "bin"
        self.home.mkdir()
        self.bin.mkdir()
        self.systemctl_log = self.root / "systemctl.log"
        self._command(
            "systemctl",
            '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$SYSTEMCTL_LOG"\n',
        )

    def tearDown(self):
        self.temp.cleanup()

    def _command(self, name, source):
        path = self.bin / name
        path.write_text(source, encoding="utf-8")
        path.chmod(0o755)

    def run_installer(self, *args):
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(self.home),
                "PATH": f"{self.bin}:{env['PATH']}",
                "SYSTEMCTL_LOG": str(self.systemctl_log),
            }
        )
        return subprocess.run(
            ["bash", str(INSTALLER), *args],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def service_path(self):
        return self.home / ".config/systemd/user/agent-monitor.service"

    def test_dry_run_uses_loopback_and_makes_no_changes(self):
        result = self.run_installer("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("127.0.0.1", result.stdout)
        self.assertIn(str(ROOT), result.stdout)
        self.assertFalse(self.service_path().exists())
        self.assertFalse(self.systemctl_log.exists())

    def test_install_writes_generic_unit_and_enables_user_service_idempotently(self):
        first = self.run_installer("--host", "127.0.0.2", "--port", "9123")
        self.assertEqual(first.returncode, 0, first.stderr)
        service = self.service_path().read_text(encoding="utf-8")
        self.assertIn(f'WorkingDirectory="{ROOT}"', service)
        self.assertIn(f'ExecStart=/usr/bin/python3 "{ROOT}/server.py" --host "127.0.0.2" --port "9123"', service)
        self.assertIn("--codex-home \"%h/.codex\" --hermes-home \"%h/.hermes\"", service)
        self.assertNotIn("0.0.0.0", service)
        original = self.service_path().read_bytes()

        second = self.run_installer("--host", "127.0.0.2", "--port", "9123")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.service_path().read_bytes(), original)
        calls = self.systemctl_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(calls.count("--user daemon-reload"), 2)
        self.assertEqual(calls.count("--user enable --now agent-monitor.service"), 2)

    def test_tailscale_binds_only_detected_ipv4(self):
        self._command("tailscale", "#!/usr/bin/env bash\nprintf '%s\\n' '192.0.2.10'\n")
        result = self.run_installer("--tailscale")
        self.assertEqual(result.returncode, 0, result.stderr)
        service = self.service_path().read_text(encoding="utf-8")
        self.assertIn('--host "192.0.2.10"', service)
        self.assertNotIn("0.0.0.0", service)

    def test_tailscale_failure_is_clear_and_does_not_write(self):
        self._command("tailscale", "#!/usr/bin/env bash\nexit 1\n")
        result = self.run_installer("--tailscale")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Tailscale", result.stderr)
        self.assertFalse(self.service_path().exists())

    def test_rejects_invalid_ports_and_conflicting_bind_options(self):
        for port in ("text", "0", "65536"):
            with self.subTest(port=port):
                result = self.run_installer("--port", port, "--dry-run")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("port", result.stderr.lower())
        conflict = self.run_installer("--host", "127.0.0.1", "--tailscale", "--dry-run")
        self.assertNotEqual(conflict.returncode, 0)
        self.assertIn("cannot be used together", conflict.stderr)

    def test_rejects_control_characters_in_checkout_path(self):
        for codepoint in (*range(1, 32), 127):
            with self.subTest(codepoint=codepoint):
                character = chr(codepoint)
                checkout = self.root / f"checkout{character}path"
                checkout.mkdir()
                installer = checkout / "install.sh"
                shutil.copy2(INSTALLER, installer)
                (checkout / "server.py").touch()

                env = os.environ.copy()
                env.update(
                    {
                        "HOME": str(self.home),
                        "PATH": f"{self.bin}:{env['PATH']}",
                        "SYSTEMCTL_LOG": str(self.systemctl_log),
                    }
                )
                result = subprocess.run(
                    ["bash", str(installer), "--dry-run"],
                    cwd=checkout,
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("control characters", result.stderr)
                self.assertNotIn("[Service]", result.stdout)

    def test_help_documents_supported_options_without_writing(self):
        result = self.run_installer("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        for option in ("--tailscale", "--host", "--port", "--dry-run", "--help"):
            self.assertIn(option, result.stdout)
        self.assertFalse(self.service_path().exists())


if __name__ == "__main__":
    unittest.main()
