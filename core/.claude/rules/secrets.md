# Secrets

- Configuration comes from environment variables. `.env` is for local development only and is gitignored. `.env.example` lists every variable with a placeholder and a one-line description.
- Never write a real credential into code, tests, fixtures, docs, logs, commit messages, or PR descriptions.
- Never read `.env` into context unless the owner explicitly asks. Read `.env.example` instead. Permission rules in `.claude/settings.json` deny reading `.env` and every `.env.*` file except `.env.example`; they cannot express "every seven-letter suffix but `example`", so seven-letter names are denied by a list (`staging`, `secrets`, `private`, ...). Treat any other env file as denied too, listed or not.
- If you find a committed secret, stop, report it, and treat it as compromised. Do not "fix" it by deleting the line; the history still has it.
