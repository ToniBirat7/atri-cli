"""
Project Nebula — Real-time Chat Backend
========================================
FastAPI-based WebSocket chat server.

Known Issues (intentional for benchmarking):
- SQLAlchemy uses `create_client` instead of `create_engine` (import error)
- Password stored in plain text
- No CORS middleware
- No input validation on WebSocket messages
- No message persistence
- Race condition in disconnect()
- No heartbeat/ping mechanism
- Tables never created (no Base.metadata.create_all)
- No typing annotations on most functions
- Hardcoded database URL
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from sqlalchemy import create_client, Column, Integer, String, Text, DateTime, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import datetime
import json

app = FastAPI(title="Project Nebula Chat API", version="0.1.0")

# --- DATABASE ---
DATABASE_URL = "sqlite:///./nebula.db"
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String)  # BUG: Missing unique=True
    email = Column(String)
    password = Column(String)  # BUG: Plain text storage
    is_active = Column(Boolean, default=True)


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer)
    room = Column(String, default="general")
    content = Column(Text)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)


class Room(Base):
    __tablename__ = "rooms"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True)
    created_by = Column(Integer)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


# --- WEBSOCKET MANAGER ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.user_map: dict[int, WebSocket] = {}

    async def connect(self, websocket: WebSocket, client_id: int):
        await websocket.accept()
        self.active_connections.append(websocket)
        self.user_map[client_id] = websocket

    def disconnect(self, websocket: WebSocket):
        # BUG: Race condition — ValueError if called twice
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

    async def send_personal(self, message: str, client_id: int):
        ws = self.user_map.get(client_id)
        if ws:
            await ws.send_text(message)

    def get_online_count(self):
        return len(self.active_connections)


manager = ConnectionManager()


# --- REST ENDPOINTS ---
@app.get("/")
def read_root():
    return {"message": "Project Nebula Chat API", "version": "0.1.0"}


@app.get("/health")
def health_check():
    return {"status": "ok", "online_users": manager.get_online_count()}


@app.post("/api/register")
def register_user(username: str, password: str):
    # BUG: No password hashing, no duplicate check
    return {"status": "registered", "username": username}


@app.post("/api/login")
def login_user(username: str, password: str):
    # BUG: No actual authentication logic
    return {"status": "logged_in", "token": "fake-jwt-token"}


@app.get("/api/rooms")
def list_rooms():
    return {"rooms": ["general", "random", "tech"]}


# --- WEBSOCKET ENDPOINT ---
@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: int):
    await manager.connect(websocket, client_id)
    try:
        while True:
            data = await websocket.receive_text()
            # BUG: No input validation
            # BUG: No message persistence (messages lost on restart)
            # BUG: No typing indicator support
            timestamp = datetime.datetime.utcnow().isoformat()
            payload = json.dumps({
                "sender": client_id,
                "content": data,
                "timestamp": timestamp,
                "room": "general"
            })
            await manager.broadcast(payload)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await manager.broadcast(json.dumps({
            "type": "system",
            "content": f"Client #{client_id} left the chat"
        }))
