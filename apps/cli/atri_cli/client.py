from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterator, Optional


@dataclass
class OrchestratorClient:
    base_url: str
    api_key: Optional[str] = None

    def _build_url(self, path: str) -> str:
        return urllib.parse.urljoin(self.base_url.rstrip("/") + "/", path.lstrip("/"))

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    def request_json(self, method: str, path: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            self._build_url(path),
            data=data,
            method=method,
            headers=self._headers(),
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(body)
            except Exception:
                parsed = {"detail": body}
            raise RuntimeError(f"HTTP {exc.code}: {parsed}") from exc

    @staticmethod
    def _normalize_stream_payload(payload: dict[str, Any]) -> dict[str, Any]:
        """Normalize typed SSE envelopes into the CLI's expected keys."""
        event_type = payload.get("type")
        if not isinstance(event_type, str):
            return payload

        if event_type == "request_started":
            request_id = payload.get("request_id")
            return {"request_id": request_id} if request_id else payload

        if event_type == "session_started":
            conversation_id = payload.get("conversation_id")
            return {"conversation_id": conversation_id} if conversation_id else payload

        if event_type == "agent_event":
            event = payload.get("event")
            return {"event": event} if isinstance(event, dict) else payload

        if event_type == "assistant_delta":
            content = payload.get("content")
            return {"content": content} if isinstance(content, str) else payload

        if event_type == "plan_proposed":
            plan = payload.get("plan")
            return {"plan": plan} if isinstance(plan, dict) else payload

        if event_type == "error":
            error = payload.get("error")
            return {"error": error} if isinstance(error, str) else payload

        return payload

    def stream_chat(self, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        req = urllib.request.Request(
            self._build_url("/chat/stream"),
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=self._headers(),
        )

        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        yield {"done": True}
                        break
                    try:
                        parsed = json.loads(data)
                        if isinstance(parsed, dict):
                            yield self._normalize_stream_payload(parsed)
                        else:
                            yield {"malformed": data}
                    except Exception:
                        yield {"malformed": data}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
