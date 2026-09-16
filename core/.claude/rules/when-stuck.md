# When stuck

Stuck means: the same error after two genuine attempts, a requirement that contradicts the plan, a dependency that does not behave as documented, or a test you cannot make pass without weakening it.

Do this:

1. Stop making changes.
2. Write a short BLOCKED report:
   - What you were trying to do
   - What you tried (each attempt, one line)
   - What you observe (exact error, exact behavior)
   - What you think is going on
   - 2 to 3 options with trade-offs and your recommendation
3. Main session: present the report to the owner and wait. Subagent: return the report as your final message with `STATUS: BLOCKED` on the first line.

Never do this to get unstuck:

- Skip, delete, or mark tests as expected-to-fail
- Add `@ts-ignore`, `# type: ignore`, `eslint-disable`, `noqa`, or equivalents
- Catch and swallow the exception
- Widen a type to `any` or `object`
- Comment out the failing check
- Hardcode the value the test expects
- Change the plan silently
