# database.py
"""
Database engine and session management.
"""
import time

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from config import settings

DATABASE_URL = settings.DATABASE_URL

# SQLite needs check_same_thread=False because uvicorn serves requests from
# multiple threads. Postgres has no such restriction and instead benefits from
# connection pooling settings.
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
else:
    engine = create_engine(
        DATABASE_URL,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,   # drops dead connections instead of erroring mid-request
        pool_recycle=1800,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_database():
    """FastAPI dependency: one session per request, always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def wait_for_database(max_attempts: int = 30, delay_seconds: float = 1.0) -> None:
    """
    Block until the database accepts connections.

    Needed in Docker: the app container starts before Postgres finishes
    initialising, and without this the first request crashes on connect.
    """
    if DATABASE_URL.startswith("sqlite"):
        return

    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print(f"[db] Connected to database on attempt {attempt}.")
            return
        except OperationalError as exc:
            last_error = exc
            print(f"[db] Not ready (attempt {attempt}/{max_attempts}), retrying...")
            time.sleep(delay_seconds)

    raise RuntimeError(f"Database never became available: {last_error}")


def ensure_pgvector_extension() -> None:
    """
    Create the pgvector extension if we are on Postgres and using it.

    Must run before create_all(), because the vector column type does not exist
    until the extension is installed.
    """
    if not settings.use_pgvector:
        return

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    print("[db] pgvector extension is available.")


def create_vector_index() -> None:
    """
    Add an approximate-nearest-neighbour index on the embedding column.

    Without this, Postgres does an exact scan of every chunk. With it, retrieval
    stays fast as the runbook corpus grows. HNSW gives better recall than
    ivfflat and does not need a pre-populated table to build.
    """
    if not settings.use_pgvector:
        return

    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding_hnsw "
                "ON document_chunks USING hnsw (embedding vector_cosine_ops)"
            )
        )
    print("[db] Vector index ready.")