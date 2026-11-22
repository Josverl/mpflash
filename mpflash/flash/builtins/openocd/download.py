"""Install the pinned Infineon OpenOCD release when no suitable one is available."""

from __future__ import annotations

import hashlib
import platform
import shutil
import stat
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from mpflash.errors import MPFlashError
from mpflash.logger import log

from .runner import ENV_VAR, find_openocd, is_suitable

OPENOCD_RELEASE = "release-v5.16.1"
OPENOCD_VERSION = "5.16.1.4486"
_RELEASE_URL = f"https://github.com/Infineon/openocd/releases/download/{OPENOCD_RELEASE}"


@dataclass(frozen=True)
class _Asset:
    name: str
    sha256: str


# Keyed by (os, cpu). Only the platforms Infineon publishes a package for are listed.
_ASSETS = {
    ("linux", "x64"): _Asset(
        f"openocd-{OPENOCD_VERSION}-linux.tar.gz",
        "d3c6d0142d29c898f11c124140d44e0ca64fe58794aea15769eb6a981293c637",
    ),
    ("windows", "x64"): _Asset(
        f"openocd-{OPENOCD_VERSION}-windows.zip",
        "5bfde009a525c6a2490f50456efc18ba8420892d0e7b5a2a47e7727603deec87",
    ),
    ("macos", "arm64"): _Asset(
        f"openocd-{OPENOCD_VERSION}-macos-arm64.zip",
        "7b1b3dfb3fc13c2c189bdcc14b25c08fa06cc50c5e37b21fd093305fa0eedafd",
    ),
}

_EXE_NAME = "openocd.exe" if sys.platform == "win32" else "openocd"


def _host_key() -> tuple[str, str]:
    os_name = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    machine = platform.machine().lower()
    cpu = "x64" if machine in {"x86_64", "amd64", "x64"} else "arm64" if machine in {"arm64", "aarch64"} else machine
    return os_name, cpu


def download_supported() -> bool:
    """True when Infineon publishes an OpenOCD package for this host."""
    return _host_key() in _ASSETS


def install_dir() -> Path:
    """Where the pinned release is installed (outside the firmware folder, which is scanned for firmware)."""
    import platformdirs

    return platformdirs.user_cache_path("mpflash") / "tools" / "openocd" / OPENOCD_VERSION


def _installed_executable() -> Optional[Path]:
    root = install_dir()
    if not root.is_dir():
        return None
    for candidate in root.rglob(_EXE_NAME):
        if candidate.parent.name == "bin" and candidate.is_file():
            return candidate
    return None


def _confirm_download(asset: _Asset, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    from mpflash.config import config

    # Non-interactive runs (CI, pipes) download without asking.
    if not (config.interactive and sys.stdin.isatty()):
        return True
    import click

    return click.confirm(
        f"Flashing PSOC Edge needs the Infineon build of OpenOCD ({asset.name}, ~5 MB from github.com/Infineon/openocd). Download it now?",
        default=True,
    )


def _inside(base: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
    except ValueError:
        return False
    return True


def _extract(archive: Path, dest: Path) -> None:
    """Extract ``archive`` to ``dest``, rejecting entries that would escape it."""
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if not _inside(dest, dest / info.filename):
                    raise MPFlashError(f"Unsafe path in OpenOCD archive: {info.filename}")
            zf.extractall(dest)
        return

    with tarfile.open(archive) as tf:
        for member in tf.getmembers():
            if not _inside(dest, dest / member.name):
                raise MPFlashError(f"Unsafe path in OpenOCD archive: {member.name}")
            if not (member.isfile() or member.isdir()):
                raise MPFlashError(f"Unexpected entry type in OpenOCD archive: {member.name}")
        tf.extractall(dest)  # noqa: S202 - members validated above


def _download(asset: _Asset, target: Path) -> None:
    import requests

    url = f"{_RELEASE_URL}/{asset.name}"
    log.info(f"Downloading {url}")
    digest = hashlib.sha256()
    try:
        with requests.get(url, stream=True, timeout=60) as response:
            response.raise_for_status()
            with open(target, "wb") as fh:
                for chunk in response.iter_content(chunk_size=1 << 16):
                    digest.update(chunk)
                    fh.write(chunk)
    except requests.RequestException as error:
        raise MPFlashError(f"Could not download {url}: {error}") from error
    if digest.hexdigest() != asset.sha256:
        raise MPFlashError(f"Checksum mismatch for {asset.name}: expected {asset.sha256}, got {digest.hexdigest()}")


def _install(asset: _Asset) -> Path:
    final = install_dir()
    final.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=final.parent) as tmp:
        tmp_path = Path(tmp)
        archive = tmp_path / asset.name
        _download(asset, archive)
        staging = tmp_path / "extracted"
        staging.mkdir()
        _extract(archive, staging)
        if final.exists():
            shutil.rmtree(final)
        shutil.move(str(staging), str(final))

    exe = _installed_executable()
    if exe is None:
        raise MPFlashError(f"{asset.name} did not contain bin/{_EXE_NAME}")
    if sys.platform != "win32":
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    if not is_suitable(exe):
        raise MPFlashError(f"Downloaded OpenOCD at {exe} could not be run")
    log.success(f"Installed Infineon OpenOCD {OPENOCD_VERSION} to {final}")
    return exe


def ensure_openocd(assume_yes: bool = False) -> Path:
    """Return a usable Infineon OpenOCD, downloading the pinned release if none is found.

    Raises:
        MPFlashError: no suitable OpenOCD and it cannot (or may not) be downloaded.
    """
    if exe := find_openocd():
        return exe
    if (exe := _installed_executable()) and is_suitable(exe):
        return exe

    hint = f"Install the Infineon OpenOCD from https://github.com/Infineon/openocd/releases and set {ENV_VAR} to the openocd executable."
    asset = _ASSETS.get(_host_key())
    if asset is None:
        raise MPFlashError(f"No Infineon OpenOCD package is published for {'/'.join(_host_key())}. {hint}")
    if not _confirm_download(asset, assume_yes):
        raise MPFlashError(f"Infineon OpenOCD is required to flash PSOC Edge. {hint}")
    return _install(asset)
