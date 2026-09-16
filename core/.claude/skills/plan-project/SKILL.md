---
name: plan-project
description: Produce the architecture and plan documents for owner review before any code is written. Use this at the start of every new project, and whenever a change to an existing project touches more than one module, adds a dependency, changes a data model, or changes a user-facing flow. Also use when the owner says "plan this", "architecture first", or "before we build".
---

# Plan project

Goal: `docs/ARCHITECTURE.md` and `docs/PLAN.md` exist, are complete, and `docs/PLAN.md` says `Status: DRAFT` waiting for the owner. No implementation code is written by this skill.

## Steps

1. Gather requirements from the conversation and any files the owner provided. Restate them as a numbered list and confirm nothing is missing before designing.
2. Check `CLAUDE.md` for `project_size`. For `small`, a one-page PLAN.md with three to six items is enough and ARCHITECTURE.md can be a short section inside it.
3. Delegate to the `architect` subagent with the requirements list, the project_size, and the stack profile. Ask for both documents in full.
4. Write the returned documents to `docs/ARCHITECTURE.md` and `docs/PLAN.md` using the templates already in `docs/` as the structure.
5. Present the owner with:
   - A five-line summary of the architecture
   - The plan items as a numbered list
   - The three decisions most worth their attention, each with the alternative rejected
   - Open questions
6. Stop. Do not start implementation. The owner changes `Status: DRAFT` to `Status: APPROVED` in `docs/PLAN.md` (or asks you to after saying so explicitly).

## For changes to an existing project

Same steps, but the architect receives the current ARCHITECTURE.md and PLAN.md and returns a diff-style update: what changes, what stays, and new plan items appended with a new version number. Existing approved items are not rewritten.
