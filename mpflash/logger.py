"""
Logger setup for CLI tools with Unicode-safe output.

Ensures log messages are compatible with the current console encoding.
Removes or replaces Unicode icons if the encoding is not UTF-8.
"""

import functools
import sys

from loguru import logger as log
from rich.console import Console

from .config import config

console = Console()


# Detect if the output encoding supports Unicode (UTF-8)
@functools.lru_cache(maxsize=1)
def _is_utf8_encoding() -> bool:
    try:
        encoding = getattr(sys.stdout, "encoding", None)
        if encoding is None:
            return False
        return encoding.lower().replace("-", "") == "utf8"
    except BaseException:
        return False


def _log_formatter(record: dict) -> str:
    """
    Log message formatter for loguru and rich.

    Removes Unicode icons if console encoding is not UTF-8.
    Handles messages containing curly braces safely.
    """
    color_map = {
        "TRACE": "cyan",
        "DEBUG": "orange",
        "INFO": "bold",
        "SUCCESS": "bold green",
        "WARNING": "yellow",
        "ERROR": "bold red",
        "CRITICAL": "bold white on red",
    }
    lvl_color = color_map.get(record["level"].name, "cyan")
    # Remove icon if not UTF-8
    if _is_utf8_encoding():
        icon = record["level"].icon
    else:
        icon = record["level"].name  # fallback to text
    # Escape curly braces in the message to prevent format conflicts
    safe_message = record["message"].replace("{", "{{").replace("}", "}}")
    # Use string concatenation to avoid f-string format conflicts
    time_part = "[not bold green]{time:HH:mm:ss}[/not bold green]"
    message_part = f"[{lvl_color}]{safe_message}[/{lvl_color}]"
    return f"{time_part} | {icon} {message_part}"


def set_loglevel(loglevel: str) -> None:
    """
    Set the log level for the logger.

    Ensures Unicode safety for log output and handles format errors.
    """
    try:
        log.remove()
    except ValueError:
        pass

    # Add error handling for format issues
    def safe_format_wrapper(message):
        try:
            console.print(message)
        except (KeyError, ValueError) as e:
            # Fallback to simple text output if formatting fails
            console.print(f"[LOG FORMAT ERROR] {message} (Error: {e})")

    log.add(safe_format_wrapper, level=loglevel.upper(), colorize=False, format=_log_formatter)  # type: ignore


def make_quiet() -> None:
    """
    Make the logger quiet.
    """
    config.quiet = True
    console.quiet = True
    set_loglevel("CRITICAL")
