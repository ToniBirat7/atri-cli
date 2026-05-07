"""
LLM Adapter for llama.cpp OpenAI-compatible API.

Abstracts away llama.cpp-specific details. Implements:
- Tool-calling with non-streamed responses for reliability
- OpenAI-compatible and native Gemma 4 tool-call parsing
- Text-based JSON tool-call parsing (fallback for peg-native models that
  ignore the OpenAI `tools` array — verified via token count parity test)
- Response parsing for tool calls
- Error handling and retries (Phase 5)

peg-native format note:
  The served model uses 'peg-native' chat format (llama.cpp b97-ea60547).
  In this format the OpenAI `tools` parameter is silently dropped — prompt_tokens
  are identical whether tools are sent or not. Tool schemas must be injected into
  the system message as plain text, and tool calls parsed from the model's output.
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
        assistant_prefix: Optional[str] = None,
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

        # Inject tool schemas into the system message (peg-native workaround).
        # The OpenAI `tools` array is silently dropped by peg-native — inject as text instead.
        # Must happen BEFORE building request_body so injected messages are sent to LLM.
        if tools:
            messages = self._inject_tools_into_system_message(messages, tools)

        # Prefix injection: force the model to complete a partial assistant turn.
        # This is the most reliable technique for E2B (2.5B) — start the JSON
        # and let the model complete it rather than hoping it picks the right tool.
        if assistant_prefix:
            messages = list(messages) + [{"role": "assistant", "content": assistant_prefix}]

        request_body = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temp,
            "top_p": self.config.top_p,
            "top_k": self.config.top_k,
            "max_tokens": tokens,
            "repeat_penalty": 1.1,
            "frequency_penalty": 0.05,
        }

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
                # Prepend prefix to model output so downstream parsers see the full JSON.
                # Always prepend — model may output empty string (EOS only) meaning the
                # prefix IS the complete tool call and we must not lose it.
                if assistant_prefix and result.get("choices"):
                    msg = result["choices"][0].get("message", {})
                    existing_content = msg.get("content") or ""
                    result["choices"][0]["message"]["content"] = assistant_prefix + existing_content
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

    async def stream_chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        enable_thinking: bool = False,
    ):
        """
        Stream a non-tool-call completion from llama-server token by token.

        Yields string deltas as they arrive. Use only for final answer turns
        where tool calls are not expected — tool parsing requires the full response.
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
            "stream": True,
            "extra_body": {"enable_thinking": enable_thinking},
        }

        _log_event("llm.stream.start", message_count=len(messages))
        buffer = ""
        try:
            async with self.client.stream("POST", "/chat/completions", json=request_body) as resp:
                resp.raise_for_status()
                async for raw_line in resp.aiter_lines():
                    if not raw_line.startswith("data:"):
                        continue
                    payload = raw_line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                        delta = chunk["choices"][0].get("delta", {}).get("content") or ""
                        if delta:
                            buffer += delta
                            # Strip thinking blocks on the fly when they close
                            if "<channel|>" in buffer:
                                buffer = self.strip_thinking_blocks(buffer)
                            # Yield only when we have content outside thinking blocks
                            if "<|channel>" not in buffer:
                                yield buffer
                                buffer = ""
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
            if buffer:
                yield self.strip_thinking_blocks(buffer)
        except Exception as exc:
            _log_event("llm.stream.error", error=str(exc))
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
        """Extract the assistant's text response, stripping thinking blocks and tool call JSON."""
        choice = completion.get("choices", [{}])[0]
        message = choice.get("message", {}) or {}
        content = message.get("content") or ""
        content = self.strip_thinking_blocks(content)
        # Strip JSON code blocks that were emitted as tool calls (peg-native mode)
        content = re.sub(r"```(?:json)?\s*\n?\{.*?\}\s*\n?```", "", content, flags=re.DOTALL).strip()
        # Strip stray ChatML control tokens the model leaks into output
        content = re.sub(r"<\|im_(start|end)\|>", "", content).strip()
        return content

    def _extract_native_tool_calls(self, text: str) -> List[ToolUse]:
        """Fallback parser — tries JSON code-block format first, then Gemma4 native tokens.

        JSON code-block format (used when peg-native drops the OpenAI tools array):
            ```json
            {"name": "tool_name", "arguments": {"param": "value"}}
            ```

        Gemma 4 native token format (used when peg-gemma4 grammar is active):
            <|tool_call>call:tool_name{param:<|"|>value<|"|>}<tool_call|>
        """
        if not text:
            return []

        # ── JSON code-block parser (peg-native fallback) ──────────────────────
        json_block_calls = self._extract_json_block_tool_calls(text)
        if json_block_calls:
            return json_block_calls

        # ── Gemma 4 native token parser ────────────────────────────────────────
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

    def _extract_json_block_tool_calls(self, text: str) -> List[ToolUse]:
        """Extract tool calls from JSON code blocks in model text output.

        Looks for:  ```json\\n{"name": "...", "arguments": {...}}\\n```
        Also tries: bare JSON objects on their own line with "name"+"arguments".
        """
        calls: List[ToolUse] = []

        # Match ```json ... ``` blocks (with or without "json" tag)
        block_re = re.compile(r"```(?:json)?\s*\n?(\{.*?\})\s*\n?```", re.DOTALL)
        for m in block_re.finditer(text):
            raw = self._strip_chatml_tokens(m.group(1).strip())
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            call = self._try_parse_tool_call_object(obj)
            if call:
                calls.append(call)

        if calls:
            return calls

        # Bare JSON fallback — look for {"name": "...", "arguments": {...}} anywhere
        bare_re = re.compile(r'\{"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:\s*\{[^{}]*\}\s*\}')
        for m in bare_re.finditer(text):
            raw = self._strip_chatml_tokens(m.group(0))
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            call = self._try_parse_tool_call_object(obj)
            if call:
                calls.append(call)

        return calls

    @staticmethod
    def _strip_chatml_tokens(text: str) -> str:
        """Remove ChatML control tokens that the model leaks into structured output."""
        return re.sub(r"<\|im_(start|end)\|?>", "", text)

    @staticmethod
    def _try_parse_tool_call_object(obj: Any) -> Optional["ToolUse"]:
        """Return a ToolUse if obj looks like a tool call, else None."""
        if not isinstance(obj, dict):
            return None
        name = obj.get("name") or obj.get("tool") or obj.get("function")
        args = obj.get("arguments") or obj.get("args") or obj.get("parameters") or {}
        if isinstance(name, str) and name and isinstance(args, dict):
            return ToolUse(tool_name=name, tool_input=args)
        return None

    # Compact key-param hints so the model uses correct argument names
    _TOOL_PARAM_HINTS: Dict[str, str] = {
        "list_directory": "target_path",
        "read_text_file": "target_file_path",
        "write_file": "target_file_path, file_text",
        "edit_file": "target_file_path, exact_text_to_replace, new_text_content",
        "bash_exec": "command",
        "grep_codebase": "pattern",
        "todo_write": "todos",
        "todo_read": "",
        "search_web": "query",
        "set_allowed_directory": "target_directory_path",
        "create_directory": "directory_path",
        "delete_file": "target_file_path",
    }

    # Tools that confuse E2B (2.5B) due to strong training priors — excluded from schema injection.
    # create_directory: model calls it for ANY path mention; set_allowed_directory: internal only.
    _SCHEMA_INJECTION_EXCLUDE: frozenset = frozenset({
        "create_directory", "set_allowed_directory", "delete_file",
        "write_file", "edit_file", "search_web", "fetch_url",
        "read_media_file_base64", "list_allowed_directories",
    })

    # Priority order for choosing the example tool (most recognizable first)
    _SCHEMA_EXAMPLE_PRIORITY: tuple = (
        "list_directory", "read_text_file", "bash_exec",
        "grep_codebase", "todo_write", "todo_read",
    )

    @classmethod
    def build_tool_schema_injection(cls, tools: List[Dict[str, Any]]) -> str:
        """Build a minimal tool hint block to inject into the system message.

        Filtered to a core set (exclude tools with strong wrong-tool priors in E2B).
        Shows 3 concrete examples — one per major tool category — for better disambiguation.
        """
        if not tools:
            return ""

        all_names = [t.get("function", t).get("name", "") for t in tools]

        # Filter to core working tools only
        names = [n for n in all_names if n not in cls._SCHEMA_INJECTION_EXCLUDE and n]
        if not names:
            names = all_names  # fallback if all excluded

        # Build 3 diverse examples to reduce ambiguity
        examples_shown = []
        for priority_name in cls._SCHEMA_EXAMPLE_PRIORITY:
            if priority_name in names and len(examples_shown) < 3:
                params = cls._TOOL_PARAM_HINTS.get(priority_name, "")
                first_param = params.split(",")[0].strip() if params else "value"
                example_args = {first_param: "..."} if first_param and first_param != "" else {}
                examples_shown.append(
                    json.dumps({"name": priority_name, "arguments": example_args})
                )

        if not examples_shown:
            # Fallback: use the first available tool
            n = names[0]
            params = cls._TOOL_PARAM_HINTS.get(n, "")
            first_param = params.split(",")[0].strip() if params else "value"
            examples_shown = [json.dumps({"name": n, "arguments": {first_param: "..."}})]

        examples_block = "\n".join(f"```json\n{ex}\n```" for ex in examples_shown)
        names_str = ", ".join(names)

        return (
            f"\n\nTo call a tool, emit ONLY a JSON block:\n"
            f"{examples_block}\n"
            f"Available tools: {names_str}\n"
            f"NEVER invent tool names. NEVER answer from memory when a tool can fetch the real data."
        )

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
        """Format tool result for inclusion in chat messages.

        peg-native models don't understand the 'tool' role — inject as a 'user'
        message with an Observation: prefix so the model sees the result in context.
        """
        return {
            "role": "user",
            "content": f"Observation from {tool_name}:\n{result}",
        }

    @staticmethod
    def _inject_tools_into_system_message(
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Append tool schema text to the system message (peg-native workaround)."""
        schema_text = LLMAdapter.build_tool_schema_injection(tools)
        if not schema_text:
            return messages

        messages = list(messages)  # shallow copy — don't mutate caller's list
        for i, msg in enumerate(messages):
            if msg.get("role") == "system":
                messages[i] = {**msg, "content": msg["content"] + schema_text}
                return messages

        # No system message found — prepend one
        messages.insert(0, {"role": "system", "content": schema_text.lstrip()})
        return messages
