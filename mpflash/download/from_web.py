import functools
import itertools
import re
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin


from loguru import logger as log
from rich.progress import track

from mpflash.common import PORT_FWTYPES, FWInfo
from mpflash.downloaded import clean_downloaded_firmwares
from mpflash.errors import MPFlashError
from mpflash.mpboard_id import get_known_ports
from mpflash.versions import clean_version



MICROPYTHON_ORG_URL = "https://micropython.org/"


# Regexes to remove dates and hashes in the filename that just get in the way
RE_DATE = r"(-\d{8}-)"
RE_HASH = r"(.g[0-9a-f]+\.)"
# regex to extract the version and the build from the firmware filename
# group 1 is the version, group 2 is the build
RE_VERSION_PREVIEW = r"v([\d\.]+)-?(?:preview\.)?(\d+)?\."


# 'RPI_PICO_W-v1.23.uf2'
# 'RPI_PICO_W-v1.23.0.uf2'
# 'RPI_PICO_W-v1.23.0-406.uf2'
# 'RPI_PICO_W-v1.23.0-preview.406.uf2'
# 'RPI_PICO_W-v1.23.0-preview.4.uf2'
# 'RPI_PICO_W-v1.23.0.uf2'
# 'https://micropython.org/resources/firmware/RPI_PICO_W-20240531-v1.24.0-preview.10.gc1a6b95bf.uf2'
# 'https://micropython.org/resources/firmware/RPI_PICO_W-20240531-v1.24.0-preview.10.uf2'
# 'RPI_PICO_W-v1.24.0-preview.10.gc1a6b95bf.uf2'
# use functools.lru_cache to avoid needing to download pages multiple times
@functools.lru_cache(maxsize=500)
def get_page(page_url: str) -> str:
    """Get the HTML of a page and return it as a string."""
    # Just in time import
    import requests

    response = requests.get(page_url)
    return response.content.decode()


@functools.lru_cache(maxsize=500)
def get_board_urls(page_url: str) -> List[Dict[str, str]]:
    """
    Get the urls to all the board pages listed on this page.
    Assumes that all links to firmware  have "class": "board-card"

    Args:
        page_url (str): The url of the page to get the board urls from.

    Returns:
        List[Dict[str, str]]: A list of dictionaries containing the board name and url.

    """
    # Just in time import
    from bs4 import BeautifulSoup

    downloads_html = get_page(page_url)
    soup = BeautifulSoup(downloads_html, "html.parser")
    tags = soup.find_all("a", recursive=True, attrs={"class": "board-card"})
    # assumes that all links are relative to the page url
    boards = [tag.get("href") for tag in tags]  # type: ignore
    if "?" in page_url:
        page_url = page_url.split("?")[0]
    return [{"board": board, "url": page_url + board} for board in boards]  # type: ignore


def board_firmware_urls(board_url: str, base_url: str, ext: str) -> List[str]:
    """
    Get the urls to all the firmware files for a board.
    Args:
        page_url (str): The url of the page to get the board urls from.
    ??? base_url (str): The base url to join the relative urls to.
        ext (str): The extension of the firmware files to get. (with or withouth leading .)

    the urls are relative urls to the site root

    """
    # Just in time import
    from bs4 import BeautifulSoup

    html = get_page(board_url)
    soup = BeautifulSoup(html, "html.parser")
    # get all the a tags:
    #  1. that have a url that starts with `/resources/firmware/`
    #  2. end with a matching extension for this port.
    tags = soup.find_all(
        "a",
        recursive=True,
        attrs={"href": re.compile(r"^/resources/firmware/.*\." + ext.lstrip(".") + "$")},
    )
    if "?" in base_url:
        base_url = base_url.split("?")[0]
    links: List = [urljoin(base_url, tag.get("href")) for tag in tags]  # type: ignore
    return links


# boards we are interested in ( this avoids getting a lot of boards we don't care about)
# The first run takes ~60 seconds to run for 4 ports , all boards
# so it makes sense to cache the results and skip boards as soon as possible
def get_boards(ports: List[str], boards: List[str], clean: bool) -> List[FWInfo]:
    # sourcery skip: use-getitem-for-re-match-groups
    """
    Retrieves a list of firmware information for the specified ports and boards.

    Args:
        ports (List[str]): The list of ports to check for firmware.
        boards (List[str]): The list of boards to retrieve firmware information for.
        clean (bool): A flag indicating whether to perform a clean retrieval.

    Returns:
        List[FWInfo]: A list of firmware information for the specified ports and boards.

    """
    board_urls: List[FWInfo] = []
    if ports is None:
        ports = get_known_ports()
    for port in ports:
        download_page_url = f"{MICROPYTHON_ORG_URL}download/?port={port}"
        urls = get_board_urls(download_page_url)
        # filter out boards we don't care about
        urls = [board for board in urls if board["board"] in boards]
        # add the port to the board urls
        for board in urls:
            board["port"] = port

        for board in track(
            urls,
            description=f"Checking {port} download pages",
            transient=True,
            refresh_per_second=1,
            show_speed=False,
        ):
            # add a board to the list for each firmware found
            firmware_urls: List[str] = []
            for ext in PORT_FWTYPES[port]:
                firmware_urls += board_firmware_urls(board["url"], MICROPYTHON_ORG_URL, ext)
            for _url in firmware_urls:
                board["firmware"] = _url
                fname = Path(board["firmware"]).name
                if clean:
                    # remove date from firmware name
                    fname = re.sub(RE_DATE, "-", fname)
                    # remove hash from firmware name
                    fname = re.sub(RE_HASH, ".", fname)
                fw_info = FWInfo(
                    filename=fname,
                    port=port,
                    board=board["board"],
                    preview="preview" in _url,
                    firmware=_url,
                    version="",
                )
                # board["firmware"] = _url
                # board["preview"] = "preview" in _url  # type: ignore
                if ver_match := re.search(RE_VERSION_PREVIEW, _url):
                    fw_info.version = clean_version(ver_match.group(1))
                    fw_info.build = ver_match.group(2) or "0"
                fw_info.preview = fw_info.build != "0"
                # # else:
                # #     board.$1= ""
                # if "preview." in fw_info.version:
                #     fw_info.build = fw_info.version.split("preview.")[-1]
                # else:
                #     fw_info.build = "0"

                fw_info.ext = Path(fw_info.firmware).suffix
                fw_info.variant = fw_info.filename.split("-v")[0] if "-v" in fw_info.filename else ""

                board_urls.append(fw_info)
    return board_urls



def fetch_firmware_files(available_firmwares: List[FWInfo], firmware_folder: Path, force: bool):
    # Just in time import
    import requests

    for board in available_firmwares:
        filename = firmware_folder / board.port / board.filename
        filename.parent.mkdir(exist_ok=True)
        if filename.exists() and not force:
            log.debug(f" {filename} already exists, skip download")
            continue
        log.info(f"Downloading {board.firmware}")
        log.info(f"         to {filename}")
        try:
            r = requests.get(board.firmware, allow_redirects=True)
            with open(filename, "wb") as fw:
                fw.write(r.content)
            board.filename = str(filename.relative_to(firmware_folder))
        except requests.RequestException as e:
            log.exception(e)
            continue
        yield board
