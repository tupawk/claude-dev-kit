# Engineering principles

Apply these on every file you write or change.

- **One job per unit.** Functions do one thing and are short enough to read without scrolling. Modules own one concern.
- **Explicit over implicit.** Named constants, not magic numbers. Typed inputs and outputs. Errors raised or returned with context, never swallowed.
- **No duplication.** If the same logic appears twice, extract it. If it appears once but is complex, name it.
- **Dependencies at the edges.** I/O, network, database, filesystem, and time live behind small interfaces so the core logic is testable without them.
- **Fail loudly in development, safely in production.** Validate inputs at boundaries. Log with enough context to diagnose without reproducing.
- **Boring beats clever.** Prefer the standard library and well-known patterns. A new dependency needs a reason written in an ADR.
- **Delete dead code.** No commented-out blocks, no unused imports, no "just in case" branches.
- **Name things for the reader.** Names say what, comments say why. If you need a comment to explain what, rename instead.
- **Leave it cleaner.** Small opportunistic refactors are welcome in the file you are already in. Large refactors get their own plan.
