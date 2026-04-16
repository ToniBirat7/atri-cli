"""
LLM Adapter for llama.cpp OpenAI-compatible API.

Abstracts away llama.cpp-specific details. Implements:
- Tool-calling with non-streamed responses for reliability
- Automatic tool schema injection into system prompt
- Response parsing for tool calls
- Error handling and retries (Phase 5)
"""

from typing import Optional, List, Dict, Any
import httpx
import json
import logging
from dataclasses import dataclass
from .config import LLMConfig

logger = logging.getLogger(__name__)


@dataclass
class ToolUse:
    """Represents a tool call extracted from LLM response."""
    tool_name: str
    tool_input: Dict[str, Any]
    id: Optional[str] = None


class LLMAdapter:
    """
    Adapter for llama.cpp OpenAI-compatible endpoint.
    
    Phase 1: Basic tool-calling support (non-streamed).
    Phase 3: Streaming responses.
    Phase 5: Retry logic, circuit-breaker, budget tracking.
    """

    def __init__(self, config: LLMConfig):
        self.config = config
        self.client = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=config.timeout_seconds
        )
        if config.api_key:
            self.client.headers["Authorization"] = f"Bearer {config.api_key}"

    async def close(self):
        """Clean up HTTP client."""
        await self.client.aclose()

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Make a chat completion request to llama.cpp.

        Args:
            messages: Conversation history
            tools: Available tools (JSON Schema format)
            temperature: Override default temperature
            max_tokens: Override default max_tokens

        Returns:
            Raw response from llama.cpp (parsed JSON)
        """
        temp = temperature if temperature is not None else self.config.temperature
        tokens = max_tokens if max_tokens is not None else self.config.max_tokens

        request_body = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temp,
            "max_tokens": tokens,
        }

        # Add tools if provided (Phase 1: non-streamed tool calling)
        if tools:
            request_body["tools"] = tools
            request_body["tool_choice"] = "auto"

        try:
            logger.debug(f"Calling llama.cpp with {len(messages)} messages")
            response = await self.client.post(
                "/chat/completions",
                json=request_body
            )
            response.raise_for_status()
            result = response.json()
            logger.debug(f"LLM response: {result.get('choices', [{}])[0].get('finish_reason')}")
            return result
        except httpx.HTTPError as e:
            logger.error(f"LLM adapter HTTP error: {e}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response: {e}")
            raise

    async def extract_tool_calls(self, completion: Dict[str, Any]) -> List[ToolUse]:
        """
        Extract tool calls from completion response.

        Returns:
            List of ToolUse objects representing requested tool calls.
        """
        tool_calls = []
        choice = completion.get("choices", [{}])[0]
        
        # Check for tool_calls in response
        if "tool_calls" in choice:
            for call in choice["tool_calls"]:
                try:
                    tool_calls.append(
                        ToolUse(
                            tool_name=call["function"]["name"],
                            tool_input=json.loads(call["function"]["arguments"]),
                            id=call.get("id")
                        )
                    )
                except (KeyError, json.JSONDecodeError) as e:
                    logger.warning(f"Failed to parse tool call: {e}")
        
        return tool_calls

    def format_tool_result(
        self,
        tool_name: str,
        result: str,
        tool_call_id: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Format tool result for inclusion in chat messages.

        Returns:
            Message object to append to conversation history.
        """
        return {
            "role": "tool",
            "content": result,
            "tool_call_id": tool_call_id or f"call_{tool_name}",
            "name": tool_name,
        }
