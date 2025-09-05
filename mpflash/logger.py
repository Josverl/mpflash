"""
Logger setup for CLI tools with Unicode-safe output.

Ensures log messages are compatible with the current console encoding.
Removes or replaces Unicode icons if the encoding is not UTF-8.
Prevents Loguru colorization errors with angle bracket notation.

Usage for external packages:
    from mpflash.logger import setup_external_logger_safety
    setup_external_logger_safety()

This is particularly important when using packages like micropython-stubber
that may log messages containing angle bracket notation like <board_default>.
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


def _sanitize_message(message: str) -> str:
    """
    Sanitize log messages to prevent Loguru colorization issues.

    Escapes angle brackets that could be interpreted as color tags.
    This prevents errors when logging documentation with placeholders like <board_default>.
    """
    # Escape angle brackets to prevent them from being interpreted as color tags
    return message.replace("<", "\\<").replace(">", "\\>")


def _log_formatter(record) -> str:
    """
    Log message formatter for loguru and rich.

    Removes Unicode icons if console encoding is not UTF-8.
    Handles messages containing curly braces and angle brackets safely.
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

    # Sanitize the message to prevent format conflicts and colorization errors
    safe_message = _sanitize_message(record["message"])
    # Escape curly braces to prevent format conflicts
    safe_message = safe_message.replace("{", "{{").replace("}", "}}")

    # Use string concatenation to avoid f-string format conflicts
    time_part = "[not bold green]{time:HH:mm:ss}[/not bold green]"
    message_part = f"[{lvl_color}]{safe_message}[/{lvl_color}]"
    return f"{time_part} | {icon} {message_part}"


def set_loglevel(loglevel: str) -> None:
    """
    Set the log level for the logger.

    Ensures Unicode safety for log output and handles format errors.
    Disables colorization to prevent angle bracket interpretation issues.
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

    # Disable colorization completely to prevent angle bracket interpretation as color tags
    log.add(
        safe_format_wrapper,
        level=loglevel.upper(),
        colorize=False,  # This prevents Loguru from parsing angle brackets as color tags
        format=_log_formatter,
    )  # type: ignore


def configure_safe_logging() -> None:
    """
    Configure logging to be safe from colorization errors.

    This function helps prevent issues when external packages
    (like micropython-stubber) log messages with angle brackets
    that could be misinterpreted as color tags.
    """
    # Remove all existing handlers to start fresh
    try:
        log.remove()
    except ValueError:
        pass

    # Add a completely safe handler with no colorization
    log.add(
        sys.stderr,
        level="TRACE",
        colorize=False,  # Completely disable colorization
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}",
    )


def setup_external_logger_safety() -> None:
    """
    Setup safe logging configuration for external packages.

    Call this function before running tools that might log messages
    with angle bracket notation (like micropython-stubber) to prevent
    Loguru colorization errors.
    """
    import logging

    # Configure the root logger to be safe
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s | %(levelname)s | %(name)s:%(funcName)s:%(lineno)d - %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)],
    )

    # Also configure loguru for safety
    configure_safe_logging()


def make_quiet() -> None:
    """
    Make the logger quiet.
    """
    config.quiet = True
    console.quiet = True
    set_loglevel("CRITICAL")
