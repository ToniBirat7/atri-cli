#!/usr/bin/env python3
"""Build Phase 6 CLI packaging artifacts.

Outputs:
- dist/atri-cli.pyz (bundled zipapp channel)
- dist/atri-cli-installer.tar.gz (script installer channel)
"""

from __future__ import annotations

import shutil
import tarfile
import tempfile
import zipapp
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def build_zipapp() -> Path:
    source_package = ROOT / "apps" / "cli"
    target = DIST / "atri-cli.pyz"
    zipapp.create_archive(
        source=str(source_package),
        target=str(target),
        interpreter="/usr/bin/env python3",
        main="tarbar_cli.main:main",
        compressed=True,
    )
    return target


def build_installer_bundle() -> Path:
    target = DIST / "atri-cli-installer.tar.gz"
    with tempfile.TemporaryDirectory(prefix="atri-installer-bundle-") as tmp:
        bundle_root = Path(tmp) / "atri-cli-installer"
        bundle_root.mkdir(parents=True, exist_ok=True)

        shutil.copy2(ROOT / "install.sh", bundle_root / "install.sh")
        scripts_dir = bundle_root / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "scripts" / "install_cli.py", scripts_dir / "install_cli.py")

        with tarfile.open(target, "w:gz") as tf:
            tf.add(bundle_root, arcname="atri-cli-installer")

    return target


def main() -> int:
    DIST.mkdir(parents=True, exist_ok=True)
    zipapp_path = build_zipapp()
    installer_path = build_installer_bundle()

    print(f"built: {zipapp_path}")
    print(f"built: {installer_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
