import shutil
from pathlib import Path

from loguru import logger as log


def copy_firmware(source: Path, fw_filename: Path, force: bool = False):
    """Add a firmware to the firmware folder.
    stored in the port folder, with the same filename as the source.
    """
    if fw_filename.exists() and not force:
        log.error(f" {fw_filename} already exists. Use --force to overwrite")
        return False
    fw_filename.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(source, Path):
        if not source.exists():
            log.error(f"File {source} does not exist")
            return False
        # file copy
        log.debug(f"Copy {source} to {fw_filename}")
        shutil.copy(source, fw_filename)
        return True


# TODO: handle github urls
# url = rewrite_url(source)
# if str(source).startswith("http://") or str(source).startswith("https://"):
#     log.debug(f"Download {url} to {fw_filename}")
#     response = requests.get(url)

#     if response.status_code == 200:
#         with open(fw_filename, "wb") as file:
#             file.write(response.content)
#             log.info("File downloaded and saved successfully.")
#             return True
#     else:
#         print("Failed to download the file.")
#         return False
# return False


# github.com/<owner>/<repo>@<branch>#<commit>
# $remote_url = git remote get-url origin
# $branch = git rev-parse --abbrev-ref HEAD
# $commit = git rev-parse --short HEAD
# if ($remote_url -match "github.com[:/](.+)/(.+?)(\.git)?$") {
#     $owner = $matches[1]
#     $repo = $matches[2]
#     "github.com/$owner/$repo@$branch#$commit"
# }
