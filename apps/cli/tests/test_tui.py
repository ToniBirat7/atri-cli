from __future__ import annotations

from tarbar_cli.tui import TUIRenderer, TurnStatus


def test_timeline_minimal_filters_non_tool_events(capsys):
    renderer = TUIRenderer(timeline_verbosity="minimal")
    renderer.render_timeline_event({"type": "turn_start", "turn": 1}, "text")
    out = capsys.readouterr().out
    assert out == ""


def test_timeline_normal_renders_turn_event(capsys):
    renderer = TUIRenderer(timeline_verbosity="normal")
    renderer.render_timeline_event({"type": "turn_start", "turn": 2}, "text")
    out = capsys.readouterr().out
    assert "turn 2 started" in out


def test_timeline_debug_renders_raw_event(capsys):
    renderer = TUIRenderer(timeline_verbosity="debug")
    renderer.render_timeline_event({"type": "turn_start", "turn": 3}, "text")
    out = capsys.readouterr().out
    assert "event turn_start" in out


def test_print_turn_card_contains_mode_and_turn(capsys):
    renderer = TUIRenderer()
    renderer.print_turn_card(4, "plan")
    out = capsys.readouterr().out
    assert "turn 4" in out
    assert "mode=plan" in out


def test_status_set_is_noop_when_not_tty(monkeypatch):
    renderer = TUIRenderer()
    monkeypatch.setattr(renderer, "is_tty", lambda: False)
    renderer.status_set(
        TurnStatus(
            turn_number=1,
            elapsed_seconds=0.2,
            input_tokens=10,
            output_tokens=20,
            tool_calls=1,
            phase="thinking",
        )
    )
    assert True
