"""Tests for the notes module and the CLI. Standard library only:

    python3 -m unittest discover -s tests
"""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from caderno import cli, notes  # noqa: E402

GIT_ENV = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}


class Sandbox(unittest.TestCase):
    """A fake home directory, so tests never touch the real one."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.env = _env(
            {"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config"), **GIT_ENV}, drop=["CADERNO_ROOT"]
        )
        self.env.__enter__()
        self.root = self.home / "caderno"

    def tearDown(self):
        self.env.__exit__(None, None, None)
        self.tmp.cleanup()

    def run_cli(self, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                code = cli.main(list(args))
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
                out.write(str(e.code))
        return code, out.getvalue()

    def init(self):
        code, out = self.run_cli("init", str(self.root), "--name", "Ana", "--host", "box", "-y")
        self.assertEqual(code, 0, out)


@contextlib.contextmanager
def _env(values: dict, drop: list[str]):
    old = dict(os.environ)
    for k in drop:
        os.environ.pop(k, None)
    os.environ.update(values)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(old)


class NotesTest(unittest.TestCase):
    def test_parse_and_render_round_trip(self):
        text = notes.render({"description": "a fact", "type": "lesson"}, "The body.\n")
        meta, body = notes.parse(text)
        self.assertEqual(meta, {"description": "a fact", "type": "lesson"})
        self.assertEqual(body.strip(), "The body.")

    def test_no_front_matter_is_all_body(self):
        self.assertEqual(notes.parse("just text"), ({}, "just text"))

    def test_index_is_deterministic_and_grouped(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "memory").mkdir()
            (root / "memory" / "b.md").write_text(notes.render({"description": "second", "type": "lesson"}, "x"))
            (root / "memory" / "a.md").write_text(notes.render({"description": "first", "type": "preference"}, "x"))
            (root / "memory" / "_archive").mkdir()
            (root / "memory" / "_archive" / "old.md").write_text(notes.render({"description": "gone"}, "x"))
            one = notes.build_index(root)
            self.assertEqual(one, notes.build_index(root))
            self.assertIn("- [b](b.md) — second", one)
            self.assertNotIn("gone", one, "archived notes stay out of the index")
            self.assertLess(one.index("## lesson"), one.index("## preference"))

    def test_secrets_are_caught(self):
        for line in [
            "password: correct-horse-battery",
            "token = abcdef1234567890",
            "-----BEGIN OPENSSH PRIVATE KEY-----",
            "export OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz0123",
            "ghp_" + "a" * 36,
            "postgres://admin:s3cretpw@db:5432/app",
            "AKIAABCDEFGHIJKLMNOP",
        ]:
            self.assertTrue(notes.scan_text(line), line)

    def test_ordinary_prose_is_not_a_secret(self):
        for line in [
            "The password manager holds the key under 'nas admin'.",
            "Set CADERNO_TOKEN=$(openssl rand -hex 32)",
            "api_key = <your key>",
            "Tokens rotate weekly; see the runbook.",
            "https://example.com/path@v2",
        ]:
            self.assertEqual(notes.scan_text(line), [], line)

    def test_allow_marker_and_denylist(self):
        self.assertEqual(notes.scan_text("password: fixture-value  <!-- caderno:allow -->"), [])
        self.assertTrue(notes.scan_text("the nas is at hidden-host.lan", ["hidden-host.lan"]))


class CliTest(Sandbox):
    def test_init_creates_a_healthy_notebook(self):
        self.init()
        self.assertTrue((self.root / "INDEX.md").exists())
        self.assertIn("Ana's caderno", (self.root / "INDEX.md").read_text())
        self.assertTrue((self.root / "memory" / "INDEX.md").exists())
        self.assertTrue((self.root / ".git" / "hooks" / "pre-commit").exists())
        code, out = self.run_cli("check")
        self.assertEqual(code, 0, out)

    def test_connect_is_idempotent_and_reversible(self):
        self.init()
        agents = self.home / ".codex" / "AGENTS.md"
        agents.parent.mkdir()
        agents.write_text("# my own rules\n\nBe brief.\n")
        self.run_cli("connect", "codex")
        self.run_cli("connect", "codex")
        text = agents.read_text()
        self.assertEqual(text.count(cli.BEGIN), 1)
        self.assertIn("Be brief.", text)
        self.assertIn("~/caderno/INDEX.md", text)
        self.run_cli("connect", "codex", "--remove")
        self.assertNotIn(cli.BEGIN, agents.read_text())
        self.assertIn("Be brief.", agents.read_text())

    def test_connect_rejects_unknown_agent(self):
        self.init()
        code, _ = self.run_cli("connect", "notanagent")
        self.assertNotEqual(code, 0)

    def test_new_refuses_to_overwrite(self):
        self.init()
        code, _ = self.run_cli("new", "Deploys need the prod overlay", "--type", "lesson")
        self.assertEqual(code, 0)
        self.assertTrue((self.root / "memory" / "deploys-need-the-prod-overlay.md").exists())
        self.assertIn("deploys-need-the-prod-overlay", (self.root / "memory" / "INDEX.md").read_text())
        code, out = self.run_cli("new", "Deploys need the prod overlay")
        self.assertNotEqual(code, 0)
        self.assertIn("already exists", out)

    def test_check_finds_missing_description_and_stale_index(self):
        self.init()
        (self.root / "memory" / "bare.md").write_text("no front matter here\n")
        code, out = self.run_cli("check")
        self.assertEqual(code, 1)
        self.assertIn("no description", out)
        self.assertIn("out of date", out)

    def test_sync_commits_and_pushes_between_two_machines(self):
        self.init()
        remote = self.home / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
        self.run_cli("remote", str(remote))
        code, out = self.run_cli("sync")
        self.assertEqual(code, 0, out)

        # A second machine joins, writes a note, syncs.
        other = self.home / "other"
        code, out = self.run_cli("init", str(other), "--clone", str(remote), "--host", "laptop", "-y")
        self.assertEqual(code, 0, out)
        (other / "memory" / "from-laptop.md").write_text(notes.render({"description": "written on the laptop"}, "hi"))
        code, out = self.run_cli("sync", "--root", str(other))
        self.assertEqual(code, 0, out)

        # The first machine sees it, with the index rebuilt.
        code, out = self.run_cli("sync", "--root", str(self.root))
        self.assertEqual(code, 0, out)
        self.assertTrue((self.root / "memory" / "from-laptop.md").exists())
        self.assertIn("written on the laptop", (self.root / "memory" / "INDEX.md").read_text())

    def test_hook_blocks_a_committed_secret(self):
        self.init()
        (self.root / "memory" / "oops.md").write_text(notes.render({"description": "db"}, "password: hunter2hunter2"))
        code, out = self.run_cli("sync")
        self.assertNotEqual(code, 0)
        log = subprocess.run(["git", "-C", str(self.root), "log", "--oneline"], capture_output=True, text=True)
        self.assertEqual(log.stdout.strip(), "", "nothing was committed")

    def test_install_timer_dry_run_writes_units(self):
        self.init()
        code, out = self.run_cli("install-timer", "--dry-run", "--minutes", "7")
        self.assertEqual(code, 0, out)
        if sys.platform.startswith("linux") and (self.home / ".config" / "systemd" / "user").exists():
            timer = (self.home / ".config" / "systemd" / "user" / "caderno-sync.timer").read_text()
            self.assertIn("OnUnitActiveSec=7min", timer)


if __name__ == "__main__":
    unittest.main()
