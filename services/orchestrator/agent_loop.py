"""
Deterministic Agent Loop.

Implements the core agentic AI loop:
1. User message → LLM
2. LLM response with tool calls → Tool execution
3. Tool results → LLM context
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

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class TurnOutcome(str, Enum):
    """Outcome of a single agent loop turn."""
    TOOL_CALLS = "tool_calls"  # LLM issued tool calls
    NO_TOOL_CALLS = "no_tool_calls"  # LLM responded without tools
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
    status: str = "initialized"  # initialized, running, completed, error


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
    ):
        self.max_turns = max_turns
        self.max_tool_calls_per_turn = max_tool_calls_per_turn
        self.enable_tool_use = enable_tool_use
        self.state = AgentState()

    async def run(
        self,
        user_message: str,
        llm_adapter: "LLMAdapter",  # type: ignore
        mcp_orchestrator: "MCPOrchestrator",  # type: ignore
        tool_registry: "ToolRegistry",  # type: ignore
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
        self.state.status = "running"
        self.state.messages = [
            {
                "role": "system",
                "content": self._build_system_prompt(),
            },
            {
                "role": "user",
                "content": user_message,
            }
        ]

        logger.info(f"Starting agent loop with user message: {user_message[:100]}...")

        while self.state.turn < self.max_turns:
            self.state.turn += 1
            turn = Turn(turn_number=self.state.turn, user_input=user_message)

            try:
                # Call LLM
                available_tools = (
                    tool_registry.to_openai_format()
                    if self.enable_tool_use
                    else None
                )
                
                completion = await llm_adapter.chat_completion(
                    messages=self.state.messages,
                    tools=available_tools,
                )

                # Extract response and tool calls
                choice = completion.get("choices", [{}])[0]
                content = choice.get("message", {}).get("content", "")
                turn.llm_response = content

                # Check for tool calls
                tool_calls = await llm_adapter.extract_tool_calls(completion)
                turn.tool_calls_requested = len(tool_calls)

                if not tool_calls:
                    # No tool calls, agent is done
                    self.state.final_response = content
                    turn.outcome = TurnOutcome.NO_TOOL_CALLS
                    self.state.turns_history.append(turn)
                    logger.info(f"Turn {self.state.turn}: Agent issued final response")
                    break

                # Enforce max tool calls per turn
                if len(tool_calls) > self.max_tool_calls_per_turn:
                    logger.warning(
                        f"Turn {self.state.turn}: "
                        f"LLM requested {len(tool_calls)} tools, "
                        f"exceeds max {self.max_tool_calls_per_turn}"
                    )
                    tool_calls = tool_calls[:self.max_tool_calls_per_turn]

                # Execute tools
                self.state.messages.append({
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [
                        {
                            "id": call.id or f"call_{i}",
                            "function": {
                                "name": call.tool_name,
                                "arguments": str(call.tool_input),
                            }
                        }
                        for i, call in enumerate(tool_calls)
                    ]
                })

                for tool_call in tool_calls:
                    try:
                        # In Phase 4+, route to correct server based on tool_name
                        result = await mcp_orchestrator.execute_tool(
                            server_name="local-mcp",  # Phase 1: hardcoded
                            tool_name=tool_call.tool_name,
                            tool_input=tool_call.tool_input,
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
                        
                        logger.debug(
                            f"Turn {self.state.turn}: "
                            f"Executed {tool_call.tool_name}"
                        )
                    except Exception as e:
                        logger.error(
                            f"Turn {self.state.turn}: "
                            f"Tool execution failed: {e}"
                        )
                        self.state.messages.append(
                            llm_adapter.format_tool_result(
                                tool_call.tool_name,
                                f"Error: {str(e)}",
                                tool_call.id,
                            )
                        )

                turn.outcome = TurnOutcome.TOOL_CALLS
                self.state.turns_history.append(turn)

            except Exception as e:
                logger.error(f"Turn {self.state.turn}: Error in agent loop: {e}")
                turn.outcome = TurnOutcome.ERROR
                turn.error = str(e)
                self.state.turns_history.append(turn)
                self.state.status = "error"
                raise

        if self.state.turn >= self.max_turns:
            # Extract final response from last message
            if self.state.messages:
                last_msg = self.state.messages[-1]
                if last_msg.get("role") == "assistant":
                    self.state.final_response = last_msg.get("content", "")
            turn = Turn(
                turn_number=self.state.turn,
                outcome=TurnOutcome.MAX_TURNS_REACHED
            )
            self.state.turns_history.append(turn)
            logger.warning(f"Reached max turns limit: {self.max_turns}")

        self.state.status = "completed"
        logger.info(
            f"Agent loop completed: {self.state.turn} turns, "
            f"{self.state.total_tool_calls} tool calls"
        )

        return self.state.final_response or "", self.state

    def _build_system_prompt(self) -> str:
        """Build system prompt for the agent."""
        return (
            "You are a helpful AI assistant. "
            "You can use tools to help answer user questions. "
            "Be concise and direct in your responses."
        )

    def reset(self) -> None:
        """Reset agent state for a new conversation."""
        self.state = AgentState()
        logger.debug("Agent state reset")
