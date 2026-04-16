"""Conversation persistence for the orchestrator.

This implementation uses sqlite3 for a minimal self-hosted persistence layer
that can be pointed at a durable on-disk path in production. The schema stores
conversations, turns, and tool calls.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

try:
    import psycopg
except Exception:  # pragma: no cover - optional dependency
    psycopg = None


@dataclass(slots=True)
class ConversationRecord:
    conversation_id: str
    prompt_profile: str
    created_at: str
    updated_at: str


class OrchestratorDatabase:
    def __init__(self, database_url: str, enabled: bool = True):
        self.database_url = database_url
        self.enabled = enabled
        self._scheme = urlparse(database_url).scheme or "sqlite"
        self._db_path = self._resolve_sqlite_path(database_url) if self._scheme == "sqlite" else None
        self._postgres_dsn = self._resolve_postgres_dsn(database_url) if self._scheme in {"postgresql", "postgres"} else None
        self._lock = asyncio.Lock()

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _resolve_sqlite_path(database_url: str) -> Path:
        parsed = urlparse(database_url)
        if parsed.scheme and parsed.scheme != "sqlite":
            raise ValueError("Only sqlite URLs are supported by the built-in persistence layer")

        if database_url == "sqlite:///:memory:":
            return Path(":memory:")

        if database_url.startswith("sqlite:////"):
            return Path("/" + database_url.removeprefix("sqlite:////"))

        if database_url.startswith("sqlite:///"):
            return Path(database_url.removeprefix("sqlite:///"))

        raw_path = parsed.path or database_url.removeprefix("sqlite://")
        if raw_path.startswith("/"):
            return Path(raw_path.lstrip("/"))
        return Path.cwd() / raw_path

    @staticmethod
    def _resolve_postgres_dsn(database_url: str) -> str:
        if database_url.startswith("postgresql://") or database_url.startswith("postgres://"):
            return database_url
        raise ValueError("Unsupported PostgreSQL URL")

    def _connect(self) -> sqlite3.Connection:
        if self._scheme in {"postgresql", "postgres"}:
            raise RuntimeError("Use _connect_postgres for PostgreSQL connections")
        connection = sqlite3.connect(str(self._db_path), check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def _connect_postgres(self):
        if psycopg is None:
            raise RuntimeError("psycopg is not installed")
        if self._postgres_dsn is None:
            raise RuntimeError("PostgreSQL DSN is not configured")
        return psycopg.connect(self._postgres_dsn)

    def _use_postgres(self) -> bool:
        return self._scheme in {"postgresql", "postgres"}

    async def initialize(self) -> None:
        if not self.enabled:
            return

        def _init() -> None:
            if not self._use_postgres() and self._db_path != Path(":memory:"):
                self._db_path.parent.mkdir(parents=True, exist_ok=True)
            if self._use_postgres():
                with self._connect_postgres() as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            CREATE TABLE IF NOT EXISTS conversations (
                                conversation_id TEXT PRIMARY KEY,
                                prompt_profile TEXT NOT NULL,
                                created_at TEXT NOT NULL,
                                updated_at TEXT NOT NULL
                            )
                            """
                        )
                        cursor.execute(
                            """
                            CREATE TABLE IF NOT EXISTS turns (
                                id BIGSERIAL PRIMARY KEY,
                                conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
                                request_id TEXT NOT NULL,
                                turn_index INTEGER NOT NULL,
                                user_message TEXT NOT NULL,
                                assistant_response TEXT NOT NULL,
                                status TEXT NOT NULL,
                                total_tool_calls INTEGER NOT NULL,
                                model TEXT NOT NULL,
                                system_prompt TEXT,
                                turn_history_json TEXT,
                                created_at TEXT NOT NULL
                            )
                            """
                        )
                        cursor.execute(
                            """
                            CREATE TABLE IF NOT EXISTS tool_calls (
                                id BIGSERIAL PRIMARY KEY,
                                turn_id BIGINT NOT NULL REFERENCES turns(id),
                                call_index INTEGER NOT NULL,
                                tool_name TEXT NOT NULL,
                                routed_server TEXT,
                                routed_tool_name TEXT,
                                input_json TEXT NOT NULL,
                                output_json TEXT,
                                status TEXT NOT NULL,
                                created_at TEXT NOT NULL
                            )
                            """
                        )
                    connection.commit()
            else:
                with self._connect() as connection:
                    connection.executescript(
                        """
                        PRAGMA journal_mode=WAL;
                        CREATE TABLE IF NOT EXISTS conversations (
                            conversation_id TEXT PRIMARY KEY,
                            prompt_profile TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        );
                        CREATE TABLE IF NOT EXISTS turns (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            conversation_id TEXT NOT NULL,
                            request_id TEXT NOT NULL,
                            turn_index INTEGER NOT NULL,
                            user_message TEXT NOT NULL,
                            assistant_response TEXT NOT NULL,
                            status TEXT NOT NULL,
                            total_tool_calls INTEGER NOT NULL,
                            model TEXT NOT NULL,
                            system_prompt TEXT,
                            turn_history_json TEXT,
                            created_at TEXT NOT NULL,
                            FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id)
                        );
                        CREATE TABLE IF NOT EXISTS tool_calls (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            turn_id INTEGER NOT NULL,
                            call_index INTEGER NOT NULL,
                            tool_name TEXT NOT NULL,
                            routed_server TEXT,
                            routed_tool_name TEXT,
                            input_json TEXT NOT NULL,
                            output_json TEXT,
                            status TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            FOREIGN KEY(turn_id) REFERENCES turns(id)
                        );
                        """
                    )
                    connection.commit()

        await asyncio.to_thread(_init)

    async def ensure_conversation(self, conversation_id: str, prompt_profile: str) -> None:
        if not self.enabled:
            return

        now = self._utc_now()

        def _ensure() -> None:
            if self._use_postgres():
                with self._connect_postgres() as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            INSERT INTO conversations (conversation_id, prompt_profile, created_at, updated_at)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT(conversation_id) DO UPDATE SET
                                prompt_profile=excluded.prompt_profile,
                                updated_at=excluded.updated_at
                            """,
                            (conversation_id, prompt_profile, now, now),
                        )
                    connection.commit()
            else:
                with self._connect() as connection:
                    connection.execute(
                        """
                        INSERT INTO conversations (conversation_id, prompt_profile, created_at, updated_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(conversation_id) DO UPDATE SET
                            prompt_profile=excluded.prompt_profile,
                            updated_at=excluded.updated_at
                        """,
                        (conversation_id, prompt_profile, now, now),
                    )
                    connection.commit()

        await asyncio.to_thread(_ensure)

    async def record_turn(
        self,
        *,
        conversation_id: str,
        request_id: str,
        turn_index: int,
        user_message: str,
        assistant_response: str,
        status: str,
        total_tool_calls: int,
        model: str,
        system_prompt: Optional[str],
        turn_history: list[dict[str, Any]],
        tool_events: list[dict[str, Any]],
    ) -> None:
        if not self.enabled:
            return

        now = self._utc_now()

        def _write() -> None:
            if self._use_postgres():
                with self._connect_postgres() as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            INSERT INTO turns (
                                conversation_id, request_id, turn_index, user_message,
                                assistant_response, status, total_tool_calls, model,
                                system_prompt, turn_history_json, created_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            RETURNING id
                            """,
                            (
                                conversation_id,
                                request_id,
                                turn_index,
                                user_message,
                                assistant_response,
                                status,
                                total_tool_calls,
                                model,
                                system_prompt,
                                json.dumps(turn_history, ensure_ascii=False),
                                now,
                            ),
                        )
                        turn_id = cursor.fetchone()[0]
                        for index, tool_event in enumerate(tool_events):
                            cursor.execute(
                                """
                                INSERT INTO tool_calls (
                                    turn_id, call_index, tool_name, routed_server,
                                    routed_tool_name, input_json, output_json, status, created_at
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                """,
                                (
                                    turn_id,
                                    index,
                                    tool_event.get("tool_name", "tool"),
                                    tool_event.get("routed_server"),
                                    tool_event.get("routed_tool_name"),
                                    json.dumps(tool_event.get("input", {}), ensure_ascii=False),
                                    json.dumps(tool_event.get("output"), ensure_ascii=False) if tool_event.get("output") is not None else None,
                                    tool_event.get("status", "ok"),
                                    now,
                                ),
                            )
                        cursor.execute(
                            "UPDATE conversations SET updated_at = %s WHERE conversation_id = %s",
                            (now, conversation_id),
                        )
                    connection.commit()
            else:
                with self._connect() as connection:
                    cursor = connection.execute(
                        """
                        INSERT INTO turns (
                            conversation_id, request_id, turn_index, user_message,
                            assistant_response, status, total_tool_calls, model,
                            system_prompt, turn_history_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            conversation_id,
                            request_id,
                            turn_index,
                            user_message,
                            assistant_response,
                            status,
                            total_tool_calls,
                            model,
                            system_prompt,
                            json.dumps(turn_history, ensure_ascii=False),
                            now,
                        ),
                    )
                    turn_id = cursor.lastrowid
                    for index, tool_event in enumerate(tool_events):
                        connection.execute(
                            """
                            INSERT INTO tool_calls (
                                turn_id, call_index, tool_name, routed_server,
                                routed_tool_name, input_json, output_json, status, created_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                turn_id,
                                index,
                                tool_event.get("tool_name", "tool"),
                                tool_event.get("routed_server"),
                                tool_event.get("routed_tool_name"),
                                json.dumps(tool_event.get("input", {}), ensure_ascii=False),
                                json.dumps(tool_event.get("output"), ensure_ascii=False) if tool_event.get("output") is not None else None,
                                tool_event.get("status", "ok"),
                                now,
                            ),
                        )
                    connection.execute(
                        "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                        (now, conversation_id),
                    )
                    connection.commit()

        await asyncio.to_thread(_write)

    async def list_conversations(self, limit: int = 20) -> list[ConversationRecord]:
        if not self.enabled:
            return []

        def _read() -> list[ConversationRecord]:
            if self._use_postgres():
                with self._connect_postgres() as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            SELECT conversation_id, prompt_profile, created_at, updated_at
                            FROM conversations
                            ORDER BY updated_at DESC
                            LIMIT %s
                            """,
                            (limit,),
                        )
                        rows = cursor.fetchall()
                        return [
                            ConversationRecord(
                                conversation_id=row[0],
                                prompt_profile=row[1],
                                created_at=row[2],
                                updated_at=row[3],
                            )
                            for row in rows
                        ]

            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT conversation_id, prompt_profile, created_at, updated_at
                    FROM conversations
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                return [
                    ConversationRecord(
                        conversation_id=row["conversation_id"],
                        prompt_profile=row["prompt_profile"],
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                    )
                    for row in rows
                ]

        return await asyncio.to_thread(_read)
