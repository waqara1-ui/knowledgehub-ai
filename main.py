from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from typing import Annotated, Optional
import os
import uuid  # generates unique links?
from datetime import datetime
import re  # for log parsing

from database import engine, Base, get_database
from sqlalchemy import func
from sqlalchemy.orm import Session
import models

from pypdf import PdfReader  # for PDF parsing

# NEW IMPORTS FOR EMBEDDINGS
from sentence_transformers import SentenceTransformer
import json  # To store embeddings as JSON string in DB
import asyncio

#NEW IMPORTS FOR SECURITY
from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import timedelta, datetime, timezone # For token expiration

from pydantic import BaseModel, EmailStr
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials


SECRET_KEY = "KEY_PASSOWRD_131" # CHANGE THIS IN PRODUCTION!
ALGORITHM = "HS256" # Hashing algorithm for JWT
ACCESS_TOKEN_EXPIRE_MINUTES = 60 # Token expires in 60 minutes


# Create all database tables defined in models.py
# This will create the .db file and tables if they don't exist
# In a real production app, you would use a migration tool like Alembic for this.
Base.metadata.create_all(bind=engine)

# creating an instance of FastAPI and assigning into app which is what Uvicorn will run
app = FastAPI(
    title="LogLens AI",
    description="AI-powered incident investigation and log analysis assistant.",
    version="0.1.0",
)

# ensuring upload directory exists
UPLOAD_DIR = "uploaded_files"
os.makedirs(UPLOAD_DIR, exist_ok=True)

DbSessionDep = Annotated[Session, Depends(get_database)]
# Annotated[Session, Depends(get_database)] tells FastAPI:
# “this parameter is a Session and should be provided by get_database.”

# SECTION: Pydantic Schemas (for requests/responses)

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


@app.get("/health")
def health_check():
    """
    Adding a health check endpoint to return a simple JSON response that indicates the service is running.
    This is useful for monitoring and uptime checks.
    """
    return {"status": "ok"}  # JSON response

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

@app.post("/debug/create-user", status_code=status.HTTP_201_CREATED)
def create_debug_user(db: DbSessionDep):
    """
    DEBUG ENDPOINT: Creates a dummy user for testing purposes.
    Sets ID to 1. REMOVE THIS IN PRODUCTION.
    """
    # Check if a user with id=1 already exists
    existing_user = db.query(models.User).filter(models.User.id == 1).first()
    if existing_user:
        return {"message": "Debug user (ID 1) already exists.", "user_id": existing_user.id}

    # Create a new user with ID 1
    new_user = models.User(
        id=1, # Explicitly set ID for testing
        username="debug_user",
        email="debug@example.com",
        hashed_password=get_password_hash("not_a_real_password_hash"), # Store a valid bcrypt hash
        is_admin=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"message": "Debug user created successfully.", "user_id": new_user.id}

# main.py (add this right after create_debug_user)

@app.post("/debug/create-incident", status_code=status.HTTP_201_CREATED)
def create_debug_incident(db: DbSessionDep):
    """
    DEBUG ENDPOINT: Creates a dummy incident for testing purposes.
    Sets ID to 1 and links to User ID 1. REMOVE THIS IN PRODUCTION.
    """
    # Check if an incident with id=1 already exists
    existing_incident = db.query(models.Incident).filter(models.Incident.id == 1).first()
    if existing_incident:
        return {"message": "Debug incident (ID 1) already exists.", "incident_id": existing_incident.id}

    # IMPORTANT: Ensure User ID 1 exists before creating incident
    existing_user = db.query(models.User).filter(models.User.id == 1).first()
    if not existing_user:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="User with ID 1 must exist before creating a debug incident. Please run /debug/create-user first."
        )

    # Create a new incident with ID 1
    new_incident = models.Incident(
        id=1, # Explicitly set ID for testing
        title="Debug Test Incident",
        description="A temporary incident for RAG feature testing.",
        status=models.IncidentStatus.OPEN,
        severity="SEV-3",
        creator_id=1, # Link to our debug_user
    )
    db.add(new_incident)
    db.commit()
    db.refresh(new_incident)
    return {"message": "Debug incident created successfully.", "incident_id": new_incident.id}

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
        print("Loading SentenceTransformer model...")
        embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
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

        # Simple chunking strategy for now: split by double newline and filter empty chunks
        raw_chunks = [chunk.strip() for chunk in full_text.split("\n\n") if chunk.strip()]

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
        for i, chunk_text in enumerate(raw_chunks):
            # Limit chunk size for demonstration
            if len(chunk_text) > 2000:
                chunk_text = chunk_text[:2000] + "..."  # Truncate and add ellipsis

            # Generate embedding for the chunk
            chunk_embedding = generate_embedding(chunk_text)

            db_chunk = models.DocumentChunk(
                document_id=document.id,
                chunk_text=chunk_text,
                chunk_order=i,
                # Store embedding as a JSON string for now
                embedding=json.dumps(chunk_embedding),
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
def search_runbooks(query: str, db: DbSessionDep, top_k: int = 5):
    """
    Semantic search over runbook/document chunks.

    Steps:
    - Embedding the query using the same embedding model.
    - Load all DocumentChunk embeddings for RUNBOOK documents.
    - Computing cosine similarity between query embedding and each chunk embedding.
    - Sorting by similarity and returning the top_k matches.

    Query parameters:
    - query: the natural language question or phrase.
    - top_k: how many top results to return (default: 5).
    """
    if not query.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query must not be empty.",
        )

    # 1. Generate embedding for the query
    query_embedding = generate_embedding(query)

    # 2. Load all chunks for documents of type RUNBOOK that have embeddings
    # Join DocumentChunk with Document to filter only RUNBOOK-type documents
    chunks_with_docs = (
        db.query(models.DocumentChunk, models.Document)
        .join(models.Document, models.Document.id == models.DocumentChunk.document_id)
        .filter(
            models.Document.type == models.DocumentType.RUNBOOK,
            models.DocumentChunk.embedding.isnot(None),
        )
        .all()
    )

    if not chunks_with_docs:
        return {
            "query": query,
            "results": [],
            "message": "No runbook/document chunks with embeddings found.",
        }

    # 3. Compute similarity with each chunk
    scored_results = []
    for chunk, document in chunks_with_docs:
        try:
            # embedding is stored as JSON string, so we parse it
            chunk_embedding = json.loads(chunk.embedding)
        except Exception:
            # If parsing fails for some reason, skip this chunk
            continue

        sim = cosine_similarity(query_embedding, chunk_embedding)

        scored_results.append(
            {
                "similarity": sim,
                "chunk_id": chunk.id,
                "document_id": document.id,
                "document_title": document.title,
                "chunk_order": chunk.chunk_order,
                "chunk_text": chunk.chunk_text,
            }
        )

    # 4. Sort by similarity (highest first) and take top_k
    scored_results.sort(key=lambda item: item["similarity"], reverse=True)
    top_results = scored_results[: top_k]

    return {
        "query": query,
        "top_k": top_k,
        "result_count": len(top_results),
        "results": top_results,
    }

# main.py (add after generate_embedding and cosine_similarity)

# ... (your generate_embedding and cosine_similarity functions) ...

# SECTION: Mock LLM for RAG (Placeholder for actual LLM integration)
async def mock_llm_generate(prompt: str) -> str:
    """
    A placeholder function that simulates an LLM generating a response.
    In a real application, this would call a service like Google Gemini, OpenAI GPT, etc.
    """
    print(f"Mock LLM received prompt:\n{prompt[:500]}...") # Print first 500 chars of prompt
    
    # Simulate thinking time
    await asyncio.sleep(0.1) 

    if "database timeout" in prompt.lower() and "connection pool" in prompt.lower():
        return "Based on the provided context, a common cause for database timeouts is connection pool exhaustion. Consider increasing the connection pool size or restarting the affected services."
    elif "restart" in prompt.lower() and "service" in prompt.lower():
        return "The context suggests that restarting the relevant service is a common troubleshooting step for many issues."
    elif "no extractable text" in prompt.lower():
        return "The document indicates it contains no extractable text, suggesting it might be an image-only PDF or corrupted."
    else:
        return "Based on the provided context, I can give a general answer. To solve the issue, you should review logs and documentation for specific steps."


# SECTION: RAG Endpoint for Incident Investigation
@app.post("/incidents/{incident_id}/ask", response_model=dict)
async def ask_incident_assistant(
    incident_id: int,
    question: Annotated[str, Form(...)],
    db: DbSessionDep,
    top_k_chunks: int = 5,
):
    """
    Ask the AI assistant a question about a specific incident,
    using RAG over runbook chunks to generate a grounded answer.

    Steps:
    1. Verify incident exists. (Currently, we don't use log entries in RAG here yet).
    2. Semantically search runbook chunks using the question.
    3. Construct a prompt for the LLM with the question and retrieved context.
    4. Call the LLM (mock for now) to generate an answer.
    5. Return the answer with citations.

    Path parameters:
    - incident_id: The ID of the incident to ask about (for future context/linking).

    Form parameters:
    - question: The natural language question to ask the assistant.
    - top_k_chunks: Number of most relevant runbook chunks to retrieve for context (default: 5).
    """

    # 1. Verify incident exists (and is 'open' or 'investigating')
    incident = db.query(models.Incident).filter(models.Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found.")
    
    if not question.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Question cannot be empty.",
        )

    # 2. Perform semantic search to retrieve relevant runbook chunks
    # (Reusing logic from search_runbooks, but directly within this function)
    query_embedding = generate_embedding(question)

    chunks_with_docs = (
        db.query(models.DocumentChunk, models.Document)
        .join(models.Document, models.Document.id == models.DocumentChunk.document_id)
        .filter(
            models.Document.type == models.DocumentType.RUNBOOK,
            models.DocumentChunk.embedding.isnot(None),
        )
        .all()
    )

    if not chunks_with_docs:
        # If no runbook chunks are available, we can still ask the LLM, but it won't be grounded.
        # For now, we'll return a specific message.
        return {
            "incident_id": incident_id,
            "question": question,
            "answer": "I cannot provide a grounded answer as no runbook documents or relevant chunks with embeddings were found.",
            "citations": [],
            "message": "No relevant runbook context available.",
        }

    scored_results = []
    for chunk, document in chunks_with_docs:
        try:
            chunk_embedding = json.loads(chunk.embedding)
        except Exception:
            continue # Skip if embedding is malformed

        sim = cosine_similarity(query_embedding, chunk_embedding)
        scored_results.append(
            {
                "similarity": sim,
                "chunk_id": chunk.id,
                "document_id": document.id,
                "document_title": document.title,
                "chunk_order": chunk.chunk_order,
                "chunk_text": chunk.chunk_text,
            }
        )
    scored_results.sort(key=lambda item: item["similarity"], reverse=True)
    
    # Take the top_k_chunks as context
    relevant_chunks = scored_results[:top_k_chunks]

    # 3. Construct the prompt for the LLM
    context_text = "\n\n".join(
        [f"Document: {c['document_title']}\nChunk Order: {c['chunk_order']}\nContent: {c['chunk_text']}" for c in relevant_chunks if c["similarity"] > 0.7] # Only use chunks above a certain similarity threshold
    )

    if not context_text:
        # If no chunks passed the similarity threshold
        answer = await mock_llm_generate(f"Question: {question}\nAnswer based on general knowledge:")
        return {
            "incident_id": incident_id,
            "question": question,
            "answer": answer,
            "citations": [],
            "message": "Answer based on general knowledge as no highly relevant runbook context was found.",
        }


    prompt = (
        "You are an expert incident response assistant. "
        "Answer the following question based ONLY on the provided context from engineering runbooks. "
        "If the answer is not in the context, state that you cannot answer from the provided information. "
        "Cite the document title and chunk order for each piece of information you use.\n\n"
        f"Question: {question}\n\n"
        f"Context:\n{context_text}\n\n"
        "Answer:"
    )

    # 4. Call the LLM to generate an answer
    ai_answer = await mock_llm_generate(prompt)

    # 5. Prepare citations
    citations = [
        {"document_id": c["document_id"], "document_title": c["document_title"], "chunk_id": c["chunk_id"], "chunk_order": c["chunk_order"], "similarity": c["similarity"]}
        for c in relevant_chunks if c["similarity"] > 0.7 # Only cite chunks used for context
    ]

    return {
        "incident_id": incident_id,
        "question": question,
        "answer": ai_answer,
        "citations": citations,
        "message": "Answer generated using RAG with runbook context."
    }