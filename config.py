"""
config.py – Centralised configuration for the RAG application.
All values are read from environment variables (loaded from .env by python-dotenv).
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ─────────────────────────────────────────────────────────────────
COHERE_API_KEY: str = os.environ["COHERE_API_KEY"]

# ── Cohere Models ─────────────────────────────────────────────────────────────
COHERE_EMBED_MODEL: str = "embed-multilingual-v3.0"
COHERE_LLM_MODEL: str = "command-a-03-2025"

# ── ChromaDB (local vector store) ────────────────────────────────────────────
BASE_DIR: Path = Path(__file__).parent
CHROMA_PERSIST_DIR: Path = BASE_DIR / "chroma_db"
CHROMA_COLLECTION_NAME: str = "agentic-tools-docs"

# ── Paths ─────────────────────────────────────────────────────────────────────
SAMPLE_PROJECT_DIR: Path = BASE_DIR / "sample_project"
EXTRACTED_DATA_PATH: Path = BASE_DIR / "extracted_data.json"

# ── Retrieval ─────────────────────────────────────────────────────────────────
TOP_K: int = 5               # number of nodes to retrieve
SIMILARITY_CUTOFF: float = 0.30  # minimum similarity score to keep a node
