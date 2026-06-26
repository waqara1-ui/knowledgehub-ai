from fastapi import FastAPI
from fastapi.responses import JSONResponse

from database import engine, Base
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