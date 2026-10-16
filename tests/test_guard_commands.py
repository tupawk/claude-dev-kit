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


class WhatTheShellRunsIsRead(HookCase):
    """Found by the adversarial review of the rewrite: forms the first parser did not read as commands."""

    def test_comments_hide_nothing_after_them(self) -> None:
        project = self.project("feat/x")
        for command, saying in [
            ("# push the branch\ngit push --force", "force push"),
            ("ls\n# now force\ngit push -f origin feat/x", "force push"),
            ("echo ${#x}; git reset --hard", "git reset --hard"),
            ("n=$#; git reset --hard", "git reset --hard"),
            ("curl https://x.test/a#frag && git push --force", "force push"),
        ]:
            with self.subTest(command=command):
                self.assert_blocked(self.run_hook(command, cwd=project), saying)

    def test_a_commit_after_a_comment_is_judged(self) -> None:
        project = self.project("main")
        self.assert_blocked(self.run_hook("git status # check\ngit commit -m x", cwd=project), "committing directly to main")

    def test_substitutions_and_text_fed_to_a_shell_are_read(self) -> None:
        project = self.project("feat/x")
        for command, saying in [
            ("echo `git push --force`", "force push"),
            ("diff <(git show HEAD:a) <(git reset --hard)", "git reset --hard"),
            ('echo "$(git reset --hard)"', "git reset --hard"),
            ('echo "git push --force" | sh', "force push"),
            ('bash <<<"git push --force"', "force push"),
            ("sh <<'EOF'\ngit push --force\nEOF", "force push"),
            ('echo "x <<EOF"\ngit reset --hard\nEOF', "git reset --hard"),
            ('cat <<< "a"\ngit push --force\na', "force push"),
        ]:
            with self.subTest(command=command):
                self.assert_blocked(self.run_hook(command, cwd=project), saying)

    def test_an_unreadable_command_still_has_its_deletes_checked(self) -> None:
        project = self.project("feat/x")
        for command in [
            'git push origin --delete main\necho "unterminated',
            "git branch -D main\necho 'x",
            "echo $'it\\'s'; git branch -D main",
        ]:
            with self.subTest(command=command):
                self.assert_blocked(self.run_hook(command, cwd=project), "deleting main")

    def test_nesting_too_deep_to_follow_is_refused(self) -> None:
        project = self.project("feat/x")
        for command in ["eval eval eval eval eval git push --force", "bash -c -- 'git reset --hard'"]:
            with self.subTest(command=command):
                result = self.run_hook(command, cwd=project)
                self.assertEqual(result.returncode, 2, result.stderr)

    def test_abbreviated_long_options_count(self) -> None:
        project = self.project("feat/x")
        for command, saying in [
            ("git reset --har", "git reset --hard"),
            ("git branch --del main", "deleting main"),
            ("git push --del origin main", "deleting main"),
            ("git clean --forc", "git clean -f"),
            ("git push --force-w origin feat/x", "force push"),
            ("git rebase --interac main", "interactive rebase"),
            ("git push --mirror backup", "force push"),
        ]:
            with self.subTest(command=command):
                self.assert_blocked(self.run_hook(command, cwd=project), saying)

    def test_an_alias_defined_in_the_same_command_is_read(self) -> None:
        project = self.project("feat/x")
        for command in ["git -c alias.zz='push --force' zz", "git config alias.yy 'push --force' && git yy"]:
            with self.subTest(command=command):
                self.assert_blocked(self.run_hook(command, cwd=project), "force push")

    def test_popd_returns_to_the_project(self) -> None:
        project = self.project("main")
        sibling = make_repo(self.tmp / "pack", "feat/y")
        self.assert_blocked(
            self.run_hook(f"pushd {posix(sibling)} && popd && git commit -am x", cwd=project),
            "committing directly to main",
        )


class TheSecondReviewsCases(HookCase):
    """Found by the second adversarial review: each was blocked by the old text hook or is a plain bypass."""

    def test_each_is_blocked(self) -> None:
        project = self.project("feat/x")
        for command in [
            # a '#' glued to an escape or a substitution is not a comment
            "echo a\\ #; git reset --hard",
            "echo \\;# ; git reset --hard",
            "echo $(true)#; git reset --hard",
            # an unquoted heredoc runs its substitutions
            "cat <<EOF\n$(git reset --hard)\nEOF",
            "cat <<EOF\n`git reset --hard`\nEOF",
            # a heredoc inside $(...), and output that becomes code
            "x=\"$(cat <<'EOF'\ndon't\nEOF\ngit reset --hard\n)\"",
            "eval \"$(cat <<'EOF'\ngit reset --hard\nEOF\n)\"",
            "bash -c \"$(cat <<'EOF'\ngit reset --hard\nEOF\n)\"",
            # text piped to a shell, without a quoted string
            "echo git reset --hard | bash",
            "echo git push -f origin x | sh",
            "echo git reset --hard | bash -s foo",
            "echo git reset --hard | bash -o errexit",
            # ANSI-C strings and here-string words
            "echo $'\\'' ; git push -uf origin x",
            "echo $'\\'' ; rm -rf ~/",
            "bash <<< $'git push -uf origin x'",
            "cat <<< a'b c' ; git checkout .",
            "bash <<<git\\ reset\\ --hard",
            # heredoc edge cases
            "cat <<EOF-X\nEOF-X\ngit reset --hard\nEOF",
            "(( x = 1 << y ))\ngit reset --hard",
            "cat <<EOF |\ngit reset --hard\nEOF\nbash",
            ". /dev/stdin <<'EOF'\ngit reset --hard\nEOF",
            "source /dev/stdin <<< 'git reset --hard'",
            # commands that run commands
            "find . -exec git reset --hard \\;",
            'git submodule foreach "git reset --hard"',
            "git rebase -x 'git reset --hard' main",
            "winpty git push -f origin x",
            "stdbuf -oL git push -f origin x",
            "setsid git reset --hard",
            "python -c \"import os; os.system('git push -f origin x')\"",
            # short long-option prefixes git and rm accept
            "git reset --ha",
            "git clean --fo",
            "git push --de origin main",
            "rm --r ~",
            # a command name computed at run time
            "$(echo git) push -f origin x",
        ]:
            with self.subTest(command=command):
                result = self.run_hook(command, cwd=project)
                self.assertEqual(result.returncode, 2, f"allowed: {command!r}\n{result.stderr}")

    def test_everyday_commands_with_awkward_prose_pass(self) -> None:
        project = self.project("feat/x")
        for command in [
            "gh pr create --title t --body \"$(cat <<'EOF'\n## Summary\nJulie's page: don't run `git push --force`.\n1) step one\nEOF\n)\"",
            "git commit -m \"$(cat <<'EOF'\nfix: Julie's form (1) don't reset --hard\nEOF\n)\"",
            'eval "$(ssh-agent -s)"',
            "$(which python) script.py",
            "python -c \"print('hello')\"",
            "find . -name '*.pyc' -exec rm {} +",
            "git submodule foreach git pull",
            "git rebase -x 'npm test' main",
            "echo foo#bar && git status",
            "bash scripts/build.sh --release",
        ]:
            with self.subTest(command=command):
                self.assert_allowed(self.run_hook(command, cwd=project))

    def test_a_nul_byte_does_not_crash_the_hook(self) -> None:
        project = self.project("feat/x")
        result = self.run_hook("git a\x00b", cwd=project)
        self.assertNotIn("could not parse", result.stderr)

    def test_pathological_commands_finish_quickly(self) -> None:
        import time

        project = self.project("feat/x")
        for shape, command in [
            ("unclosed $(", "echo $(" * 2_000),
            ("nested (", "(" * 50_000 + "ls" + ")" * 50_000),
            ("many commits", "; ".join(["git commit -am x"] * 125)),
            ("many unknown subcommands", "; ".join(f"git zz{k}" for k in range(300))),
            ("one megabyte", "echo " + "a " * 500_000),
        ]:
            with self.subTest(shape=shape):
                start = time.monotonic()
                self.run_hook(command, cwd=project)
                self.assertLess(time.monotonic() - start, 10.0)


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
            "echo 'a # b'; git status",
            "git rebase -Xignore-space-change main",
            "git push -oforce=1 origin feat/x",
            "git push -o ci.skip origin feat/x",
            "gh pr create --title t --body \"$(cat <<'EOF'\nnever git push --force or git reset --hard\nEOF\n)\"",
            "git commit -m \"$(cat <<'EOF'\ndocs: never run git push --force\nEOF\n)\"",
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
        ]:
            with self.subTest(command=command):
                self.assert_blocked(self.run_hook(command, cwd=project), "committing directly to main")

    def test_switching_back_to_an_unnamed_branch_leaves_the_commit_unplaced(self) -> None:
        project = self.project("main")
        self.assert_blocked(
            self.run_hook("git switch -c feat/x && git switch - && git commit -am x", cwd=project),
            "could not work out which branch",
        )

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
