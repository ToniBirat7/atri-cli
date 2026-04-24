"""Telemetry tracking for CLI sessions."""

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List


@dataclass
class TurnMetrics:
    """Metrics for a single turn in a conversation."""
    turn_number: int
    user_message_length: int
    assistant_response_length: int
    tool_calls_count: int
    tool_names: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class SessionTelemetry:
    """Aggregated telemetry for a session."""
    session_start: float = field(default_factory=time.time)
    turns: List[TurnMetrics] = field(default_factory=list)
    total_tool_calls: int = 0
    unique_tools: set[str] = field(default_factory=set)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    conversation_id: Optional[str] = None
    mode: str = "print"
    permission_mode: str = "default"
    max_turns: Optional[int] = None
    max_budget_usd: Optional[float] = None
    exceeded_max_turns: bool = False
    exceeded_budget: bool = False
    errors: List[str] = field(default_factory=list)

    @property
    def session_duration_seconds(self) -> float:
        """Total duration of the session."""
        return time.time() - self.session_start

    @property
    def total_turns(self) -> int:
        """Total number of turns completed."""
        return len(self.turns)

    @property
    def total_input_chars(self) -> int:
        """Total input characters across all turns."""
        return sum(t.user_message_length for t in self.turns)

    @property
    def total_output_chars(self) -> int:
        """Total output characters across all turns."""
        return sum(t.assistant_response_length for t in self.turns)

    @property
    def avg_turn_duration(self) -> float:
        """Average duration per turn in seconds."""
        if not self.turns:
            return 0.0
        return sum(t.duration_seconds for t in self.turns) / len(self.turns)

    def add_turn(
        self,
        turn_number: int,
        user_message: str,
        assistant_response: str,
        tool_calls: List[str],
        duration_seconds: float = 0.0,
    ) -> None:
        """Record a turn with telemetry."""
        turn = TurnMetrics(
            turn_number=turn_number,
            user_message_length=len(user_message),
            assistant_response_length=len(assistant_response),
            tool_calls_count=len(tool_calls),
            tool_names=tool_calls,
            duration_seconds=duration_seconds,
        )
        self.turns.append(turn)
        self.total_tool_calls += len(tool_calls)
        self.unique_tools.update(tool_calls)

    def check_budget_limits(self) -> tuple[bool, Optional[str]]:
        """Check if session has exceeded any budget limits.
        
        Returns:
            (exceeded, reason) - True if limit exceeded, with reason string
        """
        if self.max_turns and self.total_turns >= self.max_turns:
            self.exceeded_max_turns = True
            return True, f"Max turns limit ({self.max_turns}) reached"

        if self.max_budget_usd and self.total_output_tokens > 0:
            # Simple cost estimation: $0.002 per 1M output tokens (Llama.cpp typical pricing)
            estimated_cost = (self.total_output_tokens / 1_000_000) * 0.002
            if estimated_cost >= self.max_budget_usd:
                self.exceeded_budget = True
                return True, f"Budget limit (${self.max_budget_usd}) exceeded"

        return False, None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        # Convert set to list for JSON serialization
        data["unique_tools"] = sorted(list(self.unique_tools))
        data["turns"] = [asdict(t) for t in self.turns]
        return data

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    def summary(self) -> str:
        """Human-readable summary of session telemetry."""
        lines = [
            f"Session Summary",
            f"================",
            f"Duration: {self.session_duration_seconds:.1f}s",
            f"Turns: {self.total_turns}",
            f"Tool calls: {self.total_tool_calls}",
            f"Unique tools: {len(self.unique_tools)}",
            f"Input chars: {self.total_input_chars}",
            f"Output chars: {self.total_output_chars}",
            f"Avg turn time: {self.avg_turn_duration:.1f}s",
        ]
        if self.exceeded_max_turns:
            lines.append(f"⚠ Max turns limit exceeded")
        if self.exceeded_budget:
            lines.append(f"⚠ Budget limit exceeded")
        if self.errors:
            lines.append(f"Errors: {len(self.errors)}")
        return "\n".join(lines)
