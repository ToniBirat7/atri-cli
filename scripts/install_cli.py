#!/usr/bin/env python3
"""Python-first installer for the Tarbar CLI.

This script can install from:
- local repository path (developer mode)
- source archive URL (end-user mode)

It installs:
- Python package files into ~/.local/share/tarbar-cli/
- launcher binaries in ~/.local/bin (tarbar and optional aliases)
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
import urllib.request
from pathlib import Path

DEFAULT_ARCHIVE_URL = os.environ.get(
    "TARBAR_INSTALL_ARCHIVE_URL",
    "https://github.com/ToniBirat7/Agentic_AI/archive/refs/heads/master.tar.gz",
)
LAUNCHER_MANAGED_MARKER = "# tarbar-managed-launcher:1"


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
        {LAUNCHER_MANAGED_MARKER}
        import os
        import subprocess
        import sys
        import urllib.request
        from pathlib import Path

        PACKAGE_ROOT = Path({str(package_root)!r})
        BOOTSTRAP_URL = os.environ.get(
            "TARBAR_BOOTSTRAP_URL",
            "https://raw.githubusercontent.com/ToniBirat7/Agentic_AI/master/scripts/local_up.py",
        )
        RUNTIME_REPO_DIR = os.environ.get(
            "TARBAR_RUNTIME_REPO_DIR",
            str(Path.home() / ".local/share/tarbar-runtime/Agentic_AI"),
        )
        TARBAR_BRANCH = os.environ.get("TARBAR_BRANCH", "master")

        def _healthy(url: str) -> bool:
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    return 200 <= response.status < 300
            except Exception:
                return False

        def _should_autostart(argv: list[str]) -> bool:
            if os.environ.get("TARBAR_NO_AUTOSTART", "").strip().lower() in {{"1", "true", "yes"}}:
                return False
            return "-h" not in argv and "--help" not in argv

        def _bootstrap_runtime_if_needed(argv: list[str]) -> None:
            if not _should_autostart(argv):
                return

            if _healthy("http://127.0.0.1:8000/health") and _healthy("http://127.0.0.1:8001/health"):
                return

            print("[tarbar] Services not ready, bootstrapping local runtime...", file=sys.stderr)
            request = urllib.request.Request(
                BOOTSTRAP_URL,
                headers={{"User-Agent": "tarbar-launcher/1.0"}},
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                script = response.read().decode("utf-8")

            cmd = [
                sys.executable,
                "-",
                "--branch",
                TARBAR_BRANCH,
                "--mode",
                "cli",
                "--repo-dir",
                RUNTIME_REPO_DIR,
                "--no-production-prune",
                "--no-cache-clean",
            ]
            subprocess.run(cmd, input=script, text=True, check=True)

            if not (_healthy("http://127.0.0.1:8000/health") and _healthy("http://127.0.0.1:8001/health")):
                raise SystemExit("[tarbar] runtime bootstrap finished but services are still unhealthy")

        sys.path.insert(0, str(PACKAGE_ROOT))

        _bootstrap_runtime_if_needed(sys.argv[1:])

        from tarbar_cli.main import main

        if __name__ == "__main__":
            main()
        """
    )
    bin_path.write_text(launcher, encoding="utf-8")
    current_mode = bin_path.stat().st_mode
    bin_path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _is_managed_launcher(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        return LAUNCHER_MANAGED_MARKER in path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False


def _should_skip_alias(alias: str, alias_path: Path) -> bool:
    existing = shutil.which(alias)
    if alias_path.exists() and not _is_managed_launcher(alias_path):
        return True
    if existing and Path(existing).resolve() != alias_path.resolve() and not _is_managed_launcher(Path(existing)):
        return True
    return False


def _install_from_repo(
    repo_root: Path,
    install_root: Path,
    bin_root: Path,
    command_name: str,
    aliases: list[str],
) -> tuple[Path, list[Path], list[str]]:
    src_package = repo_root / "apps" / "cli" / "tarbar_cli"
    if not src_package.exists():
        raise SystemExit(f"Could not find CLI package at: {src_package}")

    install_root.mkdir(parents=True, exist_ok=True)
    bin_root.mkdir(parents=True, exist_ok=True)

    target_package = install_root / "tarbar_cli"
    _safe_rmtree(target_package)
    shutil.copytree(src_package, target_package)

    launcher_path = bin_root / command_name
    _write_launcher(launcher_path, install_root)
    alias_paths: list[Path] = []
    skipped_aliases: list[str] = []
    for alias in aliases:
        alias = alias.strip()
        if not alias or alias == command_name:
            continue
        alias_path = bin_root / alias
        if _should_skip_alias(alias, alias_path):
            skipped_aliases.append(alias)
            continue
        _write_launcher(alias_path, install_root)
        alias_paths.append(alias_path)

    return launcher_path, alias_paths, skipped_aliases


def _download_archive(archive_url: str, destination: Path) -> None:
    req = urllib.request.Request(archive_url, headers={"User-Agent": "tarbar-installer/1.0"})
    with urllib.request.urlopen(req, timeout=120) as response:
        data = response.read()
    destination.write_bytes(data)


def _extract_repo_root_from_archive(archive_path: Path, extract_dir: Path) -> Path:
    with tarfile.open(archive_path, mode="r:gz") as tf:
        tf.extractall(path=extract_dir)

    candidates = [p for p in extract_dir.iterdir() if p.is_dir()]
    if not candidates:
        raise SystemExit("Archive extraction failed: no repository directory found")

    # GitHub archives generally produce a single top-level directory.
    return candidates[0]


def install_from_archive(
    archive_url: str,
    install_root: Path,
    bin_root: Path,
    command_name: str,
    aliases: list[str],
) -> tuple[Path, list[Path], list[str]]:
    with tempfile.TemporaryDirectory(prefix="tarbar-install-") as tmp:
        tmp_path = Path(tmp)
        archive_path = tmp_path / "repo.tar.gz"
        _download_archive(archive_url, archive_path)
        repo_root = _extract_repo_root_from_archive(archive_path, tmp_path)
        return _install_from_repo(repo_root, install_root, bin_root, command_name, aliases)


def _print_success(
    launcher_path: Path,
    alias_paths: list[Path],
    skipped_aliases: list[str],
    bin_root: Path,
) -> None:
    print("Tarbar CLI installed successfully.")
    print(f"Primary launcher: {launcher_path}")
    if alias_paths:
        print("Aliases:")
        for alias in alias_paths:
            print(f"  {alias}")
    if skipped_aliases:
        print("Skipped aliases (existing non-managed commands found):")
        for alias in skipped_aliases:
            print(f"  {alias}")

    path_entries = os.environ.get("PATH", "").split(":")
    if str(bin_root) not in path_entries:
        print()
        print("Add this directory to your PATH:")
        print(f"  export PATH=\"{bin_root}:$PATH\"")
        print("Then restart your shell.")

    print()
    print("Try:")
    print(f"  {launcher_path.name} --help")


def main() -> None:
    _ensure_python_version()

    parser = argparse.ArgumentParser(description="Install Tarbar CLI")
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
        default=os.path.expanduser("~/.local/share/tarbar-cli"),
        help="Install root for Python package files",
    )
    parser.add_argument(
        "--bin-root",
        default=os.path.expanduser("~/.local/bin"),
        help="Install root for launcher binaries",
    )
    parser.add_argument(
        "--command-name",
        default="tarbar",
        help="Primary command name to install",
    )
    parser.add_argument(
        "--alias",
        action="append",
        default=[],
        help="Additional command alias to install (repeatable)",
    )
    parser.add_argument(
        "--no-claude-alias",
        action="store_true",
        help="Do not install the optional claude alias",
    )
    args = parser.parse_args()

    install_root = Path(args.install_root).expanduser().resolve()
    bin_root = Path(args.bin_root).expanduser().resolve()
    aliases = list(args.alias)
    if not args.no_claude_alias:
        aliases.append("claude")

    if args.from_local_repo:
        repo_root = Path(args.from_local_repo).expanduser().resolve()
        launcher, alias_paths, skipped_aliases = _install_from_repo(
            repo_root,
            install_root,
            bin_root,
            args.command_name,
            aliases,
        )
    else:
        launcher, alias_paths, skipped_aliases = install_from_archive(
            args.archive_url,
            install_root,
            bin_root,
            args.command_name,
            aliases,
        )

    _print_success(launcher, alias_paths, skipped_aliases, bin_root)


if __name__ == "__main__":
    main()
