"""Conversation persistence for the orchestrator.

This implementation uses sqlite3 for a minimal self-hosted persistence layer
that can be pointed at a durable on-disk path in production. The schema stores
conversations, turns, and tool calls.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import contextmanager
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


@dataclass(slots=True)
class TurnRecord:
    id: int
    conversation_id: str
    request_id: str
    turn_index: int
    user_message: str
    assistant_response: str
    status: str
    total_tool_calls: int
    model: str
    created_at: str


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

        # Strip "sqlite:///" prefix then handle the remaining path.
        # Convention: sqlite:///relative  → relative path
        #             sqlite:////abs      → absolute path (4th slash starts /abs)
        # We also handle accidentally-5-slash URLs from path concatenation bugs.
        if database_url.startswith("sqlite:///"):
            rest = database_url[len("sqlite:///"):]
            if rest.startswith("/"):
                # Absolute: normalize away any accidental double slashes
                return Path("/" + rest.lstrip("/"))
            return Path(rest)  # relative — caller resolves against CWD

        raw_path = parsed.path or database_url.removeprefix("sqlite://")
        if raw_path.startswith("/"):
            return Path(raw_path)
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
        # Wait up to 5s on a locked DB instead of failing immediately, so a
        # concurrent reader (sessions list/show) doesn't drop a turn write.
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @contextmanager
    def _session(self):
        """Yield a sqlite connection inside a transaction, then CLOSE it.

        sqlite3.Connection.__exit__ commits/rolls back but does NOT close the
        connection — using `with self._connect()` directly leaked a file
        descriptor per call. This wraps connect + transaction + close.
        """
        connection = self._connect()
        try:
            with connection:  # commit on success, rollback on exception
                yield connection
        finally:
            connection.close()

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
                with self._session() as connection:
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
                with self._session() as connection:
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
                with self._session() as connection:
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

            with self._session() as connection:
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

    async def get_conversation(self, conversation_id: str) -> Optional[ConversationRecord]:
        if not self.enabled:
            return None

        def _read() -> Optional[ConversationRecord]:
            if self._use_postgres():
                with self._connect_postgres() as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            SELECT conversation_id, prompt_profile, created_at, updated_at
                            FROM conversations
                            WHERE conversation_id = %s
                            """,
                            (conversation_id,),
                        )
                        row = cursor.fetchone()
                        if row is None:
                            return None
                        return ConversationRecord(
                            conversation_id=row[0],
                            prompt_profile=row[1],
                            created_at=row[2],
                            updated_at=row[3],
                        )

            with self._session() as connection:
                row = connection.execute(
                    """
                    SELECT conversation_id, prompt_profile, created_at, updated_at
                    FROM conversations
                    WHERE conversation_id = ?
                    """,
                    (conversation_id,),
                ).fetchone()
                if row is None:
                    return None
                return ConversationRecord(
                    conversation_id=row["conversation_id"],
                    prompt_profile=row["prompt_profile"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )

        return await asyncio.to_thread(_read)

    async def list_turns(self, conversation_id: str, limit: int = 100) -> list[TurnRecord]:
        if not self.enabled:
            return []

        def _read() -> list[TurnRecord]:
            if self._use_postgres():
                with self._connect_postgres() as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            SELECT id, conversation_id, request_id, turn_index, user_message,
                                   assistant_response, status, total_tool_calls, model, created_at
                            FROM turns
                            WHERE conversation_id = %s
                            ORDER BY id ASC
                            LIMIT %s
                            """,
                            (conversation_id, limit),
                        )
                        rows = cursor.fetchall()
                        return [
                            TurnRecord(
                                id=row[0],
                                conversation_id=row[1],
                                request_id=row[2],
                                turn_index=row[3],
                                user_message=row[4],
                                assistant_response=row[5],
                                status=row[6],
                                total_tool_calls=row[7],
                                model=row[8],
                                created_at=row[9],
                            )
                            for row in rows
                        ]

            with self._session() as connection:
                rows = connection.execute(
                    """
                    SELECT id, conversation_id, request_id, turn_index, user_message,
                           assistant_response, status, total_tool_calls, model, created_at
                    FROM turns
                    WHERE conversation_id = ?
                    ORDER BY id ASC
                    LIMIT ?
                    """,
                    (conversation_id, limit),
                ).fetchall()
                return [
                    TurnRecord(
                        id=row["id"],
                        conversation_id=row["conversation_id"],
                        request_id=row["request_id"],
                        turn_index=row["turn_index"],
                        user_message=row["user_message"],
                        assistant_response=row["assistant_response"],
                        status=row["status"],
                        total_tool_calls=row["total_tool_calls"],
                        model=row["model"],
                        created_at=row["created_at"],
                    )
                    for row in rows
                ]

        return await asyncio.to_thread(_read)

    async def build_chat_history_messages(self, conversation_id: str, max_turns: int = 10) -> list[dict[str, str]]:
        if not self.enabled:
            return []

        # list_turns is ORDER BY id ASC, so passing limit=max_turns returned the
        # OLDEST turns — a long conversation would resume with its earliest
        # context instead of its most recent. Load a generous recent window and
        # keep the latest max_turns. (Very long sessions are also compacted by
        # the agent loop, so this window is more than enough.)
        window = max(200, max_turns * 10)
        turns = await self.list_turns(conversation_id=conversation_id, limit=window)
        messages: list[dict[str, str]] = []
        for turn in turns[-max_turns:]:
            messages.append({"role": "user", "content": turn.user_message})
            messages.append({"role": "assistant", "content": turn.assistant_response})
        return messages

    async def fork_conversation(self, source_conversation_id: str, target_conversation_id: str) -> bool:
        if not self.enabled:
            return False

        now = self._utc_now()

        def _fork() -> bool:
            if self._use_postgres():
                with self._connect_postgres() as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            SELECT prompt_profile, created_at, updated_at
                            FROM conversations
                            WHERE conversation_id = %s
                            """,
                            (source_conversation_id,),
                        )
                        source = cursor.fetchone()
                        if source is None:
                            return False

                        cursor.execute(
                            """
                            INSERT INTO conversations (conversation_id, prompt_profile, created_at, updated_at)
                            VALUES (%s, %s, %s, %s)
                            """,
                            (target_conversation_id, source[0], now, now),
                        )

                        cursor.execute(
                            """
                            INSERT INTO turns (
                                conversation_id, request_id, turn_index, user_message,
                                assistant_response, status, total_tool_calls, model,
                                system_prompt, turn_history_json, created_at
                            )
                            SELECT %s, request_id, turn_index, user_message,
                                   assistant_response, status, total_tool_calls, model,
                                   system_prompt, turn_history_json, created_at
                            FROM turns
                            WHERE conversation_id = %s
                            ORDER BY id ASC
                            """,
                            (target_conversation_id, source_conversation_id),
                        )

                    connection.commit()
                    return True

            with self._session() as connection:
                source = connection.execute(
                    """
                    SELECT prompt_profile, created_at, updated_at
                    FROM conversations
                    WHERE conversation_id = ?
                    """,
                    (source_conversation_id,),
                ).fetchone()
                if source is None:
                    return False

                connection.execute(
                    """
                    INSERT INTO conversations (conversation_id, prompt_profile, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (target_conversation_id, source["prompt_profile"], now, now),
                )

                connection.execute(
                    """
                    INSERT INTO turns (
                        conversation_id, request_id, turn_index, user_message,
                        assistant_response, status, total_tool_calls, model,
                        system_prompt, turn_history_json, created_at
                    )
                    SELECT ?, request_id, turn_index, user_message,
                           assistant_response, status, total_tool_calls, model,
                           system_prompt, turn_history_json, created_at
                    FROM turns
                    WHERE conversation_id = ?
                    ORDER BY id ASC
                    """,
                    (target_conversation_id, source_conversation_id),
                )

                connection.commit()
                return True

        return await asyncio.to_thread(_fork)
