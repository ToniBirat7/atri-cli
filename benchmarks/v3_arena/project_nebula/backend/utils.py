"""
Project Nebula — Utility helpers
=================================
"""
import re
from datetime import datetime


def sanitize_message(content: str) -> str:
    """Remove HTML tags from message content."""
    # BUG: Incomplete sanitization — doesn't handle encoded entities
    return re.sub(r'<[^>]+>', '', content)


def format_timestamp(dt: datetime) -> str:
    """Format datetime for display."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def validate_username(username: str) -> bool:
    """Check if username is valid."""
    if not username:
        return False
    if len(username) < 3 or len(username) > 20:
        return False
    # BUG: Allows special characters that could cause issues
    return True


def truncate_message(content: str, max_length: int = 500) -> str:
    """Truncate message to max length."""
    if len(content) <= max_length:
        return content
    return content[:max_length] + "..."
