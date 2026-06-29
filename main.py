from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from typing import Annotated, Optional
import os
import uuid #generates unique links?
from datetime import datetime
import re  #for log parsing

from database import engine, Base, get_database
from sqlalchemy.orm import Session
import models

# Create all database tables defined in models.py
# This will create the .db file and tables if they don't exist
# In a real production app, you would use a migration tool like Alembic for this.
Base.metadata.create_all(bind=engine)

#creating an instance of FastAPI and assigning into app which is what Uvicorn will run
app = FastAPI(
    title="LogLens AI",
    description="AI-powered incident investigation and log analysis assistant.",
    version="0.1.0",
)


#ensuring upload directory exists
UPLOAD_DIR = "uploaded_files" 
os.makedirs(UPLOAD_DIR, exist_ok=True)

DbSessionDep = Annotated[Session, Depends(get_database)]
#Annotated[Session, Depends(get_db)] tells FastAPI: “this parameter is a Session and should be provided by get_database.

@app.get("/health")
def health_check():
    """
    Adding a health check endpoint to return a simple JSON response that indicates the service is running.
    This is useful for monitoring and uptime checks.
    """
    
    return {"status": "ok"} #: for JSONresponse

@app.get("/hello")
def hello(name: str = "there"):
    """
    Adding a simple ex. endpoint
    Query Param: hello, reponse: "there!
    Returns a JSON greeting
    
    """
    message = f"Hello, {name}! Welcome to the LogLens AI API."
    return JSONResponse(content={"message": message})

#helper to detect file type
def detect_document_type(file: UploadFile) -> str:
    """file detection based on file extension
    In a real system,we'd also inspectcontent signatures
    """
    filename = file.filename or ""
    lower_name = filename.lower()

    if lower_name.endswith(".log") or "log" in lower_name:
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

def parse_log_line(line:str) -> dict:
    """
    Parsing a single log line into structured data
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

    #parsing timestamp
    ts = None
    try: # to handle ISO 8601-like timestamps such as 2024-06-01T10:42:11Z
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        pass

    return {
        "timestamp": ts,
        "level": level,
        "message": message,
        "raw": line,
    }

@app.post("/admin/upload", status_code=status.HTTP_201_CREATED)
async def upload_document(
    title: Annotated[str, Form(...)] ,
    file: Annotated[UploadFile, File(...)] ,
    db: DbSessionDep,
):
    """
    Admin endpoint to upload a file.

    - For log files (.log): parses lines into LogEntry records.
    - For runbooks/docs (pdf/txt/md): saving metadata for later chunking/embedding.
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
            detail="Unsupported file type. Please upload .log, .pdf, .txt, or .md files.",
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

    # Create Document
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

    # If it's a runbook/doc, we only save metadata for now
    else:
        document.status = "processed"  # Metadata saved; text/chunking will come later
        db.add(document)
        db.commit()
        db.refresh(document)

        return {
            "id": document.id,
            "title": document.title,
            "type": document.type,
            "status": document.status,
            "message": "Runbook/document uploaded. Text parsing/chunking will be added in a later phase.",
        }
