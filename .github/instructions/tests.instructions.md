---
applyTo: "tests/**/*.py"
---

# MPFlash Tests

- Use pytest, plain `assert` statements, descriptive `test_*` names, fixtures
  for setup and teardown, `pytest.mark.parametrize` for data-driven cases, and
  `pytest.raises` for expected exceptions.
- Put tests in the existing matching area under `tests/`; keep unit tests
  separate from integration and hardware-in-the-loop tests.
- Prefer focused behavioral tests over broad implementation-coupled tests.
- Mock hardware, network, subprocess, and filesystem boundaries for ordinary
  unit tests. Reuse existing fixtures and test data before adding new ones.
- Use the existing database fixtures and data under `tests/db/` for database
  tests; do not operate on a user's MPFlash database.
- Apply the configured markers accurately. Tests that require physical boards
  must use `hardware` and the appropriate `hw_*` marker. Slow or integration
  behavior must be marked rather than hidden in the default suite.
- Keep MVP test coverage small but sufficient to prove the requested behavior
  and important failure paths.
- Run the narrowest relevant command first, for example:
  `uv run pytest tests/flash/test_registry.py`.
