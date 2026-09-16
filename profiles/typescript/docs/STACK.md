# Stack: TypeScript full-stack

For web applications with a UI, APIs, and anything user-facing. Design-system compliance matters most here.

| Concern | Tool |
|---|---|
| Runtime | Node LTS (see `.nvmrc`) |
| Language | TypeScript, `strict: true` |
| Framework | Next.js (App Router) by default; the architect may choose otherwise with an ADR |
| Styling | CSS variables from `design/tokens.css`; Tailwind mapped to tokens if used |
| Tests | Vitest for unit and integration, Playwright for end-to-end, Testing Library for components |
| Lint / format | ESLint (typescript-eslint, jsx-a11y) and Prettier |
| Package manager | pnpm for new projects. The hooks read the lockfile (`pnpm-lock.yaml`, `yarn.lock`, `package-lock.json`) in the package or the project root and use that manager; binaries are found in `node_modules/.bin` from the package up to the root, so hoisted workspaces work. |
| Coverage floor | 80% lines on `src/`, enforced in CI |

## Commands

```bash
pnpm install                 # install
pnpm dev                     # run locally
pnpm test                    # unit and integration tests
pnpm test:watch              # TDD loop
pnpm test:e2e                # Playwright
pnpm test:coverage           # coverage report
pnpm lint                    # ESLint
pnpm typecheck               # tsc --noEmit
pnpm format                  # Prettier write
pnpm format:check            # Prettier check
pnpm audit                   # dependency vulnerabilities
pnpm build                   # production build
```

## Test scope in hooks

Two hooks run tests for you, from this package's directory (the one named for it in `.claude/kit.json`). After every edit, the PostToolUse hook formats with Prettier, lints with ESLint, runs the package's `typecheck` script (or `tsc --noEmit` on the nearest `tsconfig.json` when there is none) and runs the Vitest files related to the file you touched (`vitest related`). When Claude tries to end a turn, the Stop hook refuses if tests are red.

By default the Stop hook uses **changed** scope: `vitest run --changed`, which runs only the test files related to what changed since the last commit. A package on another runner (node:test, Jest) has no related mode, so its `test` script runs in full whenever the package has uncommitted changes. To run the **full suite on every turn** instead, add to `.claude/settings.json` (or `.claude/settings.local.json` for just yourself):

```json
{ "env": { "KIT_TEST_SCOPE": "full" } }
```

For one piece of work only, run `/tdd <item> full`: the skill writes `full` to `.claude/test-scope` (gitignored), which the Stop hook honours until the skill removes it at Exit. The `settings.json` value, when set, wins over the file.

CI always runs the full suite with coverage regardless of this setting.

## Layout

```
src/
  app/          routes and pages
  components/   shared UI, tokens only
  lib/          core logic, no I/O
  server/       API handlers, data access, external clients
  types/        shared types
tests/
  unit/  integration/  e2e/
design/tokens.css
docs/
```

## Conventions

- Named exports. One component per file. Props typed with an interface.
- Core logic in `src/lib` has no imports from `src/server` or `src/app`.
- Input at every API boundary validated with Zod. Never trust `req.body`.
- No `any`. No non-null assertions without a comment saying why.
- Server components by default; client components only where interaction requires it.
