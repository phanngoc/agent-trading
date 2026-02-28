import os
import re
from pathlib import Path
from dotenv import load_dotenv


def _load_env_file(path: Path, override: bool = False):
    """Load .env file handling both 'KEY=value' and 'export KEY=value' formats."""
    if not path.exists():
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Strip leading 'export ' if present
            line = re.sub(r"^export\s+", "", line)
            match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)", line)
            if match:
                key, value = match.group(1), match.group(2).strip("\"'")
                if override or key not in os.environ:
                    os.environ[key] = value


# Load .env files in priority order (later = lower priority)
_CHATBOT_DIR = Path(__file__).parent
_TREND_NEWS_DIR_CFG = _CHATBOT_DIR.parent          # trend_news/
_PROJECT_ROOT_CFG = _CHATBOT_DIR.parent.parent     # TradingAgents/

_load_env_file(_PROJECT_ROOT_CFG / ".env")         # lowest priority
_load_env_file(_TREND_NEWS_DIR_CFG / ".env")       # trend_news/.env
_load_env_file(_CHATBOT_DIR / ".env", override=True)  # chatbot/.env (highest)

# --- Paths ---
TREND_NEWS_DIR = Path(__file__).parent.parent

# Set CONFIG_PATH so src/__init__.py can find config.yaml regardless of CWD
os.environ.setdefault("CONFIG_PATH", str(TREND_NEWS_DIR / "config" / "config.yaml"))
OUTPUT_DIR = TREND_NEWS_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

DB_PATH = os.getenv("DB_PATH", str(OUTPUT_DIR / "trend_news.db"))
COGNEE_DB_PATH = os.getenv("COGNEE_DB_PATH", str(OUTPUT_DIR / "cognee_db"))
MEM0_HISTORY_DB = os.getenv("MEM0_HISTORY_DB", str(OUTPUT_DIR / "mem0_history.db"))
MEM0_CHROMA_PATH = os.getenv("MEM0_CHROMA_PATH", str(OUTPUT_DIR / "mem0_chromadb"))

# --- LLM ---
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")  # openai | google | groq
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Forward OpenAI key so libraries that read OPENAI_API_KEY directly work
if OPENAI_API_KEY:
    os.environ.setdefault("OPENAI_API_KEY", OPENAI_API_KEY)
# mem0's gemini embedder reads GOOGLE_API_KEY env var as fallback
if GEMINI_API_KEY and not os.environ.get("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = GEMINI_API_KEY

# --- Chatbot behavior ---
MAX_NEWS_RESULTS = int(os.getenv("MAX_NEWS_RESULTS", "10"))
NEWS_DAYS_LOOKBACK = int(os.getenv("NEWS_DAYS_LOOKBACK", "30"))
INDEXER_BATCH_SIZE = int(os.getenv("INDEXER_BATCH_SIZE", "50"))
INDEXER_RUN_INTERVAL = int(os.getenv("INDEXER_RUN_INTERVAL", "1800"))  # 30 min

# --- mem0 config — switches LLM/embedder based on provider ---
_MEM0_LLM: dict
_MEM0_EMBEDDER: dict
if OPENAI_API_KEY:
    _MEM0_LLM = {
        "provider": "openai",
        "config": {"model": "gpt-4o-mini", "api_key": OPENAI_API_KEY},
    }
    _MEM0_EMBEDDER = {
        "provider": "openai",
        "config": {"model": "text-embedding-3-small", "api_key": OPENAI_API_KEY},
    }
elif GEMINI_API_KEY:
    _MEM0_LLM = {
        "provider": "gemini",
        "config": {"model": "gemini-1.5-flash", "api_key": GEMINI_API_KEY},
    }
    _MEM0_EMBEDDER = {
        "provider": "gemini",
        "config": {"model": "models/text-embedding-004", "api_key": GEMINI_API_KEY},
    }
else:
    raise RuntimeError("Set OPENAI_API_KEY or GEMINI_API_KEY in .env")

MEM0_CONFIG = {
    "version": "v1.0",
    "history_db_path": MEM0_HISTORY_DB,
    "vector_store": {
        "provider": "chroma",
        "config": {
            "collection_name": "user_memories",
            "path": MEM0_CHROMA_PATH,
        },
    },
    "llm": _MEM0_LLM,
    "embedder": _MEM0_EMBEDDER,
}

# --- Cognee config (v0.5.x API via set_llm_config + env vars) ---
_COGNEE_LLM_MODEL = "gpt-4o-mini" if OPENAI_API_KEY else "gemini/gemini-1.5-flash"
_COGNEE_LLM_KEY = OPENAI_API_KEY or GEMINI_API_KEY

COGNEE_LLM_CONFIG = {
    "llm_provider": "openai",   # litellm-compatible for both openai and gemini/
    "llm_model": _COGNEE_LLM_MODEL,
    "llm_api_key": _COGNEE_LLM_KEY,
}
# Embedding: local fastembed — no API cost regardless of LLM choice
COGNEE_EMBEDDING_ENV = {
    "EMBEDDING_PROVIDER": "fastembed",
    "EMBEDDING_MODEL": "BAAI/bge-small-en-v1.5",
    "EMBEDDING_DIMENSIONS": "384",
}


def setup_cognee_paths() -> None:
    """Set cognee DB path env vars BEFORE any `import cognee`.

    cognee's BaseConfig (pydantic-settings) reads DATA_ROOT_DIRECTORY and
    SYSTEM_ROOT_DIRECTORY at class-instantiation time. These must be set
    before cognee is imported so the databases land in the project output
    directory instead of the default venv location.

    Safe to call multiple times — uses os.environ.setdefault (no-op if already set).
    """
    os.environ.setdefault("SYSTEM_ROOT_DIRECTORY", COGNEE_DB_PATH)
    os.environ.setdefault("DATA_ROOT_DIRECTORY", str(Path(COGNEE_DB_PATH) / "data_storage"))
    
    # Note: Cognee 0.5.x stores Kuzu graph in .pkl file (pickle serialization)
    # The actual graph DB is at: databases/{uuid}/{uuid}.pkl
    # Kuzu folder is NOT used in this version
