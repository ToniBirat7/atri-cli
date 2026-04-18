from __future__ import annotations

from pathlib import Path

from settings_layer import apply_overlays, apply_overlays_from_files


def test_apply_overlays_precedence_order():
    base = {"security": {"rate_limit_per_minute": 5}, "log_level": "INFO"}
    overlays = {
        "user": {"security": {"rate_limit_per_minute": 10}},
        "project": {"security": {"rate_limit_per_minute": 20}},
        "local": {"log_level": "DEBUG"},
        "managed": {"security": {"rate_limit_per_minute": 30}},
    }

    merged = apply_overlays(base, overlays)

    assert merged["security"]["rate_limit_per_minute"] == 30
    assert merged["log_level"] == "DEBUG"


def test_apply_overlays_from_files_ignores_missing_and_invalid(tmp_path: Path):
    user_path = tmp_path / "user.json"
    user_path.write_text('{"log_level":"WARNING"}', encoding="utf-8")

    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text('{"log_level":', encoding="utf-8")

    merged = apply_overlays_from_files(
        {"log_level": "INFO"},
        {
            "user": user_path,
            "project": invalid_path,
            "local": tmp_path / "missing.json",
        },
    )

    assert merged["log_level"] == "WARNING"
