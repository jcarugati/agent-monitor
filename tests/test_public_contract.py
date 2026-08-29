import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PublicRepositoryContractTests(unittest.TestCase):
    def test_public_repository_files_and_generic_names_are_present(self):
        for relative in (
            "LICENSE",
            "SECURITY.md",
            "CONTRIBUTING.md",
            ".github/workflows/ci.yml",
            "deploy/agent-monitor.service",
            "agent_monitor/__init__.py",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)
        legacy_package = "codex" + "_monitor"
        legacy_service = "codex" + "-monitor.service"
        self.assertFalse((ROOT / legacy_package).exists())
        self.assertFalse((ROOT / "deploy" / legacy_service).exists())
        self.assertFalse((ROOT / "docs/superpowers").exists())

    def test_readme_covers_install_access_privacy_api_and_operations(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for required in (
            "# Agent Monitor",
            "## Quick start",
            "## Direct run",
            "## Install as a user service",
            "## Tailscale access",
            "## Uninstall",
            "## Provider requirements",
            "## Privacy guarantees",
            "## API endpoints",
            "## Troubleshooting",
            "mode=ro",
            "127.0.0.1",
            "./install.sh --tailscale",
        ):
            self.assertIn(required, readme)

    def test_ci_runs_all_static_and_test_gates(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        for required in (
            "3.11",
            "3.12",
            "3.13",
            "python -m unittest discover -s tests -v",
            "python -m py_compile server.py agent_monitor/*.py tests/*.py",
            "node --check frontend/app.js",
            "bash -n install.sh",
            "git diff --check",
        ):
            self.assertIn(required, workflow)


if __name__ == "__main__":
    unittest.main()
