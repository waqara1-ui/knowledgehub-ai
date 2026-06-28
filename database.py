#creating a database system using SQLalchemy 
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

#SQLite database file is here
DATABASE_URL = "sqlite:///./policy_assistant.db" 

#for the engine that manages the actual connection to the databases
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread":False})
# For SQLite, check_same_thread=False is needed because FastAPI (uvicorn)
# uses multiple threads, and SQLite typically prefers single-threaded access.
# For other databases like PostgreSQL, this argument is not needed.

#im creating a SessionLocal class and each instance of it will be a database session.
#Each session is responsible for all communications with the database
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

#database models (tables) inheriting from Base class
class Base(DeclarativeBase):
    pass

#get database session - later used by FastAPI to manage connections fro each request
def get_database():
    db = SessionLocal()
    try:
        yield db #provide database session
    finally:
        db.close() #close session after request is finished

#yiled pauses a function 