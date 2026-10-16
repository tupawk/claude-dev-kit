"""The secrets and design-token hooks read every field an edit can write, and only those.

Until v0.3.2 both read `content` and `new_string` alone, so a notebook edit or the separate edits
of a multi-part edit were never scanned, and the hooks were wired to Edit and Write only. The
secrets hook also missed `.env.*` written with Windows backslashes, and both hooks blocked
ordinary text (a CSS class named `task-management-dashboard`, `// issue #123`, `href="#add"`).
Every case below was found in the 2026-10-11 review.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_block_dangerous_git import BASH, HOOKS, make_repo

KIT = Path(__file__).resolve().parent.parent
BLOCKED, ALLOWED = 2, 0

# Assembled at run time so this file is not itself a credential or a colour to any scanner.
AWS_KEY = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
API_KEY = "sk" + "-ant-" + "api03-abcdefghijklmnopqrstuvwxyz0123456789"
GITHUB_PAT = "github" + "_pat_" + "11ABCDEFG0123456789_abcdefghijklmnopqrstuv"
GOOGLE_KEY = "AI" + "za" + "SyA-abcdefghijklmnopqrstuvwxyz0123456"
STRIPE_KEY = "sk" + "_live_" + "abcdefghijklmnop0123"
PEM = "-----BEGIN " + "ENCRYPTED PRIVATE KEY-----"
HEX = "#" + "2F6FED"


class EditHookCase(unittest.TestCase):
    hook = ""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="kit-edit-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = make_repo(self.tmp / "project", "feat/x")
        shutil.copytree(HOOKS, self.root / ".claude" / "hooks")

    def run_hook(self, tool_input: dict, *, ascii_json: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [BASH, f".claude/hooks/{self.hook}"],
            input=json.dumps({"tool_input": tool_input}, ensure_ascii=ascii_json),
            cwd=self.root,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(self.root)},
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

    def path(self, rel: str) -> str:
        return str(self.root / rel)

    def assert_blocked(self, tool_input: dict, saying: str) -> None:
        result = self.run_hook(tool_input)
        self.assertEqual(result.returncode, BLOCKED, result.stderr)
        self.assertIn(saying, result.stderr)

    def assert_allowed(self, tool_input: dict, **kw: bool) -> None:
        result = self.run_hook(tool_input, **kw)
        self.assertEqual(result.returncode, ALLOWED, result.stderr)


class TheSecretsHook(EditHookCase):
    hook = "block-secrets.sh"

    def test_scans_every_field_an_edit_can_write(self) -> None:
        for shape in [
            {"file_path": self.path("a.py"), "content": f"k = '{AWS_KEY}'"},
            {"file_path": self.path("a.py"), "old_string": "x", "new_string": f"k = '{AWS_KEY}'"},
            {"file_path": self.path("a.py"), "edits": [{"old_string": "x", "new_string": f"k = '{AWS_KEY}'"}]},
            {"notebook_path": self.path("a.ipynb"), "new_source": f"k = '{AWS_KEY}'"},
        ]:
            with self.subTest(fields=sorted(shape)):
                self.assert_blocked(shape, "AWS access key")

    def test_ignores_the_text_being_replaced(self) -> None:
        # Removing a leaked key must be possible: old_string is what is already there.
        self.assert_allowed({"file_path": self.path("a.py"), "old_string": f"k = '{AWS_KEY}'", "new_string": "k = env()"})

    def test_refuses_env_files_however_the_path_is_spelled(self) -> None:
        for rel in [".env", ".env.local", "services/api/.env.production", "prod.env"]:
            for path in (self.path(rel), self.path(rel).replace("/", "\\")):
                with self.subTest(path=path):
                    self.assert_blocked({"file_path": path, "content": "X=1"}, "writing to")

    def test_refuses_env_files_spelled_the_way_windows_and_macos_still_open_them(self) -> None:
        for rel in [".ENV", ".Env.local", ".env ", ".env::$DATA"]:
            with self.subTest(name=rel):
                self.assert_blocked({"file_path": self.path(rel), "content": "X=1"}, "writing to")

    def test_finds_credential_names_with_a_prefix(self) -> None:
        for text in [
            'DB_PASSWORD = "hunter2hunter2"',
            'dbPassword: "q8Zr1mPx4LkT9vWe"',
            'GITHUB_TOKEN="abcdefabcdef1234"',
            'AUTH0_CLIENT_SECRET: "q8Zr1mPx4LkT9vWe"',
        ]:
            with self.subTest(text=text):
                self.assert_blocked({"file_path": self.path("a.txt"), "content": text}, "hardcoded credential")

    def test_lets_env_example_through(self) -> None:
        self.assert_allowed({"file_path": self.path(".env.example"), "content": "X=<placeholder>"})

    def test_finds_each_credential_shape(self) -> None:
        for text, saying in [
            (f"key = '{API_KEY}'", "API secret key"),
            (f"key = '{STRIPE_KEY}'", "Stripe"),
            (f"t = '{GITHUB_PAT}'", "GitHub token"),
            (f"g = '{GOOGLE_KEY}'", "Google API key"),
            (PEM, "private key"),
            ('{"api_key": "q8Zr1mPx4LkT9vWe"}', "hardcoded credential"),
        ]:
            with self.subTest(saying=saying):
                self.assert_blocked({"file_path": self.path("a.txt"), "content": text}, saying)

    def test_passes_ordinary_text(self) -> None:
        for text in [
            ".ta" + "sk-management-dashboard { color: inherit; }",
            ".ri" + "sk-assessment-summary-panel {}",
            'password: "must be at least twelve characters long"',
            'api_key = os.environ["API_KEY"]',
            'token: "${{ secrets.DEPLOY_TOKEN }}"',
            'tokenizer = "bert-base-uncased-v2"',
        ]:
            with self.subTest(text=text):
                self.assert_allowed({"file_path": self.path("a.txt"), "content": text})

    def test_reads_non_ascii_payloads(self) -> None:
        for ascii_json in (True, False):
            with self.subTest(ascii_json=ascii_json):
                self.assert_allowed({"file_path": self.path("a.md"), "content": "café → 東京 🎉"}, ascii_json=ascii_json)


class TheColourHook(EditHookCase):
    hook = "block-hardcoded-colors.sh"

    def test_scans_every_field_an_edit_can_write(self) -> None:
        for shape in [
            {"file_path": self.path("src/a.css"), "content": f"a {{ color: {HEX}; }}"},
            {"file_path": self.path("src/a.css"), "edits": [{"old_string": "x", "new_string": f"a {{ color: {HEX}; }}"}]},
        ]:
            with self.subTest(fields=sorted(shape)):
                self.assert_blocked(shape, "hardcoded colour")

    def test_finds_colours_in_their_usual_places(self) -> None:
        for path, text in [
            ("src/a.css", "a { color: #333; }"),
            ("src/a.css", "a { border: 1px solid #333; }"),
            ("templates/a.html", '<td bgcolor="#fff">'),
            ("src/components/Button.tsx", f"const c = '{HEX}';"),
        ]:
            with self.subTest(text=text):
                self.assert_blocked({"file_path": self.path(path), "content": text}, "hardcoded colour")

    def test_passes_hashes_that_are_not_colours(self) -> None:
        for path, text in [
            ("src/components/List.tsx", "// fixes issue #123"),
            ("templates/order.html", "<p>Order #1001 is on its way</p>"),
            ("templates/nav.html", '<a href="#add">Add</a>'),
        ]:
            with self.subTest(text=text):
                self.assert_allowed({"file_path": self.path(path), "content": text})

    def test_a_long_line_is_checked_in_linear_time(self) -> None:
        # The first rewrite re-scanned the start of the line for every '#': 40,000 dashes and one
        # #123 took 11 seconds, and a hook that times out lets the write through unchecked.
        import time

        for text in ["-" * 200_000 + " #123", "x #123 " * 30_000, 'href=#abc ' * 20_000]:
            with self.subTest(shape=text[:12]):
                start = time.monotonic()
                self.run_hook({"file_path": self.path("templates/a.html"), "content": text})
                self.assertLess(time.monotonic() - start, 8.0)

    def test_exempts_only_the_top_level_design_directory(self) -> None:
        self.assert_allowed({"file_path": self.path("design/tokens.css"), "content": f"--x: {HEX};"})
        self.assert_blocked(
            {"file_path": self.path("src/components/design/Button.css"), "content": f"a {{ color: {HEX}; }}"},
            "hardcoded colour",
        )

    def test_an_exempt_directory_with_a_dot_in_its_name_is_exempt(self) -> None:
        (self.root / ".claude" / "kit.json").write_text(json.dumps({"design": {"exempt": ["theme.v1"]}}), encoding="utf-8")
        self.assert_allowed({"file_path": self.path("theme.v1/assets/a.css"), "content": f"a {{ color: {HEX}; }}"})


class TheHooksAreWiredToEveryWriteTool(unittest.TestCase):
    def test_settings_and_plugin_match_every_tool_that_writes_a_file(self) -> None:
        for path in (KIT / "core" / ".claude" / "settings.json", KIT / ".claude-plugin" / "hooks.json"):
            hooks = json.loads(path.read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
            guarded = [e["matcher"] for e in hooks if any("block-secrets.sh" in h["command"] for h in e["hooks"])]
            with self.subTest(file=path.name):
                self.assertEqual(len(guarded), 1)
                self.assertEqual(set(guarded[0].split("|")), {"Edit", "Write", "MultiEdit", "NotebookEdit"})


if __name__ == "__main__":
    unittest.main()
