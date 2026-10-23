"""Tests for the Stop hook's test runs: core/.claude/hooks/stop-tests.sh and the python profile's hook.

Every test builds a throwaway project with the kit's hooks installed the way new-project.sh installs
them, and runs the hook the way settings.json does: `bash .claude/hooks/stop-tests.sh` from the project.
pytest is a fake (FAKE_PYTEST below) put first on PYTHONPATH, so the kit still needs nothing installed to
test itself. It logs each call's arguments and does what FAKE_PYTEST_MODE says.

    python -m unittest discover -s tests -v

Each class is one defect seen on 2026-10-23, when a Windows checkout had thirteen full-suite runs
stacked on top of each other, plus what must keep working around it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from test_block_dangerous_git import BASH, git

KIT = Path(__file__).resolve().parent.parent
HOOKS = KIT / "core" / ".claude" / "hooks"
PYTHON_HOOKS = KIT / "profiles" / "python" / ".claude" / "hooks" / "python"
BLOCKED = 2
ALLOWED = 0
LASTFAILED = Path(".pytest_cache") / "v" / "cache" / "lastfailed"

# pass: exit 0. fail: exit 1 with a FAILED line. slow: sleep FAKE_PYTEST_SECONDS, then pass.
# hang: start a grandchild that writes a heartbeat file, then sleep a minute; the budget must kill both.
FAKE_PYTEST = '''
import json, os, subprocess, sys, time
args = sys.argv[1:]
if args == ["--version"]:
    print("pytest 0.0 (fake)")
    sys.exit(0)
with open(os.environ["FAKE_PYTEST_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\\n")
mode = os.environ.get("FAKE_PYTEST_MODE", "pass")
if mode == "fail":
    print("FAILED tests/test_a.py::test_one - assert False")
    sys.exit(1)
if mode == "slow":
    time.sleep(float(os.environ.get("FAKE_PYTEST_SECONDS", "2")))
if mode == "hang":
    beat = os.environ["FAKE_PYTEST_HEARTBEAT"]
    code = "import time\\nwhile True:\\n    open(%r, 'a').write('.')\\n    time.sleep(0.1)" % beat
    subprocess.Popen([sys.executable, "-c", code])
    time.sleep(60)
sys.exit(0)
'''


class StopHookCase(unittest.TestCase):
    """A committed python-profile project with one uncommitted change, so the hook has work to do."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="kit-stop-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        fake = self.tmp / "fake" / "pytest"
        fake.mkdir(parents=True)
        (fake / "__init__.py").write_text("", encoding="utf-8")
        (fake / "__main__.py").write_text(FAKE_PYTEST, encoding="utf-8")
        self.log = self.tmp / "pytest-calls.log"
        self.heartbeat = self.tmp / "heartbeat"
        self.env = {
            **os.environ,
            "PYTHONPATH": str(self.tmp / "fake"),
            "FAKE_PYTEST_LOG": str(self.log),
            "FAKE_PYTEST_HEARTBEAT": str(self.heartbeat),
        }
        for name in ("KIT_TEST_SCOPE", "KIT_STOP_BUDGET"):
            self.env.pop(name, None)

        root = self.root = self.tmp / "project"
        root.mkdir()
        git(root, "init", "-q", "-b", "feature")
        shutil.copytree(HOOKS, root / ".claude" / "hooks")
        shutil.copytree(PYTHON_HOOKS, root / ".claude" / "hooks" / "python")
        (root / ".claude" / "kit.json").write_text(
            json.dumps({"packages": [{"profile": "python", "path": "."}]}), encoding="utf-8"
        )
        (root / "pyproject.toml").write_text("[project]\nname = 'p'\n", encoding="utf-8")
        (root / "tests").mkdir()
        for name in ("test_a.py", "test_b.py"):
            (root / "tests" / name).write_text("def test_one():\n    pass\n", encoding="utf-8")
        git(root, "add", ".")
        git(root, "commit", "-q", "-m", "first")
        self.change()

    def change(self, text: str = "x = 1\n") -> None:
        (self.root / "module.py").write_text(text, encoding="utf-8")

    def record(self, failures: list[str]) -> None:
        """Write pytest's last-failed record the way pytest does, cache .gitignore included."""
        path = self.root / LASTFAILED
        path.parent.mkdir(parents=True, exist_ok=True)
        (self.root / ".pytest_cache" / ".gitignore").write_text("*\n", encoding="utf-8")
        path.write_text(json.dumps({f: True for f in failures}, indent=2), encoding="utf-8")

    def recorded(self) -> list[str]:
        return sorted(json.loads((self.root / LASTFAILED).read_text(encoding="utf-8")))

    def calls(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def start(self, **env: str) -> subprocess.Popen[str]:
        return subprocess.Popen(
            [BASH, ".claude/hooks/stop-tests.sh"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            cwd=self.root, env={**self.env, "CLAUDE_PROJECT_DIR": str(self.root), **env},
        )

    def run_hook(self, **env: str) -> subprocess.CompletedProcess[str]:
        proc = self.start(**env)
        out, err = proc.communicate(json.dumps({"stop_hook_active": False}), timeout=120)
        return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)


class AStaleFailureRecord(StopHookCase):
    """pytest's --lf runs the WHOLE suite when no recorded failure is collected, and a test that is
    never collected is never cleared, so one renamed failing test made every Stop a full run."""

    def test_a_record_of_tests_whose_file_is_gone_runs_nothing_and_is_dropped(self) -> None:
        self.record(["tests/test_gone.py::test_old", "tests/test_also_gone.py"])
        result = self.run_hook()
        self.assertEqual(result.returncode, ALLOWED, result.stderr)
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.recorded(), [])

    def test_only_the_files_that_hold_a_recorded_failure_are_run(self) -> None:
        self.record(["tests/test_a.py::test_renamed_away", "tests/test_gone.py::test_old"])
        result = self.run_hook()
        self.assertEqual(result.returncode, ALLOWED, result.stderr)
        (args,) = self.calls()
        self.assertIn("--lf", args)
        self.assertEqual([a for a in args if not a.startswith("-")], ["tests/test_a.py"])

    def test_a_green_run_clears_the_entries_it_ran_so_they_are_not_run_again(self) -> None:
        self.record(["tests/test_a.py::test_renamed_away"])
        self.run_hook()
        self.assertEqual(self.recorded(), [])
        self.change("x = 2\n")
        self.run_hook()
        self.assertEqual(len(self.calls()), 1)

    def test_a_red_run_still_blocks_and_keeps_the_record(self) -> None:
        self.record(["tests/test_a.py::test_one"])
        result = self.run_hook(FAKE_PYTEST_MODE="fail")
        self.assertEqual(result.returncode, BLOCKED)
        self.assertIn("FAILED tests/test_a.py::test_one", result.stderr)
        self.assertEqual(self.recorded(), ["tests/test_a.py::test_one"])

    def test_an_empty_record_runs_nothing(self) -> None:
        self.record([])
        self.assertEqual(self.run_hook().returncode, ALLOWED)
        self.assertEqual(self.calls(), [])

    def test_no_record_in_the_package_leaves_the_choice_to_pytest(self) -> None:
        """The cache may live elsewhere (a pytest.ini further up); pytest knows where, the hook does not."""
        self.run_hook()
        (args,) = self.calls()
        self.assertEqual(args, ["-q", "-x", "--lf", "--lfnf=none"])

    def test_full_scope_still_runs_the_whole_suite(self) -> None:
        self.record(["tests/test_a.py::test_one"])
        self.run_hook(KIT_TEST_SCOPE="full")
        self.assertEqual(self.calls(), [["-q", "-x"]])


class ARunPastTheBudget(StopHookCase):
    """Claude Code gave up on the hook at its timeout, but pytest and its children kept running."""

    def test_is_stopped_with_its_children_and_reported_as_not_proven(self) -> None:
        began = time.monotonic()
        result = self.run_hook(KIT_TEST_SCOPE="full", KIT_STOP_BUDGET="3", FAKE_PYTEST_MODE="hang")
        self.assertLess(time.monotonic() - began, 30)
        self.assertEqual(result.returncode, BLOCKED)
        self.assertIn("did not finish", result.stderr)
        self.assertNotIn("Tests are failing", result.stderr)
        self.assertTrue(self.heartbeat.exists(), "the grandchild never started")
        size = self.heartbeat.stat().st_size
        time.sleep(1.5)
        self.assertEqual(self.heartbeat.stat().st_size, size, "the grandchild is still running")

    def test_a_run_inside_the_budget_is_untouched(self) -> None:
        result = self.run_hook(KIT_TEST_SCOPE="full", KIT_STOP_BUDGET="30", FAKE_PYTEST_MODE="slow",
                               FAKE_PYTEST_SECONDS="1")
        self.assertEqual(result.returncode, ALLOWED, result.stderr)


class TheSameTreeTestedAgain(StopHookCase):
    """Every session in a checkout ran its own suite on every turn end, reviewers that edit nothing included."""

    def test_a_tree_already_proven_green_is_not_tested_again(self) -> None:
        self.assertEqual(self.run_hook(KIT_TEST_SCOPE="full").returncode, ALLOWED)
        self.assertEqual(self.run_hook(KIT_TEST_SCOPE="full").returncode, ALLOWED)
        self.assertEqual(len(self.calls()), 1)

    def test_a_changed_tracked_file_is_tested_again(self) -> None:
        self.run_hook(KIT_TEST_SCOPE="full")
        (self.root / "tests" / "test_b.py").write_text("def test_two():\n    pass\n", encoding="utf-8")
        self.run_hook(KIT_TEST_SCOPE="full")
        self.assertEqual(len(self.calls()), 2)

    def test_a_changed_untracked_file_is_tested_again(self) -> None:
        self.run_hook(KIT_TEST_SCOPE="full")
        (self.root / "module.py").write_text("x = 3\n", encoding="utf-8")
        self.run_hook(KIT_TEST_SCOPE="full")
        self.assertEqual(len(self.calls()), 2)

    def test_a_red_tree_is_never_recorded_as_proven(self) -> None:
        self.run_hook(KIT_TEST_SCOPE="full", FAKE_PYTEST_MODE="fail")
        result = self.run_hook(KIT_TEST_SCOPE="full", FAKE_PYTEST_MODE="fail")
        self.assertEqual(result.returncode, BLOCKED)
        self.assertEqual(len(self.calls()), 2)

    def test_a_proof_in_one_scope_does_not_count_for_another(self) -> None:
        self.run_hook()
        self.run_hook(KIT_TEST_SCOPE="full")
        self.assertEqual(self.calls()[-1], ["-q", "-x"])

    def test_a_failure_recorded_since_the_proof_is_tested_again(self) -> None:
        """A manual pytest run on the same tree can record a failure the proof never saw."""
        self.record([])
        self.run_hook()
        self.record(["tests/test_a.py::test_one"])
        result = self.run_hook(FAKE_PYTEST_MODE="fail")
        self.assertEqual(result.returncode, BLOCKED)

    def test_a_second_hook_on_the_same_tree_waits_for_the_first_and_uses_its_result(self) -> None:
        env = {"KIT_TEST_SCOPE": "full", "FAKE_PYTEST_MODE": "slow", "FAKE_PYTEST_SECONDS": "2"}
        first = self.start(**env)
        second = self.start(**env)
        payload = json.dumps({"stop_hook_active": False})
        for proc in (first, second):
            proc.stdin.write(payload)
            proc.stdin.close()
        for proc in (first, second):
            proc.wait(timeout=120)
            self.assertEqual(proc.returncode, ALLOWED, proc.stderr.read())
            proc.stdout.close()
            proc.stderr.close()
        self.assertEqual(len(self.calls()), 1)


if __name__ == "__main__":
    unittest.main()
