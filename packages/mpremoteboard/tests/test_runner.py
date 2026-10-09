"""Behavioral tests for the standalone subprocess runner."""

from __future__ import annotations

import sys
import time
from os import linesep

import pytest

from mpremoteboard.runner import run


def _python(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_timeout_raises_and_accepts_fractional_deadline():
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        run(_python("import time; time.sleep(2)"), timeout=0.1)
    assert time.monotonic() - started < 1


def test_zero_timeout_means_no_deadline():
    result, output = run(_python("print('done')"), timeout=0)
    assert result == 0
    assert output == [f"done{linesep}"]


def test_callbacks_preserve_blank_lines_and_stream_identity():
    events: list[tuple[str, str]] = []
    result, output = run(
        _python("import sys; print('out'); print(); print('err', file=sys.stderr)"),
        output_callback=lambda stream, line: events.append((stream, line)),
    )
    assert result == 0
    assert output == [f"out{linesep}", linesep]
    assert set(events) == {("stdout", f"out{linesep}"), ("stdout", linesep), ("stderr", f"err{linesep}")}


def test_nonzero_exit_and_stderr_callback():
    stderr: list[tuple[str, str]] = []
    result, output = run(
        _python("import sys; print('bad', file=sys.stderr); sys.exit(3)"),
        stderr_callback=lambda stream, line: stderr.append((stream, line)),
    )
    assert result == 3
    assert output == []
    assert stderr == [("stderr", f"bad{linesep}")]


def test_large_stderr_does_not_block_stdout():
    result, output = run(
        _python("import sys; sys.stderr.write('x' * 200000); print('done')"),
    )
    assert result == 0
    assert output == [f"done{linesep}"]


def test_callback_failure_terminates_child():
    started = time.monotonic()

    def fail(_stream: str, _line: str) -> None:
        raise ValueError("callback failed")

    with pytest.raises(ValueError, match="callback failed"):
        run(_python("print('output', flush=True); import time; time.sleep(2)"), output_callback=fail)
    assert time.monotonic() - started < 1


def test_reset_failure_cleans_up_and_propagates():
    with pytest.raises(RuntimeError, match="Board reset detected"):
        run(_python("print('rst cause:4, boot mode:')"))
