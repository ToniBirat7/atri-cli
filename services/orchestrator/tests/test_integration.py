"""
Integration tests for the full agent loop + LLM + MCP stack.

Tests end-to-end workflows:
- Tool calling with native Gemma 4 format
- Tool calling with OpenAI format
- Error handling and recovery
- State tracking and observability
- Budget enforcement
"""

import pytest
import json
import asyncio
from unittest.mock import AsyncMock, Mock, patch, MagicMock
from typing import Dict, Any

from agent_loop import AgentLoop, AgentState, TurnOutcome
from llm_adapter import LLMAdapter, ToolCall
from tool_registry import ToolRegistry
from mcp_orchestrator import MCPOrchestrator


class MockLLMAdapter:
    """Mock LLM adapter for testing."""

    def __init__(self):
        self.call_count = 0
        self.responses = []
        self.extracted_calls = []

    async def chat_completion(self, messages, tools=None):
        """Mock chat completion."""
        self.call_count += 1
        if self.call_count <= len(self.responses):
            return self.responses[self.call_count - 1]
        return {
            "choices": [
                {
                    "message": {
                        "content": "Default response",
                        "tool_calls": []
                    }
                }
            ]
        }

    async def extract_tool_calls(self, completion):
        """Mock tool call extraction."""
        if self.call_count <= len(self.extracted_calls):
            return self.extracted_calls[self.call_count - 1]
        return []

    def format_tool_result(self, tool_name, result, tool_id=None):
        """Format tool result message."""
        return {
            "role": "tool",
            "name": tool_name,
            "content": json.dumps(result) if isinstance(result, dict) else str(result),
            "tool_call_id": tool_id or "call_0",
        }


class MockMCPOrchestrator:
    """Mock MCP orchestrator for testing."""

    def __init__(self):
        self.executed_tools = []
        self.tool_results = {}

    async def execute_tool(self, server_name, tool_name, tool_input):
        """Mock tool execution."""
        self.executed_tools.append({
            "server": server_name,
            "tool": tool_name,
            "input": tool_input,
        })
        return self.tool_results.get(tool_name, {"status": "ok"})


class MockToolRegistry:
    """Mock tool registry for testing."""

    def to_openai_format(self):
        """Return mock OpenAI tools format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"}
                        },
                        "required": ["path"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "Write to a file",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"}
                        },
                        "required": ["path", "content"]
                    }
                }
            }
        ]


class TestAgentLoopBasics:
    """Test basic agent loop functionality."""

    @pytest.mark.asyncio
    async def test_agent_loop_no_tools(self):
        """Test agent loop with no tool calls."""
        loop = AgentLoop(max_turns=5)
        llm = MockLLMAdapter()
        mcp = MockMCPOrchestrator()
        tools = MockToolRegistry()

        # LLM returns text without tool calls
        llm.responses = [
            {
                "choices": [
                    {
                        "message": {
                            "content": "This is the final answer.",
                            "tool_calls": []
                        }
                    }
                ]
            }
        ]
        llm.extracted_calls = [[]]

        final_response, state = await loop.run(
            "What is 2+2?",
            llm,
            mcp,
            tools
        )

        assert final_response == "This is the final answer."
        assert state.turn == 1
        assert state.status == "completed"
        assert state.total_tool_calls == 0
        assert state.turns_history[0].outcome == TurnOutcome.NO_TOOL_CALLS

    @pytest.mark.asyncio
    async def test_agent_loop_single_tool_call(self):
        """Test agent loop with a single tool call."""
        loop = AgentLoop(max_turns=5)
        llm = MockLLMAdapter()
        mcp = MockMCPOrchestrator()
        tools = MockToolRegistry()

        # Set up tool results
        mcp.tool_results["read_file"] = {"content": "Hello, World!"}

        # First response: request tool call
        tool_call = ToolCall(
            id="call_1",
            tool_name="read_file",
            tool_input={"path": "/tmp/test.txt"}
        )

        llm.responses = [
            {
                "choices": [
                    {
                        "message": {
                            "content": "Let me read that file.",
                            "tool_calls": [tool_call]
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": "The file contains: Hello, World!",
                            "tool_calls": []
                        }
                    }
                ]
            }
        ]

        llm.extracted_calls = [[tool_call], []]

        final_response, state = await loop.run(
            "Read /tmp/test.txt",
            llm,
            mcp,
            tools
        )

        assert "Hello, World!" in final_response
        assert state.turn == 2
        assert state.total_tool_calls == 1
        assert len(mcp.executed_tools) == 1
        assert mcp.executed_tools[0]["tool"] == "read_file"

    @pytest.mark.asyncio
    async def test_agent_loop_parallel_tool_calls(self):
        """Test agent loop with multiple parallel tool calls."""
        loop = AgentLoop(max_turns=5, max_tool_calls_per_turn=3)
        llm = MockLLMAdapter()
        mcp = MockMCPOrchestrator()
        tools = MockToolRegistry()

        # Set up tool results
        mcp.tool_results["read_file"] = {"content": "file1"}
        mcp.tool_results["write_file"] = {"status": "written"}

        # First response: request multiple tool calls
        tool_calls = [
            ToolCall(id="call_1", tool_name="read_file", tool_input={"path": "/tmp/a.txt"}),
            ToolCall(id="call_2", tool_name="read_file", tool_input={"path": "/tmp/b.txt"}),
            ToolCall(id="call_3", tool_name="write_file", tool_input={"path": "/tmp/c.txt", "content": "merged"}),
        ]

        llm.responses = [
            {
                "choices": [
                    {
                        "message": {
                            "content": "Reading both files and merging...",
                            "tool_calls": tool_calls
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": "Successfully merged files.",
                            "tool_calls": []
                        }
                    }
                ]
            }
        ]

        llm.extracted_calls = [tool_calls, []]

        final_response, state = await loop.run(
            "Merge files",
            llm,
            mcp,
            tools
        )

        assert state.total_tool_calls == 3
        assert len(mcp.executed_tools) == 3
        assert state.turn == 2

    @pytest.mark.asyncio
    async def test_agent_loop_max_turns_enforcement(self):
        """Test that agent loop enforces max_turns budget."""
        loop = AgentLoop(max_turns=3, max_tool_calls_per_turn=1)
        llm = MockLLMAdapter()
        mcp = MockMCPOrchestrator()
        tools = MockToolRegistry()

        # Set up responses that always request tool calls
        tool_call = ToolCall(
            id="call_1",
            tool_name="read_file",
            tool_input={"path": "/tmp/test.txt"}
        )

        # Create 4 responses (more than max_turns)
        llm.responses = [
            {
                "choices": [
                    {
                        "message": {
                            "content": f"Turn {i}",
                            "tool_calls": [tool_call]
                        }
                    }
                ]
            }
            for i in range(1, 5)
        ]

        llm.extracted_calls = [[tool_call] for _ in range(4)]
        mcp.tool_results["read_file"] = {"content": "result"}

        final_response, state = await loop.run(
            "Keep going",
            llm,
            mcp,
            tools
        )

        assert state.turn >= 3
        assert len(state.turns_history) >= 3
        # Last turn should be MAX_TURNS_REACHED
        assert state.turns_history[-1].outcome == TurnOutcome.MAX_TURNS_REACHED

    @pytest.mark.asyncio
    async def test_agent_loop_max_tool_calls_per_turn_enforcement(self):
        """Test that agent loop caps tool calls per turn."""
        loop = AgentLoop(max_turns=2, max_tool_calls_per_turn=2)
        llm = MockLLMAdapter()
        mcp = MockMCPOrchestrator()
        tools = MockToolRegistry()

        # LLM requests 5 tools but limit is 2
        tool_calls = [
            ToolCall(id=f"call_{i}", tool_name="read_file", tool_input={"path": f"/tmp/{i}.txt"})
            for i in range(5)
        ]

        llm.responses = [
            {
                "choices": [
                    {
                        "message": {
                            "content": "Reading multiple files",
                            "tool_calls": tool_calls
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": "Done",
                            "tool_calls": []
                        }
                    }
                ]
            }
        ]

        llm.extracted_calls = [tool_calls, []]
        mcp.tool_results["read_file"] = {"content": "result"}

        final_response, state = await loop.run(
            "Read files",
            llm,
            mcp,
            tools
        )

        # Only 2 tools should be executed (max_tool_calls_per_turn)
        assert len(mcp.executed_tools) == 2
        assert state.turns_history[0].tool_calls_executed == 2

    @pytest.mark.asyncio
    async def test_agent_loop_tool_execution_error_handling(self):
        """Test agent loop handles tool execution errors gracefully."""
        loop = AgentLoop(max_turns=5)
        llm = MockLLMAdapter()
        mcp = MockMCPOrchestrator()
        tools = MockToolRegistry()

        # Mock orchestrator to raise an error
        async def failing_execute_tool(*args, **kwargs):
            raise RuntimeError("Tool execution failed: file not found")

        mcp.execute_tool = failing_execute_tool

        tool_call = ToolCall(
            id="call_1",
            tool_name="read_file",
            tool_input={"path": "/nonexistent/file.txt"}
        )

        llm.responses = [
            {
                "choices": [
                    {
                        "message": {
                            "content": "Let me try to read this file",
                            "tool_calls": [tool_call]
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": "The file could not be read, but I can help you another way.",
                            "tool_calls": []
                        }
                    }
                ]
            }
        ]

        llm.extracted_calls = [[tool_call], []]

        final_response, state = await loop.run(
            "Read missing file",
            llm,
            mcp,
            tools
        )

        # Agent should continue despite error
        assert state.turn == 2
        assert "could not be read" in final_response
        assert state.status == "completed"

    @pytest.mark.asyncio
    async def test_agent_loop_thinking_mode(self):
        """Test agent loop with thinking mode enabled."""
        loop = AgentLoop(max_turns=2, enable_thinking=True)
        llm = MockLLMAdapter()
        mcp = MockMCPOrchestrator()
        tools = MockToolRegistry()

        llm.responses = [
            {
                "choices": [
                    {
                        "message": {
                            "content": "The answer is 42",
                            "tool_calls": []
                        }
                    }
                ]
            }
        ]
        llm.extracted_calls = [[]]

        final_response, state = await loop.run(
            "What is the answer?",
            llm,
            mcp,
            tools
        )

        # System prompt should include thinking token
        assert state.messages[0]["content"].startswith("<|think|>")

    @pytest.mark.asyncio
    async def test_agent_loop_state_tracking(self):
        """Test agent loop properly tracks state."""
        loop = AgentLoop(max_turns=3)
        llm = MockLLMAdapter()
        mcp = MockMCPOrchestrator()
        tools = MockToolRegistry()

        tool_call = ToolCall(
            id="call_1",
            tool_name="read_file",
            tool_input={"path": "/tmp/test.txt"}
        )

        llm.responses = [
            {
                "choices": [
                    {
                        "message": {
                            "content": "Reading file",
                            "tool_calls": [tool_call]
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": "Got the content",
                            "tool_calls": []
                        }
                    }
                ]
            }
        ]

        llm.extracted_calls = [[tool_call], []]
        mcp.tool_results["read_file"] = {"content": "data"}

        final_response, state = await loop.run(
            "Test message",
            llm,
            mcp,
            tools
        )

        # Verify state tracking
        assert state.turn == 2
        assert state.total_tool_calls == 1
        assert len(state.messages) >= 4  # system, user, assistant, tool
        assert len(state.turns_history) == 2
        assert state.turns_history[0].tool_calls_requested == 1
        assert state.turns_history[0].tool_calls_executed == 1
        assert state.turns_history[0].outcome == TurnOutcome.TOOL_CALLS
        assert state.turns_history[1].outcome == TurnOutcome.NO_TOOL_CALLS


class TestNativeToolCallParsing:
    """Test native Gemma 4 tool-call format parsing."""

    @pytest.mark.asyncio
    async def test_native_tool_call_extraction(self):
        """Test extraction of native Gemma 4 tool calls."""
        # This would test the llm_adapter's native tool-call parser
        # Mock LLM response with native format: <|tool_call>call:name{key:<|"|>value<|"|>}<tool_call|>
        pass

    @pytest.mark.asyncio
    async def test_openai_tool_call_extraction(self):
        """Test extraction of OpenAI format tool calls."""
        # This would test the llm_adapter's OpenAI format parser
        pass


class TestErrorRecovery:
    """Test error recovery and resilience."""

    @pytest.mark.asyncio
    async def test_malformed_tool_input_handling(self):
        """Test handling of malformed tool input."""
        pass

    @pytest.mark.asyncio
    async def test_network_error_recovery(self):
        """Test recovery from network errors."""
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
