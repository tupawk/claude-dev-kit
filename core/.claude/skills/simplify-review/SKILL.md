---
name: simplify-review
description: Review the current diff, a file, or the whole repo for over-engineering only, and return a delete list. Use mid-task before handing off to code-reviewer, when the owner says "what can we delete", "is this over-engineered", "simplify review", or "find bloat", or when a diff has grown past what the plan item needed. Lists findings, applies nothing.
argument-hint: "[diff | <path> | repo]"
---

# Simplify review

Scope from `$ARGUMENTS`: nothing or `diff` means `git diff main...HEAD` plus unstaged changes; a path means that file or directory; `repo` means the whole tree, ranked biggest cut first. Read every file in scope in full before writing a finding.

## Findings

One line each: `<file>:L<line>: <tag> <what to cut>. <replacement>.`

- `delete:` dead code, unused flexibility, speculative feature. Replacement: nothing.
- `stdlib:` hand-rolled thing the standard library ships. Name the function.
- `native:` dependency or code doing what the platform already does. Name the feature.
- `yagni:` abstraction with one implementation, config nobody sets, layer with one caller, scaffolding for later.
- `shrink:` same logic, fewer lines. Show the shorter form.

Examples of the format:

```
src/validate.py:L12: stdlib: 27-line email validator class. "@" in address plus a confirmation mail.
src/dates.ts:L4: native: moment imported for one format call. Intl.DateTimeFormat, 0 deps.
src/repo.py:L88: yagni: AbstractRepository with one implementation. Inline it until a second exists.
src/util.ts:L30: shrink: manual loop builds a map. Object.fromEntries(pairs), 1 line.
```

## Never flag

Tests, input validation at trust boundaries, error handling that prevents data loss, security measures, accessibility, the small interfaces that isolate I/O per `.claude/rules/engineering-principles.md`, and anything the approved plan item or the owner explicitly asked for.

## Output

The findings, then `net: -<N> lines, -<M> deps possible.` If there is nothing to cut, say `Lean already.` and stop.

Correctness, security, and performance are out of scope; `code-reviewer` and `security-reviewer` own those. This skill applies nothing. If the owner wants the cuts made, each one goes through `/tdd` like any other change.
