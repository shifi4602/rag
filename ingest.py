"""
ingest.py – RAG Data Ingestion Pipeline
========================================
Steps:
  1. Load   – Read .md and .mdc files from sample_project/ with LlamaIndex SimpleDirectoryReader
  2. Chunk  – Split each document into smaller nodes with MarkdownNodeParser
  3. Embed  – Generate Cohere multilingual embeddings (embed-multilingual-v3.0)
  4. Store  – Persist vectors + metadata in a local ChromaDB collection via VectorStoreIndex

Run:
  python ingest.py
"""

# SSL fix for Windows / Python 3.14: inject system certificate store
import truststore
truststore.inject_into_ssl()

import logging
from pathlib import Path

import chromadb
from dotenv import load_dotenv

from llama_index.core import SimpleDirectoryReader, StorageContext, VectorStoreIndex, Settings
from llama_index.core.node_parser import MarkdownNodeParser
from llama_index.embeddings.cohere import CohereEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore

from config import (
    COHERE_API_KEY,
    COHERE_EMBED_MODEL,
    CHROMA_PERSIST_DIR,
    CHROMA_COLLECTION_NAME,
    SAMPLE_PROJECT_DIR,
)

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


# ── Metadata extraction ───────────────────────────────────────────────────────

def get_file_metadata(filepath: str) -> dict:
    """
    Extract contextual metadata from a file path so every node stored in
    ChromaDB carries information about which tool produced it.

    Metadata fields:
        tool       – 'Cursor' | 'Claude Code' | 'Unknown'
        filename   – e.g. 'setup.md'
        filepath   – full path as a string
        file_type  – 'rules' (for .mdc) | 'documentation' (for .md)
        title      – human-readable title derived from the file stem
    """
    path = Path(filepath)
    # Normalise to forward slashes for OS-independent matching
    parts = filepath.replace("\\", "/").lower()

    if "/cursor/" in parts:
        tool = "Cursor"
    elif "/claude" in parts:
        tool = "Claude Code"
    else:
        tool = "Unknown"

    file_type = "rules" if path.suffix == ".mdc" else "documentation"

    return {
        "tool": tool,
        "filename": path.name,
        "filepath": filepath,
        "file_type": file_type,
        "title": path.stem.replace("-", " ").replace("_", " ").title(),
    }


# ── Pipeline steps ────────────────────────────────────────────────────────────

def load_documents():
    """
    Step 1 – Loading
    Use SimpleDirectoryReader to load all .md and .mdc files recursively.
    Each document automatically receives the metadata from get_file_metadata.
    """
    logger.info("Step 1 – Loading documents from: %s", SAMPLE_PROJECT_DIR)

    reader = SimpleDirectoryReader(
        input_dir=str(SAMPLE_PROJECT_DIR),
        recursive=True,
        required_exts=[".md", ".mdc"],
        file_metadata=get_file_metadata,
    )
    documents = reader.load_data()

    logger.info("  Loaded %d documents", len(documents))
    for doc in documents:
        logger.info("    • [%s] %s", doc.metadata.get("tool", "?"), doc.metadata.get("filename", "?"))

    return documents


def chunk_documents(documents):
    """
    Step 2 – Chunking
    MarkdownNodeParser splits documents on markdown headings.
    Each resulting node represents a logical section of the source file and
    inherits the document's metadata (tool, filename, etc.).
    """
    logger.info("Step 2 – Chunking with MarkdownNodeParser …")

    parser = MarkdownNodeParser()
    nodes = parser.get_nodes_from_documents(documents, show_progress=True)

    logger.info("  Created %d nodes from %d documents", len(nodes), len(documents))
    return nodes


def build_vector_index(nodes):
    """
    Steps 3 & 4 – Embedding + VectorStoreIndex
    Configure Cohere embeddings globally via Settings, then let VectorStoreIndex
    embed every node and persist it (with metadata) in a local ChromaDB collection.

    The 'search_document' input_type instructs Cohere to optimise the embedding
    for storage/retrieval rather than query matching.
    """
    logger.info("Step 3+4 – Embedding nodes and building VectorStoreIndex …")

    embed_model = CohereEmbedding(
        api_key=COHERE_API_KEY,
        model_name=COHERE_EMBED_MODEL,
        input_type="search_document",
    )

    # Register the embed model globally so VectorStoreIndex picks it up
    Settings.embed_model = embed_model

    CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))
    # Delete existing collection so re-running ingest starts fresh
    try:
        chroma_client.delete_collection(CHROMA_COLLECTION_NAME)
    except Exception:
        pass
    chroma_collection = chroma_client.get_or_create_collection(CHROMA_COLLECTION_NAME)

    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    index = VectorStoreIndex(
        nodes,
        storage_context=storage_context,
        show_progress=True,
    )

    logger.info("  All nodes embedded and stored in ChromaDB at: %s", CHROMA_PERSIST_DIR)
    return index


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    logger.info("═══════════════════════════════════════")
    logger.info("  RAG Ingestion Pipeline – START")
    logger.info("═══════════════════════════════════════")

    documents = load_documents()
    nodes = chunk_documents(documents)
    build_vector_index(nodes)

    logger.info("═══════════════════════════════════════")
    logger.info("  Ingestion complete!")
    logger.info("  Documents  : %d", len(documents))
    logger.info("  Chunks     : %d", len(nodes))
    logger.info("  Collection : %s", CHROMA_COLLECTION_NAME)
    logger.info("  Persisted  : %s", CHROMA_PERSIST_DIR)
    logger.info("═══════════════════════════════════════")


if __name__ == "__main__":
    main()
