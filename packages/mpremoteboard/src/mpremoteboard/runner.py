"""Run subprocess commands with tagged logging and bounded cleanup."""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass
from queue import Empty, Queue
from threading import Thread
from typing import Callable, List, Optional, Tuple

DEFAULT = object()
log = logging.getLogger(__name__)

LogTagList = List[str]
OutputCallback = Callable[[str, str], None]


@dataclass
class LogTags:
    reset_tags: LogTagList
    error_tags: LogTagList
    warning_tags: LogTagList
    success_tags: LogTagList
    ignore_tags: LogTagList


DEFAULT_RESET_TAGS = [
    "rst cause:1, boot mode:",
    "rst cause:2, boot mode:",
    "rst cause:3, boot mode:",
    "rst cause:4, boot mode:",
    "boot.esp32: PRO CPU has been reset by WDT.",
    "rst:0x10 (RTCWDT_RTC_RESET)",
]
DEFAULT_ERROR_TAGS = ["Traceback ", "Error: ", "Exception: ", "ERROR :", "CRIT  :"]
DEFAULT_WARNING_TAGS = ["WARN  :", "TRACE :"]
DEFAULT_SUCCESS_TAGS = ["Done", "File saved", "File removed", "File renamed"]
DEFAULT_IGNORE_TAGS = ['  File "<stdin>",', "mpremote: rm -r: cannot remove :/ Operation not permitted"]


def _read_stream(stream_name: str, stream, events: Queue[Tuple[str, Optional[bytes], Optional[BaseException]]]) -> None:
    try:
        while True:
            chunk = stream.readline()
            if not chunk:
                break
            events.put((stream_name, chunk, None))
    except BaseException as exc:
        events.put((stream_name, None, exc))
    finally:
        events.put((stream_name, None, None))


def run(
    cmd: List[str],
    timeout: float = 60,
    log_errors: bool = True,
    no_info: bool = False,
    *,
    log_warnings: bool = False,
    reset_tags: Optional[LogTagList] = None,
    error_tags: Optional[LogTagList] = None,
    warning_tags: Optional[LogTagList] = None,
    success_tags: Optional[LogTagList] = None,
    ignore_tags: Optional[LogTagList] = None,
    output_callback: Optional[OutputCallback] = None,
    stdout_callback: Optional[OutputCallback] = None,
    stderr_callback: Optional[OutputCallback] = None,
) -> Tuple[int, List[str]]:
    """Run a command, returning its exit code and lossless stdout lines.

    Callbacks receive ``("stdout", line)`` or ``("stderr", line)`` before
    tagged logging. Lines retain their original newline and blank lines.
    """
    reset_tags = DEFAULT_RESET_TAGS if reset_tags is None else reset_tags
    error_tags = DEFAULT_ERROR_TAGS if error_tags is None else error_tags
    warning_tags = DEFAULT_WARNING_TAGS if warning_tags is None else warning_tags
    success_tags = DEFAULT_SUCCESS_TAGS if success_tags is None else success_tags
    ignore_tags = DEFAULT_IGNORE_TAGS if ignore_tags is None else ignore_tags

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=False,
        )
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Failed to start {cmd[0]}") from exc

    events: Queue[Tuple[str, Optional[bytes], Optional[BaseException]]] = Queue()
    threads = [
        Thread(target=_read_stream, args=("stdout", proc.stdout, events), daemon=True),
        Thread(target=_read_stream, args=("stderr", proc.stderr, events), daemon=True),
    ]
    for thread in threads:
        thread.start()

    output: List[str] = []
    finished_streams = set()
    deadline = None if timeout == 0 else time.monotonic() + timeout
    failure: Optional[BaseException] = None
    timed_out = False
    cleanup_deadline: Optional[float] = None

    def terminate() -> None:
        nonlocal cleanup_deadline
        if proc.poll() is None:
            proc.kill()
        if cleanup_deadline is None:
            cleanup_deadline = time.monotonic() + 1

    def handle_event(stream_name: str, payload: Optional[bytes], stream_error: Optional[BaseException]) -> None:
        nonlocal failure
        if stream_error is not None:
            failure = stream_error
            return
        if payload is None:
            finished_streams.add(stream_name)
            return
        try:
            line = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            failure = exc
            return
        if output_callback is not None:
            output_callback(stream_name, line)
        callback = stdout_callback if stream_name == "stdout" else stderr_callback
        if callback is not None:
            callback(stream_name, line)
        if stream_name == "stdout":
            output.append(line)
        if not line.strip():
            return
        clean_line = line.replace("\x1b[1A", "").rstrip("\n")
        if stream_name == "stderr":
            if log_errors and not any(tag in clean_line for tag in ignore_tags):
                log.warning(clean_line)
            return
        if any(tag in clean_line for tag in reset_tags):
            failure = RuntimeError("Board reset detected")
        elif any(tag in clean_line for tag in error_tags):
            if log_errors:
                log.error(clean_line)
        elif any(tag in clean_line for tag in warning_tags):
            log.warning(clean_line)
        elif any(tag in clean_line for tag in success_tags):
            log.info(clean_line)
        elif not any(tag in clean_line for tag in ignore_tags) and not no_info:
            if clean_line.startswith(("INFO  : ", "WARN  : ", "ERROR : ")):
                clean_line = clean_line[8:].lstrip()
            log.info(clean_line)

    try:
        while len(finished_streams) < 2:
            if failure is not None:
                terminate()
            elif deadline is not None and time.monotonic() >= deadline:
                timed_out = True
                if log_warnings:
                    log.warning(f"Command {cmd} timed out after {timeout} seconds")
                terminate()
            if cleanup_deadline is not None and time.monotonic() >= cleanup_deadline:
                break
            try:
                stream_name, payload, stream_error = events.get(timeout=0.05)
            except Empty:
                if proc.poll() is not None and all(not thread.is_alive() for thread in threads):
                    break
                continue
            handle_event(stream_name, payload, stream_error)
    finally:
        if proc.poll() is None:
            terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=1)
        for thread in threads:
            thread.join(timeout=1)
        for pipe in (proc.stdout, proc.stderr):
            if pipe is not None and not pipe.closed:
                pipe.close()

    if timed_out:
        raise TimeoutError(f"Command {cmd} timed out after {timeout} seconds")
    if failure is not None:
        raise failure
    return proc.returncode or 0, output
