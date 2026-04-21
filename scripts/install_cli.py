#!/usr/bin/env python3
"""Python-first installer for the Atri Code CLI.

This script can install from:
- local repository path (developer mode)
- source archive URL (end-user mode)

It installs:
- Python package files into ~/.local/share/atri-code-cli/
- launcher binary ~/.local/bin/atri-cli
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import sys
import tarfile
import tempfile
import textwrap
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_ARCHIVE_URL = os.environ.get(
    "TARBAR_INSTALL_ARCHIVE_URL",
    "https://github.com/ToniBirat7/Agentic_AI/archive/refs/heads/master.tar.gz",
)
PRIMARY_LAUNCHER = "atri-cli"
COMPAT_LAUNCHER = "tarbar"


def _ensure_python_version() -> None:
    if sys.version_info < (3, 10):
        raise SystemExit("Tarbar installer requires Python 3.10 or newer")


def _safe_rmtree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def _write_launcher(bin_path: Path, package_root: Path) -> None:
    launcher = textwrap.dedent(
        f"""\
        #!/usr/bin/env python3
        import sys
        from pathlib import Path

        PACKAGE_ROOT = Path({str(package_root)!r})
        sys.path.insert(0, str(PACKAGE_ROOT))

        from tarbar_cli.main import main

        if __name__ == "__main__":
            main()
        """
    )
    bin_path.write_text(launcher, encoding="utf-8")
    current_mode = bin_path.stat().st_mode
    bin_path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _write_compat_launcher(bin_path: Path, primary_bin: Path) -> None:
    launcher = textwrap.dedent(
        f"""\
        #!/usr/bin/env sh
        echo "[deprecated] 'tarbar' is a compatibility alias. Use 'atri-cli' instead." >&2
        exec {str(primary_bin)!r} "$@"
        """
    )
    bin_path.write_text(launcher, encoding="utf-8")
    current_mode = bin_path.stat().st_mode
    bin_path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _install_from_repo(repo_root: Path, install_root: Path, bin_root: Path) -> Path:
    src_package = repo_root / "apps" / "cli" / "tarbar_cli"
    if not src_package.exists():
        raise SystemExit(f"Could not find CLI package at: {src_package}")

    install_root.mkdir(parents=True, exist_ok=True)
    bin_root.mkdir(parents=True, exist_ok=True)

    target_package = install_root / "tarbar_cli"
    _safe_rmtree(target_package)
    shutil.copytree(src_package, target_package)

    launcher_path = bin_root / PRIMARY_LAUNCHER
    _write_launcher(launcher_path, install_root)

    compat_launcher_path = bin_root / COMPAT_LAUNCHER
    _write_compat_launcher(compat_launcher_path, launcher_path)

    return launcher_path


def _download_archive(archive_url: str, destination: Path) -> None:
    archive_candidates = [archive_url]
    if archive_url.endswith("/master.tar.gz"):
        archive_candidates.append(archive_url.replace("/master.tar.gz", "/main.tar.gz"))
    elif archive_url.endswith("/main.tar.gz"):
        archive_candidates.append(archive_url.replace("/main.tar.gz", "/master.tar.gz"))

    last_error = None
    for candidate_url in archive_candidates:
        req = urllib.request.Request(candidate_url, headers={"User-Agent": "tarbar-installer/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                data = response.read()
            destination.write_bytes(data)
            return
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code != 404:
                raise

    if last_error is not None:
        raise last_error
    raise RuntimeError("Unable to download installer archive from configured URLs")


def _extract_repo_root_from_archive(archive_path: Path, extract_dir: Path) -> Path:
    with tarfile.open(archive_path, mode="r:gz") as tf:
        tf.extractall(path=extract_dir)

    candidates = [p for p in extract_dir.iterdir() if p.is_dir()]
    if not candidates:
        raise SystemExit("Archive extraction failed: no repository directory found")

    # GitHub archives generally produce a single top-level directory.
    return candidates[0]


def install_from_archive(archive_url: str, install_root: Path, bin_root: Path) -> Path:
    with tempfile.TemporaryDirectory(prefix="tarbar-install-") as tmp:
        tmp_path = Path(tmp)
        archive_path = tmp_path / "repo.tar.gz"
        _download_archive(archive_url, archive_path)
        repo_root = _extract_repo_root_from_archive(archive_path, tmp_path)
        return _install_from_repo(repo_root, install_root, bin_root)


def _print_success(launcher_path: Path, bin_root: Path) -> None:
    print("Atri Code CLI installed successfully.")
    print(f"Launcher: {launcher_path}")

    path_entries = os.environ.get("PATH", "").split(":")
    if str(bin_root) not in path_entries:
        print()
        print("Add this directory to your PATH:")
        print(f"  export PATH=\"{bin_root}:$PATH\"")
        print("Then restart your shell.")

    print()
    print("Try:")
    print("  atri-cli --help")
    print("  atri-cli doctor")


def main() -> None:
    _ensure_python_version()

    parser = argparse.ArgumentParser(description="Install Atri Code CLI")
    parser.add_argument(
        "--archive-url",
        default=DEFAULT_ARCHIVE_URL,
        help="Source archive URL for end-user installation",
    )
    parser.add_argument(
        "--from-local-repo",
        help="Install from a local repository path instead of downloading",
    )
    parser.add_argument(
        "--install-root",
        default=os.path.expanduser("~/.local/share/atri-code-cli"),
        help="Install root for Python package files",
    )
    parser.add_argument(
        "--bin-root",
        default=os.path.expanduser("~/.local/bin"),
        help="Install root for launcher binaries",
    )
    args = parser.parse_args()

    install_root = Path(args.install_root).expanduser().resolve()
    bin_root = Path(args.bin_root).expanduser().resolve()

    if args.from_local_repo:
        repo_root = Path(args.from_local_repo).expanduser().resolve()
        launcher = _install_from_repo(repo_root, install_root, bin_root)
    else:
        launcher = install_from_archive(args.archive_url, install_root, bin_root)

    _print_success(launcher, bin_root)


if __name__ == "__main__":
    main()
