# Documentation

Documentation is written for the next engineer, who may be Claude in six months with no memory of this session.

- `README.md`: what it is, how to install, how to run, how to test, how to deploy. Copy-pasteable commands. Kept current.
- `docs/ARCHITECTURE.md`: components, data flow, key boundaries, why the structure is the way it is. A Mermaid diagram where it helps.
- `docs/DECISIONS/NNNN-title.md`: one ADR per non-obvious choice (framework, dependency, data model, integration approach). Context, decision, consequences. Short. Never edited after acceptance; superseded by a new ADR.
- `docs/CHANGELOG.md`: Keep a Changelog format. Every PR adds a line under Unreleased.
- Code comments explain why. Public functions and modules have a docstring or JSDoc stating purpose, inputs, outputs, and errors.
- Any change to a public interface (API, CLI flag, config, exported function, UI flow) updates the relevant doc in the same PR. Use `/update-docs` to check.
