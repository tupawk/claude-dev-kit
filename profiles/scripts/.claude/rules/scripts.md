---
paths:
  - "scripts/**"
  - "lib/**"
---
# Script rules

- Every script starts with a module docstring: what it does, inputs, outputs, how to run it, example.
- Argument parsing with `argparse` or Typer, never `sys.argv` indexing. `--dry-run` for anything that writes or sends.
- Credentials from environment variables. Fail fast with a clear message if one is missing.
- Idempotent where possible: running twice should not double-write or double-send.
- Log what was done at the end (counts, files written, records touched).
- Logic that can be tested goes in a function; the `if __name__ == "__main__":` block only wires arguments to it.
