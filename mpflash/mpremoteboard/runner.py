"""
Run a command and return the output and return code as a tuple
"""

import subprocess
from dataclasses import dataclass
from threading import Timer
from typing import Callable, List, Optional, Tuple, Union

from loguru import logger as log

LogTagList = List[str]
LineHandler = Callable[[str], Optional[str]]


@dataclass
class LogTags:
    reset_tags: LogTagList
    error_tags: LogTagList
    warning_tags: LogTagList
    success_tags: LogTagList
    ignore_tags: LogTagList
    trace_tags: Optional[LogTagList] = None
    trace_res: Optional[LogTagList] = None


DEFAULT_RESET_TAGS = [
    # ESP32 reset causes
    "rst cause:1, boot mode:",  # 1 -> hardware watch dog reset
    "rst cause:2, boot mode:",  # 2 -> software watch dog reset (From an exception)
    "rst cause:3, boot mode:",  # 3 -> software watch dog reset system_restart (Possibly unfed watchdog got angry)
    "rst cause:4, boot mode:",  # 4 -> soft restart (Possibly with a restart command)
    "boot.esp32: PRO CPU has been reset by WDT.",
    "rst:0x10 (RTCWDT_RTC_RESET)",
]

DEFAULT_ERROR_TAGS = ["Traceback ", "Error: ", "Exception: ", "ERROR :", "CRIT  :"]
DEFAULT_WARNING_TAGS = ["WARNING:", "WARN  :", "TRACE :"]
DEFAULT_SUCCESS_TAGS = ["Done", "File saved", "File removed", "File renamed"]
DEFAULT_IGNORE_TAGS = [
    '  File "<stdin>",',
    "mpremote: rm -r: cannot remove :/ Operation not permitted",
]

CLI_LOG_TAGS = LogTags(
    reset_tags=DEFAULT_RESET_TAGS,
    error_tags=DEFAULT_ERROR_TAGS,
    warning_tags=DEFAULT_WARNING_TAGS,
    success_tags=DEFAULT_SUCCESS_TAGS,
    ignore_tags=DEFAULT_IGNORE_TAGS,
)

IPYTHON_LOG_TAGS = LogTags(
    reset_tags=DEFAULT_RESET_TAGS,
    error_tags=DEFAULT_ERROR_TAGS,
    warning_tags=DEFAULT_WARNING_TAGS,
    success_tags=["SUCCESS", "SUCCESS~"],
    ignore_tags=[],
    trace_tags=["Traceback (most recent call last)", '   File "<stdin>", '],
    trace_res=[r"\s+File \"[\w<>.]+\", line \d+, in .*"],
)


def _default_cli_handler(*, tags: LogTags, log_errors: bool, no_info: bool) -> LineHandler:
    def handle(line: str) -> Optional[str]:
        stripped = line.rstrip("\n")
        if any(tag in line for tag in tags.reset_tags):
            raise RuntimeError("Board reset detected")
        if any(tag in line for tag in tags.error_tags):
            if log_errors:
                log.error(stripped)
        elif any(tag in line for tag in tags.warning_tags):
            log.warning(stripped)
        elif any(tag in line for tag in tags.success_tags):
            log.success(stripped)
        elif any(tag in line for tag in tags.ignore_tags):
            return None
        else:
            if not no_info:
                if stripped.startswith(("INFO  : ", "WARN  : ", "ERROR : ")):
                    stripped = stripped[8:].lstrip()
                log.info(stripped)
        return line

    return handle


def execute(
    cmd: List[str],
    *,
    timeout: Union[int, float] = 60,
    line_handler: LineHandler,
    log_errors: bool = True,
    log_warnings: bool = False,
    ignore_tags: Optional[LogTagList] = None,
    follow: bool = True,
) -> Tuple[int, List[str]]:
    # sourcery skip: no-long-functions
    """
    Run a command with a pluggable line handler and return the exit code and output.
    The handler controls logging and filtering so both CLI and Jupyter flows can share
    the same core loop.
    """

    replace_tags = ["\x1b[1A"]
    output: List[str] = []
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            encoding="utf-8",
        )
    except FileNotFoundError as e:
        raise FileNotFoundError(f"Failed to start {cmd[0]}") from e

    # timeout == 0 means wait forever
    timer: Optional[Timer] = None
    _timed_out = False

    def timed_out():
        nonlocal _timed_out
        _timed_out = True
        if log_warnings:
            log.warning(f"Command {cmd} timed out after {timeout} seconds")
        proc.kill()

    if timeout > 0:
        timer = Timer(timeout, timed_out)
        timer.start()

    try:
        if not follow:
            proc.wait(timeout=timeout if timeout > 0 else None)
            return proc.returncode or 0, output

        if proc.stdout:
            for line in proc.stdout:
                if not line or not line.strip():
                    continue
                for tag in replace_tags:
                    line = line.replace(tag, "")
                handled = line_handler(line)
                if handled is not None:
                    output.append(handled)
        if proc.stderr and log_errors:
            for line in proc.stderr:
                if ignore_tags and any(tag in line for tag in ignore_tags):
                    continue
                log.warning(line.rstrip("\n"))
    except UnicodeDecodeError as e:
        log.error(f"Failed to decode output: {e}")
    finally:
        if timer:
            timer.cancel()
        if _timed_out:
            raise TimeoutError(f"Command {cmd} timed out after {timeout} seconds")

    proc.wait(timeout=1)
    return proc.returncode or 0, output


def run(
    cmd: List[str],
    timeout: Union[int, float] = 60,
    log_errors: bool = True,
    no_info: bool = False,
    *,
    log_warnings: bool = False,
    reset_tags: Optional[LogTagList] = None,
    error_tags: Optional[LogTagList] = None,
    warning_tags: Optional[LogTagList] = None,
    success_tags: Optional[LogTagList] = None,
    ignore_tags: Optional[LogTagList] = None,
) -> Tuple[int, List[str]]:
    """
    CLI-oriented wrapper around the shared executor.
    Uses mpflash defaults while delegating processing to the shared loop.
    """

    tags = LogTags(
        reset_tags or DEFAULT_RESET_TAGS,
        error_tags or DEFAULT_ERROR_TAGS,
        warning_tags or DEFAULT_WARNING_TAGS,
        success_tags or DEFAULT_SUCCESS_TAGS,
        ignore_tags or DEFAULT_IGNORE_TAGS,
    )

    handler = _default_cli_handler(tags=tags, log_errors=log_errors, no_info=no_info)

    return execute(
        cmd,
        timeout=timeout,
        line_handler=handler,
        log_errors=log_errors,
        log_warnings=log_warnings,
        ignore_tags=tags.ignore_tags,
    )
