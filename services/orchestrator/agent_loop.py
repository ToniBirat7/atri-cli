"""
Deterministic Agent Loop.

Implements the core agentic AI loop:
1. User message -> LLM
2. LLM response with tool calls -> Tool execution
3. Tool results -> LLM context
4. Repeat until max turns or no more tool calls

Supports budget controls:
- Max turns (agent loop iterations)
- Max tool calls per turn
- Tool execution timeouts

Phase 1: Basic deterministic loop with budgets.
Phase 2: Streaming responses.
Phase 3: Error recovery and backtracking.
Phase 5: Circuit-breaker, retry logic, observability.
Phase 7: Full observability with structured logging and tracing.
"""

from typing import List, Dict, Any, Optional, Tuple, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum
import asyncio
import json
import ast
import logging

try:
    from .logging_context import get_request_id, set_turn_id, get_turn_id
except ImportError:
    from logging_context import get_request_id, set_turn_id, get_turn_id

logger = logging.getLogger(__name__)


def _log_event(event: str, **fields: Any) -> None:
    payload: Dict[str, Any] = {
        "event": event,
        "request_id": get_request_id(),
        "turn_id": get_turn_id(),
    }
    payload.update(fields)
    logger.info(json.dumps(payload, ensure_ascii=True))


class TurnOutcome(str, Enum):
    """Outcome of a single agent loop turn."""
    TOOL_CALLS = "tool_calls"
    NO_TOOL_CALLS = "no_tool_calls"
    MAX_TURNS_REACHED = "max_turns_reached"
    ERROR = "error"


@dataclass
class Turn:
    """Represents a single turn in the agent loop."""
    turn_number: int
    user_input: Optional[str] = None
    llm_response: Optional[str] = None
    tool_calls_requested: int = 0
    tool_calls_executed: int = 0
    outcome: Optional[TurnOutcome] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentState:
    """State of the agent loop execution."""
    turn: int = 0
    messages: List[Dict[str, str]] = field(default_factory=list)
    turns_history: List[Turn] = field(default_factory=list)
    total_tool_calls: int = 0
    final_response: Optional[str] = None
    status: str = "initialized"


class AgentLoop:
    """
    Deterministic agent loop with budget controls.

    Phase 1 responsibilities:
    - Message history management
    - Tool call extraction from LLM responses
    - Tool execution and result injection
    - Budget enforcement (max turns, max tool calls per turn)
    - State tracking for observability
    """

    def __init__(
        self,
        max_turns: int = 10,
        max_tool_calls_per_turn: int = 3,
        enable_tool_use: bool = True,
        enable_thinking: bool = False,
        tool_timeout_seconds: int = 10,
        max_tool_call_retries: int = 2,
    ):
        self.max_turns = max_turns
        self.max_tool_calls_per_turn = max_tool_calls_per_turn
        self.enable_tool_use = enable_tool_use
        self.enable_thinking = enable_thinking
        self.tool_timeout_seconds = tool_timeout_seconds
        self.max_tool_call_retries = max_tool_call_retries
        self.state = AgentState()

    async def _emit_event(
        self,
        event_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None] | None]],
        payload: Dict[str, Any],
    ) -> None:
        if event_callback is None:
            return
        try:
            maybe = event_callback(payload)
            if asyncio.iscoroutine(maybe):
                await maybe
        except Exception:
            # Keep loop progress resilient even if telemetry/event sink fails.
            return

    def _validate_tool_input(self, tool_name: str, tool_input: Any, tool_registry: "ToolRegistry") -> Dict[str, Any]:  # type: ignore
        if not isinstance(tool_input, dict):
            raise ValueError(f"Tool input must be an object for {tool_name}")

        tool = tool_registry.get_tool(tool_name)
        if tool is None and hasattr(tool_registry, "resolve_tool_call"):
            try:
                _, routed_name = tool_registry.resolve_tool_call(tool_name)
                tool = tool_registry.get_tool(routed_name)
            except Exception:
                tool = None

        if tool is None:
            return tool_input

        schema = tool.input_schema or {}
        required = schema.get("required", [])
        if isinstance(required, list):
            missing = [key for key in required if key not in tool_input]
            if missing:
                raise ValueError(f"Missing required fields for {tool_name}: {', '.join(missing)}")

        properties = schema.get("properties", {})
        additional_props = schema.get("additionalProperties", True)
        if additional_props is False and isinstance(properties, dict):
            unknown = [key for key in tool_input.keys() if key not in properties]
            if unknown:
                raise ValueError(f"Unexpected fields for {tool_name}: {', '.join(unknown)}")

        return tool_input

    async def run(
        self,
        user_message: str,
        llm_adapter: "LLMAdapter",  # type: ignore
        mcp_orchestrator: "MCPOrchestrator",  # type: ignore
        tool_registry: "ToolRegistry",  # type: ignore
        system_prompt: Optional[str] = None,
        event_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None] | None]] = None,
    ) -> Tuple[str, AgentState]:
        """
        Run the agent loop.

        Args:
            user_message: Initial user message
            llm_adapter: LLM adapter for completions
            mcp_orchestrator: MCP orchestrator for tool execution
            tool_registry: Registry of available tools

        Returns:
            Tuple of (final_response, agent_state)
        """
        # Ensure each /chat request starts from a clean state.
        self.state = AgentState()
        self.state.status = "running"
        selected_system_prompt = system_prompt or self._build_system_prompt()
        self.state.messages = [
            {
                "role": "system",
                "content": selected_system_prompt,
            },
            {
                "role": "user",
                "content": user_message,
            }
        ]

        _log_event("agent_loop.start", message_preview=user_message[:100])

        try:
            while self.state.turn < self.max_turns:
                self.state.turn += 1
                set_turn_id(self.state.turn)
                turn = Turn(turn_number=self.state.turn, user_input=user_message)
                await self._emit_event(
                    event_callback,
                    {
                        "type": "turn_start",
                        "turn": self.state.turn,
                        "max_turns": self.max_turns,
                    },
                )

                try:
                    available_tools = tool_registry.to_openai_format() if self.enable_tool_use else None

                    try:
                        completion = await llm_adapter.chat_completion(
                            messages=self.state.messages,
                            tools=available_tools,
                        )
                    except Exception as e:
                        # Gemma/llama.cpp can occasionally fail on the follow-up turn after a tool result.
                        # If we already executed at least one tool, return a deterministic fallback.
                        if self.state.total_tool_calls > 0:
                            fallback = self._fallback_from_latest_tool_result()
                            if fallback:
                                self.state.final_response = fallback
                                turn.outcome = TurnOutcome.NO_TOOL_CALLS
                                self.state.turns_history.append(turn)
                                logger.warning(
                                    "Turn %s: LLM follow-up failed after tool execution; returning fallback response: %s",
                                    self.state.turn,
                                    e,
                                )
                                break
                        raise

                    choice = completion.get("choices", [{}])[0]
                    content = choice.get("message", {}).get("content", "")
                    turn.llm_response = content
                    await self._emit_event(
                        event_callback,
                        {
                            "type": "llm_response",
                            "turn": self.state.turn,
                            "has_content": bool(content),
                            "content_preview": content[:160],
                        },
                    )

                    tool_calls = await llm_adapter.extract_tool_calls(completion)
                    turn.tool_calls_requested = len(tool_calls)

                    if not tool_calls:
                        self.state.final_response = content
                        turn.outcome = TurnOutcome.NO_TOOL_CALLS
                        self.state.turns_history.append(turn)
                        _log_event("agent_loop.turn.final_response", tool_calls_requested=0)
                        await self._emit_event(
                            event_callback,
                            {
                                "type": "turn_final_response",
                                "turn": self.state.turn,
                            },
                        )
                        break

                    if len(tool_calls) > self.max_tool_calls_per_turn:
                        logger.warning(
                            json.dumps(
                                {
                                    "event": "agent_loop.turn.tool_calls_capped",
                                    "request_id": get_request_id(),
                                    "turn_id": get_turn_id(),
                                    "requested": len(tool_calls),
                                    "max_allowed": self.max_tool_calls_per_turn,
                                },
                                ensure_ascii=True,
                            )
                        )
                        tool_calls = tool_calls[:self.max_tool_calls_per_turn]

                    self.state.messages.append(
                        {
                            "role": "assistant",
                            "content": content,
                            "tool_calls": [
                                {
                                    "id": call.id or f"call_{i}",
                                    "function": {
                                        "name": call.tool_name,
                                        "arguments": json.dumps(call.tool_input, ensure_ascii=False),
                                    },
                                }
                                for i, call in enumerate(tool_calls)
                            ],
                        }
                    )

                    for tool_call in tool_calls:
                        try:
                            validated_input = self._validate_tool_input(
                                tool_name=tool_call.tool_name,
                                tool_input=tool_call.tool_input,
                                tool_registry=tool_registry,
                            )
                            routed_server = "local-mcp"
                            routed_tool_name = tool_call.tool_name
                            if hasattr(tool_registry, "resolve_tool_call"):
                                routed_server, routed_tool_name = tool_registry.resolve_tool_call(tool_call.tool_name)

                            await self._emit_event(
                                event_callback,
                                {
                                    "type": "tool_call_start",
                                    "turn": self.state.turn,
                                    "tool_name": tool_call.tool_name,
                                    "routed_server": routed_server,
                                    "routed_tool_name": routed_tool_name,
                                },
                            )

                            result = await mcp_orchestrator.execute_tool(
                                server_name=routed_server,
                                tool_name=routed_tool_name,
                                tool_input=validated_input,
                                timeout_seconds=self.tool_timeout_seconds,
                                max_retries=self.max_tool_call_retries,
                            )

                            turn.metadata.setdefault("tool_events", []).append(
                                {
                                    "tool_name": tool_call.tool_name,
                                    "routed_server": routed_server,
                                    "routed_tool_name": routed_tool_name,
                                    "input": tool_call.tool_input,
                                    "output": result,
                                    "status": "ok",
                                }
                            )

                            self.state.messages.append(
                                llm_adapter.format_tool_result(
                                    tool_call.tool_name,
                                    result,
                                    tool_call.id,
                                )
                            )
                            turn.tool_calls_executed += 1
                            self.state.total_tool_calls += 1
                            _log_event(
                                "agent_loop.turn.tool_executed",
                                tool_name=tool_call.tool_name,
                                tool_calls_executed_in_turn=turn.tool_calls_executed,
                            )
                            await self._emit_event(
                                event_callback,
                                {
                                    "type": "tool_call_result",
                                    "turn": self.state.turn,
                                    "tool_name": tool_call.tool_name,
                                    "status": "ok",
                                },
                            )
                        except Exception as e:
                            import traceback
                            error_traceback = traceback.format_exc()
                            logger.error(
                                json.dumps(
                                    {
                                        "event": "agent_loop.turn.tool_failed",
                                        "request_id": get_request_id(),
                                        "turn_id": get_turn_id(),
                                        "tool_name": tool_call.tool_name,
                                        "routed_server": routed_server,
                                        "routed_tool_name": routed_tool_name,
                                        "error_type": type(e).__name__,
                                        "error_message": str(e),
                                        "error_traceback": error_traceback,
                                        "tool_input_keys": list(validated_input.keys()) if isinstance(validated_input, dict) else None,
                                    },
                                    ensure_ascii=True,
                                )
                            )
                            turn.metadata.setdefault("tool_events", []).append(
                                {
                                    "tool_name": tool_call.tool_name,
                                    "routed_server": routed_server,
                                    "routed_tool_name": routed_tool_name,
                                    "input": tool_call.tool_input,
                                    "output": f"Error: {str(e)}",
                                    "error_type": type(e).__name__,
                                    "status": "error",
                                }
                            )
                            self.state.messages.append(
                                llm_adapter.format_tool_result(
                                    tool_call.tool_name,
                                    f"Error: {str(e)}",
                                    tool_call.id,
                                )
                            )
                            await self._emit_event(
                                event_callback,
                                {
                                    "type": "tool_call_result",
                                    "turn": self.state.turn,
                                    "tool_name": tool_call.tool_name,
                                    "status": "error",
                                    "error": str(e),
                                    "error_type": type(e).__name__,
                                },
                            )

                    turn.outcome = TurnOutcome.TOOL_CALLS
                    self.state.turns_history.append(turn)
                    _log_event(
                        "agent_loop.turn.complete",
                        tool_calls_requested=turn.tool_calls_requested,
                        tool_calls_executed=turn.tool_calls_executed,
                    )
                    await self._emit_event(
                        event_callback,
                        {
                            "type": "turn_complete",
                            "turn": self.state.turn,
                            "tool_calls_requested": turn.tool_calls_requested,
                            "tool_calls_executed": turn.tool_calls_executed,
                        },
                    )

                except asyncio.CancelledError:
                    self.state.status = "cancelled"
                    turn.outcome = TurnOutcome.ERROR
                    turn.error = "cancelled"
                    self.state.turns_history.append(turn)
                    raise

                except Exception as e:
                    logger.error(
                        json.dumps(
                            {
                                "event": "agent_loop.turn.error",
                                "request_id": get_request_id(),
                                "turn_id": get_turn_id(),
                                "error": str(e),
                            },
                            ensure_ascii=True,
                        )
                    )
                    turn.outcome = TurnOutcome.ERROR
                    turn.error = str(e)
                    self.state.turns_history.append(turn)
                    self.state.status = "error"
                    raise

            if self.state.turn >= self.max_turns:
                if self.state.messages:
                    last_msg = self.state.messages[-1]
                    if last_msg.get("role") == "assistant":
                        self.state.final_response = last_msg.get("content", "")
                turn = Turn(turn_number=self.state.turn, outcome=TurnOutcome.MAX_TURNS_REACHED)
                self.state.turns_history.append(turn)
                logger.warning(
                    json.dumps(
                        {
                            "event": "agent_loop.max_turns_reached",
                            "request_id": get_request_id(),
                            "turn_id": get_turn_id(),
                            "max_turns": self.max_turns,
                        },
                        ensure_ascii=True,
                    )
                )

            self.state.status = "completed"
            _log_event(
                "agent_loop.complete",
                turns=self.state.turn,
                total_tool_calls=self.state.total_tool_calls,
                status=self.state.status,
            )
            await self._emit_event(
                event_callback,
                {
                    "type": "agent_complete",
                    "turns": self.state.turn,
                    "total_tool_calls": self.state.total_tool_calls,
                    "status": self.state.status,
                },
            )
            return self.state.final_response or "", self.state
        finally:
            set_turn_id(None)

    def _fallback_from_latest_tool_result(self) -> Optional[str]:
        """Build a deterministic user-facing response from the most recent tool result."""
        latest_tool_msg: Optional[Dict[str, Any]] = None
        for msg in reversed(self.state.messages):
            if msg.get("role") == "tool":
                latest_tool_msg = msg
                break

        if not latest_tool_msg:
            return None

        tool_name = latest_tool_msg.get("name", "tool")
        content = str(latest_tool_msg.get("content", "")).strip()

        if tool_name == "list_directory":
            entries: List[str] = []
            parsed: Any = None
            try:
                parsed = json.loads(content)
            except Exception:
                try:
                    parsed = ast.literal_eval(content)
                except Exception:
                    parsed = None

            if isinstance(parsed, list):
                for item in parsed[:5]:
                    if isinstance(item, dict):
                        entries.append(str(item.get("name") or item.get("path") or item))
                    else:
                        entries.append(str(item))

            if entries:
                bullets = "\n".join(f"- {entry}" for entry in entries)
                return f"I executed list_directory and found these entries:\n{bullets}"

        return f"I executed {tool_name} successfully.\n\nResult:\n{content[:2000]}"

    def _build_system_prompt(self) -> str:
        """Build system prompt for the agent."""
        prompt = (
            "You are Tarbar_AI, a general-purpose assistant for local and remote tasks.\n"
            "Follow these rules:\n"
            "- Be accurate, concise, and useful.\n"
            "- Use tools whenever they materially improve correctness, freshness, or access to local state.\n"
            "- Prefer the minimum number of tool calls needed. If multiple independent tool calls are useful, request them in the same turn.\n"
            "- Never reveal hidden reasoning, chain-of-thought, or internal scratch work.\n"
            "- If a request is ambiguous, ask one focused clarifying question before acting.\n"
            "- For file edits, destructive actions, or state-changing operations, be careful and prefer reversible steps.\n"
            "- If a tool fails, report the failure plainly and continue only if another safe path is available.\n"
            "- Format responses cleanly in Markdown when it improves readability, but avoid unnecessary verbosity."
        )

        if self.enable_thinking:
            return "<|think|>\n" + prompt

        return prompt

    def reset(self) -> None:
        """Reset agent state for a new conversation."""
        self.state = AgentState()
        logger.debug("Agent state reset")
