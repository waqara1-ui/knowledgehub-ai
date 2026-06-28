from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from typing import Annotated 
import os
import uuid #generates unqiue filenames
from database import engine, Base, get_database
from sqlalchemy.orm import Session 
import models

# Create all database tables defined in models.py
# This will create the .db file and tables if they don't exist
# In a real production app, you would use a migration tool like Alembic for this.
Base.metadata.create_all(bind=engine)

#creating an instance of FastAPI and assigning into app which is what Uvicorn will run
app = FastAPI(
    title="AI Policy Assistant",
    description="Backend API for an internal AI-powered policy assistant.",
    version="0.1.0",
)

#ensuring upload directory exists
UPLOAD_DIR = "uploaded_files" 
os.makedirs(UPLOAD_DIR, exist_ok=True)


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
    message = f"Hello, {name}! Welcome to the AI Policy Assistant API."
    return JSONResponse(content={"message": message})

DbSessionDep = Annotated[Session, Depends(get_database)]
#Annotated[Session, Depends(get_db)] tells FastAPI: “this parameter is a Session and should be provided by get_db.

@app.post("/admin/upload", status_code=status.HTTP_201_CREATED)
async def upload_document(
    title: Annotated[str, Form(...)],
    file: Annotated[UploadFile, File(...)],
    db: DbSessionDep
):
    
    #Basic file type check (content-type)
    if file.content_type != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Only PDF files are allowed."
            )

    #generating a safe unique filename, 
    # using UUIF to avoid collisions and potential path issues

    file_extension = ".pdf"
    unique_id = str(uuid.uuid4())
    safe_filename = f"{unique_id}{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, safe_filename)

    #saving file to disk in chunks to avoid loading entire file into memory
    try:
        with open(file_path, "wb") as f:
            while chunk := await file.read(1024 * 1024):  # 1 MB chunks
                f.write(chunk)
    except Exception as e:
        # If saving fails, return an error
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save file: {e}",
        )
    
    #for now pretend uploader
    fake_uploader_id =1

    #creating a new doc
    new_doc = models.Document(title=title, file_path=file_path, uploader_id =fake_uploader_id, status="pending")

    db.add(new_doc)
    db.commit()
    db.refresh(new_doc)

    return {
        "id": new_doc.id,
        "title": new_doc.title,
        "file_path": new_doc.file_path,
        "status": new_doc.status,
    }


