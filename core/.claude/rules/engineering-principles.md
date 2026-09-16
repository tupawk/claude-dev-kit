# Engineering principles

Apply these on every file you write or change.

## Before you write

Stop at the first rung that holds. Read the task and the code it touches first; the ladder shortens the solution, never the reading.

1. **Does it need to exist?** Speculative need means skip it and say so in one line.
2. **Does it already exist here?** A helper, type, or pattern a few files over is reused, not rewritten. Grep before you write.
3. **Does the standard library do it?** Use it.
4. **Does the platform do it natively?** A native `<input type="date">` over a picker library, CSS over JS, a database constraint over application code.
5. **Does an installed dependency do it?** Use it. A new dependency needs a reason written in an ADR.
6. **Only then** write the minimum code that works.

Two rungs work: take the higher one. Two same-size options: take the one that is correct on edge cases. This ladder never removes input validation at trust boundaries, error handling that prevents data loss, security measures, accessibility basics, tests, or anything the owner explicitly asked for.

## Bug fixes

A bug report names a symptom. Before editing, grep every caller of the function you are about to touch and fix the shared code once. A guard in the shared function is a smaller diff than a guard in every caller, and patching only the path the ticket names leaves the sibling callers broken. The test that reproduces the bug comes first (see `/tdd`).

## While you write

- **One job per unit.** Functions do one thing and are short enough to read without scrolling. Modules own one concern.
- **Explicit over implicit.** Named constants, not magic numbers. Typed inputs and outputs. Errors raised or returned with context, never swallowed.
- **No duplication.** If the same logic appears twice, extract it. If it appears once but is complex, name it.
- **Dependencies at the edges.** I/O, network, database, filesystem, and time live behind small interfaces so the core logic is testable without them. This is the one place an interface with a single implementation is expected.
- **No unrequested abstractions elsewhere.** No factory for one product, no config for a value that never changes, no layer with one caller, no scaffolding "for later".
- **Fail loudly in development, safely in production.** Validate inputs at boundaries. Log with enough context to diagnose without reproducing.
- **Boring beats clever.** Well-known patterns. Clever is what someone decodes at 3am.
- **Delete dead code.** No commented-out blocks, no unused imports, no "just in case" branches.
- **Name things for the reader.** Names say what, comments say why. If you need a comment to explain what, rename instead.
- **Leave it cleaner.** Small opportunistic refactors are welcome in the file you are already in. Large refactors get their own plan.

## Deliberate shortcuts

When you knowingly cut a corner with a real ceiling (a global lock, an O(n²) scan, a naive heuristic, an in-memory store), mark it on the same line or the line above:

```
# defer: global lock, per-account locks if throughput matters
// defer: linear scan, index by id above ~10k rows
```

Format is `defer: <ceiling>, <upgrade path>`. Both halves are required; a marker with no upgrade trigger rots. `/definition-of-done` lists every marker in the diff so the owner sees each one before merge. Use an ADR instead when the shortcut shapes the architecture.
