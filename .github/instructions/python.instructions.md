---
applyTo: "mpflash/**/*.py"
---

# MPFlash Python Implementation

- Add precise type annotations to new and changed code. The supported floor is
  Python 3.10, so do not use syntax introduced in later versions.
- Follow the Ruff configuration in `pyproject.toml`: 4-space indentation,
  double-quoted strings, and a 140-character line limit.
- Use concise docstrings for public modules, classes, and functions. Do not
  duplicate type annotations in docstrings.
- Prefer `pathlib.Path`, generators for potentially large collections, and
  f-strings where appropriate.
- Keep imports lazy when a dependency or backend is expensive or optional.
- Use `loguru` through the repository's existing logging patterns. Raise or
  propagate meaningful exceptions instead of silently returning success-shaped
  defaults.

## Architecture

- Add CLI commands in `mpflash/cli_*.py` and register them through the existing
  Click command group patterns.
- Implement flash behavior through `mpflash.flash` abstractions and registries.
  Do not add backend-specific branching to generic services when a backend
  implementation can own it.
- Implement bootloader behavior through `mpflash.bootloader` abstractions and
  registries.
- Use the existing Peewee models and database helpers for persistence. Do not
  introduce SQLAlchemy or a second persistence layer.
- Preserve plugin loading through the `mpflash.flash_plugins` entry-point group.
- Keep platform-specific behavior isolated in the existing platform or backend
  modules.
- Avoid editing `mpflash/vendor/` unless the task explicitly concerns vendored
  code.

## Dependencies and Compatibility

- Use `uv`; declare runtime dependencies in `[project].dependencies` and
  optional dependencies in the matching `[project.optional-dependencies]`
  group.
- Minimize new dependencies, especially those imported during CLI startup.
- Preserve behavior on Windows, Linux, and macOS unless the code is explicitly
  platform-specific.

