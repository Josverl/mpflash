import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import mpflash.basicgit as git
from mpflash.logger import log


def custom_fw_from_path(fw_path: Path) -> Dict[str, Union[str, int, bool]]:
    """Generate a custom name for the firmware file based on its path.

    Args:
        firmware_path: Path to firmware file

    Returns:
        Custom name for the firmware file
    """
    repo_path = fw_path.expanduser().absolute().parent
    port, board_id = port_and_boardid_from_path(fw_path)
    if not port or not board_id:
        raise ValueError(f"Could not extract port and board_id from path: {fw_path}")
    if "wsl.localhost" in str(repo_path):
        log.info("Accessing WSL path; please note that it may take a few seconds to get git info across filesystems")
    version = git.get_local_tag(repo_path) or "unknown"
    describe = git.get_git_describe(repo_path)
    if describe:
        build = extract_commit_count(describe)
    else:
        build = 0
    branch = git.get_current_branch(repo_path)
    if branch:
        branch = branch.split("/")[-1]  # Use only last part of the branch name (?)
    build_str = f".{build}" if build > 0 else ""
    branch_str = f"@{branch}" if branch else ""
    new_fw_path = Path(port) / f"{board_id}{branch_str}-{version}{build_str}{fw_path.suffix}"

    return {
        "port": port,
        "board_id": f"{board_id}",
        "custom_id": f"{board_id}{branch_str}",
        "version": version,
        "build": build,
        "custom": True,
        "firmware_file": new_fw_path.as_posix(),
        "source": fw_path.expanduser().absolute().as_uri() if isinstance(fw_path, Path) else fw_path,  # Use URI for local files
    }


def port_and_boardid_from_path(firmware_path: Path) -> Tuple[Optional[str], Optional[str]]:
    """Extract port and board_id from firmware path.

    Args:
        firmware_path: Path to firmware file

    Returns:
        Tuple of (port, board_id) or (None, None) if not found
    """
    path_str = str(firmware_path).replace("\\", "/")  # Normalize path for regex matching

    # Pattern: /path/to/micropython/ports/{port}/build-{board_id}/firmware.ext
    build_match = re.search(r"/ports/([^/]+)/build-([^/]+)/", path_str)
    if build_match:
        port = build_match.group(1)
        board_id = build_match.group(2)
        # Remove variant suffix (e.g., GENERIC_S3-SPIRAM_OCT -> GENERIC_S3)
        board_id = board_id.split("-")[0]
        return port, board_id

    # Pattern: /path/to/micropython/ports/{port}/firmware.ext
    port_match = re.search(r"/ports/([^/]+)/[^/]*firmware\.[^/]*$", path_str)
    if port_match:
        port = port_match.group(1)
        return port, None

    return None, None


def extract_commit_count(git_describe: str) -> int:
    """Extract commit count from git describe string.

    Args:
        git_describe: Git describe output like 'v1.26.0-preview-214-ga56a1eec7b-dirty'

    Returns:
        Commit count as integer or None if not found
    """
    # Match patterns like v1.26.0-preview-214-g... or v1.26.0-214-g...
    match = re.search(r"-(\d+)-g[a-f0-9]+", git_describe)
    if match:
        return int(match.group(1))
    return 0
