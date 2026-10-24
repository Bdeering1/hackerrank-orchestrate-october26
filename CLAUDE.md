@AGENTS.md

## Tooling

- The uv project lives in `code/`; run every command from there through `uv run`
- Verify changes with: `pytest`, `ruff check .`, `ruff format --check .`, `basedpyright`, `lint-imports`
- Install the pre-commit hook once per clone: `git config core.hooksPath .githooks`. It runs
  ruff check, ruff format and basedpyright on staged files; a full basedpyright run and pytest run
  in CI.
- `code/.github` and `code/.githooks` symlink to the root directories so `code.zip` includes them.
