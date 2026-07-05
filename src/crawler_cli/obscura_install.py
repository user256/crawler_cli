"""Obscura binary resolution and installer.

Obscura is a native Rust binary (https://github.com/h4ckf0r0day/obscura), not a
Python dependency, so it cannot ship inside the crawler_cli wheel. This module
gives crawler_cli a Playwright-style story instead:

- ``find_obscura_binary()`` locates an existing ``obscura`` binary across the
  sensible places (explicit override, env var, the install dir this module
  manages, PATH, a sibling source checkout).
- ``install_obscura()`` downloads the correct prebuilt release for the host
  OS/arch from GitHub and unpacks it into a per-user data dir, so that
  ``crawler-cli install-obscura`` followed by ``--obscura`` works with no
  further configuration.
"""

from __future__ import annotations

import os
import platform
import shutil
import stat
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

OBSCURA_REPO = "h4ckf0r0day/obscura"
# Pin a known-good default; override per invocation with --obscura-version.
DEFAULT_OBSCURA_VERSION = "v0.1.8"

# (system, machine) -> release asset basename (without extension). Mirrors the
# matrix in obscura's .github/workflows/release.yml.
_ASSET_MATRIX: dict[tuple[str, str], str] = {
    ("linux", "x86_64"): "obscura-x86_64-linux",
    ("linux", "amd64"): "obscura-x86_64-linux",
    ("linux", "aarch64"): "obscura-aarch64-linux",
    ("linux", "arm64"): "obscura-aarch64-linux",
    ("darwin", "x86_64"): "obscura-x86_64-macos",
    ("darwin", "arm64"): "obscura-aarch64-macos",
    ("darwin", "aarch64"): "obscura-aarch64-macos",
    ("windows", "x86_64"): "obscura-x86_64-windows",
    ("windows", "amd64"): "obscura-x86_64-windows",
}


def install_dir() -> Path:
    """Per-user directory where ``install_obscura`` places the binaries.

    Honours ``XDG_DATA_HOME``; falls back to ``~/.local/share``.
    """
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "crawler_cli" / "obscura"


def _binary_name() -> str:
    return "obscura.exe" if platform.system().lower() == "windows" else "obscura"


def _asset_for_host() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    key = (system, machine)
    if key not in _ASSET_MATRIX:
        raise RuntimeError(
            f"No prebuilt Obscura release for this platform ({system}/{machine}). "
            f"Build it from source (https://github.com/{OBSCURA_REPO}) and point "
            "crawler_cli at it with --obscura-binary or the OBSCURA_BINARY env var."
        )
    return _ASSET_MATRIX[key]


def find_obscura_binary(explicit: str | None = None) -> str | None:
    """Return a usable obscura binary path, or None if none is found.

    Resolution order (first hit wins):
    1. *explicit* path/name (e.g. from --obscura-binary), if it exists or
       resolves on PATH.
    2. ``OBSCURA_BINARY`` environment variable.
    3. The install dir managed by ``install_obscura``.
    4. ``obscura`` on PATH.
    5. A sibling source checkout at ``../obscura/target/release/obscura``.
    """
    name = _binary_name()

    candidates: list[str | None] = [explicit, os.environ.get("OBSCURA_BINARY")]
    for cand in candidates:
        if not cand:
            continue
        # A bare name (no separator) should be resolved on PATH.
        if os.sep not in cand and (os.altsep is None or os.altsep not in cand):
            resolved = shutil.which(cand)
            if resolved:
                return resolved
        elif Path(cand).is_file():
            return str(Path(cand).resolve())

    installed = install_dir() / name
    if installed.is_file():
        return str(installed)

    on_path = shutil.which("obscura")
    if on_path:
        return on_path

    # Sibling source checkout next to the crawler_cli repo.
    sibling = (
        Path(__file__).resolve().parents[2].parent / "obscura" / "target" / "release" / name
    )
    if sibling.is_file():
        return str(sibling)

    return None


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "crawler_cli-installer"})
    with urllib.request.urlopen(req) as resp, open(dest, "wb") as fh:  # noqa: S310 - github release
        shutil.copyfileobj(resp, fh)


def _extract(archive: Path, dest_dir: Path) -> None:
    if archive.suffix == ".zip" or archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest_dir)
    else:
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(dest_dir)  # noqa: S202 - trusted GitHub release artifact


def install_obscura(
    version: str = DEFAULT_OBSCURA_VERSION,
    *,
    force: bool = False,
    log=print,
) -> str:
    """Download and install the prebuilt Obscura binaries for this host.

    Returns the path to the installed ``obscura`` binary. Installs both
    ``obscura`` and ``obscura-worker`` (the latter is required for multi-worker
    ``obscura serve`` and ``scrape``). Idempotent unless *force* is set.
    """
    target = install_dir()
    binary = target / _binary_name()
    if binary.is_file() and not force:
        log(f"Obscura already installed at {binary} (use --force to reinstall).")
        return str(binary)

    asset = _asset_for_host()
    is_windows = platform.system().lower() == "windows"
    ext = ".zip" if is_windows else ".tar.gz"
    asset_file = f"{asset}{ext}"
    url = f"https://github.com/{OBSCURA_REPO}/releases/download/{version}/{asset_file}"

    target.mkdir(parents=True, exist_ok=True)
    log(f"Downloading {asset_file} ({version})...")
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / asset_file
        _download(url, archive)
        log("Extracting...")
        _extract(archive, target)

    if not binary.is_file():
        raise RuntimeError(
            f"Install completed but {binary} is missing — the release asset "
            f"layout for {asset_file} may have changed."
        )

    # Ensure the binaries are executable (tarball usually preserves this; be safe).
    for name in (_binary_name(), "obscura-worker" + (".exe" if is_windows else "")):
        p = target / name
        if p.is_file():
            p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    log(f"Installed Obscura to {binary}")
    log("crawler_cli will now find it automatically when you pass --obscura.")
    return str(binary)
