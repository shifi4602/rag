"""
ingest.py – Event-Driven RAG Ingestion Workflow
================================================

Event Flow
----------

  IngestStartEvent (source_dir)
        │
        ▼
  validate_source ──[dir missing / no .md files]──► IngestStopEvent (error)
        │ SourceValidatedEvent
        ▼
  load_documents
        │ DocumentsLoadedEvent
        ▼
  chunk_documents
        │ NodesCreatedEvent
        ▼
  build_index
        │ IngestStopEvent (stats)
        ▼
  (stats printed to log)

Design notes
------------
- Steps 1–4 contain zero LLM calls; only Step 3 (build_index) calls Cohere
  for embedding – this makes the LLM boundary explicit.
- Events carry only the data produced at that step; nothing else is passed forward.
- Adding a retry step or a different chunking strategy only requires adding a new
  Event type and handler – existing steps are not touched.

Run:
  python ingest.py
"""

# SSL fix for Windows / Python 3.14: inject system certificate store
import truststore
truststore.inject_into_ssl()

import logging
import asyncio
from pathlib import Path

import chromadb
from dotenv import load_dotenv

from llama_index.core import SimpleDirectoryReader, StorageContext, VectorStoreIndex, Settings
from llama_index.core.node_parser import MarkdownNodeParser
from llama_index.core.workflow import (
    Workflow,
    step,
    StartEvent,
    StopEvent,
    Event,
)
from llama_index.utils.workflow import draw_all_possible_flows
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


# ── Ingest Events ───────────────────────────────────────────────────────────

# ── Ingest Events: StartEvent and StopEvent come from llama_index.core.workflow.
# Custom events extend Event (a Pydantic BaseModel).


class SourceValidatedEvent(Event):
    """Source directory exists and contains at least one eligible file."""
    source_dir: Path


class DocumentsLoadedEvent(Event):
    """Documents successfully loaded from disk."""
    documents: list


class NodesCreatedEvent(Event):
    """Documents chunked into indexable nodes."""
    documents: list
    nodes: list


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


# ── Ingest Workflow ───────────────────────────────────────────────────────────


class IngestWorkflow(Workflow):
    """
    Event-Driven ingestion pipeline built on the LlamaIndex Workflow pattern.

    Each @step is an async handler.  LlamaIndex reads the type annotations to
    route events automatically – no manual DISPATCH table needed.

    Usage::

        stats = await IngestWorkflow(timeout=300).run(source_dir=SAMPLE_PROJECT_DIR)

    To draw a visual HTML graph of the workflow::

        python ingest.py --draw   →  ingest_graph.html
    """

    @step
    async def validate_source(self, ev: StartEvent) -> SourceValidatedEvent | StopEvent:
        """Step 1 – Source Validation: ensures the directory exists and has eligible files."""
        source_dir = Path(ev.get("source_dir"))

        if not source_dir.exists():
            logger.error("[validate_source] Directory not found: %s", source_dir)
            return StopEvent(result={"error": f"Directory not found: {source_dir}"})

        eligible = list(source_dir.rglob("*.md")) + list(source_dir.rglob("*.mdc"))
        if not eligible:
            logger.error("[validate_source] No .md / .mdc files in: %s", source_dir)
            return StopEvent(result={"error": f"No .md/.mdc files found in {source_dir}"})

        logger.info("[validate_source] OK – %d eligible files", len(eligible))
        return SourceValidatedEvent(source_dir=source_dir)

    @step
    async def load_documents(self, ev: SourceValidatedEvent) -> DocumentsLoadedEvent:
        """Step 2 – Document Loading: reads all .md/.mdc files with full metadata."""
        logger.info("[load_documents] Loading from: %s", ev.source_dir)

        reader = SimpleDirectoryReader(
            input_dir=str(ev.source_dir),
            recursive=True,
            required_exts=[".md", ".mdc"],
            file_metadata=get_file_metadata,
        )
        documents = reader.load_data()

        logger.info("[load_documents] %d documents loaded", len(documents))
        for doc in documents:
            logger.info(
                "    • [%s] %s",
                doc.metadata.get("tool", "?"),
                doc.metadata.get("filename", "?"),
            )

        return DocumentsLoadedEvent(documents=documents)

    @step
    async def chunk_documents(self, ev: DocumentsLoadedEvent) -> NodesCreatedEvent:
        """Step 3 – Chunking: splits documents on Markdown headings."""
        logger.info("[chunk_documents] Chunking with MarkdownNodeParser …")

        parser = MarkdownNodeParser()
        nodes = parser.get_nodes_from_documents(ev.documents, show_progress=True)

        logger.info(
            "[chunk_documents] %d nodes from %d documents",
            len(nodes), len(ev.documents),
        )
        return NodesCreatedEvent(documents=ev.documents, nodes=nodes)

    @step
    async def build_index(self, ev: NodesCreatedEvent) -> StopEvent:
        """Step 4 – Embedding + Index Storage  ← only step that calls Cohere."""
        logger.info("[build_index] Embedding and storing %d nodes …", len(ev.nodes))

        embed_model = CohereEmbedding(
            api_key=COHERE_API_KEY,
            model_name=COHERE_EMBED_MODEL,
            input_type="search_document",
        )
        Settings.embed_model = embed_model

        CHROMA_PERSIST_DIR.mkdir(parents=True, exist_ok=True)
        chroma_client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))
        try:
            chroma_client.delete_collection(CHROMA_COLLECTION_NAME)
        except Exception:
            pass
        chroma_collection = chroma_client.get_or_create_collection(CHROMA_COLLECTION_NAME)

        vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
        storage_context = StorageContext.from_defaults(vector_store=vector_store)

        VectorStoreIndex(
            ev.nodes,
            storage_context=storage_context,
            show_progress=True,
        )

        logger.info("[build_index] Stored in ChromaDB at: %s", CHROMA_PERSIST_DIR)
        return StopEvent(result={
            "documents": len(ev.documents),
            "nodes": len(ev.nodes),
            "collection": CHROMA_COLLECTION_NAME,
            "persist_dir": str(CHROMA_PERSIST_DIR),
        })



# ── Entry point ───────────────────────────────────────────────────────────────


async def _run():
    stats = await IngestWorkflow(timeout=300).run(source_dir=SAMPLE_PROJECT_DIR)
    if "error" in stats:
        logger.error("  Ingestion failed: %s", stats["error"])
        return
    logger.info("Ingestion complete! docs=%d nodes=%d", stats["documents"], stats["nodes"])


def main():
    logger.info("RAG Ingestion Workflow - START")
    asyncio.run(_run())


if __name__ == "__main__":
    import sys
    if "--draw" in sys.argv:
        out = Path(__file__).parent / "ingest_graph.html"
        draw_all_possible_flows(IngestWorkflow(), filename=str(out))
        print(f"Ingest graph saved -> {out}")
    else:
        main()
