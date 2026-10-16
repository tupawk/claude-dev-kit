"""A commit is judged by the branch checked out where the command runs, worktrees included.

Claude Code runs hooks in the project directory but runs the Bash command in the session's own
working directory, and reports that one as the payload's `cwd`. A session that works in a git
worktree (the desktop app puts one under `.claude/worktrees/`) has the primary checkout, usually
on `main`, as its project. Until v0.3.2 the hook started every judgement from the project, so on
2026-10-12 both of these were refused as "committing directly to main" in a worktree that was not
on main: `cd <worktree> && git commit -F - <<EOF` on a detached HEAD, and a plain `git commit`
right after `git switch -c fix/operations-studio-date` there.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
from pathlib import Path

from test_block_dangerous_git import HookCase, git, posix

HEREDOC_COMMIT = "git commit -F - <<'EOF'\nfix: x\n\nbody\nEOF"
UNKNOWN = "could not work out which branch"


class WorktreeCase(HookCase):
    def worktree(self, project: Path, name: str, *options: str, branch: str = "") -> Path:
        """A worktree of `project` where the desktop app puts them, with `worktree add` options."""
        path = project / ".claude" / "worktrees" / name
        git(project, "worktree", "add", "-q", *options, str(path), *([branch] if branch else []))
        return path

    def shapes(self, project: Path, tree: Path) -> list[tuple[str, str, Path]]:
        """(label, command, Bash cwd): every way the commits of 2026-10-12 reached that worktree."""
        return [
            ("commit with the worktree as cwd", 'git add README.md && git commit -m "x"', tree),
            ("heredoc commit with the worktree as cwd", HEREDOC_COMMIT, tree),
            ("cd from the project", f'cd {posix(tree)} && git add README.md && git commit -m "x"', project),
            ("cd to a native path from the project", f'cd "{tree}" && {HEREDOC_COMMIT}', project),
            ("git -C from the project", f'git -C {posix(tree)} commit -am "x"', project),
            ("cd into itself", f"cd {posix(tree)} && {HEREDOC_COMMIT}", tree),
        ]

    def assert_each_shape(self, project: Path, tree: Path, *, blocked_saying: str = "") -> None:
        for label, command, bash_cwd in self.shapes(project, tree):
            with self.subTest(label):
                result = self.run_hook(command, cwd=project, bash_cwd=bash_cwd)
                if blocked_saying:
                    self.assert_blocked(result, blocked_saying)
                else:
                    self.assert_allowed(result)


class AWorktreeIsJudgedByItsOwnBranch(WorktreeCase):
    def test_a_worktree_on_a_feature_branch_is_allowed_while_the_project_is_on_main(self) -> None:
        project = self.project("main")
        tree = self.worktree(project, "feature", "-b", "feat/x")
        self.assert_each_shape(project, tree)

    def test_a_worktree_on_main_is_blocked_while_the_project_is_on_a_feature_branch(self) -> None:
        project = self.project("feat/p")
        tree = self.worktree(project, "on-main", branch="main")
        self.assert_each_shape(project, tree, blocked_saying="committing directly to main")

    def test_a_worktree_on_a_detached_head_is_allowed(self) -> None:
        project = self.project("main")
        tree = self.worktree(project, "detached", "--detach")
        self.assert_each_shape(project, tree)

    def test_the_project_on_main_is_still_blocked_when_the_command_runs_there(self) -> None:
        project = self.project("main")
        self.assert_blocked(
            self.run_hook('git commit -am "x"', cwd=project, bash_cwd=project),
            "committing directly to main",
        )

    def test_a_checkout_in_the_worktree_decides_the_branch_there(self) -> None:
        # Allowed as it stands (detached); moved onto main by the command itself, it is refused.
        project = self.project("feat/p")
        tree = self.worktree(project, "detached", "--detach")
        self.assert_blocked(
            self.run_hook(f"git checkout main && {HEREDOC_COMMIT}", cwd=project, bash_cwd=tree),
            "committing directly to main",
        )


class RelativePathsStartWhereTheCommandRuns(WorktreeCase):
    def test_a_relative_cd_or_dash_c_is_resolved_from_the_bash_cwd(self) -> None:
        # From the project, ../feature names nothing; from a sibling worktree it is the
        # feature worktree, and ../on-main is the one on main.
        project = self.project("feat/p")
        here = self.worktree(project, "here", "-b", "feat/here")
        self.worktree(project, "feature", "-b", "feat/x")
        self.worktree(project, "on-main", branch="main")
        for command in ('cd ../feature && git commit -am "x"', 'git -C ../feature commit -am "x"'):
            with self.subTest(command):
                self.assert_allowed(self.run_hook(command, cwd=project, bash_cwd=here))
        for command in ('cd ../on-main && git commit -am "x"', 'git -C ../on-main commit -am "x"'):
            with self.subTest(command):
                self.assert_blocked(
                    self.run_hook(command, cwd=project, bash_cwd=here), "committing directly to main"
                )


class AnUnknownTargetIsRefused(WorktreeCase):
    """Where the commit lands cannot be worked out: block, whatever branch the project is on."""

    def test_each_unknowable_target_is_refused(self) -> None:
        project = self.project("feat/p")
        not_a_repo = self.tmp / "plain"
        not_a_repo.mkdir()
        gone = self.tmp / "removed-worktree"
        for label, command, bash_cwd in [
            ("the Bash cwd no longer exists", 'git commit -am "x"', gone),
            ("the Bash cwd is no repository", 'git commit -am "x"', not_a_repo),
            ("git -C a directory that does not exist", 'git -C /no/such/dir commit -am "x"', project),
            ("a relative cd from a cwd that does not exist", 'cd .. && git commit -am "x"', gone),
            ("cd - goes somewhere unnamed", 'cd - && git commit -am "x"', project),
            ("a variable this cannot expand", 'cd "$TREE" && git commit -am "x"', project),
            ("popd with nothing pushed", 'popd && git commit -am "x"', project),
            ("pushd alone swaps the stack", 'pushd && git commit -am "x"', project),
            ("pushd +1 turns the stack", 'pushd +1 && git commit -am "x"', project),
            ("another git directory", f'git --git-dir={posix(project)}/.git commit -am "x"', project),
            ("another work tree", f'git --work-tree {posix(project)} commit -am "x"', project),
            ("--git-dir before a -C", f'git --git-dir={posix(project)}/.git -C {posix(project)} commit -am x', project),
            ("GIT_DIR in front of git", f'GIT_DIR={posix(project)}/.git git commit -am "x"', project),
            ("GIT_WORK_TREE through env", f'env GIT_WORK_TREE={posix(project)} git commit -am "x"', project),
            ("GIT_DIR exported", f'export GIT_DIR={posix(project)}/.git; git commit -am "x"', project),
            ("env -C runs git elsewhere", f'env -C {posix(project)} git commit -am "x"', project),
            ("pushd -n does not move", f'pushd -n {posix(project)} && git commit -am "x"', project),
            ("a checkout this cannot place", 'git -C "$PWD" checkout main && git commit -am "x"', project),
        ]:
            with self.subTest(label):
                self.assert_blocked(self.run_hook(command, cwd=project, bash_cwd=bash_cwd), UNKNOWN)

    def test_a_literal_path_still_works_when_the_bash_cwd_is_gone(self) -> None:
        # What the refusal tells Claude to do has to work: a rooted path needs no starting point.
        project = self.project("main")
        tree = self.worktree(project, "feature", "-b", "feat/x")
        gone = self.tmp / "removed-worktree"
        for command in (f'git -C {posix(tree)} commit -am "x"', f'cd {posix(tree)} && git commit -am "x"'):
            with self.subTest(command):
                self.assert_allowed(self.run_hook(command, cwd=project, bash_cwd=gone))

    def test_a_command_with_no_commit_is_not_refused_for_an_unknown_target(self) -> None:
        project = self.project("feat/p")
        self.assert_allowed(
            self.run_hook("cd /no/such/dir && git status", cwd=project, bash_cwd=self.tmp / "gone")
        )

    def test_an_empty_protected_list_turns_the_check_off_unknown_targets_included(self) -> None:
        project = self.project("main")
        (project / ".claude" / "kit.json").write_text(
            json.dumps({"protected_branches": []}), encoding="utf-8"
        )
        self.assert_allowed(
            self.run_hook('cd /no/such/dir && git commit -am "x"', cwd=project, bash_cwd=project)
        )

    def test_a_cwd_that_is_not_text_is_bad_input(self) -> None:
        project = self.project("feat/p")
        self.assert_blocked(
            self.run_payload({"cwd": 7, "tool_input": {"command": "ls"}}, cwd=project),
            "could not parse",
        )


class ACommandThatCannotBeReadIsJudgedWhereItRuns(WorktreeCase):
    """A broken quote stops shlex but not bash, which still runs the lines before it. Each line is
    judged on its own, from the directory the command runs in."""

    COMMIT_THEN_BROKEN_QUOTE = 'git commit -am "x"\necho "unterminated'

    def test_the_lines_before_a_broken_quote_are_judged_by_the_bash_cwd(self) -> None:
        project = self.project("main")
        tree = self.worktree(project, "feature", "-b", "feat/x")
        self.assert_allowed(self.run_hook(self.COMMIT_THEN_BROKEN_QUOTE, cwd=project, bash_cwd=tree))
        self.assert_blocked(
            self.run_hook(self.COMMIT_THEN_BROKEN_QUOTE, cwd=project, bash_cwd=project),
            "committing directly to main",
        )
