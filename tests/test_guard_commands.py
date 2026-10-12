"""The git safety hook reads a command as shell words, not as text.

Until v0.3.2 it matched raw text with regular expressions: ordinary spellings of a destructive
command walked past it (`git push -uf`, `git -c x=y reset --hard`, `rm -rf ~/`), and words that
only mentioned one were blocked (a branch called `feat/seat-inventory` read as `rebase -i`, a
`grep` for "git reset --hard"). Every case below was found in the 2026-10-11 review.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import unittest

from test_block_dangerous_git import HookCase, git, make_repo, posix


class DestructiveSpellingsAreBlocked(HookCase):
    def test_each_spelling_is_blocked(self) -> None:
        project = self.project("feat/x")
        for command, saying in [
            ("git push -uf origin feat/x", "force push"),
            ("git push origin +feat/x", "force push"),
            ("git push --force-with-lease origin feat/x", "force push"),
            ("git push origin :main", "deleting main"),
            ("git push origin --delete main", "deleting main"),
            ("git push origin -d main", "deleting main"),
            ("git branch -D master", "deleting master"),
            ("git branch --delete --force main", "deleting main"),
            ("git -c x=y reset --hard", "git reset --hard"),
            ("git --no-pager reset --hard", "git reset --hard"),
            ("git reset -q --hard", "git reset --hard"),
            ("git checkout .", "discarding all working changes"),
            ("git restore .", "discarding all working changes"),
            ("git clean -d -f", "git clean -f"),
            ("git clean --force", "git clean -f"),
            ("git rebase -ir HEAD~3", "interactive rebase"),
            ("rm -rf ~/", "recursive delete"),
            ("rm -rf $HOME/", "recursive delete"),
            ("rm -rf ../", "recursive delete"),
            ("rm -r -f ~", "recursive delete"),
            ("rm --recursive --force /", "recursive delete"),
        ]:
            with self.subTest(command=command):
                self.assert_blocked(self.run_hook(command, cwd=project), saying)


class MentionsAreNotCommands(HookCase):
    def test_each_harmless_command_passes(self) -> None:
        project = self.project("feat/x")
        for command in [
            "git rebase origin/main && git push -u origin feat/seat-inventory",
            "git checkout -- ./src/file.ts",
            "git push origin --delete main-backup",
            "grep 'git reset --hard' docs/notes.md",
            "echo 'never run git push --force'",
            "cat > notes.md <<'EOF'\nnever run git reset --hard or git clean -fd\nEOF",
            "git restore --staged .",
            "git clean -n -f",
            "rm -rf ./build",
            "rm -rf ../sibling/build",
            'echo "café → 🎉"',
        ]:
            with self.subTest(command=command):
                self.assert_allowed(self.run_hook(command, cwd=project))


class CommitsInEveryShellShapeAreJudged(HookCase):
    def test_a_commit_on_main_is_found_in_every_shape(self) -> None:
        project = self.project("main")
        for command in [
            "cat <<'EOF' | git commit -F -\nmessage\nEOF",
            "python - <<'EOF' && git commit -am x\nprint(1)\nEOF",
            "for i in 1; do git commit -am x; done",
            "if true; then git commit -am x; fi",
            "! git commit -am x",
            "env GIT_EDITOR=true git commit -am x",
            "nice -n 5 git commit -am x",
            "sh -c 'git commit -am x'",
            'bash -c "git commit -am x"',
            "eval git commit -am x",
            "git switch -c feat/x && git switch - && git commit -am x",
        ]:
            with self.subTest(command=command):
                self.assert_blocked(self.run_hook(command, cwd=project), "committing directly to main")

    def test_a_git_alias_for_commit_is_judged(self) -> None:
        project = self.project("main")
        git(project, "config", "alias.ci", "commit")
        self.assert_blocked(self.run_hook("git ci -am x", cwd=project), "committing directly to main")

    def test_a_cd_inside_a_subshell_does_not_leak_out(self) -> None:
        project = self.project("main")
        sibling = make_repo(self.tmp / "pack", "feat/y")
        self.assert_blocked(
            self.run_hook(f"(cd {posix(sibling)} && git status) && git commit -am x", cwd=project),
            "committing directly to main",
        )

    def test_a_cd_into_a_feature_branch_repo_inside_sh_c_is_followed(self) -> None:
        project = self.project("main")
        sibling = make_repo(self.tmp / "pack", "feat/y")
        self.assert_allowed(self.run_hook(f"sh -c 'cd {posix(sibling)} && git commit -am x'", cwd=project))


if __name__ == "__main__":
    unittest.main()
