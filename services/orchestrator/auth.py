"""Authentication helpers for the orchestrator.

Supports JWT bearer tokens with HMAC SHA-256 verification and an optional
legacy API-key fallback for bootstrap or local development.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import HTTPException, Request


@dataclass(slots=True)
class AuthContext:
    subject: str
    issuer: str
    audience: str
    scopes: list[str]
    is_admin: bool = False


class AuthError(Exception):
    pass


class JwtAuth:
    def __init__(self, secret: Optional[str], issuer: str, audience: str):
        self.secret = secret.encode("utf-8") if secret else None
        self.issuer = issuer
        self.audience = audience

    @staticmethod
    def _b64url_decode(value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(value + padding)

    def _verify_signature(self, signing_input: bytes, signature: str) -> None:
        if not self.secret:
            raise AuthError("JWT secret is not configured")

        expected = hmac.new(self.secret, signing_input, hashlib.sha256).digest()
        provided = self._b64url_decode(signature)
        if not hmac.compare_digest(expected, provided):
            raise AuthError("Invalid token signature")

    def verify(self, token: str) -> AuthContext:
        try:
            header_b64, payload_b64, signature = token.split(".", 2)
        except ValueError as exc:
            raise AuthError("Invalid token format") from exc

        header = json.loads(self._b64url_decode(header_b64))
        if header.get("alg") != "HS256":
            raise AuthError("Unsupported JWT algorithm")

        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
        self._verify_signature(signing_input, signature)

        payload = json.loads(self._b64url_decode(payload_b64))
        if payload.get("iss") != self.issuer:
            raise AuthError("Invalid token issuer")

        audience = payload.get("aud")
        if isinstance(audience, list):
            audience_ok = self.audience in audience
        else:
            audience_ok = audience == self.audience
        if not audience_ok:
            raise AuthError("Invalid token audience")

        subject = payload.get("sub")
        if not subject:
            raise AuthError("Token subject is missing")

        scopes = payload.get("scope", [])
        if isinstance(scopes, str):
            scopes = scopes.split()
        if not isinstance(scopes, list):
            scopes = []

        return AuthContext(
            subject=str(subject),
            issuer=self.issuer,
            audience=self.audience,
            scopes=[str(scope) for scope in scopes],
            is_admin=bool(payload.get("admin", False)),
        )


class RequestAuthenticator:
    def __init__(self, *, jwt_auth: JwtAuth, api_key: Optional[str], admin_api_key: Optional[str], mode: str):
        self.jwt_auth = jwt_auth
        self.api_key = api_key
        self.admin_api_key = admin_api_key
        self.mode = mode.lower()

    @staticmethod
    def _extract_token(request: Request) -> Optional[str]:
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            return authorization.split(None, 1)[1].strip() or None

        header_key = request.headers.get("x-api-key")
        if header_key:
            return header_key.strip() or None

        return None

    def _is_auth_configured(self) -> bool:
        has_api_key = bool(self.api_key or self.admin_api_key)
        has_jwt = bool(self.jwt_auth.secret)
        return has_api_key or has_jwt

    def authenticate(self, request: Request) -> Optional[AuthContext]:
        token = self._extract_token(request)
        if not token:
            if not self._is_auth_configured():
                return AuthContext(
                    subject="anonymous",
                    issuer="local",
                    audience="orchestrator",
                    scopes=["chat:read", "chat:write"],
                )
            raise HTTPException(status_code=401, detail="Unauthorized")

        if self.mode in {"api-key", "hybrid"} and self.api_key and token in {self.api_key, self.admin_api_key}:
            return AuthContext(
                subject="api-key-client",
                issuer="legacy",
                audience="orchestrator",
                scopes=["chat:read", "chat:write"],
                is_admin=token == self.admin_api_key,
            )

        if self.mode in {"jwt", "hybrid"}:
            try:
                return self.jwt_auth.verify(token)
            except AuthError as exc:
                if self.mode == "jwt":
                    raise HTTPException(status_code=401, detail=str(exc)) from exc

        raise HTTPException(status_code=401, detail="Unauthorized")
