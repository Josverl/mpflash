import shutil
from pathlib import Path
from typing import Union

import jsonlines
import requests
from loguru import logger as log
# re-use logic from mpremote
from mpremote.mip import _rewrite_url as rewrite_url  # type: ignore
from pytest import Session

from mpflash.config import config
from mpflash.db.core import Session
from mpflash.db.models import Firmware
from mpflash.versions import get_preview_mp_version, get_stable_mp_version

from .naming import port_and_boardid_from_path, custom_fw_from_path, extract_commit_count


# 
# github.com/<owner>/<repo>@<branch>#<commit>
# $remote_url = git remote get-url origin
# $branch = git rev-parse --abbrev-ref HEAD
# $commit = git rev-parse --short HEAD
# if ($remote_url -match "github.com[:/](.+)/(.+?)(\.git)?$") {
#     $owner = $matches[1]
#     $repo = $matches[2]
#     "github.com/$owner/$repo@$branch#$commit"
# }


# 1) local path 


def add_firmware(
    source: Path,  
    fw_info: dict,
    *,
    force: bool = False,
    custom: bool = False,
) -> bool:
    """
    Add a firmware to the database , and firmware folder.
    stored in the port folder, with the filename.

    fw_info is a dict with the following keys:
    - board_id: str, required
    - version: str, required
    - port: str, required
    - firmware_file: str, required, the filename to store in the firmware folder
    - source: str, optional, the source of the firmware, can be a local path
    - description: str, optional, a description of the firmware
    - custom: bool, optional, if the firmware is a custom firmware, default False
    """
    source = source.expanduser().absolute()
    if not source.exists() or not source.is_file():
        log.error(f"Source file {source} does not exist or is not a file")
        return False
    with Session() as session:
        # Check minimal info needed
        new_fw = Firmware(**fw_info)
        if custom:
            new_fw.custom = True

        if not new_fw.board_id:
            log.error("board_id is required")
            return False

        # assume the the firmware_file has already been prepared 
        fw_filename = config.firmware_folder / new_fw.firmware_file

        if not copy_firmware(source, fw_filename, force):
            log.error(f"Failed to copy {source} to {fw_filename}")
            return False
        # add to inventory
        # check if the firmware already exists
        existing_fw = (
            session.query(Firmware)
            .filter(
                Firmware.board_id == new_fw.board_id,
                Firmware.version == new_fw.version,
                Firmware.port == new_fw.port,
                Firmware.custom == new_fw.custom,
            )
            .first()
        )
        if existing_fw:
            if not force:
                log.warning(f"Firmware {existing_fw} already exists")
                return False
            # update the existing firmware
            existing_fw.firmware_file = new_fw.firmware_file
            existing_fw.source = new_fw.source
            existing_fw.custom = custom
            existing_fw.description = new_fw.description
        else:
            session.add(new_fw)
        session.commit()

    return True


def copy_firmware(source: Path, fw_filename: Path, force: bool = False):
    """Add a firmware to the firmware folder.
    stored in the port folder, with the same filename as the source.
    """
    if fw_filename.exists() and not force:
        log.error(f" {fw_filename} already exists. Use --force to overwrite")
        return False
    fw_filename.parent.mkdir(exist_ok=True)
    if isinstance(source, Path):
        if not source.exists():
            log.error(f"File {source} does not exist")
            return False
        # file copy
        log.debug(f"Copy {source} to {fw_filename}")
        shutil.copy(source, fw_filename)
        return True
    # handle github urls
    url = rewrite_url(source)
    if str(source).startswith("http://") or str(source).startswith("https://"):
        log.debug(f"Download {url} to {fw_filename}")
        response = requests.get(url)

        if response.status_code == 200:
            with open(fw_filename, "wb") as file:
                file.write(response.content)
                log.info("File downloaded and saved successfully.")
                return True
        else:
            print("Failed to download the file.")
            return False
    return False
