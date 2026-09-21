"""Tests for core/.claude/hooks/block-dangerous-git.sh and the path handling in lib.sh.

The hook is a bash script that reads a PreToolUse payload on stdin and exits 2 to block. These
tests build throwaway git repositories, install the kit's hooks into one of them the way
new-project.sh does (a copy under .claude/hooks), and run the hook exactly as settings.json
does: `bash .claude/hooks/block-dangerous-git.sh`, a relative path, from a working directory.

Standard library only, so the kit needs nothing installed to test itself:

    python -m unittest discover -s tests -v

Issue #5 is why this file exists. Each class below is one of its three defects, plus a class
that pins the blocks that must never loosen.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
HOOKS = KIT / "core" / ".claude" / "hooks"
HOOK_RELATIVE = ".claude/hooks/block-dangerous-git.sh"
BLOCKED = 2
ALLOWED = 0


def git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def make_repo(path: Path, branch: str) -> Path:
    """A repository with one commit, checked out on `branch`."""
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    (path / "README.md").write_text("x\n", encoding="utf-8")
    git(path, "add", ".")
    git(path, "commit", "-q", "-m", "first")
    if branch != "main":
        git(path, "checkout", "-q", "-b", branch)
    return path


def posix(path: Path) -> str:
    """The path as a bash command would spell it (forward slashes work in Git Bash too)."""
    return path.as_posix()


class HookCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="kit-hook-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def project(self, branch: str = "main", *, with_hooks: bool = True) -> Path:
        root = make_repo(self.tmp / "project", branch)
        if with_hooks:
            shutil.copytree(HOOKS, root / ".claude" / "hooks")
        return root

    def run_hook(
        self, command: str, *, cwd: Path, project_dir: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir or cwd)}
        return subprocess.run(
            ["bash", HOOK_RELATIVE],
            input=json.dumps({"tool_input": {"command": command}}),
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def assert_allowed(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, ALLOWED, result.stderr)

    def assert_blocked(self, result: subprocess.CompletedProcess[str], saying: str) -> None:
        self.assertEqual(result.returncode, BLOCKED, result.stderr)
        self.assertIn(saying, result.stderr)


class TheCommitIsJudgedInTheRepoItTargets(HookCase):
    """Defect 1: the branch was read in the session's project, whatever the command aimed at."""

    def test_cd_into_a_sibling_on_a_feature_branch_is_allowed(self) -> None:
        project = self.project("main")
        sibling = make_repo(self.tmp / "pack", "docs/email-rule")
        result = self.run_hook(
            f'cd {posix(sibling)} && git add README.md && git commit -m "x"', cwd=project
        )
        self.assert_allowed(result)

    def test_git_dash_c_into_a_sibling_on_a_feature_branch_is_allowed(self) -> None:
        project = self.project("main")
        sibling = make_repo(self.tmp / "pack", "docs/email-rule")
        self.assert_allowed(
            self.run_hook(f'git -C {posix(sibling)} commit -am "x"', cwd=project)
        )

    def test_a_quoted_path_with_a_space_is_followed(self) -> None:
        project = self.project("main")
        sibling = make_repo(self.tmp / "design pack", "docs/email-rule")
        self.assert_allowed(
            self.run_hook(f'git -C "{posix(sibling)}" commit -am "x"', cwd=project)
        )

    def test_a_sibling_that_is_itself_on_main_is_blocked(self) -> None:
        project = self.project("feat/something")
        sibling = make_repo(self.tmp / "pack", "main")
        self.assert_blocked(
            self.run_hook(f'cd {posix(sibling)} && git commit -am "x"', cwd=project),
            "committing directly to main",
        )
        self.assert_blocked(
            self.run_hook(f'git -C {posix(sibling)} commit -am "x"', cwd=project),
            "committing directly to main",
        )

    def test_the_project_on_main_is_still_blocked(self) -> None:
        project = self.project("main")
        self.assert_blocked(
            self.run_hook('git commit -am "x"', cwd=project), "committing directly to main"
        )

    def test_options_between_git_and_commit_do_not_hide_the_commit(self) -> None:
        # Found while writing these tests: the old pattern wanted the two words side by
        # side, so any global option between them walked past the protected-branch check.
        project = self.project("main")
        for command in [
            'git -C . commit -am "x"',
            'git -c user.name=x commit -am "x"',
            'git --no-pager commit -am "x"',
            'FOO=bar git commit -am "x"',
        ]:
            with self.subTest(command=command):
                self.assert_blocked(
                    self.run_hook(command, cwd=project), "committing directly to main"
                )

    def test_words_that_only_mention_a_commit_are_not_one(self) -> None:
        project = self.project("main")
        for command in [
            'git log --grep "git commit"',
            'echo "then run git commit"',
            "git commit-graph verify",
            "python - <<'EOF'\nprint('git commit -am x')\nEOF",
        ]:
            with self.subTest(command=command):
                self.assert_allowed(self.run_hook(command, cwd=project))

    def test_a_target_that_does_not_exist_falls_back_to_the_project(self) -> None:
        # Unknown target: keep today's answer rather than guess. On main that is a block.
        project = self.project("main")
        self.assert_blocked(
            self.run_hook('cd /no/such/dir && git commit -am "x"', cwd=project),
            "committing directly to main",
        )


class TheCommitIsJudgedOnTheBranchItWillLandOn(HookCase):
    """Defect 2: HEAD was read before the command ran, so checkout-then-commit was blocked."""

    def test_checkout_dash_b_then_commit_is_allowed(self) -> None:
        project = self.project("main")
        self.assert_allowed(
            self.run_hook('git checkout -q -b feat/x && git commit -am "x"', cwd=project)
        )

    def test_checkout_of_an_existing_branch_then_commit_is_allowed(self) -> None:
        project = self.project("main")
        git(project, "branch", "docs/plan")
        self.assert_allowed(
            self.run_hook(
                'git checkout -q docs/plan && python edit.py && git add f && git commit -m "x"',
                cwd=project,
            )
        )

    def test_switch_dash_c_then_commit_is_allowed(self) -> None:
        project = self.project("main")
        self.assert_allowed(
            self.run_hook('git switch -c feat/x && git commit -am "x"', cwd=project)
        )

    def test_checkout_main_then_commit_from_a_feature_branch_is_blocked(self) -> None:
        project = self.project("feat/x")
        self.assert_blocked(
            self.run_hook('git checkout main && git commit -am "x"', cwd=project),
            "committing directly to main",
        )

    def test_a_checkout_after_the_commit_does_not_excuse_it(self) -> None:
        project = self.project("main")
        self.assert_blocked(
            self.run_hook('git commit -am "x" && git checkout -b feat/x', cwd=project),
            "committing directly to main",
        )

    def test_checking_out_a_name_that_is_no_branch_excuses_nothing(self) -> None:
        # `git checkout README.md` restores a file; it does not move HEAD off main.
        project = self.project("main")
        self.assert_blocked(
            self.run_hook('git checkout README.md && git commit -am "x"', cwd=project),
            "committing directly to main",
        )

    def test_checking_out_a_file_is_not_a_branch_switch(self) -> None:
        project = self.project("main")
        self.assert_blocked(
            self.run_hook('git checkout -- README.md && git commit -am "x"', cwd=project),
            "committing directly to main",
        )


class TheHookFindsItsOwnFiles(HookCase):
    """Defect 3: lib.sh resolved its own directory after changing directory, and lost it."""

    def test_project_dir_elsewhere_with_no_dot_claude_still_parses_input(self) -> None:
        # The session's working directory has the hooks; CLAUDE_PROJECT_DIR points at a
        # directory that does not (a removed worktree). The hook must still read its input
        # and let a harmless command through, not block every Bash call.
        here = self.project("feat/x")
        gone = self.tmp / "removed-worktree"
        gone.mkdir()
        result = self.run_hook("ls", cwd=here, project_dir=gone)
        self.assert_allowed(result)
        self.assertNotIn("could not parse", result.stderr)

    def test_it_still_blocks_from_there(self) -> None:
        here = self.project("feat/x")
        gone = self.tmp / "removed-worktree"
        gone.mkdir()
        self.assert_blocked(
            self.run_hook("git reset --hard HEAD~1", cwd=here, project_dir=gone),
            "git reset --hard",
        )


class TheBlocksThatMustNotLoosen(HookCase):
    def test_each_destructive_command_is_still_blocked(self) -> None:
        project = self.project("feat/x")
        for command, saying in [
            ("git push --force origin feat/x", "force push"),
            ("git push -f", "force push"),
            ("git reset --hard origin/main", "git reset --hard"),
            ("git clean -fd", "git clean -f"),
            ("git checkout -- .", "discarding all working changes"),
            ("git rebase -i HEAD~3", "interactive rebase"),
            ("git branch -D main", "deleting main"),
            ("rm -rf ~", "recursive delete"),
        ]:
            with self.subTest(command=command):
                self.assert_blocked(self.run_hook(command, cwd=project), saying)

    def test_ordinary_commands_pass(self) -> None:
        project = self.project("feat/x")
        for command in ["ls", "git status", "git push -u origin feat/x", 'git commit -am "x"']:
            with self.subTest(command=command):
                self.assert_allowed(self.run_hook(command, cwd=project))

    def test_a_custom_protected_branch_is_honoured_in_the_target_repo(self) -> None:
        project = self.project("main")
        (project / ".claude" / "kit.json").write_text(
            json.dumps({"protected_branches": ["main", "release"]}), encoding="utf-8"
        )
        sibling = make_repo(self.tmp / "pack", "release")
        self.assert_blocked(
            self.run_hook(f'git -C {posix(sibling)} commit -am "x"', cwd=project),
            "committing directly to release",
        )


if __name__ == "__main__":
    unittest.main()
