# models.py
from sqlalchemy import (Column, Integer, String, DateTime, ForeignKey, Text, Boolean, Float,)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base


# Model table
class User(Base):
    """
    Represents a user of LogLens AI.

    Note: Add authentication later
    Note to self:
    - username and email must be unique.
    - is_admin tells us who can upload logs/docs.
    """

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    #One user can upload many documents and potentially create many incidents
    documents = relationship("Document", back_populates="uploader", cascade="all, delete-orphan")
    incidents = relationship("Incident", back_populates="creator", cascade="all, delete-orphan")


# Document model (for logs and docs)
class DocumentType:
    LOG = "log"
    RUNBOOK = "runbook"
    OTHER = "other"


class Document(Base):
    """
    Represents an uploaded file.

    type:
      - 'log' for log files (like: app.log)
      - 'runbook' for engineering documentation
      - 'other' for anything else

    status:
      - 'pending' -> uploaded but not yet processed
      - 'processing' -> being parsed/chunked
      - 'processed' ->successfully parsed
      - 'failed' -> processing failed
    """

    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True, nullable=False)
    file_path = Column(String, nullable=False)

    type = Column(String, default=DocumentType.OTHER, index=True, nullable=False)
    status = Column(String, default="pending", nullable=False)

    uploader_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    uploader = relationship("User", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")
    log_entries = relationship("LogEntry", back_populates="document", cascade="all, delete-orphan")


#DocumentChunk model (for runbooks/docs text)
class DocumentChunk(Base):
    """
    Represents a chunk (section/paragraph) of a document.

    Used for:
      - runbooks/docs (RAG)
      - later higher level log chunks 
    """

    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    chunk_text = Column(Text, nullable=False)
    chunk_order = Column(Integer, nullable=False)

    # Embedding stored as JSON/text for now. Later will use a vector DB.
    embedding = Column(Text, nullable=True)
    document = relationship("Document", back_populates="chunks")


# Incident table
class IncidentStatus:
    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    CLOSED = "closed"


class Incident(Base):
    """
    Represents an incident (an outage or major issue).

    The core unit that can check:
      - when did it start/end?
      - what was impacted?
      - what was the root cause?
    """

    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)

    status = Column(String, default=IncidentStatus.OPEN, nullable=False)
    severity = Column(String, nullable=True)  # ex: "SEV-1", "SEV-2"

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    creator_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Relationships
    #one user can have many incidents
    creator = relationship("User", back_populates="incidents")
    #one incident can have many LogEntry records associated with it
    log_entries = relationship("LogEntry", back_populates="incident")


# SECTION: LogEntry model
class LogEntry(Base):
    """
    Represents a single parsed line (or event) from a log file.

    Storing:
      - which document (log file) it came from
      - optional incident link
      - timestamp, level, message, and any extra parsed data
    """

    __tablename__ = "log_entries"

    id = Column(Integer, primary_key=True, index=True)

    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=True)

    # Basic structured fields
    timestamp = Column(DateTime(timezone=True), nullable=True)
    level = Column(String, index=True, nullable=True)  # ex: INFO, WARN, ERROR
    message = Column(Text, nullable=False)

    # Raw line as it appears in the log (for reference)
    raw = Column(Text, nullable=True)

    #Optional numeric fields for later analysis like response time
    numeric_value = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    document = relationship("Document", back_populates="log_entries")
    incident = relationship("Incident", back_populates="log_entries")


# SECTION: Feedback Model
class AnswerFeedback(Base):
    """
    Stores user feedback on AI-generated answers.
    """
    __tablename__ = "answer_feedback"

    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True) # User who gave feedback
    question = Column(Text, nullable=False) # The question that was asked
    answer = Column(Text, nullable=False) # The AI's answer
    is_helpful = Column(Boolean, nullable=False) # True for thumbs up, False for thumbs down
    feedback_text = Column(Text, nullable=True) # Optional text comment
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    incident = relationship("Incident") # Simplified relationship, no back_populates needed for simple feedback
    user = relationship("User") # Simplified relationship


# SECTION: Analytics Model for Questions
class QuestionLog(Base):
    """
    Stores questions and AI responses for analytics and feedback.
    """
    __tablename__ = "question_logs"

    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    question = Column(Text, nullable=False)
    ai_answer = Column(Text, nullable=True)
    answered_at = Column(DateTime(timezone=True), server_default=func.now())

    incident = relationship("Incident")
    user = relationship("User")
