"""Configuration for LogLensAI 
Everything that chages between laptop, cloud, is read from environment variables. I'm getting rid of hard code"""
import os
 
#Reading an environment variable and converting to bool
def _get_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")
# 0, false, no, off, or anything else is false
 

def _get_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
 
 
def _get_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
 
 
class Settings:
    # Database -----------------------------------------------------------
    # Using Postgres:  postgresql+psycopg://loglens:loglens@db:5432/loglens
    DATABASE_URL: str = os.environ.get(
        "DATABASE_URL", "sqlite:///./policy_assistant.db"
    )
 
    # --- Authorization --------------------------------------------------
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = _get_int("ACCESS_TOKEN_EXPIRE_MINUTES", 60)
 
    # Debug endpoints will stay OFF unless explicitly enabled.
    ENABLE_DEBUG_ENDPOINTS: bool = _get_bool("ENABLE_DEBUG_ENDPOINTS", False)
 
    # Bootstrap admin: created once on startup if it does not exist.
    # I'm replacing the old /debug/create-user endpoint.
    BOOTSTRAP_ADMIN_USERNAME: str = os.environ.get("BOOTSTRAP_ADMIN_USERNAME", "")
    BOOTSTRAP_ADMIN_EMAIL: str = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "")
    BOOTSTRAP_ADMIN_PASSWORD: str = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "")
 
    # --- Embeddings ---------------------------------------------------------
    EMBEDDING_MODEL: str = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    EMBEDDING_DIM: int = _get_int("EMBEDDING_DIM", 384)  # all-MiniLM-L6-v2 = 384
 
    # Cosine similarity floor for a chunk to be considered relevant.
    # NOTE: 0.7 (like i previosly had) is too strict for all-MiniLM-L6-v2. Real
    # matches on this model usually land between 0.35 and 0.60, so a 0.7 floor
    # silently discarded every chunk and always fell back to "no context".
    SIMILARITY_THRESHOLD: float = _get_float("SIMILARITY_THRESHOLD", 0.35)
    TOP_K_CHUNKS: int = _get_int("TOP_K_CHUNKS", 5)
 
    # --- Chunking -----------------------------------------------------------
    # Since all-MiniLM-L6-v2 has a 256 token input limit which is roughly 1000
    # characters. Anything past that is silently truncated when the chunk is
    # embedded, so a larger chunk does not fail loudly, it just becomes partly
    # invisible to search. 
    # So keeping this under the limit. 
    # Note: Raise the token limit if I later switch to a longer context embedding model
    CHUNK_MAX_CHARS: int = _get_int("CHUNK_MAX_CHARS", 800)
    CHUNK_OVERLAP_CHARS: int = _get_int("CHUNK_OVERLAP_CHARS", 120)
 
    # --- LLM ----------------------------------------------------------------
    # One of: mock | ollama | gemini | openai_compatible
    LLM_PROVIDER: str = os.environ.get("LLM_PROVIDER", "mock").strip().lower()
    LLM_MODEL: str = os.environ.get("LLM_MODEL", "")
    LLM_API_KEY: str = os.environ.get("LLM_API_KEY", "")
    LLM_BASE_URL: str = os.environ.get("LLM_BASE_URL", "")
    LLM_TIMEOUT_SECONDS: float = _get_float("LLM_TIMEOUT_SECONDS", 60.0)
    LLM_MAX_TOKENS: int = _get_int("LLM_MAX_TOKENS", 800)
    #temp = 0.2, Node: change it if needed after testing
    LLM_TEMPERATURE: float = _get_float("LLM_TEMPERATURE", 0.2)
 
    # --- CORS ---------------------------------------------------------------
    # It's usually comma separated. 
    # Only needed if the front end is served from a different origin than the API. 
    # The bundled front end is same origin, so this is empty by default.
    CORS_ORIGINS: str = os.environ.get("CORS_ORIGINS", "")
 
    # --- Derived ------------------------------------------------------------
    @property
    def is_postgres(self) -> bool:
        return self.DATABASE_URL.startswith("postgres")
 
    @property
    def use_pgvector(self) -> bool:
        #pgvector only used when database is PostgreSQL and USE_PGVector is enabled
        return self.is_postgres and _get_bool("USE_PGVECTOR", True)
 
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]
 
 
settings = Settings()
 
# gonna make application refuse to run if a secret key is not set
if not settings.SECRET_KEY:
    if settings.ENABLE_DEBUG_ENDPOINTS:
        settings.SECRET_KEY = "dev-only-insecure-key-change-me"
        print("WARNING: SECRET_KEY not set. Using an insecure dev key.")
    else:
        raise RuntimeError(
            "SECRET_KEY is not set. Copy .env.example to .env and set a real "
            "value (python -c \"import secrets; print(secrets.token_urlsafe(48))\")."
        )
 