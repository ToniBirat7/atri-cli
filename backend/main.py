from typing import Dict, List
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Configure CORS middleware to allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def read_root() -> Dict[str, str]:
    # Create all database tables on startup
    Base.metadata.create_all(bind=engine)
    return {"message": "CORS middleware is active. API is running."}

def get_messages() -> List[Message]:
    # Placeholder for actual database query logic.
    # Replace 'Message' with your actual model and ensure database access is correct.
    messages = db.query(Message).order_by(Message.timestamp.desc()).limit(50).all()
    return messages
