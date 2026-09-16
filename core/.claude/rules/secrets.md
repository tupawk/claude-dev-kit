# Secrets

- Configuration comes from environment variables. `.env` is for local development only and is gitignored. `.env.example` lists every variable with a placeholder and a one-line description.
- Never write a real credential into code, tests, fixtures, docs, logs, commit messages, or PR descriptions.
- Never read `.env` into context unless the owner explicitly asks. Read `.env.example` instead.
- If you find a committed secret, stop, report it, and treat it as compromised. Do not "fix" it by deleting the line; the history still has it.
