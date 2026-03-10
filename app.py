"""
app.py – RAG Chat Application (Gradio)
=======================================
Exposes a chat interface where users can ask questions about the Agentic Coding
tool documentation that was indexed by ingest.py.

Query pipeline per user message:
  1. Retrieve  – VectorRetriever fetches the top-K most similar nodes from ChromaDB
  2. Postprocess – SimilarityPostprocessor filters out low-relevance nodes
  3. Synthesize  – ResponseSynthesizer sends question + context to Cohere LLM
  4. Return      – Answer + formatted source list displayed in the chat

Run:
  python app.py
"""

# SSL fix for Windows / Python 3.14: inject system certificate store
import truststore
truststore.inject_into_ssl()

import logging

import chromadb
import gradio as gr
from dotenv import load_dotenv

from llama_index.core import VectorStoreIndex, StorageContext, Settings
from llama_index.core.postprocessor import SimilarityPostprocessor
from llama_index.core.response_synthesizers import get_response_synthesizer, ResponseMode
from llama_index.embeddings.cohere import CohereEmbedding
from llama_index.llms.cohere import Cohere
from llama_index.vector_stores.chroma import ChromaVectorStore

from config import (
    COHERE_API_KEY,
    COHERE_EMBED_MODEL,
    COHERE_LLM_MODEL,
    CHROMA_PERSIST_DIR,
    CHROMA_COLLECTION_NAME,
    TOP_K,
    SIMILARITY_CUTOFF,
)

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


# ── Initialise RAG components (once at startup) ───────────────────────────────

def _init_rag():
    """
    Build and return the three main RAG components:
      - retriever         : finds relevant nodes in Pinecone
      - postprocessor     : prunes low-similarity nodes
      - response_synthesizer : generates the final answer via the LLM
    """
    # Embedding model in query mode
    embed_model = CohereEmbedding(
        api_key=COHERE_API_KEY,
        model_name=COHERE_EMBED_MODEL,
        input_type="search_query",
    )

    # LLM for answer synthesis
    llm = Cohere(
        api_key=COHERE_API_KEY,
        model=COHERE_LLM_MODEL,
    )

    # Register globally so VectorStoreIndex and the synthesizer use them
    Settings.embed_model = embed_model
    Settings.llm = llm

    # Load the existing ChromaDB collection (persisted by ingest.py)
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_PERSIST_DIR))
    chroma_collection = chroma_client.get_collection(CHROMA_COLLECTION_NAME)
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    index = VectorStoreIndex.from_vector_store(vector_store, storage_context=storage_context)

    # Step 1 – Retriever
    retriever = index.as_retriever(similarity_top_k=TOP_K)

    # Step 2 – Postprocessor
    postprocessor = SimilarityPostprocessor(similarity_cutoff=SIMILARITY_CUTOFF)

    # Step 3 – Response Synthesizer
    response_synthesizer = get_response_synthesizer(
        response_mode=ResponseMode.COMPACT,
        llm=llm,
    )

    return retriever, postprocessor, response_synthesizer


logger.info("Initialising RAG components …")
retriever, postprocessor, response_synthesizer = _init_rag()
logger.info("RAG components ready.")


# ── Query pipeline ────────────────────────────────────────────────────────────

def _format_sources(nodes: list) -> str:
    """Build a compact, de-duplicated source list from retrieved nodes."""
    seen: set[str] = set()
    lines: list[str] = []

    for node in nodes:
        meta = node.metadata
        tool = meta.get("tool", "Unknown")
        title = meta.get("title") or meta.get("filename", "Unknown")
        key = f"{tool}|{title}"

        if key not in seen:
            seen.add(key)
            score = node.score
            score_str = f" ({score:.2f})" if score is not None else ""
            lines.append(f"• **{tool}** – {title}{score_str}")

    return "\n".join(lines)


def query_rag(question: str) -> tuple[str, str]:
    """
    Run the full RAG pipeline for a single question.
    Returns (answer_text, sources_text).
    """
    logger.info("Query: %s", question)

    # 1. Retrieve
    nodes = retriever.retrieve(question)
    logger.info("  Retrieved %d nodes", len(nodes))

    # 2. Postprocess – filter by similarity score
    filtered = postprocessor.postprocess_nodes(nodes, query_str=question)
    logger.info("  After filtering: %d nodes", len(filtered))

    # Graceful fallback: if nothing passes the cutoff, use top-3 anyway
    if not filtered:
        logger.warning("  All nodes below cutoff; falling back to top-3")
        filtered = nodes[:3]

    if not filtered:
        return "לא נמצא מידע רלוונטי לשאלתך. נסה לנסח מחדש.", ""

    # 3. Synthesize
    response = response_synthesizer.synthesize(question, nodes=filtered)
    answer = str(response)

    sources = _format_sources(filtered)
    return answer, sources


# ── Gradio UI ─────────────────────────────────────────────────────────────────

def chat_fn(message: str, history: list) -> str:
    """
    Gradio chat callback.
    Runs the RAG pipeline and appends the formatted sources to the answer.
    """
    answer, sources = query_rag(message)
    if sources:
        return f"{answer}\n\n---\n**מקורות:**\n{sources}"
    return answer


with gr.Blocks(title="RAG – Agentic Coding Docs") as demo:
    gr.Markdown(
        """
        # 🔍 RAG – מאגר ידע Agentic Coding
        שאל שאלות על כלי **Cursor** ו-**Claude Code** ועל הפרויקט Task Manager API.

        המערכת מחפשת סמנטית בתיעוד, מאחזרת את הקטעים הרלוונטיים ביותר,
        ומנסחת תשובה מפורטת בעזרת Cohere Command-R+.
        """
    )

    gr.ChatInterface(
        fn=chat_fn,
        examples=[
            "איך מתקינים את המערכת?",
            "מה הארכיטקטורה של הפרויקט?",
            "איך מריצים את הטסטים?",
            "מהי מדיניות האימות (Authentication) של ה-API?",
            "איך מגדירים משתני סביבה לפיתוח מקומי?",
            "איך מוסיפים Migration חדש לבסיס הנתונים?",
            "מה קורה כשמישהו שולח בקשה לא מאומתת?",
            "איך מבצעים Deployment לפרודקשן?",
        ],
    )


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False, theme=gr.themes.Soft())
