"""
Project Nebula — Configuration
===============================
Hardcoded configuration (intentional flaw).
Should use environment variables.
"""

# BUG: All values hardcoded, should use os.environ
DATABASE_URL = "sqlite:///./nebula.db"
SECRET_KEY = "super-secret-key-that-should-not-be-here"
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_MINUTES = 30
MAX_CONNECTIONS = 100
DEBUG_MODE = True  # BUG: Debug mode left on in "production"
ALLOWED_ORIGINS = ["http://localhost:3000"]
