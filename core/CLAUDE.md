# CLAUDE.md - development standards

This file is the index. It stays under 200 lines. Details live in the files it points to.

## Project (fill in per project)

- **Name:** <project name>
- **Purpose:** <one sentence: who uses it and what problem it solves>
- **Stack profile(s):** <typescript | python | scripts> (see `docs/STACK.md` for commands and layout; the package list, design pack and hook settings are in `.claude/kit.json`)
- **project_size:** full
  - `full` = all gates on: approved plan before code, TDD, security review, Definition of Done
  - `small` = single-purpose utility: plan can be a short PLAN.md, tests still required, reviews optional
- **Owner:** <name>

## How we work (always on)

1. **Plan before code.** No implementation until `docs/PLAN.md` has `Status: APPROVED` set by the owner. Use the `/plan-project` skill to produce `docs/ARCHITECTURE.md` and `docs/PLAN.md`, then stop and wait for review. For changes to an existing project, update the plan first and get it re-approved.
2. **TDD.** Write the failing test, show it failing, implement, show it passing, refactor. Use `/tdd` (`/tdd <item> full` runs the whole suite through the cycle). No feature or fix lands without a test that would have caught it.
3. **Ask when stuck.** After two failed attempts at the same error, stop. Summarize what was tried, what you think is wrong, and 2 to 3 options. Do not work around a problem by skipping tests, loosening types, suppressing lint, or commenting out checks. See `.claude/rules/when-stuck.md`.
4. **Delegate review-heavy work to subagents.** The main session orchestrates. Use `architect` for design, `test-writer` for test suites, `security-reviewer` and `code-reviewer` before every PR, `docs-writer` when interfaces change. Subagents cannot ask the user questions; they return BLOCKED with details and the main session raises it.
5. **Done means the Definition of Done is met.** Run `/definition-of-done` before declaring any task complete.

## Engineering principles

See `.claude/rules/engineering-principles.md`. Short version: small functions with one job, explicit errors, no duplication, no magic values, dependencies injected not hardcoded, boring and readable beats clever.

## Git

Feature branches off `main`, conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`), small PRs with the template filled in. Never commit directly to `main`, never force push, never rewrite shared history. Hooks enforce the destructive cases. See `.claude/rules/git-workflow.md`.

## Documentation

`docs/` is part of the product. README says how to run it, ARCHITECTURE says how it is built, DECISIONS holds one short ADR per non-obvious choice, CHANGELOG tracks what shipped. Any change to a public interface updates the docs in the same PR. See `.claude/rules/documentation.md`.

## Frontend (when the project has one)

Clean, modern, restrained. Design tokens only, from `design/tokens.css` (the brand values come from the design pack named in `.claude/kit.json`). No hardcoded colors, fonts, or spacing. The dark surface dominates, the primary colour marks interactive elements, the accent is for emphasis only. Accessible by default (WCAG AA contrast, keyboard navigable, semantic HTML). Logos and images: set width only, never both dimensions. Frontend-specific rules load from `.claude/rules/frontend.md` when frontend files are touched; `.claude/rules/design-system.md` covers documents, decks, and other non-web output.

## Secrets and safety

Secrets live in `.env` (gitignored) or the platform's secret store. Never in code, tests, fixtures, docs, or commit messages. Hooks block common key patterns and destructive git commands. If a hook blocks you, do not work around it. Explain what you were trying to do.

## Commands

See `docs/STACK.md` for the exact install, test, lint, format, and run commands for this project's stack profile.

## Updating these standards

Standards are versioned in the `claude-dev-kit` repo. Fix mistakes there, not only here: a local edit to anything under `.claude/agents`, `skills`, `rules` or `hooks` is erased by the next `new-project.sh update`. Per-project settings go in `.claude/kit.json`. After any mistake Claude makes that a rule could have prevented, add the rule to the kit and note it in the kit CHANGELOG.
