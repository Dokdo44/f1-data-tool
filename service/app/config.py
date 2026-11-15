import os

# Local dev falls back to SQLite so the app runs before Postgres is up.
# Docker Compose and Render both inject DATABASE_URL.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tsi.db")

# Render/Heroku hand out postgres:// ; SQLAlchemy 2.x wants postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", 5 * 1024 * 1024))
MAX_ROWS = int(os.getenv("MAX_ROWS", 200_000))
