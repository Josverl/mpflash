"""mpflash is a CLI to download and flash MicroPython firmware to various boards."""

import os

import click.exceptions as click_exceptions
from dotenv import load_dotenv
from loguru import logger as log

# Load environment variables from a local .env file (if present) before
# anything else reads os.environ. This lets users configure e.g. MICROPY_DIR
# for `mpflash flash --build` without exporting it in every shell.
load_dotenv()
# Expand ~ in path-style env vars that downstream tools (mpbuild) consume
# verbatim. mpbuild uses Path(env).resolve() which does not expand ~.
for _var in ("MICROPY_DIR", "MPFLASH_FIRMWARE"):
    _val = os.environ.get(_var)
    if _val and _val.startswith("~"):
        os.environ[_var] = os.path.expanduser(_val)

from mpflash.errors import MPFlashError

from .cli_add import cli_add_custom
from .cli_download import cli_download
from .cli_flash import cli_flash_board
from .cli_group import cli
from .cli_list import cli_list_mcus
from .db.core import migrate_database


def mpflash():
    """Main entry point for the mpflash CLI."""
    migrate_database(boards=True, firmwares=True)

    cli.add_command(cli_list_mcus)
    cli.add_command(cli_download)
    cli.add_command(cli_flash_board)
    cli.add_command(cli_add_custom)

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
        except MPFlashError as e:
            log.error(f"MPFlashError: {e}")
            exit(-4)


if __name__ == "__main__":
    mpflash()
