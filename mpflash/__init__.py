"""MPFlash - MicroPython firmware flashing tool."""

from .logger import configure_safe_logging, setup_external_logger_safety

__all__ = ["configure_safe_logging", "setup_external_logger_safety"]
