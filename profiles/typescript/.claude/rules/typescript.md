---
paths:
  - "**/*.ts"
  - "**/*.tsx"
---
# TypeScript rules

- `strict` is on and stays on. No `any`, no `@ts-ignore`, no `!` non-null assertions without a justifying comment.
- Prefer `type` for unions and shapes, `interface` for objects that will be extended. Export types next to the code that owns them.
- Async code uses `async/await`. Every awaited call that can fail is either handled or deliberately propagated with context.
- Zod schemas at boundaries; infer types from them (`z.infer`) rather than duplicating.
- Tests live next to the module for unit tests (`foo.test.ts`) or under `tests/` for integration and e2e. Vitest `describe`/`it` with sentence-style names.
- Components: props interface at the top, hooks before render, no business logic in JSX. Accessibility attributes are not optional.
