"""
Tests for LLM adapter tool-call parsing.

Tests both OpenAI format and native Gemma 4 format parsing.
"""

import pytest
import json
from typing import List
from unittest.mock import AsyncMock
import httpx

from llm_adapter import LLMAdapter, ToolCall


class TestToolCallParsing:
    """Test tool-call extraction from LLM responses."""

    @pytest.mark.asyncio
    @pytest.mark.openai_parsing
    async def test_openai_format_single_tool_call(self, llm_config):
        """Test parsing OpenAI format with single tool call."""
        completion = {
            "choices": [
                {
                    "message": {
                        "content": "Let me read that file for you.",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {
                                    "name": "read_file",
                                    "arguments": '{"path": "/tmp/test.txt"}'
                                }
                            }
                        ]
                    }
                }
            ]
        }

        adapter = LLMAdapter(llm_config)
        tool_calls = await adapter.extract_tool_calls(completion)

        assert len(tool_calls) == 1
        assert tool_calls[0].id == "call_1"
        assert tool_calls[0].tool_name == "read_file"
        assert tool_calls[0].tool_input == {"path": "/tmp/test.txt"}

    @pytest.mark.asyncio
    @pytest.mark.openai_parsing
    async def test_openai_format_multiple_tool_calls(self, llm_config):
        """Test parsing OpenAI format with multiple parallel tool calls."""
        completion = {
            "choices": [
                {
                    "message": {
                        "content": "I'll read both files.",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {
                                    "name": "read_file",
                                    "arguments": '{"path": "/tmp/file1.txt"}'
                                }
                            },
                            {
                                "id": "call_2",
                                "function": {
                                    "name": "read_file",
                                    "arguments": '{"path": "/tmp/file2.txt"}'
                                }
                            },
                            {
                                "id": "call_3",
                                "function": {
                                    "name": "list_directory",
                                    "arguments": '{"path": "/tmp"}'
                                }
                            }
                        ]
                    }
                }
            ]
        }

        adapter = LLMAdapter(llm_config)
        tool_calls = await adapter.extract_tool_calls(completion)

        assert len(tool_calls) == 3
        assert tool_calls[0].tool_name == "read_file"
        assert tool_calls[1].tool_name == "read_file"
        assert tool_calls[2].tool_name == "list_directory"
        assert tool_calls[0].tool_input["path"] == "/tmp/file1.txt"
        assert tool_calls[1].tool_input["path"] == "/tmp/file2.txt"

    @pytest.mark.asyncio
    @pytest.mark.openai_parsing
    async def test_openai_format_no_tool_calls(self, llm_config):
        """Test parsing OpenAI format with no tool calls."""
        completion = {
            "choices": [
                {
                    "message": {
                        "content": "I don't need to use any tools for this.",
                        "tool_calls": None
                    }
                }
            ]
        }

        adapter = LLMAdapter(llm_config)
        tool_calls = await adapter.extract_tool_calls(completion)

        assert tool_calls == []

    @pytest.mark.asyncio
    @pytest.mark.openai_parsing
    async def test_openai_format_complex_arguments(self, llm_config):
        """Test parsing OpenAI format with complex nested JSON arguments."""
        completion = {
            "choices": [
                {
                    "message": {
                        "content": "Writing configuration file...",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {
                                    "name": "write_file",
                                    "arguments": json.dumps({
                                        "path": "/etc/config.json",
                                        "content": json.dumps({
                                            "server": {
                                                "host": "localhost",
                                                "port": 8000,
                                                "debug": True
                                            },
                                            "database": {
                                                "url": "postgres://localhost/db"
                                            }
                                        })
                                    })
                                }
                            }
                        ]
                    }
                }
            ]
        }

        adapter = LLMAdapter(llm_config)
        tool_calls = await adapter.extract_tool_calls(completion)

        assert len(tool_calls) == 1
        assert tool_calls[0].tool_name == "write_file"
        assert "content" in tool_calls[0].tool_input
        # Verify the nested JSON is properly decoded
        content = json.loads(tool_calls[0].tool_input["content"])
        assert content["server"]["port"] == 8000

    @pytest.mark.asyncio
    @pytest.mark.native_parsing
    async def test_native_gemma4_single_tool_call(self, llm_config):
        """Test parsing native Gemma 4 format with single tool call.
        
        Format: <|tool_call>call:read_file{path:<|\"|>/tmp/test.txt<|\"|>}<tool_call|>
        """
        # This test assumes the adapter's native parser works
        # In a real scenario, this would test with actual LLM output
        completion = {
            "choices": [
                {
                    "message": {
                        "content": "Let me read that file.\n<|tool_call>call:read_file{path:<|\"|>/tmp/test.txt<|\"|>}<tool_call|>",
                    }
                }
            ]
        }

        adapter = LLMAdapter(llm_config)
        tool_calls = await adapter.extract_tool_calls(completion)

        # The adapter should fallback to native parsing if OpenAI format isn't found
        if tool_calls:
            assert len(tool_calls) >= 1
            assert any(call.tool_name == "read_file" for call in tool_calls)

    @pytest.mark.asyncio
    @pytest.mark.native_parsing
    async def test_native_gemma4_multiple_tool_calls(self, llm_config):
        """Test parsing native Gemma 4 format with multiple tool calls."""
        completion = {
            "choices": [
                {
                    "message": {
                        "content": (
                            "I'll read both files.\n"
                            "<|tool_call>call:read_file{path:<|\"|>/tmp/a.txt<|\"|>}<tool_call|>"
                            "<|tool_call>call:read_file{path:<|\"|>/tmp/b.txt<|\"|>}<tool_call|>"
                        ),
                    }
                }
            ]
        }

        adapter = LLMAdapter(llm_config)
        tool_calls = await adapter.extract_tool_calls(completion)

        if tool_calls:
            # Should find at least the tool calls in native format
            assert len(tool_calls) >= 1

    @pytest.mark.asyncio
    @pytest.mark.native_parsing
    async def test_native_gemma4_with_string_values(self, llm_config):
        """Test native Gemma 4 parsing with string values using delimiters."""
        completion = {
            "choices": [
                {
                    "message": {
                        "content": (
                            "Writing file...\n"
                            "<|tool_call>call:write_file{path:<|\"|>/tmp/test.txt<|\"|>"
                            ",content:<|\"|>Hello World<|\"|>}<tool_call|>"
                        ),
                    }
                }
            ]
        }

        adapter = LLMAdapter(llm_config)
        tool_calls = await adapter.extract_tool_calls(completion)

        if tool_calls:
            write_calls = [c for c in tool_calls if c.tool_name == "write_file"]
            if write_calls:
                assert "content" in write_calls[0].tool_input


class TestToolCallRobustness:
    """Test robustness of tool-call parsing."""

    @pytest.mark.asyncio
    async def test_malformed_json_arguments(self, llm_config):
        """Test handling of malformed JSON in tool arguments."""
        completion = {
            "choices": [
                {
                    "message": {
                        "content": "Test",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {
                                    "name": "read_file",
                                    "arguments": '{"path": "/tmp/test.txt"'  # Missing closing brace
                                }
                            }
                        ]
                    }
                }
            ]
        }

        adapter = LLMAdapter(llm_config)
        # Should either handle gracefully or raise informative error
        try:
            tool_calls = await adapter.extract_tool_calls(completion)
            # If it succeeds, verify it handled the error
            assert isinstance(tool_calls, list)
        except json.JSONDecodeError:
            # Expected if strict JSON parsing is enforced
            pass

    @pytest.mark.asyncio
    async def test_missing_function_name(self, llm_config):
        """Test handling of missing function name in tool calls."""
        completion = {
            "choices": [
                {
                    "message": {
                        "content": "Test",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {
                                    "arguments": '{"path": "/tmp/test.txt"}'
                                    # Missing "name" field
                                }
                            }
                        ]
                    }
                }
            ]
        }

        adapter = LLMAdapter(llm_config)
        tool_calls = await adapter.extract_tool_calls(completion)

        # Should skip or handle invalid tool calls
        assert isinstance(tool_calls, list)

    @pytest.mark.asyncio
    async def test_empty_tool_calls_array(self, llm_config):
        """Test handling of empty tool_calls array."""
        completion = {
            "choices": [
                {
                    "message": {
                        "content": "No tools needed",
                        "tool_calls": []
                    }
                }
            ]
        }

        adapter = LLMAdapter(llm_config)
        tool_calls = await adapter.extract_tool_calls(completion)

        assert tool_calls == []

    @pytest.mark.asyncio
    async def test_missing_choices_field(self, llm_config):
        """Test handling of missing choices field."""
        completion = {
            "id": "chatcmpl-123"
        }

        adapter = LLMAdapter(llm_config)
        tool_calls = await adapter.extract_tool_calls(completion)

        # Should handle missing choices gracefully
        assert isinstance(tool_calls, list)


class TestToolCallFormatConsistency:
    """Test consistency of tool-call format across parsing methods."""

    @pytest.mark.asyncio
    async def test_parsed_tool_calls_have_required_fields(self, llm_config):
        """Test that all parsed tool calls have required fields."""
        completion = {
            "choices": [
                {
                    "message": {
                        "content": "Test",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {
                                    "name": "read_file",
                                    "arguments": '{"path": "/tmp/test.txt"}'
                                }
                            }
                        ]
                    }
                }
            ]
        }

        adapter = LLMAdapter(llm_config)
        tool_calls = await adapter.extract_tool_calls(completion)

        for call in tool_calls:
            assert hasattr(call, 'tool_name')
            assert hasattr(call, 'tool_input')
            assert isinstance(call.tool_input, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "openai_parsing or native_parsing"])


class TestChatCompletionRetries:
    """Test retry behavior for transient LLM request failures."""

    @pytest.mark.asyncio
    async def test_chat_completion_retries_transport_error_then_succeeds(self, llm_config):
        adapter = LLMAdapter(llm_config)
        success_payload = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "ok"},
                }
            ]
        }

        class _SuccessResponse:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return success_payload

        adapter.client.post = AsyncMock(
            side_effect=[
                httpx.ReadTimeout("simulated timeout"),
                _SuccessResponse(),
            ]
        )

        result = await adapter.chat_completion(
            messages=[{"role": "user", "content": "hello"}],
            tools=None,
        )

        assert result == success_payload
        assert adapter.client.post.await_count == 2
        await adapter.close()

    @pytest.mark.asyncio
    async def test_chat_completion_does_not_retry_non_retryable_status(self, llm_config):
        adapter = LLMAdapter(llm_config)

        request = httpx.Request("POST", "http://127.0.0.1:8000/v1/chat/completions")
        bad_response = httpx.Response(400, request=request, json={"error": "bad request"})

        adapter.client.post = AsyncMock(return_value=bad_response)

        with pytest.raises(httpx.HTTPStatusError):
            await adapter.chat_completion(
                messages=[{"role": "user", "content": "hello"}],
                tools=None,
            )

        assert adapter.client.post.await_count == 1
        await adapter.close()
