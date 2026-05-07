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
"""
Atri Code Agent Loop - The core reasoning engine.

Implements a multi-turn ReAct loop that:
1. Receives user queries and system context.
2. Interacts with the LLM to decide on actions.
3. Executes MCP tools (filesystem, search, shell).
4. Maintains state and conversation history.
5. Handles fallback logic and error recovery.
"""

import asyncio
import json
import ast
import logging
import re
import os
try:
    from ..mcp.diff_engine import DiffEngine
except (ImportError, ValueError):
    import sys
    import os
    # Add repo root to sys.path to allow absolute imports of services.mcp
    _repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)
    try:
        from services.mcp.diff_engine import DiffEngine
    except ImportError:
        # Fallback for different execution contexts
        _mcp_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp"))
        if _mcp_path not in sys.path:
            sys.path.insert(0, _mcp_path)
        from diff_engine import DiffEngine

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
    PLANNING = "planning"
    VERIFICATION = "verification"
    MAX_TURNS_REACHED = "max_turns_reached"
    ERROR = "error"
    REVIEW = "review"


@dataclass
class Turn:
    """
    Represents a single discrete turn in the agent reasoning loop.
    Contains the model's response, any tool calls initiated, and the eventual outcome.
    """
    turn_number: int
    user_input: Optional[str] = None
    llm_response: Optional[str] = None
    tool_calls_requested: int = 0
    tool_calls_executed: int = 0
    tool_calls: List[str] = field(default_factory=list)
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
        thinking_mode: str = "tool_calls_off",
        tool_timeout_seconds: int = 10,
        max_tool_call_retries: int = 2,
        permission_mode: str = "default",
        # Legacy alias kept so existing callers don't break during the transition
        enable_thinking: bool = False,
    ):
        self.max_turns = max_turns
        self.max_tool_calls_per_turn = max_tool_calls_per_turn
        self.enable_tool_use = enable_tool_use
        # Resolve legacy enable_thinking into thinking_mode
        if enable_thinking and thinking_mode == "tool_calls_off":
            thinking_mode = "always"
        self.thinking_mode = thinking_mode
        self.stream_responses = False  # toggled by config/caller
        self.tool_timeout_seconds = tool_timeout_seconds
        self.max_tool_call_retries = max_tool_call_retries
        self.permission_mode = permission_mode
        self.state = AgentState()

    async def _stream_final_answer(
        self,
        llm_adapter,
        messages,
        event_callback,
        enable_thinking: bool = False,
    ) -> str:
        """Stream the final answer turn token-by-token, emitting text_delta events."""
        chunks: list[str] = []
        async for delta in llm_adapter.stream_chat_completion(
            messages=messages,
            enable_thinking=enable_thinking,
        ):
            chunks.append(delta)
            await self._emit_event(event_callback, {"type": "text_delta", "content": delta})
        return "".join(chunks)

    def _thinking_for_turn(self, has_tools: bool) -> bool:
        """Return whether thinking should be enabled for this LLM call."""
        if self.thinking_mode == "always":
            return True
        if self.thinking_mode == "tool_calls_off":
            return not has_tools  # think on final answer, not during tool loop
        return False  # "off"

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
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        
        # Strict validation: No unknown fields allowed
        additional_props = schema.get("additionalProperties", False)
        if not additional_props:
            unknown = [key for key in tool_input.keys() if key not in properties]
            if unknown:
                valid_keys = ", ".join(properties.keys())
                raise ValueError(
                    f"Unexpected fields for tool '{tool_name}': {', '.join(unknown)}. "
                    f"Valid fields are: {valid_keys}"
                )

        if isinstance(required, list):
            missing = [key for key in required if key not in tool_input]
            if missing:
                raise ValueError(f"Missing required fields for tool '{tool_name}': {', '.join(missing)}")

        return tool_input

    async def run(
        self,
        user_message: str,
        llm_adapter: "LLMAdapter",  # type: ignore
        mcp_orchestrator: "MCPOrchestrator",  # type: ignore
        tool_registry: "ToolRegistry",  # type: ignore
        system_prompt: Optional[str] = None,
        prior_messages: Optional[List[Dict[str, str]]] = None,
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
        historical_messages = prior_messages or []
        self.state.messages = [
            {
                "role": "system",
                "content": selected_system_prompt,
            },
            *historical_messages,
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
                    # Context Trimming: Prevent context saturation for smaller models while preserving mission-critical history.
                    # We keep the system prompt [0], the original user prompt [1], and the last 40 messages.
                    if len(self.state.messages) > 50:
                        system_msg = self.state.messages[0]
                        user_prompt = self.state.messages[1] if len(self.state.messages) > 1 else None
                        
                        trimmed = self.state.messages[-40:]
                        new_messages = [system_msg]
                        if user_prompt and user_prompt["role"] == "user":
                             new_messages.append(user_prompt)
                        
                        self.state.messages = new_messages + trimmed
                        logger.info(f"Turn {self.state.turn}: Trimmed context history (History length: {len(self.state.messages)})")

                    available_tools = tool_registry.to_openai_format() if self.enable_tool_use else None

                    # Use streaming for tool-free turns when enabled (final answer quality)
                    use_streaming = (
                        self.stream_responses
                        and not available_tools
                        and event_callback is not None
                    )

                    try:
                        if use_streaming:
                            streamed_text = await self._stream_final_answer(
                                llm_adapter=llm_adapter,
                                messages=self.state.messages,
                                event_callback=event_callback,
                                enable_thinking=self._thinking_for_turn(has_tools=False),
                            )
                            # Build a fake completion dict so the rest of the loop is unchanged
                            completion = {
                                "choices": [{
                                    "message": {
                                        "role": "assistant",
                                        "content": streamed_text,
                                        "tool_calls": None,
                                    },
                                    "finish_reason": "stop",
                                }],
                                "usage": {},
                            }
                        else:
                            completion = await llm_adapter.chat_completion(
                                messages=self.state.messages,
                                tools=available_tools,
                                # Very low temp for tool-call turns — peg-native needs deterministic JSON
                                temperature=0.1 if available_tools else None,
                                enable_thinking=self._thinking_for_turn(has_tools=bool(available_tools)),
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

                    usage = completion.get("usage")
                    if isinstance(usage, dict):
                        prompt_tokens = int(usage.get("prompt_tokens") or 0)
                        completion_tokens = int(usage.get("completion_tokens") or 0)
                        total_tokens = int(
                            usage.get("total_tokens")
                            or (prompt_tokens + completion_tokens)
                        )
                        turn.metadata.setdefault("usage", []).append(
                            {
                                "prompt_tokens": prompt_tokens,
                                "completion_tokens": completion_tokens,
                                "total_tokens": total_tokens,
                            }
                        )
                        await self._emit_event(
                            event_callback,
                            {
                                "type": "usage",
                                "turn": self.state.turn,
                                "prompt_tokens": prompt_tokens,
                                "completion_tokens": completion_tokens,
                                "total_tokens": total_tokens,
                            },
                        )

                    tool_calls = await llm_adapter.extract_tool_calls(completion)
                    turn.tool_calls_requested = len(tool_calls)
                    turn.tool_calls = [tc.tool_name for tc in tool_calls]

                    if not tool_calls:
                        # Zero-tool forced execution: if no successful tool calls yet AND the prompt
                        # clearly needed a specific tool, call it directly without relying on the
                        # model to pick it. Fires at most once per request.
                        if (
                            self.state.total_tool_calls == 0
                            and available_tools
                            and not getattr(self.state, "_forced_tool_fired", False)
                        ):
                            forced_result = await self._try_force_tool_call(
                                user_message=user_message,
                                mcp_orchestrator=mcp_orchestrator,
                                tool_registry=tool_registry,
                            )
                            if forced_result is not None:
                                self.state._forced_tool_fired = True
                                # Inject the real tool result so the model can answer from data.
                                # We drop the hallucinated content and inject only the tool result.
                                self.state.messages.append(
                                    {
                                        "role": "user",
                                        "content": (
                                            f"Tool result for your reference:\n{forced_result}\n\n"
                                            f"Using the tool result above, answer this question: {user_message}"
                                        ),
                                    }
                                )
                                self.state.total_tool_calls += 1
                                self.state.turns_history.append(turn)
                                _log_event(
                                    "agent_loop.turn.forced_tool_call",
                                    turn=self.state.turn,
                                )
                                continue

                        if self.state.total_tool_calls == 0:
                            forced_listing_response = await self._try_force_directory_listing_response(
                                user_message=user_message,
                                content=content,
                                mcp_orchestrator=mcp_orchestrator,
                                tool_registry=tool_registry,
                            )
                            if forced_listing_response is not None:
                                self.state.final_response = forced_listing_response
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

                        if self.state.total_tool_calls > 0:
                            replacement = self._normalize_tool_summary_response(content)
                            if replacement is not None:
                                self.state.final_response = replacement
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

                    # Intent-based tool correction: E2B often defaults to list_directory
                    # for bash/grep/read queries. Redirect on the first turn if intent is clear.
                    if self.state.turn == 1 and self.state.total_tool_calls == 0:
                        tool_calls = self._correct_tool_calls_for_intent(
                            tool_calls, user_message
                        )

                    self.state.messages.append(
                        {
                            "role": "assistant",
                            "content": content,
                            "tool_calls": [
                                {
                                    "id": call.id or f"call_{i}",
                                    "type": "function",
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
                        await self._emit_event(
                            event_callback,
                            {
                                "type": "tool_call_start",
                                "turn": self.state.turn,
                                "tool_name": tool_call.tool_name,
                                "tool_input": tool_call.tool_input,
                            },
                        )
                        routed_server = "local-mcp"
                        routed_tool_name = tool_call.tool_name
                        validated_input = tool_call.tool_input

                        try:
                            validated_input = self._validate_tool_input(
                                tool_name=tool_call.tool_name,
                                tool_input=tool_call.tool_input,
                                tool_registry=tool_registry,
                            )
                            if hasattr(tool_registry, "resolve_tool_call"):
                                resolved = tool_registry.resolve_tool_call(tool_call.tool_name)
                                if isinstance(resolved, (tuple, list)) and len(resolved) >= 2:
                                    routed_server, routed_tool_name = resolved[0], resolved[1]



                            # Intercept edit tools for review mode
                            if self.permission_mode == "review" and routed_tool_name in ["edit_diff", "edit_file"]:
                                file_path = validated_input.get("target_file_path")
                                if file_path and os.path.exists(file_path):
                                    with open(file_path, "r", encoding="utf-8") as f:
                                        before_content = f.read()
                                    
                                    after_content = None
                                    if routed_tool_name == "edit_diff":
                                        after_content = DiffEngine.get_preview(file_path, validated_input.get("diff", ""))
                                    elif routed_tool_name == "edit_file":
                                        # Simple text replacement for preview
                                        old_text = validated_input.get("exact_text_to_replace")
                                        new_text = validated_input.get("new_text_content")
                                        if old_text and new_text:
                                            after_content = before_content.replace(old_text, new_text)

                                    if after_content is not None:
                                        turn.outcome = TurnOutcome.REVIEW
                                        turn.metadata["review_data"] = {
                                            "path": file_path,
                                            "before": before_content,
                                            "after": after_content,
                                            "tool": routed_tool_name,
                                            "input": validated_input
                                        }
                                        await self._emit_event(
                                            event_callback,
                                            {
                                                "type": "turn_review_requested",
                                                "turn": self.state.turn,
                                                "review": turn.metadata["review_data"]
                                            }
                                        )
                                        self.state.final_response = f"Review requested for {file_path}"
                                        self.state.turns_history.append(turn)
                                        return self.state.final_response, self.state

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
                            await self._emit_event(
                                event_callback,
                                {
                                    "type": "tool_call_result",
                                    "turn": self.state.turn,
                                    "tool_name": tool_call.tool_name,
                                    "tool_result": result,
                                    "status": "ok",
                                },
                            )
                            
                            # v2 Planning Interception
                            if tool_call.tool_name in ["propose_plan", "intelligence.propose_plan"]:
                                turn.outcome = TurnOutcome.PLANNING
                                turn.metadata["proposed_plan"] = validated_input
                                _log_event("agent_loop.turn.planning_triggered", plan=validated_input)
                                
                                # Extract goal and steps for the UI
                                goal = validated_input.get("goal", "Execute task")
                                steps = validated_input.get("steps", [])
                                
                                await self._emit_event(
                                    event_callback,
                                    {
                                        "type": "plan_proposed",
                                        "turn": self.state.turn,
                                        "plan": {
                                            "goal": goal,
                                            "steps": steps
                                        },
                                    },
                                )
                                self.state.final_response = f"Plan proposed: {goal}"
                                self.state.turns_history.append(turn)
                                return self.state.final_response, self.state

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

                    # Post-tool execution check for errors to nudge the model
                    recent_msgs = self.state.messages[-len(tool_calls):]
                    has_tool_errors = any("Error:" in str(msg.get("content", "")) for msg in recent_msgs)
                    if has_tool_errors:
                        # Detect "Tool not found" so we can give a specific correction
                        not_found_tools = [
                            tc.tool_name for tc in tool_calls
                            if any(
                                f"Tool not found in registry: {tc.tool_name}" in str(m.get("content", ""))
                                for m in recent_msgs
                            )
                        ]
                        if not_found_tools and available_tools:
                            valid_names = [t.get("function", t).get("name", "") for t in available_tools]
                            error_nudge = (
                                f"Tool(s) {not_found_tools} do not exist. "
                                f"You MUST only call tools from this exact list: {valid_names}. "
                                f"Choose the correct tool and retry."
                            )
                        else:
                            error_nudge = (
                                "One or more of your tool calls returned an 'Error:'. "
                                "Examine the error messages and retry with corrected parameters."
                            )
                        self.state.messages.append({"role": "user", "content": error_nudge})
                        logger.info(f"Turn {self.state.turn}: Injected error correction nudge due to tool failure.")

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
            summary = self._summarize_list_directory_result(
                content,
                requested_path=self._latest_requested_directory_path(),
            )
            if summary:
                return summary

        return f"I executed {tool_name} successfully.\n\nResult:\n{content[:2000]}"

    def _normalize_tool_summary_response(self, content: str) -> Optional[str]:
        """Replace shell-style directory answers with the actual directory summary."""
        if not content.strip():
            return self._fallback_from_latest_tool_result()

        normalized = content.strip().lower()
        if not self._looks_like_shell_directory_response(normalized):
            return None

        # Only trigger fallback if the last tool was a filesystem-oriented tool
        # (where the model might be tempted to just echo 'ls')
        filesystem_tools = {"list_directory", "ls", "find", "tree", "dir", "search_files"}
        latest_tool = ""
        for msg in reversed(self.state.messages):
            if msg.get("role") == "tool":
                latest_tool = msg.get("name", "")
                break
        
        if latest_tool not in filesystem_tools:
            return None

        return self._fallback_from_latest_tool_result()

    async def _try_force_tool_call(
        self,
        *,
        user_message: str,
        mcp_orchestrator: "MCPOrchestrator",  # type: ignore
        tool_registry: "ToolRegistry",  # type: ignore
    ) -> Optional[str]:
        """Directly execute the tool implied by the user message, bypassing model tool selection.

        Returns the raw tool result string, or None if no matching intent is found or execution fails.
        """
        msg = user_message.strip().lower()

        # read_text_file intent
        path_match = re.search(
            r"(?:read|open|show|cat|view|inspect|check|look at|summari[sz]e)\s+"
            r"(?:the\s+)?(?:file\s+|contents?\s+of\s+)?([a-zA-Z][\w./\-]+\.[a-zA-Z]{1,5})",
            msg,
        )
        if path_match:
            fpath = path_match.group(1).strip("\"'")
            try:
                route = self._resolve_tool_route("read_text_file", tool_registry)
                if route:
                    _server, _tool = route
                    result = await mcp_orchestrator.execute_tool(
                        server_name=_server,
                        tool_name=_tool,
                        tool_input={"target_file_path": fpath},
                        timeout_seconds=self.tool_timeout_seconds,
                        max_retries=self.max_tool_call_retries,
                    )
                    _log_event("agent_loop.forced_tool_call.read_text_file", path=fpath)
                    return json.dumps(result) if isinstance(result, (dict, list)) else str(result)
            except Exception as exc:
                logger.debug("Forced read_text_file failed for %s: %s", fpath, exc)
                return None

        # list_directory intent (no file extension = it's a directory)
        dir_match = re.search(
            r"(?:list|show|display)\s+(?:the\s+)?(?:files?\s+(?:in|inside|under|at)\s+|contents?\s+of\s+)?"
            r"(?:the\s+)?([a-zA-Z][\w./\-]+/?|current\s+(?:working\s+)?directory|\.)",
            msg,
        )
        if dir_match:
            raw_path = dir_match.group(1).strip().rstrip("/")
            if raw_path in ("current working directory", "current directory", "."):
                raw_path = "."
            # Only proceed if path doesn't have a file extension (it's really a dir)
            if "." not in raw_path.split("/")[-1] or raw_path == ".":
                try:
                    route = self._resolve_tool_route("list_directory", tool_registry)
                    if route:
                        _server, _tool = route
                        result = await mcp_orchestrator.execute_tool(
                            server_name=_server,
                            tool_name=_tool,
                            tool_input={"target_path": raw_path},
                            timeout_seconds=self.tool_timeout_seconds,
                            max_retries=self.max_tool_call_retries,
                        )
                        _log_event("agent_loop.forced_tool_call.list_directory", path=raw_path)
                        return json.dumps(result) if isinstance(result, (dict, list)) else str(result)
                except Exception as exc:
                    logger.debug("Forced list_directory failed for %s: %s", raw_path, exc)

        # bash_exec intent
        cmd_match = re.search(r"(?:run|execute|use bash|shell|use bash to)\s+`([^`]+)`", msg)
        if not cmd_match:
            # Also match "Run `cmd`" at start of message
            cmd_match = re.search(r"^run\s+`([^`]+)`", msg)
        if cmd_match:
            cmd = cmd_match.group(1)
            try:
                route = self._resolve_tool_route("bash_exec", tool_registry)
                if route:
                    _server, _tool = route
                    result = await mcp_orchestrator.execute_tool(
                        server_name=_server,
                        tool_name=_tool,
                        tool_input={"command": cmd},
                        timeout_seconds=self.tool_timeout_seconds,
                        max_retries=self.max_tool_call_retries,
                    )
                    _log_event("agent_loop.forced_tool_call.bash_exec", cmd=cmd)
                    return json.dumps(result) if isinstance(result, (dict, list)) else str(result)
            except Exception as exc:
                logger.debug("Forced bash_exec failed for %s: %s", cmd, exc)
                return None

        # grep_codebase intent
        grep_match = re.search(r"(?:search|grep|find all|find every|look for)\s+['\"]?([a-zA-Z_][\w.]+)['\"]?", msg)
        if grep_match and re.search(r"\b(codebase|import|uses?|across|through|appear|file)\b", msg):
            pattern = grep_match.group(1).strip("'\"")
            try:
                route = self._resolve_tool_route("grep_codebase", tool_registry)
                if route:
                    _server, _tool = route
                    result = await mcp_orchestrator.execute_tool(
                        server_name=_server,
                        tool_name=_tool,
                        tool_input={"pattern": pattern},
                        timeout_seconds=self.tool_timeout_seconds,
                        max_retries=self.max_tool_call_retries,
                    )
                    _log_event("agent_loop.forced_tool_call.grep_codebase", pattern=pattern)
                    return json.dumps(result) if isinstance(result, (dict, list)) else str(result)
            except Exception as exc:
                logger.debug("Forced grep_codebase failed for %s: %s", pattern, exc)

        return None

    def _resolve_tool_route(
        self,
        tool_name: str,
        tool_registry: "ToolRegistry",  # type: ignore
    ) -> Optional[Tuple[str, str]]:
        """Return (server_name, source_name) for a given tool name, trying prefixed aliases."""
        candidates = [tool_name, f"local-mcp.{tool_name}"]
        for candidate in candidates:
            try:
                if hasattr(tool_registry, "resolve_tool_call"):
                    server_name, source_name = tool_registry.resolve_tool_call(candidate)
                    return server_name, source_name
            except Exception:
                continue
        return None

    async def _try_force_directory_listing_response(
        self,
        *,
        user_message: str,
        content: str,
        mcp_orchestrator: "MCPOrchestrator",  # type: ignore
        tool_registry: "ToolRegistry",  # type: ignore
    ) -> Optional[str]:
        """Force a real directory listing when a directory request got a shell snippet reply."""
        normalized_content = content.strip().lower()
        if not self._looks_like_shell_directory_response(normalized_content):
            return None

        if not self._looks_like_directory_request(user_message):
            return None

        target_path = self._extract_path_for_directory_listing(content, user_message)
        resolved_route = self._resolve_directory_listing_tool(tool_registry)
        if resolved_route is None:
            return None

        exposed_tool_name, routed_server, routed_tool_name = resolved_route

        try:
            result = await mcp_orchestrator.execute_tool(
                server_name=routed_server,
                tool_name=routed_tool_name,
                tool_input={"target_path": target_path},
                timeout_seconds=self.tool_timeout_seconds,
                max_retries=self.max_tool_call_retries,
            )
        except Exception:
            return None

        summary = self._summarize_list_directory_result(result, requested_path=target_path)
        if summary is None:
            return None

        self.state.messages.append(
            {
                "role": "tool",
                "name": exposed_tool_name,
                "content": json.dumps(result, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result),
            }
        )
        self.state.total_tool_calls += 1
        return summary

    def _resolve_directory_listing_tool(
        self,
        tool_registry: "ToolRegistry",  # type: ignore
    ) -> Optional[Tuple[str, str, str]]:
        """Resolve a directory-listing tool name even when only namespaced aliases are present."""
        preferred_names = (
            "list_directory",
            "local-mcp.list_directory",
            "filesystem.list_directory",
        )

        for candidate in preferred_names:
            try:
                if hasattr(tool_registry, "resolve_tool_call"):
                    server_name, source_name = tool_registry.resolve_tool_call(candidate)
                    return candidate, server_name, source_name
            except Exception:
                continue

        if hasattr(tool_registry, "list_all_tools") and hasattr(tool_registry, "resolve_tool_call"):
            try:
                for tool in tool_registry.list_all_tools():
                    name = getattr(tool, "name", "")
                    if not isinstance(name, str):
                        continue
                    if name == "list_directory" or name.endswith(".list_directory"):
                        try:
                            server_name, source_name = tool_registry.resolve_tool_call(name)
                            return name, server_name, source_name
                        except Exception:
                            continue
            except Exception:
                return None

        return None

    def _summarize_list_directory_result(self, result: Any, requested_path: Optional[str] = None) -> Optional[str]:
        """Build a short user-facing list from a list_directory tool result."""
        entries: List[str] = []
        directory_path = ""

        parsed: Any = result
        if isinstance(result, str):
            text = result.strip()
            if text:
                try:
                    parsed = json.loads(text)
                except Exception:
                    try:
                        parsed = ast.literal_eval(text)
                    except Exception:
                        parsed = text

        if isinstance(parsed, list):
            for item in parsed[:3]:
                if isinstance(item, dict):
                    entries.append(str(item.get("name") or item.get("path") or item))
                else:
                    entries.append(str(item))
        elif isinstance(parsed, dict):
            directory_path = str(parsed.get("path") or parsed.get("directory") or "").strip()
            raw_entries = parsed.get("entries")
            if isinstance(raw_entries, list):
                for item in raw_entries[:3]:
                    if isinstance(item, dict):
                        entries.append(str(item.get("name") or item.get("path") or item))
                    else:
                        entries.append(str(item))

        if not entries:
            return None

        bullets = "\n".join(f"- {entry}" for entry in entries)

        effective_path = self._resolve_directory_display_path(
            directory_path,
            requested_path or self._latest_requested_directory_path(),
        )
        if effective_path:
            return f"Top entries in {effective_path}:\n{bullets}"
        return f"Top entries in the directory:\n{bullets}"

    def _latest_requested_directory_path(self) -> Optional[str]:
        """Best-effort extraction of the latest path requested for list_directory."""
        for msg in reversed(self.state.messages):
            if msg.get("role") == "assistant":
                tool_calls = msg.get("tool_calls") or []
                if not isinstance(tool_calls, list):
                    continue
                for call in reversed(tool_calls):
                    try:
                        function_payload = call.get("function") or {}
                        if function_payload.get("name") != "list_directory":
                            continue
                        arguments = function_payload.get("arguments") or "{}"
                        parsed_args = json.loads(arguments) if isinstance(arguments, str) else arguments
                        path = str((parsed_args or {}).get("path") or "").strip()
                        if path:
                            return path
                    except Exception:
                        continue

        for msg in reversed(self.state.messages):
            if msg.get("role") != "user":
                continue
            text = str(msg.get("content") or "")
            match = re.search(r"(/[^\s,;:]+)", text)
            if match:
                return match.group(1)

        return None

    def _resolve_directory_display_path(self, tool_path: str, requested_path: Optional[str]) -> str:
        """Prefer user-requested path when tool returns ambiguous current-directory markers."""
        normalized_tool_path = tool_path.strip()
        if normalized_tool_path and normalized_tool_path not in {".", "./"}:
            return normalized_tool_path

        normalized_requested = (requested_path or "").strip()
        if normalized_requested and normalized_requested not in {".", "./"}:
            return normalized_requested

        if normalized_tool_path in {".", "./"}:
            return "current directory"

        return ""

    def _looks_like_directory_request(self, user_message: str) -> bool:
        """Detect user intent to list or inspect directory entries."""
        normalized = user_message.lower()
        patterns = (
            r"\blist\b.*\b(directory|folder|files?|items?|entries)\b",
            r"\bshow\b.*\b(directory|folder|files?|items?|entries)\b",
            r"\btop\s+\d+\b.*\b(files?|items?|entries|directory)\b",
        )
        return any(re.search(pattern, normalized) for pattern in patterns)

    def _extract_path_for_directory_listing(self, content: str, user_message: str) -> str:
        """Extract the best candidate directory path from assistant/user text."""
        content_match = re.search(r"\bls(?:\s+-\S+)*\s+([^\s|;&]+)", content)
        if content_match:
            return content_match.group(1)

        user_match = re.search(r"(/[^\s,;:]+)", user_message)
        if user_match:
            return user_match.group(1)

        return "."

    def _looks_like_shell_directory_response(self, normalized_content: str) -> bool:
        """Detect when the model echoed a shell command instead of summarizing files."""
        shell_markers = (
            r"```(?:bash|sh|shell)?",
            r"\bls\s+-",
            r"\bls\b",
            r"\bfind\b",
            r"\btree\b",
            r"\bdir\b",
        )
        if not any(re.search(pattern, normalized_content) for pattern in shell_markers):
            return False

        if "/" not in normalized_content and "." not in normalized_content:
            return False

        if any(marker in normalized_content for marker in ("top 3", "files are", "entries are", "directory contains")):
            return False

        return True

    def _build_system_prompt(self) -> str:
        """Build system prompt for the agent."""
        prompt = (
            "You are Atri Code, a general-purpose assistant for local and remote tasks.\n"
            "Follow these rules:\n"
            "- Be accurate, concise, and useful.\n"
            "- Use tools whenever they materially improve correctness, freshness, or access to local state.\n"
            "- Prefer the minimum number of tool calls needed. If multiple independent tool calls are useful, request them in the same turn.\n"
            "- When a filesystem listing is requested, return the actual entries in plain text or bullets.\n"
            "- Do not echo the shell command used to inspect a directory, and do not wrap directory listings in code fences unless the user explicitly asks for code.\n"
            "- Never reveal hidden reasoning, chain-of-thought, or internal scratch work.\n"
            "- If a request is ambiguous, ask one focused clarifying question before acting.\n"
            "- For file edits, destructive actions, or state-changing operations, be careful and prefer reversible steps.\n"
            "- If a tool call fails with an 'Error:', you MUST NOT say you are finished. You must attempt to fix the error or explain it clearly.\n"
            "- IMPORTANT: When using file-editing tools (edit_diff, edit_file), the 'path' parameter is REQUIRED. You must always specify which file you are changing.\n"
            "- Format responses cleanly in Markdown when it improves readability, but avoid unnecessary verbosity."
        )

        return prompt

    # ── Prefix injection helpers ──────────────────────────────────────────────

    _TOOL_PREFIX_PATTERNS: List[Tuple[re.Pattern, str, str]] = []  # filled after class

    def _correct_tool_calls_for_intent(
        self, tool_calls: List["ToolUse"], user_message: str  # type: ignore
    ) -> List["ToolUse"]:  # type: ignore
        """Redirect model's wrong tool choices to the correct tool based on user intent.

        E2B (2.5B) defaults to list_directory for many queries. If the intent clearly maps
        to a different tool, swap the tool_name and arguments. Only fires once on turn 1.
        """
        if not tool_calls:
            return tool_calls

        msg = user_message.strip().lower()

        # bash_exec intent detection
        bash_intent = (
            re.search(r"(?:run|execute)\s+`[^`]+`", msg)
            or re.search(r"^run\s+`", msg)
            or re.search(r"\buse bash\b.*\bcount\b", msg)
            or re.search(r"\buse bash\b.*\blines?\b", msg)
        )
        cmd_match = re.search(r"`([^`]+)`", msg)

        try:
            from llm_adapter import ToolUse as _ToolUse
        except ImportError:
            try:
                from .llm_adapter import ToolUse as _ToolUse
            except ImportError:
                return tool_calls  # can't import ToolUse, skip correction

        def _make(tool: str, args: dict, orig_id: Optional[str] = None) -> "_ToolUse":
            return _ToolUse(tool_name=tool, tool_input=args, id=orig_id)

        if bash_intent and cmd_match:
            wrong_names = {tc.tool_name for tc in tool_calls}
            if "bash_exec" not in wrong_names:
                cmd = cmd_match.group(1)
                _log_event("agent_loop.tool_correction", from_tool=list(wrong_names), to_tool="bash_exec")
                return [_make("bash_exec", {"command": cmd}, tool_calls[0].id)]

        # grep_codebase intent detection
        grep_intent = (
            re.search(r"\b(search|grep|find all|find every)\b", msg)
            and re.search(r"\b(codebase|import|across|through|appear|times?)\b", msg)
        )
        if grep_intent:
            wrong_names = {tc.tool_name for tc in tool_calls}
            if "grep_codebase" not in wrong_names:
                grep_pat = re.search(r"(?:for|of)\s+['\"]?([a-zA-Z_][\w.]+)['\"]?", msg)
                if grep_pat:
                    pattern = grep_pat.group(1)
                    _log_event("agent_loop.tool_correction", from_tool=list(wrong_names), to_tool="grep_codebase")
                    return [_make("grep_codebase", {"pattern": pattern}, tool_calls[0].id)]

        # read_text_file intent (when list_directory is called but a file was requested)
        file_match = re.search(
            r"(?:read|open|show|cat|view|inspect|summari[sz]e)\s+"
            r"(?:the\s+)?(?:file\s+|contents?\s+of\s+)?([a-zA-Z][\w./\-]+\.[a-zA-Z]{1,5})",
            msg,
        )
        if file_match:
            wrong_names = {tc.tool_name for tc in tool_calls}
            if "read_text_file" not in wrong_names and "list_directory" in wrong_names:
                fpath = file_match.group(1).strip("\"'")
                _log_event("agent_loop.tool_correction", from_tool=list(wrong_names), to_tool="read_text_file")
                return [_make("read_text_file", {"target_file_path": fpath}, tool_calls[0].id)]

        # todo_write intent
        if re.search(r"\b(create|add|make|write)\b.*\btodo\b", msg):
            wrong_names = {tc.tool_name for tc in tool_calls}
            if "todo_write" not in wrong_names:
                items_text = re.findall(r"\d+\)\s*([^,\n]+)", user_message)
                items = [i.strip() for i in items_text] if items_text else ["todo item"]
                _log_event("agent_loop.tool_correction", from_tool=list(wrong_names), to_tool="todo_write")
                return [_make("todo_write", {"todos": items}, tool_calls[0].id)]

        # todo_read intent
        if re.search(r"\b(read|show|list|get|check)\b.*\btodo\b", msg):
            wrong_names = {tc.tool_name for tc in tool_calls}
            if "todo_read" not in wrong_names:
                _log_event("agent_loop.tool_correction", from_tool=list(wrong_names), to_tool="todo_read")
                return [_make("todo_read", {}, tool_calls[0].id)]

        return tool_calls

    def _detect_prefix_injection(self, user_message: str, available_tools: List[Dict]) -> Optional[str]:
        """Return a partial assistant JSON prefix to force the model toward the right tool.

        Only fires on the first turn (no tool calls yet) when the model's strong training
        priors would otherwise cause it to hallucinate a tool name.  Returns None when
        no pattern matches — the model handles it normally.
        """
        if self.state.total_tool_calls > 0:
            return None  # only help on the first turn

        tool_names = {t.get("function", t).get("name", "") for t in (available_tools or [])}
        msg = user_message.strip().lower()

        # read_text_file — check BEFORE list_directory so "read file X" doesn't hit list
        if "read_text_file" in tool_names:
            path_match = re.search(
                r"(?:read|open|show|cat|view|inspect|check|look at|summari[sz]e)\s+"
                r"(?:the\s+)?(?:file\s+|contents?\s+of\s+)?([a-zA-Z][\w./\-]+\.[a-zA-Z]{1,5})",
                msg,
            )
            if path_match:
                fpath = path_match.group(1).strip("\"'")
                return f'```json\n{{"name": "read_text_file", "arguments": {{"target_file_path": "{fpath}"}}}}\n```'

        # list_directory — only when the intent is clearly listing a directory (not reading a file)
        if "list_directory" in tool_names:
            is_list_intent = (
                re.search(r"\b(list|show|display)\b.*\b(files?|dir|folder|contents?|entries)\b", msg) or
                re.search(r"\bhow many (python|\.py|files?)\b", msg) or
                re.search(r"\bfiles?\s+(in|inside|under|at)\b", msg) or
                re.search(r"\b(count|number of)\s+files?\b", msg)
            )
            # Exclude if message is about reading a specific file
            is_read_intent = re.search(r"\b(read|open|cat|view|inspect|summarize)\b", msg)
            if is_list_intent and not is_read_intent:
                path = self._extract_relative_path(user_message) or "."
                return f'```json\n{{"name": "list_directory", "arguments": {{"target_path": "{path}"}}}}\n```'

        # bash_exec
        if "bash_exec" in tool_names:
            cmd_match = re.search(r"(?:run|execute|bash|shell|use bash.*?run)\s+`([^`]+)`", msg)
            if cmd_match:
                cmd = cmd_match.group(1)
                return f'```json\n{{"name": "bash_exec", "arguments": {{"command": "{cmd}"}}}}\n```'

        # grep_codebase
        if "grep_codebase" in tool_names:
            grep_match = re.search(
                r"(?:search|grep|find all|find every|look for)\s+(?:the\s+codebase\s+for\s+)?['\"]?([^'\"]+?)['\"]?"
                r"\s*(?:in|across|through|and list|$)",
                msg,
            )
            if grep_match and re.search(r"\b(codebase|import|usage|uses?|files?)\b", msg):
                pattern = grep_match.group(1).strip().strip("'\"")
                return f'```json\n{{"name": "grep_codebase", "arguments": {{"pattern": "{pattern}"}}}}\n```'

        return None

    def _build_tool_nudge(self, user_message: str, available_tools: List[Dict]) -> Optional[Dict]:
        """Return a dict {tool, nudge} with a precise JSON example to force the model to call a tool.

        Unlike _detect_prefix_injection (which failed because a complete assistant message is
        treated as already-done), this nudge is injected as a USER message so the model
        generates the JSON as its next ASSISTANT response, which the tool parser then picks up.
        """
        tool_names = {t.get("function", t).get("name", "") for t in (available_tools or [])}
        msg = user_message.strip().lower()

        def make_nudge(tool: str, args: dict) -> dict:
            json_block = json.dumps({"name": tool, "arguments": args}, indent=None)
            return {
                "tool": tool,
                "nudge": (
                    f"You did not call any tool. To answer this question you MUST call a tool. "
                    f"Output ONLY this JSON block and nothing else:\n"
                    f"```json\n{json_block}\n```"
                ),
            }

        # read_text_file
        if "read_text_file" in tool_names:
            path_match = re.search(
                r"(?:read|open|show|cat|view|inspect|check|look at|summari[sz]e)\s+"
                r"(?:the\s+)?(?:file\s+|contents?\s+of\s+)?([a-zA-Z][\w./\-]+\.[a-zA-Z]{1,5})",
                msg,
            )
            if path_match:
                fpath = path_match.group(1).strip("\"'")
                return make_nudge("read_text_file", {"target_file_path": fpath})

        # list_directory
        if "list_directory" in tool_names:
            is_list = (
                re.search(r"\b(list|show|display)\b.*\b(files?|dir|folder|contents?|entries)\b", msg)
                or re.search(r"\bhow many (python|\.py|files?)\b", msg)
                or re.search(r"\bfiles?\s+(in|inside|under|at)\b", msg)
                or re.search(r"\b(count|number of)\s+files?\b", msg)
            )
            is_read = re.search(r"\b(read|open|cat|view|inspect|summarize)\b", msg)
            if is_list and not is_read:
                path = self._extract_relative_path(user_message) or "."
                return make_nudge("list_directory", {"target_path": path})

        # bash_exec
        if "bash_exec" in tool_names:
            cmd_match = re.search(r"(?:run|execute|use bash|shell)\s+`([^`]+)`", msg)
            if cmd_match:
                return make_nudge("bash_exec", {"command": cmd_match.group(1)})

        # grep_codebase
        if "grep_codebase" in tool_names:
            if re.search(r"\b(search|grep|find all|find every|look for)\b", msg) and \
               re.search(r"\b(codebase|import|usage|uses?|across|through)\b", msg):
                grep_match = re.search(r"(?:for|of)\s+['\"]?([a-zA-Z_][\w.]+)['\"]?", msg)
                pattern = grep_match.group(1) if grep_match else "pattern"
                return make_nudge("grep_codebase", {"pattern": pattern})

        # todo_write
        if "todo_write" in tool_names:
            if re.search(r"\b(create|add|make|write)\b.*\btodo\b", msg):
                return make_nudge("todo_write", {"items": []})

        # todo_read
        if "todo_read" in tool_names:
            if re.search(r"\b(read|show|list|get|check)\b.*\btodo\b", msg):
                return make_nudge("todo_read", {})

        return None

    def _detect_required_tool(self, user_message: str, available_tools: List[Dict]) -> Optional[str]:
        """Return the single tool name this message requires, or None if no tool call is needed.

        Used by the zero-tool retry to inject a targeted correction nudge.
        """
        tool_names = {t.get("function", t).get("name", "") for t in (available_tools or [])}
        msg = user_message.strip().lower()

        if "read_text_file" in tool_names:
            if re.search(
                r"(?:read|open|show|cat|view|inspect|check|look at|summari[sz]e)\s+"
                r"(?:the\s+)?(?:file\s+|contents?\s+of\s+)?[a-zA-Z][\w./\-]+\.[a-zA-Z]{1,5}",
                msg,
            ):
                return "read_text_file"

        if "list_directory" in tool_names:
            is_list = (
                re.search(r"\b(list|show|display)\b.*\b(files?|dir|folder|contents?|entries)\b", msg)
                or re.search(r"\bhow many (python|\.py|files?)\b", msg)
                or re.search(r"\bfiles?\s+(in|inside|under|at)\b", msg)
                or re.search(r"\b(count|number of)\s+files?\b", msg)
            )
            is_read = re.search(r"\b(read|open|cat|view|inspect|summarize)\b", msg)
            if is_list and not is_read:
                return "list_directory"

        if "bash_exec" in tool_names:
            if re.search(r"(?:run|execute|use bash|shell)\s+`[^`]+`", msg):
                return "bash_exec"

        if "grep_codebase" in tool_names:
            if re.search(r"\b(search|grep|find all|find every|look for)\b", msg) and \
               re.search(r"\b(codebase|import|usage|uses?|across|through)\b", msg):
                return "grep_codebase"

        if "todo_write" in tool_names:
            if re.search(r"\b(create|add|make|write)\b.*\btodo\b", msg):
                return "todo_write"

        if "todo_read" in tool_names:
            if re.search(r"\b(read|show|list|get|check)\b.*\btodo\b", msg):
                return "todo_read"

        return None

    def _extract_relative_path(self, user_message: str) -> Optional[str]:
        """Extract a relative path (no leading /) from user message for use as a tool argument."""
        # Match explicit relative paths like "services/orchestrator/" or "apps/cli/"
        rel_match = re.search(r"\b([a-zA-Z][\w./\-]+/[\w./\-]*)\b", user_message)
        if rel_match:
            path = rel_match.group(1).rstrip(".")
            if not path.startswith("/"):
                return path.rstrip("/") or "."
        # Fall back to current directory
        return "."

    def reset(self) -> None:
        """Reset agent state for a new conversation."""
        self.state = AgentState()
        logger.debug("Agent state reset")
