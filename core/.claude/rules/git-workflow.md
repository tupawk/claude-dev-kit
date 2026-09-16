# Git workflow

- `main` is always deployable. Work on branches named `feat/<short-name>`, `fix/<short-name>`, `docs/<short-name>`, `chore/<short-name>`.
- Conventional commits: `type(scope): imperative summary`. Body explains why, not what. Reference the plan item or issue.
- Commit in small, coherent steps. A commit should leave tests green.
- One PR per plan item where possible. Fill in the PR template. PRs are reviewed by `code-reviewer` and `security-reviewer` subagents before a human looks at them.
- Never: commit to `main` directly, `git push --force` to a shared branch, `git reset --hard` on shared work, rewrite published history, commit `.env` or any secret. Hooks block these; if one fires, stop and explain.
- Before opening a PR: rebase on `main`, all tests green, lint clean, docs updated, CHANGELOG entry added under Unreleased.
