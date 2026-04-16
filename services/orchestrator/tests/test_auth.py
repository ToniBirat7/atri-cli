"""Tests for orchestrator auth helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest
from fastapi import HTTPException

from auth import JwtAuth, RequestAuthenticator


class _Request:
    def __init__(self, headers=None):
        self.headers = headers or {}


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _make_jwt(secret: str, payload: dict) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{_b64url(signature)}"


def test_jwt_auth_verifies_hs256_token():
    token = _make_jwt(
        "secret",
        {
            "iss": "tarbar-ai",
            "aud": "tarbar-ai-orchestrator",
            "sub": "svc-a",
            "scope": "chat:write chat:read",
            "admin": True,
        },
    )

    auth = JwtAuth("secret", issuer="tarbar-ai", audience="tarbar-ai-orchestrator")
    context = auth.verify(token)

    assert context.subject == "svc-a"
    assert context.is_admin is True
    assert "chat:write" in context.scopes


@pytest.mark.parametrize("mode", ["api-key", "hybrid"])
def test_request_authenticator_accepts_api_key(mode):
    authenticator = RequestAuthenticator(
        jwt_auth=JwtAuth(None, issuer="tarbar-ai", audience="tarbar-ai-orchestrator"),
        api_key="secret",
        admin_api_key="admin-secret",
        mode=mode,
    )

    context = authenticator.authenticate(_Request({"authorization": "Bearer admin-secret"}))

    assert context.is_admin is True
    assert context.subject == "api-key-client"


def test_request_authenticator_rejects_invalid_token():
    authenticator = RequestAuthenticator(
        jwt_auth=JwtAuth("secret", issuer="tarbar-ai", audience="tarbar-ai-orchestrator"),
        api_key=None,
        admin_api_key=None,
        mode="jwt",
    )

    with pytest.raises(HTTPException) as exc_info:
        authenticator.authenticate(_Request({"authorization": "Bearer not-a-jwt"}))

    assert exc_info.value.status_code == 401
