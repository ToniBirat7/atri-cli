"""Managed settings overlay support for orchestrator configuration."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict


def _deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_json_file(path: Path) -> Dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(data, dict):
        return data
    return {}


def resolve_overlay_paths() -> Dict[str, Path]:
    paths: Dict[str, Path] = {}
    for scope, env_name in (
        ("user", "ORCHESTRATOR_SETTINGS_USER_PATH"),
        ("project", "ORCHESTRATOR_SETTINGS_PROJECT_PATH"),
        ("local", "ORCHESTRATOR_SETTINGS_LOCAL_PATH"),
        ("managed", "ORCHESTRATOR_MANAGED_SETTINGS_PATH"),
    ):
        raw = os.getenv(env_name)
        if raw:
            paths[scope] = Path(raw)
    return paths


def apply_overlays(base_data: Dict[str, Any], overlays: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Apply overlays in precedence order: user < project < local < managed."""
    merged = dict(base_data)
    for scope in ("user", "project", "local", "managed"):
        payload = overlays.get(scope, {})
        if payload:
            merged = _deep_merge(merged, payload)
    return merged


def apply_overlays_from_files(base_data: Dict[str, Any], paths: Dict[str, Path]) -> Dict[str, Any]:
    overlays = {
        scope: _load_json_file(path)
        for scope, path in paths.items()
        if str(path)
    }
    return apply_overlays(base_data, overlays)
