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
import re
import shutil
import stat
import tarfile
import tempfile
import urllib.parse
import urllib.request
import uuid
import zipfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath, PureWindowsPath

OBSCURA_REPO = "h4ckf0r0day/obscura"
# Pin a known-good default; override per invocation with --obscura-version.
DEFAULT_OBSCURA_VERSION = "v0.1.8"
_GITHUB_HOST = "github.com"
_VERSION_RE = re.compile(r"^v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")

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

_ASSET_SHA256: dict[tuple[str, str], str] = {
    ("v0.1.8", "obscura-aarch64-linux.tar.gz"): "58602b8293a93caa6fdac98a2868292c9a91ecab86d835f9bd20361ac7e48ea0",
    ("v0.1.8", "obscura-aarch64-macos.tar.gz"): "dfa84fa20e0e33c7b1af9ded190cdbf928c5a52a3edb308600595e11455ee7bb",
    ("v0.1.8", "obscura-x86_64-linux.tar.gz"): "e54d07054047d4180247f03bea08d1bd724ef1859829331a433da972f973988b",
    ("v0.1.8", "obscura-x86_64-macos.tar.gz"): "34cbeb9706f0af95de7fd6693346a3f1d601b35ddc3c623f060a363e9adac206",
    ("v0.1.8", "obscura-x86_64-windows.zip"): "5bcbf6789897f7e6d67a160f45510cf06e6d44a966357aa5f8b238961bac0b53",
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


def _validate_version(version: str) -> str:
    if not _VERSION_RE.fullmatch(version):
        raise ValueError(
            "Invalid Obscura version. Expected a pinned release tag like v1.2.3; "
            "slashes, URL components, and unscoped refs are not allowed."
        )
    return version


def _expected_archive_digest(version: str, asset_file: str) -> str:
    digest = _ASSET_SHA256.get((version, asset_file))
    if not digest:
        raise RuntimeError(
            f"No pinned SHA-256 digest for Obscura {version} asset {asset_file}. "
            "Refusing to install an unverified release."
        )
    return digest


def _validate_release_url(url: str, version: str, asset_file: str) -> None:
    parsed = urllib.parse.urlparse(url)
    expected_path = f"/{OBSCURA_REPO}/releases/download/{version}/{asset_file}"
    if parsed.scheme != "https" or parsed.netloc != _GITHUB_HOST or parsed.path != expected_path or parsed.query or parsed.fragment:
        raise ValueError(f"Refusing to download Obscura from unexpected release URL: {url}")


def _release_url(version: str, asset_file: str) -> str:
    version = _validate_version(version)
    if "/" in asset_file or "\\" in asset_file:
        raise ValueError(f"Invalid Obscura asset name: {asset_file!r}")
    url = f"https://{_GITHUB_HOST}/{OBSCURA_REPO}/releases/download/{version}/{asset_file}"
    _validate_release_url(url, version, asset_file)
    return url


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
    sibling = Path(__file__).resolve().parents[2].parent / "obscura" / "target" / "release" / name
    if sibling.is_file():
        return str(sibling)

    return None


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "crawler_cli-installer"})
    with urllib.request.urlopen(req) as resp, open(dest, "wb") as fh:  # noqa: S310 - github release
        shutil.copyfileobj(resp, fh)


def _sha256_file(path: Path) -> str:
    import hashlib

    hasher = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _verify_archive_digest(archive: Path, expected_sha256: str) -> None:
    actual = _sha256_file(archive)
    if actual.lower() != expected_sha256.lower():
        raise RuntimeError(
            f"Obscura archive checksum mismatch for {archive.name}: expected {expected_sha256}, got {actual}"
        )


def _safe_member_path(name: str, dest_dir: Path) -> Path:
    if not name or name in {".", "./"} or "\x00" in name or "\\" in name:
        raise RuntimeError(f"Unsafe Obscura archive member path: {name!r}")

    posix_path = PurePosixPath(name)
    windows_path = PureWindowsPath(name)
    if posix_path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise RuntimeError(f"Unsafe absolute Obscura archive member path: {name!r}")
    if any(part in {"", ".", ".."} for part in posix_path.parts):
        raise RuntimeError(f"Unsafe Obscura archive member path: {name!r}")

    root = dest_dir.resolve()
    candidate = (root / Path(*posix_path.parts)).resolve(strict=False)
    if candidate != root and root not in candidate.parents:
        raise RuntimeError(f"Obscura archive member escapes extraction root: {name!r}")
    return candidate


def _reject_zip_member(info: zipfile.ZipInfo) -> None:
    mode = (info.external_attr >> 16) & 0o170000
    if mode in {
        stat.S_IFLNK,
        stat.S_IFCHR,
        stat.S_IFBLK,
        stat.S_IFIFO,
        stat.S_IFSOCK,
    }:
        raise RuntimeError(f"Refusing unsafe Obscura zip member type: {info.filename!r}")


def _extract_zip_safely(archive: Path, dest_dir: Path) -> None:
    seen: set[Path] = set()
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            _reject_zip_member(info)
            dest = _safe_member_path(info.filename, dest_dir)
            if dest in seen:
                raise RuntimeError(f"Duplicate Obscura archive member path: {info.filename!r}")
            seen.add(dest)
            if info.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                raise RuntimeError(f"Obscura archive would overwrite staged path: {info.filename!r}")
            with zf.open(info) as src, open(dest, "xb") as fh:
                shutil.copyfileobj(src, fh)


def _reject_tar_member(member: tarfile.TarInfo) -> None:
    if member.issym() or member.islnk() or member.isdev() or member.isfifo():
        raise RuntimeError(f"Refusing unsafe Obscura tar member type: {member.name!r}")
    if not (member.isfile() or member.isdir()):
        raise RuntimeError(f"Refusing unsupported Obscura tar member type: {member.name!r}")


def _extract_tar_safely(archive: Path, dest_dir: Path) -> None:
    seen: set[Path] = set()
    with tarfile.open(archive, "r:gz") as tf:
        for member in tf.getmembers():
            _reject_tar_member(member)
            dest = _safe_member_path(member.name, dest_dir)
            if dest in seen:
                raise RuntimeError(f"Duplicate Obscura archive member path: {member.name!r}")
            seen.add(dest)
            if member.isdir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            extracted = tf.extractfile(member)
            if extracted is None:
                raise RuntimeError(f"Could not read Obscura tar member: {member.name!r}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                raise RuntimeError(f"Obscura archive would overwrite staged path: {member.name!r}")
            with extracted, open(dest, "xb") as fh:
                shutil.copyfileobj(extracted, fh)
            os.chmod(dest, member.mode & 0o777)


def _extract(archive: Path, dest_dir: Path) -> None:
    if archive.suffix == ".zip" or archive.name.endswith(".zip"):
        _extract_zip_safely(archive, dest_dir)
        return
    _extract_tar_safely(archive, dest_dir)


def _expected_binary_names(is_windows: bool) -> tuple[str, str]:
    suffix = ".exe" if is_windows else ""
    return ("obscura" + suffix, "obscura-worker" + suffix)


def _validate_staged_install(staging_dir: Path, expected_names: Iterable[str]) -> None:
    for name in expected_names:
        path = staging_dir / name
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"Obscura archive did not stage expected binary file: {name}")
        if path.stat().st_size <= 0:
            raise RuntimeError(f"Obscura archive staged an empty binary file: {name}")


def _mark_executable(staging_dir: Path, expected_names: Iterable[str]) -> None:
    for name in expected_names:
        path = staging_dir / name
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _replace_tree_atomically(staging_dir: Path, target: Path) -> None:
    target_parent = target.parent
    target_parent.mkdir(parents=True, exist_ok=True)
    backup = target_parent / f".{target.name}.backup-{os.getpid()}-{uuid.uuid4().hex}"

    if target.exists() or target.is_symlink():
        if not target.is_dir() or target.is_symlink():
            raise RuntimeError(f"Obscura install target is not a directory: {target}")
        os.replace(target, backup)
        try:
            os.replace(staging_dir, target)
        except Exception:
            os.replace(backup, target)
            raise
        else:
            shutil.rmtree(backup)
        return

    os.replace(staging_dir, target)


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
    version = _validate_version(version)
    target = install_dir()
    binary = target / _binary_name()
    if binary.is_file() and not force:
        log(f"Obscura already installed at {binary} (use --force to reinstall).")
        return str(binary)

    asset = _asset_for_host()
    is_windows = platform.system().lower() == "windows"
    ext = ".zip" if is_windows else ".tar.gz"
    asset_file = f"{asset}{ext}"
    expected_sha256 = _expected_archive_digest(version, asset_file)
    url = _release_url(version, asset_file)
    expected_names = _expected_binary_names(is_windows)

    log(f"Downloading {asset_file} ({version})...")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
        archive = Path(tmp) / asset_file
        staging = Path(tmp) / "staging"
        staging.mkdir()
        _download(url, archive)
        _verify_archive_digest(archive, expected_sha256)
        log("Extracting...")
        _extract(archive, staging)
        _validate_staged_install(staging, expected_names)
        _mark_executable(staging, expected_names)
        _replace_tree_atomically(staging, target)

    if not binary.is_file():
        raise RuntimeError(f"Install completed but {binary} is missing.")

    log(f"Installed Obscura to {binary}")
    log("crawler_cli will now find it automatically when you pass --obscura.")
    return str(binary)
