# GitHub Copilot Instructions for MPFlash

MPFlash is a Python 3.10+ command-line tool and library for downloading,
identifying, and flashing MicroPython firmware across multiple hardware
platforms.

## Working Agreement

- Read the relevant implementation, tests, and configuration before editing.
- Make focused changes and preserve existing CLI and library behavior unless the
  request explicitly changes it.
- Prefer existing abstractions and patterns over new dependencies or parallel
  implementations.
- Keep startup time low. Avoid expensive module-level imports and eagerly
  loading optional flash backends.
- Surface failures explicitly using the existing exception and logging patterns.
- Do not modify vendored code under `mpflash/vendor/` unless specifically asked.
- Use `uv` for dependency management and command execution. Add dependencies only
  to the appropriate `pyproject.toml` dependency group.

## Beads Issue Tracking

This repository uses Beads (`bd`) as the durable source of truth for tasks,
blockers, dependencies, and project memory.

1. Run `bd prime` when starting work or when Beads context is missing.
2. Check `bd ready`, inspect the selected issue with `bd show <id>`, and claim it
   atomically with `bd update <id> --claim`.
3. Create a Beads issue for newly discovered follow-up work. Do not create
   markdown TODO or memory files.
4. Close an issue only after its requested outcome has been implemented and
   verified.

Useful commands:

```text
bd prime
bd ready
bd show <id>
bd create --title="..." --description="..." --type=task --priority=2
bd update <id> --claim
bd close <id> --reason="Completed"
```

Run `bd prime` for the complete and current workflow; it is the source of truth
for operational Beads commands.

### Git and Sync Authority

Use the conservative profile by default:

- Do not commit, push, pull/rebase, or run `bd dolt push/pull` unless the user or
  active repository policy explicitly authorizes it.
- At handoff, report changed files, validation performed, Beads issue status, and
  any recommended next commands.
- User and repository instructions take precedence over generated Beads
  guidance.

## Project Layout

- `mpflash/cli_*.py`: Click command implementations.
- `mpflash/flash/`: flash services, worklists, backend registry, and built-in
  ESP, UF2, DFU, and pyOCD backends.
- `mpflash/bootloader/`: bootloader detection, activation, and registry.
- `mpflash/db/`: Peewee models and SQLite board/firmware database operations.
- `mpflash/download/`: firmware discovery and download support.
- `tests/`: unit, integration, CLI, platform, and hardware-in-the-loop tests.

## Validation

- Run the smallest relevant test selection first:
  `uv run pytest tests/path/test_file.py`.
- The configured default test run excludes tests marked `slow`.
- Hardware tests require physical devices and must not be treated as ordinary
  unit tests.
- For broad changes, run `uv run pytest`.
- Respect the Ruff and Pyright settings in `pyproject.toml`; do not substitute
  different style or type-checking defaults.

## Instruction Scope

Additional path-specific guidance lives in `.github/instructions/`:

- Python implementation guidance applies to `mpflash/**/*.py`.
- Test guidance applies to `tests/**/*.py`.
