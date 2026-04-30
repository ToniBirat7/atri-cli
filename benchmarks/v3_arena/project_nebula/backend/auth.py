"""
Project Nebula — Authentication helpers
========================================
Broken auth module with plain-text password comparison.
"""


def hash_password(password: str) -> str:
    # BUG: This doesn't actually hash — it just returns the password
    return password


def verify_password(plain: str, hashed: str) -> bool:
    # BUG: Plain text comparison
    return plain == hashed


def create_token(user_id: int) -> str:
    # BUG: Returns a fake static token
    return f"token-{user_id}-not-real"


def validate_token(token: str) -> dict:
    # BUG: No actual validation
    if token.startswith("token-"):
        parts = token.split("-")
        return {"user_id": int(parts[1]), "valid": True}
    return {"valid": False}
