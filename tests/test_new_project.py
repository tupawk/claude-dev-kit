"""Tests for scripts/new-project.sh: assembling a project and refreshing it with `update`.

Every test builds throwaway projects in a temporary directory and runs the script the way a person
does, `bash scripts/new-project.sh ...`. Design packs are local git repositories reached through a
file:// URL, and XDG_CACHE_HOME points the pack cache into the temporary directory, so nothing
outside it is touched.

    python -m unittest discover -s tests -v

Each class is one defect found in the 2026-10-11 review, plus what must keep working around it.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_block_dangerous_git import BASH, git

KIT = Path(__file__).resolve().parent.parent
SCRIPT = KIT / "scripts" / "new-project.sh"


class Sandbox:
    """A temporary directory holding projects, packs and the pack cache for one test."""

    def __init__(self, case: unittest.TestCase) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        case.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.env = dict(os.environ, XDG_CACHE_HOME=str(self.root / "cache"))

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        # check=False: the tests read the exit code, and a refusal is an expected outcome.
        return subprocess.run(
            [BASH, str(SCRIPT), *args], capture_output=True, text=True, env=self.env, cwd=self.root, check=False
        )

    def new(self, spec: str, name: str = "proj") -> Path:
        result = self.run(spec, str(self.root / name), "My App")
        if result.returncode != 0:
            raise AssertionError(f"new {spec} failed ({result.returncode}): {result.stderr}")
        return self.root / name

    def update(self, project: Path) -> subprocess.CompletedProcess[str]:
        return self.run("update", str(project))

    def pack(self, relpath: str, rule_text: str) -> str:
        """A git repo holding a design pack whose design-system.md says `rule_text`. Returns its URL."""
        repo = self.root / relpath
        repo.mkdir(parents=True)
        git(repo, "init", "-q", "-b", "main")
        (repo / "design-system.md").write_text(rule_text + "\n", encoding="utf-8")
        (repo / "brand.css").write_text(":root { --brand-primary: #123456; }\n", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "-q", "-m", "pack")
        return repo.as_uri()


def set_kit_json(project: Path, **changes: object) -> None:
    path = project / ".claude" / "kit.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.update(changes)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def snapshot(project: Path) -> dict[str, str]:
    """A hash of every file under .claude/ and design/, to prove a failed run changed nothing."""
    out: dict[str, str] = {}
    for top in (".claude", "design"):
        for f in sorted((project / top).rglob("*")):
            if f.is_file():
                out[f.relative_to(project).as_posix()] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


class ANewProject(unittest.TestCase):
    """A `typescript` package last in the spec used to abort the script with no message."""

    def test_completes_for_every_profile_and_every_profile_last(self) -> None:
        for spec in ["typescript", "python", "scripts", "python,typescript=web", "typescript=web,python"]:
            with self.subTest(spec=spec):
                sandbox = Sandbox(self)
                result = sandbox.run(spec, str(sandbox.root / "proj"), "My App")
                project = sandbox.root / "proj"
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(".env", (project / ".gitignore").read_text(encoding="utf-8").splitlines())
                self.assertTrue((project / ".git").is_dir())
                self.assertTrue((project / ".claude" / "KIT_VERSION").is_file())
                self.assertNotIn("<project name>", (project / "CLAUDE.md").read_text(encoding="utf-8"))

    def test_gets_the_kit_ignore_entries_once_after_an_update(self) -> None:
        sandbox = Sandbox(self)
        project = sandbox.new("python")
        self.assertEqual(sandbox.update(project).returncode, 0)
        lines = (project / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines.count(".claude/settings.local.json"), 1)


class AnUpdate(unittest.TestCase):
    """`update` used to delete .claude/agents, skills, rules and hooks whole, project files included."""

    def test_keeps_the_projects_own_agents_skills_rules_and_hooks(self) -> None:
        sandbox = Sandbox(self)
        project = sandbox.new("python")
        own = [
            ".claude/agents/my-agent.md",
            ".claude/skills/my-skill/SKILL.md",
            ".claude/rules/project-rule.md",
            ".claude/hooks/my-guard.sh",
        ]
        for rel in own:
            (project / rel).parent.mkdir(parents=True, exist_ok=True)
            (project / rel).write_text("mine\n", encoding="utf-8")

        self.assertEqual(sandbox.update(project).returncode, 0)

        for rel in own:
            with self.subTest(file=rel):
                self.assertEqual((project / rel).read_text(encoding="utf-8"), "mine\n")

    def test_still_removes_a_file_the_kit_installed_and_no_longer_ships(self) -> None:
        sandbox = Sandbox(self)
        project = sandbox.new("python")
        retired = project / ".claude" / "rules" / "retired-kit-rule.md"
        retired.write_text("old kit rule\n", encoding="utf-8")
        manifest = project / ".claude" / "KIT_FILES"
        manifest.write_text(manifest.read_text(encoding="utf-8") + ".claude/rules/retired-kit-rule.md\n", encoding="utf-8")

        self.assertEqual(sandbox.update(project).returncode, 0)

        self.assertFalse(retired.exists())
        self.assertTrue((project / ".claude" / "rules" / "secrets.md").is_file())


class TheSettingsMerge(unittest.TestCase):
    """The merge spelled a scalar permission setting as a list of letters and dropped project hooks."""

    def test_keeps_scalar_settings_and_project_hooks_and_does_not_duplicate_kit_hooks(self) -> None:
        sandbox = Sandbox(self)
        project = sandbox.new("python")
        path = project / ".claude" / "settings.json"
        settings = json.loads(path.read_text(encoding="utf-8"))
        settings["permissions"]["defaultMode"] = "acceptEdits"
        settings["permissions"]["additionalDirectories"] = ["../shared"]
        session_start = {"hooks": [{"type": "command", "command": "echo hello"}]}
        project_guard = {"matcher": "Bash", "hooks": [{"type": "command", "command": "bash .claude/hooks/my-guard.sh"}]}
        settings["hooks"]["SessionStart"] = [session_start]
        settings["hooks"]["PreToolUse"].append(project_guard)
        path.write_text(json.dumps(settings), encoding="utf-8")

        for _ in range(2):
            self.assertEqual(sandbox.update(project).returncode, 0)

        merged = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(merged["permissions"]["defaultMode"], "acceptEdits")
        self.assertEqual(merged["permissions"]["additionalDirectories"], ["../shared"])
        self.assertEqual(merged["hooks"]["SessionStart"], [session_start])
        pre = merged["hooks"]["PreToolUse"]
        self.assertEqual(pre.count(project_guard), 1)
        kit_git_guard = [e for e in pre if any("block-dangerous-git.sh" in h["command"] for h in e["hooks"])]
        self.assertEqual(len(kit_git_guard), 1)


class AGitPack(unittest.TestCase):
    """The pack cache was keyed on the repo's name alone and refreshed with a fast-forward-only pull."""

    def test_two_packs_with_the_same_repo_name_stay_apart(self) -> None:
        sandbox = Sandbox(self)
        url_a = sandbox.pack("orgA/design", "Rule from orgA")
        url_b = sandbox.pack("orgB/design", "Rule from orgB")
        project_a = sandbox.new("python", "proj-a")
        project_b = sandbox.new("python", "proj-b")
        set_kit_json(project_a, design={"pack": url_a, "exempt": []})
        set_kit_json(project_b, design={"pack": url_b, "exempt": []})

        self.assertEqual(sandbox.update(project_a).returncode, 0)
        self.assertEqual(sandbox.update(project_b).returncode, 0)

        rule = (project_b / ".claude" / "rules" / "design-system.md").read_text(encoding="utf-8")
        self.assertIn("Rule from orgB", rule)

    def test_follows_a_pack_whose_history_was_rewritten(self) -> None:
        sandbox = Sandbox(self)
        url = sandbox.pack("org/design", "First wording")
        project = sandbox.new("python")
        set_kit_json(project, design={"pack": url, "exempt": []})
        self.assertEqual(sandbox.update(project).returncode, 0)

        repo = sandbox.root / "org" / "design"
        (repo / "design-system.md").write_text("Rewritten wording\n", encoding="utf-8")
        git(repo, "commit", "-q", "-a", "--amend", "-m", "pack, amended")

        result = sandbox.update(project)
        self.assertEqual(result.returncode, 0, result.stderr)
        rule = (project / ".claude" / "rules" / "design-system.md").read_text(encoding="utf-8")
        self.assertIn("Rewritten wording", rule)


class AFailingUpdate(unittest.TestCase):
    """Bad input used to be found after kit-owned files were already deleted or overwritten."""

    def assert_refused_untouched(self, sandbox: Sandbox, project: Path) -> subprocess.CompletedProcess[str]:
        before = snapshot(project)
        result = sandbox.update(project)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(snapshot(project), before)
        self.assertTrue(result.stderr.strip(), "a refusal must say why")
        return result

    def test_refuses_an_unknown_profile_before_changing_anything(self) -> None:
        sandbox = Sandbox(self)
        project = sandbox.new("python")
        set_kit_json(project, packages=[{"profile": "rust", "path": "."}])
        self.assertIn("rust", self.assert_refused_untouched(sandbox, project).stderr)

    def test_refuses_a_package_path_that_does_not_exist(self) -> None:
        sandbox = Sandbox(self)
        project = sandbox.new("python")
        set_kit_json(project, packages=[{"profile": "python", "path": "wrokers/agnet"}])
        self.assertIn("wrokers/agnet", self.assert_refused_untouched(sandbox, project).stderr)
        self.assertFalse((project / "wrokers").exists())

    def test_refuses_a_missing_pack_before_changing_anything(self) -> None:
        sandbox = Sandbox(self)
        project = sandbox.new("python")
        # A branded project first, so that a premature reset to the kit's neutral files would show.
        pack = sandbox.root / "good-pack"
        pack.mkdir()
        (pack / "brand.css").write_text(":root { --brand-primary: #123456; }\n", encoding="utf-8")
        (pack / "design-system.md").write_text("Branded rule\n", encoding="utf-8")
        set_kit_json(project, design={"pack": "../good-pack", "exempt": []})
        self.assertEqual(sandbox.update(project).returncode, 0)

        set_kit_json(project, design={"pack": "../no-such-pack", "exempt": []})
        self.assertIn("no-such-pack", self.assert_refused_untouched(sandbox, project).stderr)


if __name__ == "__main__":
    unittest.main()
