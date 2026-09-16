---
name: update-docs
description: Audit and update project documentation to match the current code. Use after completing a plan item, before a PR, after adding a dependency or config variable, when a public interface changes, or when the owner asks "update the docs", "is the README current", or "document this".
---

# Update docs

1. Run `git diff main...HEAD --stat` to see what changed. If nothing is on the branch, audit the whole project.
2. Delegate to `docs-writer` with the diff scope. Ask it to check README.md, docs/ARCHITECTURE.md, docs/DECISIONS/, docs/CHANGELOG.md, .env.example, and docstrings on changed public functions.
3. Review its report. Confirm every command in README.md was verified to run.
4. If a new dependency or notable decision has no ADR, create one from `docs/DECISIONS/0000-template.md` with the next number.
5. Summarize for the owner: what was out of date, what was fixed, what still needs a human decision.
