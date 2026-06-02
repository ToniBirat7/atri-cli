"""
Multi-model support and routing for atri-cli.
Inspired by Gemini's modelRouterService.

Detects all .gguf models in configured directories and routes requests
to the appropriate model based on task type.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ModelInfo:
    name: str           # Display name (filename without .gguf)
    path: str           # Absolute path to .gguf file
    size_bytes: int     # File size
    is_default: bool = False


class ModelRouter:
    """
    Routes requests to appropriate models based on task type.

    Strategy:
    - PLAN mode → largest (highest-context) model
    - Quick responses → smallest (fastest) model
    - Code editing → default model
    """

    def __init__(self, model_dirs: list[str] | None = None, default_model: str = ""):
        self._dirs = [Path(d) for d in (model_dirs or [])]
        self._default_model = default_model
        self._models: list[ModelInfo] = []
        self._override: Optional[str] = None  # /model command override
        self._discover()

    def _discover(self) -> None:
        seen: set[str] = set()
        for d in self._dirs:
            if not d.exists():
                continue
            for gguf in sorted(d.glob("*.gguf")):
                key = str(gguf)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    size = gguf.stat().st_size
                except OSError:
                    size = 0
                is_default = (
                    self._default_model and
                    (gguf.name == self._default_model or str(gguf) == self._default_model)
                )
                self._models.append(ModelInfo(
                    name=gguf.stem,
                    path=str(gguf),
                    size_bytes=size,
                    is_default=is_default,
                ))

        if self._models:
            logger.info("ModelRouter: discovered %d models", len(self._models))
            for m in self._models:
                logger.info("  %s%s (%s)", m.name, " [default]" if m.is_default else "", _fmt_size(m.size_bytes))

    def set_override(self, model_name: str) -> bool:
        """Set a runtime model override (e.g. from /model command). Returns False if not found."""
        for m in self._models:
            if m.name == model_name or m.path == model_name:
                self._override = m.path
                return True
        return False

    def clear_override(self) -> None:
        self._override = None

    def get_model_path(self, task_type: str = "default") -> Optional[str]:
        """
        Return the best model path for the given task type.
        task_type: "plan" | "quick" | "default"
        """
        if self._override:
            return self._override

        if not self._models:
            return None

        if task_type == "plan":
            # Largest model for planning
            return max(self._models, key=lambda m: m.size_bytes).path

        if task_type == "quick":
            # Smallest model for quick responses
            return min(self._models, key=lambda m: m.size_bytes).path

        # Default: prefer the explicitly configured default
        for m in self._models:
            if m.is_default:
                return m.path

        return self._models[0].path

    def list_models(self) -> list[dict]:
        return [
            {
                "name": m.name,
                "path": m.path,
                "size_mb": round(m.size_bytes / 1024 / 1024, 1),
                "is_default": m.is_default,
                "is_active": self._override == m.path or (not self._override and m.is_default),
            }
            for m in self._models
        ]


def _fmt_size(size_bytes: int) -> str:
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / 1024**3:.1f} GB"
    elif size_bytes >= 1024 ** 2:
        return f"{size_bytes / 1024**2:.1f} MB"
    return f"{size_bytes / 1024:.1f} KB"
