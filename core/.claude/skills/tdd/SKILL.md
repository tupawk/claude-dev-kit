---
name: tdd
description: Run the red-green-refactor cycle for a feature, fix, or plan item. Use for every implementation task, including bug fixes and small changes, and whenever the owner says "implement", "build", "add", "fix", or names a plan item. Enforces that a failing test exists before any production code.
argument-hint: "[plan item] [full]"
---

# TDD cycle

Precondition: the plan item is in `docs/PLAN.md` with `Status: APPROVED`, or `project_size: small` and the owner has agreed to the change in conversation.

## Test scope

Arguments: `$ARGUMENTS`. Default scope is **related**: during the cycle run only the test you are working on and the tests related to the touched files; the full suite runs at Exit.

If the arguments contain the word `full` (for example `/tdd 3 full`), use **full** scope for this item:

1. Before the first Red step, write the single word `full` to `.claude/test-scope`. The Stop hook reads this file and runs the whole suite at the end of every turn until it is removed. Nothing in `settings.json` changes.
2. Run the full suite, not just the related tests, after every Green and every Refactor step.
3. At Exit, delete `.claude/test-scope` and say so.

The owner can also set the scope for everyone in `.claude/settings.json` (`"env": {"KIT_TEST_SCOPE": "full"}`); that setting wins over the file. See `docs/STACK.md`.

## Per behavior

1. **Red.** Write one test for one behavior. Name it as a sentence. Run only that test. It must fail, and the failure must be the assertion or a missing symbol, not a syntax or import error. Show the owner the failing output summary.
2. **Green.** Write the minimum code to pass. No extra branches, no speculative generality. Run the test. Show it passing.
3. **Refactor.** With the whole suite green, improve names, remove duplication, apply engineering principles. Run the whole suite again.
4. **Commit.** Conventional commit on the feature branch.

Repeat until the plan item's listed tests all exist and pass.

## Rules

- Production code is only written in response to a failing test.
- A bug fix starts with a test that reproduces the bug.
- If you cannot write a test for something, that is a design problem. Stop and raise it, do not skip the test.
- Never mark tests skipped, expected-fail, or delete them to get to green.
- For larger items, delegate: `test-writer` writes the suite first, `implementer` makes it pass. The main session verifies both reports.

## Exit

Run the full suite, lint, type check, and format check from `docs/STACK.md`. Report counts. Then run `/definition-of-done`.
