from sqlalchemy import Column,Integer, String, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func #default timestamps
from database import Base #Base class from database.py

#user table
class User(Base):
    __tablename__= "users"
    #name of the table in the data 
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False) #unique username
    email = Column(String, unique=True, index=True, nullable=False) #unique email
    hashed_password = Column(String, nullable=False)
    is_admin = Column(Boolean, default=False) #role based access control
    created_at = Column(DateTime(timezone=True), server_default=func.now()) #timestamp

    #one to many relatinship 
    #one user can upload many documents
    documents = relationship("Document", back_populates="uploader")

#document table
class Document(Base):
    __tablename__= "documents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True, nullable=False)
    file_path = Column(String, nullable=False)
    uploader_id = Column(Integer, ForeignKey("users.id")) #foregn key linking to User
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String, default="pending", nullable=False) #pending,processed, failed

    #many to one relatinships: Many documents can be uploaded by one user
    uploader = relationship("User", back_populates="documents")

    #One-to-many relationship: One document can have many chunks
    chunks = relationship("DocumentChunk", back_populates="document")

#DocumentChunk model (table)
class DocumentChunk(Base):
    __tablename__ = "document_chunks" # Name of the table in the database

    id = Column(Integer, primary_key=True, index=True) 
    document_id = Column(Integer, ForeignKey("documents.id")) # Foreign Key linking to Document
    chunk_text = Column(Text, nullable=False) # The actual text content of the chunk
    chunk_order = Column(Integer, nullable=False) # To maintain original order
    embedding = Column(Text, nullable=True) # To store the vector embedding later
    #This is where we’ll store the AI-generated vector embedding of the chunk later. For now, it’s just a text field.
    # Many-to-one relationship: Many chunks belong to one document
    document = relationship("Document", back_populates="chunks")
