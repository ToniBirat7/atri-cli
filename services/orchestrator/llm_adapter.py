"""
LLM Adapter for llama.cpp OpenAI-compatible API.

Abstracts away llama.cpp-specific details. Implements:
- Tool-calling with non-streamed responses for reliability
- OpenAI-compatible and native Gemma 4 tool-call parsing
- Response parsing for tool calls
- Error handling and retries (Phase 5)
"""

from typing import Optional, List, Dict, Any
import asyncio
import httpx
import json
import logging
import re
from dataclasses import dataclass

try:
    from .config import LLMConfig
    from .logging_context import get_request_id, get_turn_id
except ImportError:
    from config import LLMConfig
    from logging_context import get_request_id, get_turn_id

logger = logging.getLogger(__name__)


def _log_event(event: str, **fields: Any) -> None:
    payload: Dict[str, Any] = {
        "event": event,
        "request_id": get_request_id(),
        "turn_id": get_turn_id(),
    }
    payload.update(fields)
    logger.info(json.dumps(payload, ensure_ascii=True))

@dataclass
class ToolUse:
    """Represents a tool call extracted from LLM response."""
    tool_name: str
    tool_input: Dict[str, Any]
    id: Optional[str] = None


# Alias for backward compatibility
ToolCall = ToolUse

# Gemma 4 emits reasoning inside <|channel>thought...<channel|> blocks.
# Some builds also emit <think>...</think>. Strip both from user-facing output.
_THINKING_BLOCK_RE = re.compile(
    r"<\|channel>thought.*?<channel\|>\s*|<think>.*?</think>\s*",
    re.DOTALL,
)


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
        self._max_retry_attempts = 3
        self._retryable_status_codes = {408, 409, 425, 429}

    def _is_retryable_status(self, status_code: int) -> bool:
        return status_code >= 500 or status_code in self._retryable_status_codes

    def _is_retryable_transport_error(self, error: Exception) -> bool:
        # These error classes represent transient network/transport failures.
        return isinstance(error, (httpx.TimeoutException, httpx.TransportError))

    async def close(self):
        """Clean up HTTP client."""
        await self.client.aclose()

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        parallel_tool_calls: Optional[bool] = None,
        enable_thinking: bool = False,
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
            "top_p": self.config.top_p,
            "top_k": self.config.top_k,
            "max_tokens": tokens,
        }

        # Add tools if provided (Phase 1: non-streamed tool calling)
        if tools:
            request_body["tools"] = tools
            request_body["tool_choice"] = "auto"
            request_body["parallel_tool_calls"] = (
                self.config.parallel_tool_calls if parallel_tool_calls is None else parallel_tool_calls
            )

        # Pass enable_thinking to llama.cpp via extra_body so the Gemma 4
        # Jinja template can inject <|think|> / suppress <|channel>thought blocks.
        request_body["extra_body"] = {"enable_thinking": enable_thinking}

        has_tool_result_context = any(message.get("role") == "tool" for message in messages)
        max_attempts = self._max_retry_attempts

        try:
            for attempt in range(1, max_attempts + 1):
                _log_event(
                    "llm.request.start",
                    attempt=attempt,
                    max_attempts=max_attempts,
                    message_count=len(messages),
                    tool_schema_count=len(tools) if tools else 0,
                    has_tool_result_context=has_tool_result_context,
                )
                try:
                    response = await self.client.post(
                        "/chat/completions",
                        json=request_body
                    )
                except Exception as e:
                    retryable = self._is_retryable_transport_error(e)
                    will_retry = retryable and attempt < max_attempts
                    logger.error(
                        json.dumps(
                            {
                                "event": "llm.request.transport_error",
                                "request_id": get_request_id(),
                                "turn_id": get_turn_id(),
                                "attempt": attempt,
                                "max_attempts": max_attempts,
                                "retryable": retryable,
                                "will_retry": will_retry,
                                "error_type": type(e).__name__,
                                "error": str(e),
                                "error_repr": repr(e),
                                "message_count": len(messages),
                                "tool_schema_count": len(tools) if tools else 0,
                            },
                            ensure_ascii=True,
                        )
                    )
                    if will_retry:
                        await asyncio.sleep(0.25 * attempt)
                        continue
                    raise

                if self._is_retryable_status(response.status_code) and attempt < max_attempts:
                    _log_event(
                        "llm.request.retry",
                        attempt=attempt,
                        status_code=response.status_code,
                    )
                    await asyncio.sleep(0.25 * attempt)
                    continue

                response.raise_for_status()
                result = response.json()
                _log_event(
                    "llm.request.success",
                    attempt=attempt,
                    finish_reason=result.get("choices", [{}])[0].get("finish_reason"),
                )
                return result
        except httpx.HTTPStatusError as e:
            response_text = ""
            try:
                response_text = e.response.text
            except Exception:
                response_text = "<unavailable>"

            request_url = ""
            request_method = ""
            try:
                request_url = str(e.request.url)
                request_method = e.request.method
            except Exception:
                request_url = "<unavailable>"
                request_method = "<unavailable>"

            logger.error(json.dumps({
                "event": "llm.request.status_error",
                "request_id": get_request_id(),
                "turn_id": get_turn_id(),
                "error": str(e),
                "error_repr": repr(e),
                "error_type": type(e).__name__,
                "status_code": getattr(e.response, "status_code", "unknown"),
                "request_url": request_url,
                "request_method": request_method,
                "body": response_text[:2000],
                "message_count": len(messages),
                "tool_schema_count": len(tools) if tools else 0,
            }, ensure_ascii=True))
            raise
        except httpx.HTTPError as e:
            logger.error(json.dumps({
                "event": "llm.request.http_error",
                "request_id": get_request_id(),
                "turn_id": get_turn_id(),
                "error": str(e),
                "error_repr": repr(e),
                "error_type": type(e).__name__,
                "message_count": len(messages),
                "tool_schema_count": len(tools) if tools else 0,
            }, ensure_ascii=True))
            raise
        except json.JSONDecodeError as e:
            logger.error(json.dumps({
                "event": "llm.response.decode_error",
                "request_id": get_request_id(),
                "turn_id": get_turn_id(),
                "error": str(e),
            }, ensure_ascii=True))
            raise

    async def extract_tool_calls(self, completion: Dict[str, Any]) -> List[ToolUse]:
        """
        Extract tool calls from completion response.

        Returns:
            List of ToolUse objects representing requested tool calls.
        """
        tool_calls = []
        choice = completion.get("choices", [{}])[0]
        message = choice.get("message", {}) or {}
        
        # Check for tool_calls in response
        if "tool_calls" in message and message["tool_calls"] is not None:
            for call in message["tool_calls"]:
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

        if tool_calls:
            return tool_calls

        content = message.get("content") or ""
        # Strip thinking blocks from content before extracting tool calls
        content = self.strip_thinking_blocks(content)
        return self._extract_native_tool_calls(content)

    @staticmethod
    def strip_thinking_blocks(text: str) -> str:
        """Remove Gemma 4 reasoning blocks from LLM output before showing to user.

        Gemma 4 wraps internal reasoning in <|channel>thought...<channel|>.
        Some builds additionally emit <think>...</think>. Both are stripped and
        logged at DEBUG level for diagnostics.
        """
        if "<|channel>" not in text and "<think>" not in text:
            return text
        thinking_matches = _THINKING_BLOCK_RE.findall(text)
        for block in thinking_matches:
            logger.debug(json.dumps({
                "event": "llm.thinking_block",
                "content": block[:500],
            }, ensure_ascii=True))
        cleaned = _THINKING_BLOCK_RE.sub("", text).strip()
        return cleaned

    def extract_response_text(self, completion: dict) -> str:
        """Extract the assistant's text response, stripping thinking blocks."""
        choice = completion.get("choices", [{}])[0]
        message = choice.get("message", {}) or {}
        content = message.get("content") or ""
        return self.strip_thinking_blocks(content)

    def _extract_native_tool_calls(self, text: str) -> List[ToolUse]:
        """Fallback parser for Gemma 4 native tool-call tokens in assistant text."""
        if not text:
            return []

        tool_call_pattern = re.compile(
            r"<\|tool_call\>call:(?P<name>[A-Za-z_][\w\-]*)\{(?P<args>.*?)\}<tool_call\|>",
            re.DOTALL,
        )

        parsed_calls: List[ToolUse] = []
        for match in tool_call_pattern.finditer(text):
            parsed_calls.append(
                ToolUse(
                    tool_name=match.group("name"),
                    tool_input=self._parse_native_arguments(match.group("args")),
                )
            )

        return parsed_calls

    def _parse_native_arguments(self, argument_block: str) -> Dict[str, Any]:
        """Parse Gemma 4 native key/value arguments into Python types."""
        argument_pattern = re.compile(
            r"(?P<key>[A-Za-z_][\w\-]*)\s*:\s*(?:<\|\"\|>(?P<quoted>.*?)<\|\"\|>|(?P<raw>[^,}]*))",
            re.DOTALL,
        )

        arguments: Dict[str, Any] = {}
        for match in argument_pattern.finditer(argument_block):
            raw_value = match.group("quoted") if match.group("quoted") is not None else match.group("raw")
            arguments[match.group("key")] = self._coerce_native_value(raw_value.strip())

        return arguments

    def _coerce_native_value(self, value: str) -> Any:
        """Best-effort conversion of native Gemma string values."""
        if value.lower() == "true":
            return True
        if value.lower() == "false":
            return False

        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            return value.strip("\"'")

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
