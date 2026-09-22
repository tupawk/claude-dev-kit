"""Tests for the .env read-deny rules in core/.claude/settings.json and their refresh.

The secrets rule tells Claude to read `.env.example` instead of `.env`. Until v0.3.1 the kit also
denied `Read(./.env.*)`, which matches `.env.example`, so the one file the rule points at could
not be read. Claude Code's matcher treats `[!e]` and `[^e]` as literal characters, not negation
(checked live on 2026-09-22), so the rules are built from `*` and `?` only: every suffix length
except seven, plus the seven-letter names worth guarding by name.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from fnmatch import fnmatchcase
from pathlib import Path

from test_block_dangerous_git import find_bash

KIT = Path(__file__).resolve().parent.parent
CORE_SETTINGS = KIT / "core" / ".claude" / "settings.json"
RETIRED_RULE = "Read(./.env.*)"


def read_deny_globs() -> list[str]:
    """The path globs of every Read(...) deny rule, with the leading ./ removed."""
    rules = json.loads(CORE_SETTINGS.read_text(encoding="utf-8"))["permissions"]["deny"]
    return [r[len("Read(./") : -1] for r in rules if r.startswith("Read(./")]


def denied(name: str) -> bool:
    # `*` and `?` mean the same in fnmatch as in the permission matcher, and no rule uses brackets.
    return any(fnmatchcase(name, glob) or fnmatchcase(name, glob.removeprefix("**/")) for glob in read_deny_globs())


class TheCoreRules(unittest.TestCase):
    def test_leave_env_example_readable(self) -> None:
        self.assertFalse(denied(".env.example"))

    def test_deny_every_common_env_file(self) -> None:
        for name in [
            ".env",
            ".env.local",
            ".env.test",
            ".env.production",
            ".env.development",
            ".env.staging",
            ".env.secrets",
            ".env.bak",
            ".env.bak-2026-09-06",
            ".env.example.bak",
            ".env.local.backup",
        ]:
            with self.subTest(name=name):
                self.assertTrue(denied(name), f"{name} is readable")

    def test_use_no_bracket_expressions(self) -> None:
        # Brackets looked like negation and were silently literal; never again.
        for glob in read_deny_globs():
            self.assertNotIn("[", glob)

    def test_no_longer_ship_the_retired_rule(self) -> None:
        self.assertNotIn(RETIRED_RULE, json.loads(CORE_SETTINGS.read_text(encoding="utf-8"))["permissions"]["deny"])


class ARefresh(unittest.TestCase):
    """`new-project.sh update` merges permissions, keeping a project's own rules."""

    def test_drops_the_retired_rule_and_keeps_the_projects_own(self) -> None:
        own_rule = "Bash(rm -rf ./scratch*)"
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".claude").mkdir()
            (project / "CLAUDE.md").write_text("# project\n", encoding="utf-8")
            (project / ".claude" / "KIT_VERSION").write_text("v0.3.0\n", encoding="utf-8")
            (project / ".claude" / "kit.json").write_text(
                json.dumps({"packages": [{"profile": "scripts", "path": "."}]}), encoding="utf-8"
            )
            (project / ".claude" / "settings.json").write_text(
                json.dumps({"permissions": {"deny": ["Read(./.env)", RETIRED_RULE, own_rule]}}),
                encoding="utf-8",
            )
            subprocess.run(
                [find_bash(), str(KIT / "scripts" / "new-project.sh"), "update", str(project)],
                check=True,
                capture_output=True,
            )
            deny = json.loads((project / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]["deny"]

        self.assertNotIn(RETIRED_RULE, deny)
        self.assertIn(own_rule, deny)
        self.assertIn("Read(./.env.????????*)", deny)


if __name__ == "__main__":
    unittest.main()
