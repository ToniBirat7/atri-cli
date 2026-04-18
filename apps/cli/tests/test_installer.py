from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_installer_module(repo_root: Path):
    installer_path = repo_root / "scripts" / "install_cli.py"
    spec = importlib.util.spec_from_file_location("install_cli", installer_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_local_repo_install_writes_launcher(tmp_path):
    repo_root = Path(__file__).resolve().parents[3]
    module = _load_installer_module(repo_root)

    install_root = tmp_path / "share"
    bin_root = tmp_path / "bin"

    launcher = module._install_from_repo(repo_root=repo_root, install_root=install_root, bin_root=bin_root)

    assert launcher.exists()
    assert (install_root / "tarbar_cli" / "main.py").exists()
    content = launcher.read_text(encoding="utf-8")
    assert "from tarbar_cli.main import main" in content
