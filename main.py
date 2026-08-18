from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, status
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Annotated, Optional
import os
import uuid
import re  # for log parsing

from database import (
    engine,
    Base,
    get_database,
    SessionLocal,
    wait_for_database,
    ensure_pgvector_extension,
    create_vector_index,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session
import models

from pypdf import PdfReader  # for PDF parsing

from sentence_transformers import SentenceTransformer
import json
import asyncio

from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import timedelta, datetime, timezone

from pydantic import BaseModel, EmailStr, Field
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from config import settings
import llm

# Auth config now comes from the environment. Nothing secret is in this file.
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES


def bootstrap_admin() -> None:
    """
    Create the first admin account from environment variables, once.

    This replaces the old /debug/create-user endpoint, which created an admin
    with a password that was readable in the source. Anyone who found the
    deployed API could have logged in as that admin and uploaded documents.
    """
    if not (settings.BOOTSTRAP_ADMIN_USERNAME and settings.BOOTSTRAP_ADMIN_PASSWORD):
        return

    db = SessionLocal()
    try:
        existing = (
            db.query(models.User)
            .filter(models.User.username == settings.BOOTSTRAP_ADMIN_USERNAME)
            .first()
        )
        if existing:
            return

        admin = models.User(
            username=settings.BOOTSTRAP_ADMIN_USERNAME,
            email=settings.BOOTSTRAP_ADMIN_EMAIL
            or f"{settings.BOOTSTRAP_ADMIN_USERNAME}@loglens.local",
            hashed_password=get_password_hash(settings.BOOTSTRAP_ADMIN_PASSWORD),
            is_admin=True,
        )
        db.add(admin)
        db.commit()
        print(f"[bootstrap] Created admin user '{admin.username}'.")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup work, in the order it has to happen.

    In Docker the app container starts before Postgres is ready, so we wait.
    pgvector has to be installed before create_all(), because the vector column
    type does not exist until the extension does. The index comes after the
    table exists.
    """
    wait_for_database()
    ensure_pgvector_extension()
    Base.metadata.create_all(bind=engine)
    create_vector_index()
    bootstrap_admin()

    # Warm the embedding model so the first upload is not slow.
    await asyncio.to_thread(get_embedding_model)

    print(f"[startup] DB: {settings.DATABASE_URL.split('@')[-1]}")
    print(f"[startup] pgvector: {settings.use_pgvector}")
    print(f"[startup] LLM provider: {settings.LLM_PROVIDER}")
    yield


app = FastAPI(
    title="LogLens AI",
    description="AI-powered incident investigation and log analysis assistant.",
    version="0.2.0",
    lifespan=lifespan,
)

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# ensuring upload directory exists
UPLOAD_DIR = "uploaded_files"
os.makedirs(UPLOAD_DIR, exist_ok=True)

DbSessionDep = Annotated[Session, Depends(get_database)]
# Annotated[Session, Depends(get_database)] tells FastAPI:
# “this parameter is a Session and should be provided by get_database.”

#Pydantic Schemas (for requests/responses)

class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class AnswerFeedbackSubmit(BaseModel):
    question_log_id: int
    is_helpful: bool
    feedback_text: Optional[str] = None


class IncidentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    description: Optional[str] = None
    severity: Optional[str] = None
    status: str = "open"


@app.get("/health")
def health_check():
    """Liveness probe. Cheap, no external calls."""
    return {
        "status": "ok",
        "database": "postgres" if settings.is_postgres else "sqlite",
        "pgvector": settings.use_pgvector,
        "llm_provider": settings.LLM_PROVIDER,
        "embedding_model": settings.EMBEDDING_MODEL,
    }


@app.get("/health/llm")
async def health_check_llm():
    """
    Readiness probe that actually calls the LLM.

    Worth having separately: the API can be perfectly healthy while the model
    endpoint is unreachable, and you want to know which one is broken.
    """
    return await llm.health_check()

@app.get("/hello")
def hello(name: str = "there"):
    """
    Adding a simple example endpoint.
    Query Param: name, response: "there" by default.
    Returns a JSON greeting.
    """
    message = f"Hello, {name}! Welcome to the LogLens AI API."
    return JSONResponse(content={"message": message})

# SECTION: Password Hashing Utilities (NEW)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Checks if a plain-text password matches a hashed password.
    """
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """
    Hashes a plain-text password.
    """
    return pwd_context.hash(password)

# SECTION: JWT Token Utilities (NEW)
def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Creates a signed JWT access token.

    - data: dictionary of claims to embed in the token (e.g. {"sub": username, "user_id": 1})
    - expires_delta: optional timedelta for custom expiration; if not provided,
      ACCESS_TOKEN_EXPIRE_MINUTES is used.
    """
    if not isinstance(data, dict):
        raise ValueError("data passed to create_access_token must be a dict")

    # Copy the input data so we don't accidentally mutate the caller's dictionary
    to_encode = data.copy()

    # Compute expiry time
    if expires_delta is not None:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode["exp"] = expire

    # Encode and sign the token using our SECRET_KEY and ALGORITHM
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> dict:
    """
    Decodes a JWT access token and returns its payload (data).
    Raises JWTError if the token is invalid or expired.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


# SECTION: Bearer Token / Current User Dependencies

bearer_scheme = HTTPBearer()


def get_user_by_username(db: Session, username: str) -> Optional[models.User]:
    return db.query(models.User).filter(models.User.username == username).first()


def get_user_by_id(db: Session, user_id: int) -> Optional[models.User]:
    return db.query(models.User).filter(models.User.id == user_id).first()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    db: DbSessionDep,
) -> models.User:
    """
    Extracts the current user from the JWT access token.
    Raises 401 if the token is invalid or user does not exist.
    """
    token = credentials.credentials

    try:
        payload = decode_access_token(token)
    except HTTPException:
        # normalize as 401 with proper header
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    username: str | None = payload.get("sub")
    user_id: int | None = payload.get("user_id")

    if username is None or user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_user_by_id(db, user_id)
    if user is None or user.username != username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


async def get_current_admin(
    current_user: Annotated[models.User, Depends(get_current_user)],
) -> models.User:
    """
    Ensures that the current user is an admin.
    Raises 403 if not.
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions (admin required)",
        )
    return current_user


# SECTION: Auth Endpoints
@app.post("/auth/signup", status_code=status.HTTP_201_CREATED)
def signup(user_data: UserCreate, db: DbSessionDep):
    """
    Create a new user account.

    NOTE: For now, this is open; in a real company this would be restricted
    (e.g., only admins can create users, or via SSO).
    """
    # Check if username or email already exists
    existing_user = (
        db.query(models.User)
        .filter(
            (models.User.username == user_data.username)
            | (models.User.email == user_data.email)
        )
        .first()
    )

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username or email already registered.",
        )

    hashed_password = get_password_hash(user_data.password)

    new_user = models.User(
        username=user_data.username,
        email=user_data.email,
        hashed_password=hashed_password,
        is_admin=False,  # default new users to non-admin
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "id": new_user.id,
        "username": new_user.username,
        "email": new_user.email,
        "is_admin": new_user.is_admin,
        "message": "User created successfully.",
    }

@app.post("/auth/login", response_model=TokenResponse)
def login(form_data: UserLogin, db: DbSessionDep):
    """
    Log in a user and return a JWT access token.

    In a more 'OAuth2' style implementation, you'd accept form-encoded data using
    OAuth2PasswordRequestForm, but here we keep it simple with JSON.
    """
    user = get_user_by_username(db, form_data.username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
        )

    if not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password.",
        )

    # Create token payload; sub = subject (standard JWT claim)
    token_data = {
        "sub": user.username,
        "user_id": user.id,
        "is_admin": user.is_admin,
    }

    access_token = create_access_token(data=token_data)

    return TokenResponse(access_token=access_token)

# SECTION: Current user + Incident endpoints
@app.get("/me")
def read_current_user(
    current_user: Annotated[models.User, Depends(get_current_user)],
):
    """Who am I? Used by the front end to decide whether to show admin controls."""
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "is_admin": current_user.is_admin,
    }


@app.post("/incidents", status_code=status.HTTP_201_CREATED)
def create_incident(
    payload: IncidentCreate,
    db: DbSessionDep,
    current_user: Annotated[models.User, Depends(get_current_user)],
):
    """Create an incident. Replaces the old unauthenticated debug endpoint."""
    incident = models.Incident(
        title=payload.title,
        description=payload.description,
        severity=payload.severity,
        status=payload.status or models.IncidentStatus.OPEN,
        creator_id=current_user.id,
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)
    return _incident_to_dict(incident)


@app.get("/incidents")
def list_incidents(
    db: DbSessionDep,
    current_user: Annotated[models.User, Depends(get_current_user)],
    limit: int = 50,
):
    incidents = (
        db.query(models.Incident)
        .order_by(models.Incident.created_at.desc())
        .limit(min(limit, 200))
        .all()
    )
    return {"count": len(incidents), "incidents": [_incident_to_dict(i) for i in incidents]}


@app.get("/incidents/{incident_id}")
def get_incident(
    incident_id: int,
    db: DbSessionDep,
    current_user: Annotated[models.User, Depends(get_current_user)],
):
    incident = db.query(models.Incident).filter(models.Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found.")
    return _incident_to_dict(incident)


def _incident_to_dict(i: models.Incident) -> dict:
    return {
        "id": i.id,
        "title": i.title,
        "description": i.description,
        "status": i.status,
        "severity": i.severity,
        "created_at": i.created_at.isoformat() if i.created_at else None,
        "creator_id": i.creator_id,
    }


@app.get("/documents")
def list_documents(
    db: DbSessionDep,
    current_user: Annotated[models.User, Depends(get_current_user)],
    type: Optional[str] = None,
):
    """List uploaded documents, optionally filtered by type (log / runbook)."""
    q = db.query(models.Document)
    if type:
        q = q.filter(models.Document.type == type)
    docs = q.order_by(models.Document.uploaded_at.desc()).limit(200).all()

    return {
        "count": len(docs),
        "documents": [
            {
                "id": d.id,
                "title": d.title,
                "type": d.type,
                "status": d.status,
                "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
                "chunk_count": len(d.chunks) if d.type == models.DocumentType.RUNBOOK else None,
            }
            for d in docs
        ],
    }


# SECTION: Debug endpoints (disabled unless ENABLE_DEBUG_ENDPOINTS=true)
if settings.ENABLE_DEBUG_ENDPOINTS:

    @app.post("/debug/create-incident", status_code=status.HTTP_201_CREATED)
    def create_debug_incident(
        db: DbSessionDep,
        current_admin: Annotated[models.User, Depends(get_current_admin)],
    ):
        """Local testing helper. Requires an admin token even when enabled."""
        incident = models.Incident(
            title="Debug Test Incident",
            description="A temporary incident for RAG feature testing.",
            status=models.IncidentStatus.OPEN,
            severity="SEV-3",
            creator_id=current_admin.id,
        )
        db.add(incident)
        db.commit()
        db.refresh(incident)
        return {"message": "Debug incident created.", "incident_id": incident.id}

# helper to detect file type
def detect_document_type(file: UploadFile) -> str:
    """
    File detection based on file extension.
    In a real system, we'd also inspect content signatures (magic numbers).
    """
    filename = file.filename or ""
    lower_name = filename.lower()

    # Common log extensions
    if lower_name.endswith((".log", ".jsonl", ".ndjson")):
        return models.DocumentType.LOG
    if lower_name.endswith(".pdf"):
        return models.DocumentType.RUNBOOK
    if lower_name.endswith(".txt") or lower_name.endswith(".md"):
        return models.DocumentType.RUNBOOK

    return models.DocumentType.OTHER


# SECTION: Simple log line parser
LOG_LINE_REGEX = re.compile(
    r"^(?P<timestamp>\S+)\s+(?P<level>[A-Z]+)\s+(?P<message>.+)$"
)


def parse_log_line(line: str) -> dict:
    """
    Parsing a single log line into structured data.
    Expected format (simple style):
      2024-06-01T10:42:11Z INFO User 123 logged in

    Returns a dict with keys:
      - timestamp (datetime or None)
      - level (str or None)
      - message (str)
      - raw (str)
    """
    line = line.strip()
    if not line:
        return {}

    match = LOG_LINE_REGEX.match(line)
    if not match:
        # If it doesn't match the simple pattern,
        # treat the whole line as message
        return {
            "timestamp": None,
            "level": None,
            "message": line,
            "raw": line,
        }

    ts_str = match.group("timestamp")
    level = match.group("level")
    message = match.group("message")

    # parsing timestamp
    ts = None
    try:
        # to handle ISO 8601-like timestamps such as 2024-06-01T10:42:11Z
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        pass

    return {
        "timestamp": ts,
        "level": level,
        "message": message,
        "raw": line,
    }


# SECTION: Embedding Model Initialization
# Global variable to hold the embedding model
embedding_model: Optional[SentenceTransformer] = None


def get_embedding_model() -> SentenceTransformer:
    """
    Lazy-load the SentenceTransformer model.
    We only load it once and reuse it to avoid expensive reloads.
    """
    global embedding_model
    if embedding_model is None:
        # Load a small, fast model suitable for CPU and local development.
        # This model is good for general-purpose sentence embeddings.
        print(f"Loading SentenceTransformer model: {settings.EMBEDDING_MODEL} ...")
        embedding_model = SentenceTransformer(settings.EMBEDDING_MODEL)
        print("Model loaded.")
    return embedding_model


def generate_embedding(text: str) -> list[float]:
    """
    Generates an embedding vector (list of floats) for a given text.
    """
    model = get_embedding_model()
    # Encode the text to get its embedding
    embedding = model.encode(text)
    # Convert numpy array to list for JSON serialization and database storage
    return embedding.tolist()

# SECTION: Cosine similarity helper for vector search
#phase 3 function
def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """
    Computes cosine similarity between two vectors.

    Cosine similarity measures how close two vectors are in direction.
    1.0 -> identical direction (very similar)
    0.0 -> orthogonal (unrelated)
    -1.0 -> opposite direction

    We assume both vectors are non-empty and of the same length.
    """
    if not vec_a or not vec_b:
        return 0.0

    # Compute dot product and magnitudes
    dot = 0.0
    mag_a = 0.0
    mag_b = 0.0
    for a, b in zip(vec_a, vec_b):
        dot += a * b
        mag_a += a * a
        mag_b += b * b

    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0

    return dot / ((mag_a ** 0.5) * (mag_b ** 0.5))


# SECTION: Chunking
def chunk_text(
    text: str,
    max_chars: int = None,
    overlap: int = None,
) -> list[str]:
    """
    Split document text into overlapping chunks.

    The old approach split on blank lines and truncated anything over 2000
    characters with an ellipsis, which threw away real content: a long runbook
    section would lose everything past the cutoff, and the answer to a question
    could sit in the discarded tail.

    This version packs paragraphs up to a size limit, hard-splits paragraphs
    that are individually too long, and carries a short overlap between chunks
    so a procedure spanning a boundary is still retrievable from both sides.
    """
    max_chars = max_chars or settings.CHUNK_MAX_CHARS
    overlap = overlap or settings.CHUNK_OVERLAP_CHARS

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return []

    # Break any single paragraph that already exceeds the limit.
    pieces: list[str] = []
    for para in paragraphs:
        if len(para) <= max_chars:
            pieces.append(para)
            continue
        start = 0
        while start < len(para):
            pieces.append(para[start : start + max_chars])
            start += max_chars - overlap

    # Pack pieces into chunks.
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if not current:
            current = piece
        elif len(current) + len(piece) + 2 <= max_chars:
            current = f"{current}\n\n{piece}"
        else:
            chunks.append(current)
            tail = current[-overlap:] if overlap else ""
            current = f"{tail}\n\n{piece}".strip() if tail else piece

    if current:
        chunks.append(current)

    return chunks


def serialize_embedding(vector: list[float]):
    """pgvector takes the list directly; SQLite needs a JSON string."""
    return vector if settings.use_pgvector else json.dumps(vector)


def deserialize_embedding(stored) -> list[float]:
    if stored is None:
        return []
    if isinstance(stored, str):
        try:
            return json.loads(stored)
        except json.JSONDecodeError:
            return []
    return list(stored)


# SECTION: Retrieval
def retrieve_relevant_chunks(
    db: Session,
    query: str,
    top_k: int = None,
    threshold: float = None,
) -> list[dict]:
    """
    Semantic search over runbook chunks.

    On Postgres with pgvector this is a single indexed SQL query: the database
    does the distance maths and returns only top_k rows.

    On SQLite we fall back to loading every chunk and scoring in Python, which
    is what the original code did everywhere. That is O(n) in both rows and
    memory and is the main reason this project needed Postgres.
    """
    top_k = top_k or settings.TOP_K_CHUNKS
    threshold = settings.SIMILARITY_THRESHOLD if threshold is None else threshold

    query_embedding = generate_embedding(query)

    if settings.use_pgvector:
        # cosine_distance = 1 - cosine_similarity
        distance = models.DocumentChunk.embedding.cosine_distance(query_embedding)
        rows = (
            db.query(
                models.DocumentChunk,
                models.Document,
                distance.label("distance"),
            )
            .join(models.Document, models.Document.id == models.DocumentChunk.document_id)
            .filter(
                models.Document.type == models.DocumentType.RUNBOOK,
                models.DocumentChunk.embedding.isnot(None),
            )
            .order_by(distance)
            .limit(top_k)
            .all()
        )
        scored = [
            {
                "similarity": 1.0 - float(dist),
                "chunk_id": chunk.id,
                "document_id": doc.id,
                "document_title": doc.title,
                "chunk_order": chunk.chunk_order,
                "chunk_text": chunk.chunk_text,
            }
            for chunk, doc, dist in rows
        ]
    else:
        chunks_with_docs = (
            db.query(models.DocumentChunk, models.Document)
            .join(models.Document, models.Document.id == models.DocumentChunk.document_id)
            .filter(
                models.Document.type == models.DocumentType.RUNBOOK,
                models.DocumentChunk.embedding.isnot(None),
            )
            .all()
        )
        scored = []
        for chunk, doc in chunks_with_docs:
            vec = deserialize_embedding(chunk.embedding)
            if not vec:
                continue
            scored.append(
                {
                    "similarity": cosine_similarity(query_embedding, vec),
                    "chunk_id": chunk.id,
                    "document_id": doc.id,
                    "document_title": doc.title,
                    "chunk_order": chunk.chunk_order,
                    "chunk_text": chunk.chunk_text,
                }
            )
        scored.sort(key=lambda item: item["similarity"], reverse=True)
        scored = scored[:top_k]

    return [s for s in scored if s["similarity"] >= threshold]



def retrieve_relevant_log_patterns(
    db: Session,
    query: str,
    incident: models.Incident,
    top_k: int = 5,
) -> list[dict]:
    """
    Find related historical log patterns for the current incident.

    This is intentionally lightweight: it groups repeated uploaded log messages
    and ranks them by keyword overlap, severity, and frequency. Runbooks remain
    the primary grounded source; logs are supporting historical evidence.
    """
    search_text = " ".join(
        [
            query,
            incident.title or "",
            incident.description or "",
        ]
    ).lower()

    stop_words = {
        "the", "a", "an", "and", "or", "is", "are", "was", "were",
        "to", "of", "in", "on", "for", "with", "what", "why", "how",
        "do", "does", "did", "this", "that", "it", "my", "our",
    }

    search_terms = {
        word
        for word in re.findall(r"[a-zA-Z0-9_-]+", search_text)
        if len(word) >= 3 and word not in stop_words
    }

    if not search_terms:
        return []

    rows = (
        db.query(
            models.LogEntry.message,
            models.LogEntry.level,
            models.Document.id.label("document_id"),
            models.Document.title.label("document_title"),
            func.count(models.LogEntry.id).label("occurrence_count"),
            func.max(models.LogEntry.timestamp).label("latest_timestamp"),
        )
        .join(
            models.Document,
            models.Document.id == models.LogEntry.document_id,
        )
        .filter(models.Document.type == models.DocumentType.LOG)
        .group_by(
            models.LogEntry.message,
            models.LogEntry.level,
            models.Document.id,
            models.Document.title,
        )
        .all()
    )

    level_weights = {
        "FATAL": 4,
        "CRITICAL": 4,
        "ERROR": 3,
        "ERR": 3,
        "WARN": 2,
        "WARNING": 2,
        "INFO": 0,
        "DEBUG": 0,
    }

    scored_patterns = []

    for row in rows:
        message = row.message or ""
        message_terms = set(re.findall(r"[a-zA-Z0-9_-]+", message.lower()))
        matching_terms = search_terms.intersection(message_terms)

        if not matching_terms:
            continue

        level = (row.level or "UNKNOWN").upper()
        score = (
            len(matching_terms) * 3
            + level_weights.get(level, 1)
            + min(int(row.occurrence_count or 0), 10) * 0.1
        )

        scored_patterns.append(
            {
                "score": round(score, 2),
                "message": message,
                "level": level,
                "occurrence_count": int(row.occurrence_count or 0),
                "document_id": row.document_id,
                "document_title": row.document_title,
                "latest_timestamp": (
                    row.latest_timestamp.isoformat()
                    if row.latest_timestamp
                    else None
                ),
                "matching_terms": sorted(matching_terms),
            }
        )

    scored_patterns.sort(key=lambda item: item["score"], reverse=True)
    return scored_patterns[:top_k]


def build_log_context(log_patterns: list[dict]) -> str:
    """Format related historical log patterns for the LLM prompt."""
    if not log_patterns:
        return "No related historical log patterns were found."

    sections = []
    for index, pattern in enumerate(log_patterns, start=1):
        sections.append(
            f"[Historical Log Pattern {index}]\n"
            f"Source file: {pattern['document_title']}\n"
            f"Level: {pattern['level']}\n"
            f"Message: {pattern['message']}\n"
            f"Occurrences: {pattern['occurrence_count']}\n"
            f"Most recent occurrence: "
            f"{pattern['latest_timestamp'] or 'unknown'}"
        )

    return "\n\n".join(sections)

@app.post("/admin/upload", status_code=status.HTTP_201_CREATED)
async def upload_document(
    title: Annotated[str, Form(...)] ,
    file: Annotated[UploadFile, File(...)] ,
    db: DbSessionDep,
    current_admin: Annotated[models.User, Depends(get_current_admin)],
    ):
    """
    Admin endpoint to upload a file.

    - For log files (.log/.jsonl/.ndjson): parses lines into LogEntry records.
    - For runbooks/docs (pdf/txt/md): parses text, chunks it, and generates embeddings for each chunk.
    """

    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must have a name.",
        )

    doc_type = detect_document_type(file)

    # For now, only allow log and runbook/doc types
    if doc_type not in (models.DocumentType.LOG, models.DocumentType.RUNBOOK):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type. Please upload .log, .jsonl, .ndjson, .pdf, .txt, or .md files.",
        )

    # Generating safe unique filename
    file_extension = os.path.splitext(file.filename)[1] or ""
    unique_id = str(uuid.uuid4())
    safe_filename = f"{unique_id}{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, safe_filename)

    # Save to disk
    try:
        with open(file_path, "wb") as f:
            while chunk := await file.read(1024 * 1024):
                f.write(chunk)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save file: {e}",
        )

    # Create Document record with initial status
    document = models.Document(
        title=title,
        file_path=file_path,
        type=doc_type,
        status="processing",
        uploader_id=current_admin.id,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    # --- Document Type Specific Processing ---

    # If it's a log file, parse into LogEntry
    if doc_type == models.DocumentType.LOG:
        created_count = 0

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    parsed = parse_log_line(line)
                    if not parsed:
                        continue

                    log_entry = models.LogEntry(
                        document_id=document.id,
                        incident_id=None,  # Later we may link to an Incident
                        timestamp=parsed["timestamp"],
                        level=parsed["level"],
                        message=parsed["message"],
                        raw=parsed["raw"],
                    )
                    db.add(log_entry)
                    created_count += 1

            document.status = "processed"
            db.add(document)
            db.commit()
            db.refresh(document)

        except Exception as e:
            document.status = "failed"
            db.add(document)
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to parse log file: {e}",
            )

        return {
            "id": document.id,
            "title": document.title,
            "type": document.type,
            "status": document.status,
            "log_entries_created": created_count,
        }

    # If it's a runbook/doc, parse text, chunk, and embed
    elif doc_type == models.DocumentType.RUNBOOK:
        full_text = ""
        try:
            # Check file extension before trying pypdf
            if file_extension.lower() == ".pdf":
                reader = PdfReader(file_path)
                for page_num, page in enumerate(reader.pages):
                    extracted = page.extract_text() or ""
                    full_text += extracted + "\n"
            else:  # For .txt, .md, etc., just read the raw file
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    full_text = f.read()

        except Exception as e:
            document.status = "failed"
            db.add(document)
            db.commit()
            os.remove(file_path)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to parse document content: {e}",
            )

        # Overlapping chunking. See chunk_text() for why this replaced the
        # old split-on-blank-line-and-truncate approach.
        raw_chunks = chunk_text(full_text)

        if not raw_chunks and full_text.strip():
            raw_chunks = [full_text.strip()]
        elif not raw_chunks:
            document.status = "failed"
            db.add(document)
            db.commit()
            os.remove(file_path)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Document contains no extractable text content.",
            )

        document_chunks = []
        for i, text_piece in enumerate(raw_chunks):
            chunk_embedding = generate_embedding(text_piece)

            db_chunk = models.DocumentChunk(
                document_id=document.id,
                chunk_text=text_piece,
                chunk_order=i,
                embedding=serialize_embedding(chunk_embedding),
                embedding_model=settings.EMBEDDING_MODEL,
            )
            document_chunks.append(db_chunk)

        db.add_all(document_chunks)
        document.status = "processed"
        db.add(document)
        db.commit()
        db.refresh(document)

        return {
            "id": document.id,
            "title": document.title,
            "type": document.type,
            "status": document.status,
            "chunk_count": len(document_chunks),
            "message": "Runbook/document uploaded, parsed, chunked, and embeddings generated.",
        }

    # Should not happen due to prior type check, but here for safety
    else:
        document.status = "failed"
        db.add(document)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected document type encountered.",
        )


@app.get("/logs/{document_id}/summary", response_model=dict)
def get_log_summary(document_id: int, db: DbSessionDep):
    """
    Retrieves a summary of log entries for a given document.

    Includes:
    - Total log entries
    - Count by log level (INFO, WARN, ERROR, etc.)
    - Clustered common messages (top N most frequent messages)
    - Time range of logs
    """
    # Verifying document exists and is a log file
    document = db.query(models.Document).filter(models.Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    if document.type != models.DocumentType.LOG:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Document is not a log file.")

    # 1. Basic count
    total_entries = db.query(models.LogEntry).filter(models.LogEntry.document_id == document_id).count()

    # 2. Get min/max timestamps for the log entries
    time_range = (
        db.query(
            func.min(models.LogEntry.timestamp),
            func.max(models.LogEntry.timestamp),
        )
        .filter(models.LogEntry.document_id == document_id)
        .first()
    )
    first_log_time, last_log_time = time_range if time_range else (None, None)

    # 3. Count by log level
    level_counts = (
        db.query(models.LogEntry.level, func.count(models.LogEntry.id))
        .filter(models.LogEntry.document_id == document_id)
        .group_by(models.LogEntry.level)
        .order_by(func.count(models.LogEntry.id).desc())
        .all()
    )

    # Format: {"INFO": 100, "ERROR": 20, "WARN": 5}
    formatted_level_counts = {level: count for level, count in level_counts if level is not None}
    # Include entries without a recognized level
    if None in [lc[0] for lc in level_counts]:
        formatted_level_counts["UNKNOWN_LEVEL"] = next(
            (lc[1] for lc in level_counts if lc[0] is None), 0
        )

    # 4. Cluster common messages (top N)
    message_clusters = (
        db.query(models.LogEntry.message, func.count(models.LogEntry.id))
        .filter(models.LogEntry.document_id == document_id)
        .group_by(models.LogEntry.message)
        .order_by(func.count(models.LogEntry.id).desc())
        .limit(10)  # Get top 10 most frequent messages
        .all()
    )
    # Format: [{"message": "Database timeout", "count": 150}, ...]
    formatted_message_clusters = [{"message": msg, "count": count} for msg, count in message_clusters]

    return {
        "document_id": document_id,
        "total_log_entries": total_entries,
        "first_log_entry_at": first_log_time.isoformat() if first_log_time else None,
        "last_log_entry_at": last_log_time.isoformat() if last_log_time else None,
        "level_counts": formatted_level_counts,
        "top_message_clusters": formatted_message_clusters,
    }

#phase 3
@app.get("/search/runbooks", response_model=dict)
def search_runbooks(
    query: str,
    db: DbSessionDep,
    current_user: Annotated[models.User, Depends(get_current_user)],
    top_k: int = 5,
    threshold: float = 0.0,
):
    """
    Semantic search over runbook chunks.

    Retrieval now lives in retrieve_relevant_chunks() so that this endpoint and
    the RAG endpoint cannot drift apart. Default threshold is 0.0 here because
    when you are inspecting search quality you want to see the weak matches too.
    """
    results = retrieve_relevant_chunks(db, query, top_k=top_k, threshold=threshold)

    return {
        "query": query,
        "top_k": top_k,
        "threshold": threshold,
        "backend": "pgvector" if settings.use_pgvector else "python",
        "result_count": len(results),
        "results": [
            {**r, "similarity": round(float(r["similarity"]), 4)} for r in results
        ],
    }


# SECTION: RAG Endpoint for Incident Investigation
@app.post("/incidents/{incident_id}/ask", response_model=dict)
async def ask_incident_assistant(
    incident_id: int,
    question: Annotated[str, Form(...)],
    db: DbSessionDep,
    current_user: Annotated[models.User, Depends(get_current_user)],
    top_k_chunks: int = None,
):
    """
    Ask a question about an incident, answered from the runbook corpus.

    Flow: retrieve -> build a numbered context block -> call the configured LLM
    -> persist the question and answer for analytics.
    """
    incident = db.query(models.Incident).filter(models.Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found.")

    question = question.strip()
    if not question:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Question cannot be empty.",
        )

    top_k = top_k_chunks or settings.TOP_K_CHUNKS

    # Retrieval happens off the event loop: embedding a query is CPU-bound and
    # would otherwise block every other request on this worker.
    relevant_chunks = await asyncio.to_thread(
        retrieve_relevant_chunks, db, question, top_k
    )

    # Searching previously uploaded logs for related historical patterns.
    relevant_log_patterns = await asyncio.to_thread(
        retrieve_relevant_log_patterns,
        db,
        question,
        incident,
        5,
    )
    log_context = build_log_context(relevant_log_patterns)

    if relevant_chunks:
        context_block, citations = llm.build_context_block(relevant_chunks)
        system_prompt = llm.GROUNDED_SYSTEM_PROMPT
        user_prompt = (
            f"Incident: {incident.title}\n"
            f"Incident description: {incident.description or 'not provided'}\n\n"
            f"Question: {question}\n\n"
            f"Official runbook context:\n{context_block}\n\n"
            f"Related historical log patterns:\n{log_context}\n\n"
            "Use the runbook as the primary troubleshooting source. "
            "Use historical logs only as supporting evidence about patterns "
            "that occurred before. Do not claim a historical pattern is the "
            "confirmed cause of the current incident."
        )
        grounded = True
        message = (
            "Answer generated from runbook context and related historical "
            "log patterns."
            if relevant_log_patterns
            else "Answer generated from runbook context."
        )
    else:
        context_block, citations = "", []
        system_prompt = llm.UNGROUNDED_SYSTEM_PROMPT
        user_prompt = (
            f"Incident: {incident.title}\n"
            f"Incident description: {incident.description or 'not provided'}\n\n"
            f"Question: {question}\n\n"
            "No relevant runbook guidance was retrieved.\n\n"
            f"Related historical log patterns:\n{log_context}\n\n"
            "Historical logs are supporting evidence only. Explain that no "
            "official runbook guidance was found, and do not present a "
            "historical pattern as the confirmed cause of the current incident."
        )
        grounded = False
        message = (
            "No runbook content cleared the similarity threshold. "
            "Related historical log patterns were included as supporting evidence."
            if relevant_log_patterns
            else (
                "No runbook content or related historical log patterns were found. "
                "Answer is general guidance only."
            )
        )

    result = await llm.generate(system_prompt, user_prompt)

    # Persist once, after we have the answer. The old code committed the
    # question first and then committed again with the answer, doubling the
    # writes on every single request.
    question_log = models.QuestionLog(
        incident_id=incident_id,
        user_id=current_user.id,
        question=question,
        ai_answer=result.text,
    )
    db.add(question_log)
    db.commit()
    db.refresh(question_log)

    return {
        "incident_id": incident_id,
        "question_log_id": question_log.id,
        "question": question,
        "answer": result.text,
        "citations": citations,
        "grounded": grounded,
        "llm": {
            "provider": result.provider,
            "model": result.model,
            "degraded": result.degraded,
            "error": result.error,
        },
        "retrieval": {
            "backend": "pgvector" if settings.use_pgvector else "python",
            "threshold": settings.SIMILARITY_THRESHOLD,
            "chunks_used": len(citations),
            "historical_log_patterns_used": len(relevant_log_patterns),
        },
        "historical_log_patterns": relevant_log_patterns,
        "message": message,
    }


@app.post("/feedback", status_code=status.HTTP_201_CREATED)
def submit_answer_feedback(
    feedback_data: AnswerFeedbackSubmit,
    db: DbSessionDep,
    current_user: Annotated[models.User, Depends(get_current_user)],
):
    """
    Allows users to submit feedback on an AI-generated answer,
    linking it directly to a specific question log entry.
    """
    # 1. Retrieve the original question log entry
    question_log_entry = db.query(models.QuestionLog).filter(
        models.QuestionLog.id == feedback_data.question_log_id
    ).first()

    if not question_log_entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Question log entry with ID {feedback_data.question_log_id} not found."
        )
    
    # 2. Create feedback record
    new_feedback = models.AnswerFeedback(
        incident_id=question_log_entry.incident_id, # Link to the incident from the log
        user_id=current_user.id, # The user submitting feedback
        question=question_log_entry.question, # The original question
        answer=question_log_entry.ai_answer, # The AI's full answer from the log
        is_helpful=feedback_data.is_helpful,
        feedback_text=feedback_data.feedback_text,
    )

    db.add(new_feedback)
    db.commit()
    db.refresh(new_feedback)

    return {
        "feedback_id": new_feedback.id,
        "question_log_id": question_log_entry.id,
        "message": "Feedback submitted successfully.",
        "is_helpful": new_feedback.is_helpful,
    }


# SECTION: Analytics
@app.get("/analytics/summary")
def analytics_summary(
    db: DbSessionDep,
    current_user: Annotated[models.User, Depends(get_current_user)],
):
    """
    Aggregate view of how the assistant is being used and whether it is helping.

    The feedback loop only has value if you can see it, so this surfaces the
    helpful/unhelpful split alongside volume.
    """
    total_questions = db.query(func.count(models.QuestionLog.id)).scalar() or 0
    total_feedback = db.query(func.count(models.AnswerFeedback.id)).scalar() or 0
    helpful = (
        db.query(func.count(models.AnswerFeedback.id))
        .filter(models.AnswerFeedback.is_helpful.is_(True))
        .scalar()
        or 0
    )

    recent = (
        db.query(models.QuestionLog)
        .order_by(models.QuestionLog.answered_at.desc())
        .limit(10)
        .all()
    )

    return {
        "total_questions": total_questions,
        "total_feedback": total_feedback,
        "helpful_count": helpful,
        "unhelpful_count": total_feedback - helpful,
        "helpful_rate": round(helpful / total_feedback, 3) if total_feedback else None,
        "documents": {
            "runbooks": db.query(func.count(models.Document.id))
            .filter(models.Document.type == models.DocumentType.RUNBOOK)
            .scalar()
            or 0,
            "logs": db.query(func.count(models.Document.id))
            .filter(models.Document.type == models.DocumentType.LOG)
            .scalar()
            or 0,
        },
        "total_chunks": db.query(func.count(models.DocumentChunk.id)).scalar() or 0,
        "total_log_entries": db.query(func.count(models.LogEntry.id)).scalar() or 0,
        "recent_questions": [
            {
                "id": q.id,
                "incident_id": q.incident_id,
                "question": q.question,
                "answered_at": q.answered_at.isoformat() if q.answered_at else None,
            }
            for q in recent
        ],
    }


# SECTION: Front end
# Mounted last so it does not shadow the API routes above. html=True makes
# StaticFiles serve index.html at "/".
_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")