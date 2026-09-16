---
name: definition-of-done
description: Verify a plan item or task is actually complete before declaring it done or opening a PR. Use at the end of every implementation task, before every PR, and whenever the owner asks "is this done", "ready to merge", or "what's left".
---

# Definition of Done

Run every check. Report each as PASS, FAIL, or N/A with one line of evidence. Do not declare done with any FAIL.

## Checklist

1. **Plan.** The work matches an approved item in `docs/PLAN.md`. No scope added silently.
2. **Tests.** Full suite green. New behavior has new tests. No skipped or weakened tests. Coverage did not drop (run the coverage command from `docs/STACK.md`).
3. **Quality gates.** Lint clean, type check clean, formatter clean.
4. **Security review.** `security-reviewer` returned `STATUS: PASS` on this diff, or `project_size: small` and the change touches no input handling, auth, data, or dependencies.
5. **Code review.** `code-reviewer` returned `STATUS: APPROVE`, or `project_size: small` and the owner waived it.
6. **Docs.** README still accurate. ARCHITECTURE.md updated if structure changed. ADR added for any new dependency or notable decision. CHANGELOG has an entry under Unreleased. Public functions documented.
7. **Design system (if any user-facing output was touched: UI, document, deck, spreadsheet, email, report).** Colours only from `design/tokens.css` or the hex table in `.claude/rules/design-system.md`; any logo comes from `design/logo/` with one dimension set; `design/check_logo_aspect.py` exits 0 on every produced `.pptx` or `.docx`; text meets WCAG AA contrast; UI works at mobile width.
8. **Secrets.** No credentials in the diff. `.env.example` updated if new config was added.
9. **Git.** On a feature branch, rebased on main, conventional commits, PR template filled in.
10. **Suppressions.** Zero new `ts-ignore`, `noqa`, `eslint-disable`, `type: ignore`, or equivalents, or each one is justified in a comment.

## Output

A table of the ten checks with status and evidence, then either "Ready for PR" or the list of what remains.
