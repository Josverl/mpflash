"""mpflash is a CLI to download and flash MicroPython firmware to various boards."""

import os

import click.exceptions as click_exceptions
from loguru import logger as log

from .cli_download import cli_download
from .cli_flash import cli_flash_board
from .cli_group import cli
from .cli_list import cli_list_mcus
from .config import config


def migrate_database():
    """Migrate from 1.24.x to 1.25.x"""
    # lazy import to avoid slowdowns
    if not config.db_path.exists():
        import mpflash.db.update as update

        update.update_database()
    jsonl_file = config.firmware_folder / "firmware.jsonl"
    if jsonl_file.exists():
        import mpflash.db.update as update

        log.info(f"Migrating JSONL data {jsonl_file}to SQLite database.")
        update.migrate_jsonl(jsonl_file)


def mpflash():
    """Main entry point for the mpflash CLI."""
    migrate_database()

    cli.add_command(cli_list_mcus)
    cli.add_command(cli_download)
    cli.add_command(cli_flash_board)

    # cli(auto_envvar_prefix="MPFLASH")
    if False and os.environ.get("COMPUTERNAME").upper().startswith("JOSVERL"):
        # intentional less error suppression on dev machine
        result = cli(standalone_mode=False)
    else:
        try:
            result = cli(standalone_mode=True)
            exit(result)
        except AttributeError as e:
            log.error(f"Error: {e}")
            exit(-1)
        except click_exceptions.ClickException as e:
            log.error(f"Error: {e}")
            exit(-2)
        except click_exceptions.Abort:
            # Aborted - Ctrl-C
            exit(-3)


if __name__ == "__main__":
    mpflash()
