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

    # Fake uploader for now
    fake_uploader_id: Optional[int] = 1

    # Create Document record with initial status
    document = models.Document(
        title=title,
        file_path=file_path,
        type=doc_type,
        status="processing",
        uploader_id=fake_uploader_id,
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

